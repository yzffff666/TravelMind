"""Deterministic multi-turn conversation decision and state-transition gate."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from app.domain.travel.conversation_runtime import (
    ConversationDecisionService,
    ConversationRuntimeSnapshot,
    apply_transition,
)
from app.services.travel_clarification_service import TravelClarificationService


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES_PATH = BACKEND_ROOT / "evaluation/multi_turn_conversation_cases.json"
DEFAULT_OUTPUT_DIR = Path("reports/multi-turn-conversation-eval/latest")


def load_cases(path: Path = DEFAULT_CASES_PATH) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("multi-turn conversation cases must be a JSON list")
    return payload


def _itinerary(destination: str, revision_id: str) -> dict[str, Any]:
    return {
        "schema_version": "itinerary.v1",
        "itinerary_id": f"itinerary-{destination}",
        "revision_id": revision_id,
        "trip_profile": {
            "destination_city": destination,
            "constraints": {
                "budget_range": "6000",
                "traveler_type": "朋友",
                "preferences": ["美食", "文化"],
            },
        },
        "days": [
            {
                "day_index": 1,
                "slots": [
                    {
                        "slot": "上午",
                        "activity": "参观",
                        "place": f"{destination}博物馆",
                    }
                ],
            }
        ],
        "budget_summary": {"total_estimate": 6000},
    }


def _snapshot(case_id: str, payload: dict[str, Any]) -> ConversationRuntimeSnapshot:
    destination = str(payload.get("active_destination") or "").strip() or None
    revision_id = str(payload.get("current_revision_id") or "").strip() or None
    has_itinerary = bool(payload.get("has_itinerary"))
    itinerary = _itinerary(destination or "未设置", revision_id or "rev-initial") if has_itinerary else None
    return ConversationRuntimeSnapshot(
        conversation_id=f"eval-{case_id}",
        active_destination=destination,
        trip_profile=(itinerary or {}).get("trip_profile") or {},
        current_itinerary=itinerary,
        current_revision_id=revision_id if has_itinerary else None,
        pending_clarification=payload.get("pending_clarification"),
        asked_fields=list(payload.get("asked_fields") or []),
        last_user_query=payload.get("last_user_query"),
    )


def _normalize_qp(payload: dict[str, Any]) -> dict[str, Any]:
    intent = str(payload.get("intent") or "chat")
    return {
        "intent": intent,
        "intent_detail": payload.get("intent_detail")
        or {
            "create": "first_create",
            "edit": "edit_day",
            "qa": "qa_local",
            "chat": "general_chat",
            "reset": "reset_all",
        }.get(intent, "general_chat"),
        "constraints": dict(payload.get("constraints") or {}),
        "target_day": payload.get("target_day"),
        "target_slot": payload.get("target_slot"),
        "confidence": payload.get("confidence"),
    }


def _evaluate_clarification_turn(
    *,
    turn: dict[str, Any],
    snapshot: ConversationRuntimeSnapshot,
    service: TravelClarificationService,
) -> tuple[ConversationRuntimeSnapshot, dict[str, Any]]:
    query = str(turn.get("query") or "")
    action = str(turn.get("clarification_action") or "")
    service.restore_pending(snapshot.conversation_id, snapshot.pending_clarification)
    if action == "start":
        result = service.start_new(snapshot.conversation_id, query)
    elif action == "continue":
        result = service.continue_pending(snapshot.conversation_id, query)
    else:
        raise ValueError(f"unsupported clarification_action: {action!r}")

    state_after = snapshot.model_copy(deep=True)
    state_after.pending_clarification = service.snapshot_pending(snapshot.conversation_id)
    if state_after.pending_clarification:
        state_after.asked_fields = list(
            state_after.pending_clarification.get("asked_fields") or []
        )
    else:
        state_after.asked_fields = []
    state_after.last_user_query = query
    actual = {
        "intent": "clarify" if result.get("need_clarification") else "create",
        "mutation_scope": "constraints_only"
        if result.get("need_clarification")
        else "whole_trip",
        "active_destination": state_after.active_destination,
        "revision_before": snapshot.current_revision_id,
        "revision_after": state_after.current_revision_id,
        "revision_changed": False,
        "pending": bool(state_after.pending_clarification),
        "missing_hard": list(result.get("missing_hard") or []),
        "combined_query": result.get("combined_query"),
        "assumptions": list(result.get("assumptions") or []),
    }
    return state_after, actual


def _evaluate_decision_turn(
    *,
    turn: dict[str, Any],
    snapshot: ConversationRuntimeSnapshot,
    decision_service: ConversationDecisionService,
) -> tuple[ConversationRuntimeSnapshot, dict[str, Any]]:
    query = str(turn.get("query") or "")
    decision = decision_service.decide(
        query,
        _normalize_qp(dict(turn.get("qp") or {})),
        snapshot,
    )
    transition = apply_transition(snapshot, decision)
    state_after = transition.state_after
    state_after.last_user_query = query

    commit_revision_id = str(turn.get("commit_revision_id") or "").strip() or None
    if commit_revision_id:
        state_after.current_revision_id = commit_revision_id
        if state_after.current_itinerary is None:
            state_after.current_itinerary = _itinerary(
                state_after.active_destination or decision.destination or "未设置",
                commit_revision_id,
            )
        else:
            state_after.current_itinerary["revision_id"] = commit_revision_id

    actual = {
        "intent": decision.intent,
        "intent_detail": decision.intent_detail,
        "mutation_scope": decision.mutation_scope,
        "active_destination": state_after.active_destination,
        "revision_before": snapshot.current_revision_id,
        "revision_after": state_after.current_revision_id,
        "revision_changed": snapshot.current_revision_id
        != state_after.current_revision_id,
        "pending": bool(state_after.pending_clarification),
        "target_day": decision.target_day,
        "target_slot": decision.target_slot,
        "reason": decision.reason,
    }
    return state_after, actual


def _match_expected(actual: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key, expected_value in expected.items():
        if key.endswith("_contains"):
            actual_key = key.removesuffix("_contains")
            actual_value = actual.get(actual_key)
            if str(expected_value) not in str(actual_value or ""):
                errors.append(
                    f"{actual_key}: expected to contain {expected_value!r}, got {actual_value!r}"
                )
            continue
        actual_value = actual.get(key)
        if actual_value != expected_value:
            errors.append(f"{key}: expected {expected_value!r}, got {actual_value!r}")
    return errors


def evaluate_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    decision_service = ConversationDecisionService()
    case_results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    category_counts: Counter[str] = Counter()
    category_passed: Counter[str] = Counter()
    turn_count = 0

    for case in cases:
        case_id = str(case.get("case_id") or "unknown")
        category = str(case.get("category") or "uncategorized")
        category_counts[category] += 1
        snapshot = _snapshot(case_id, dict(case.get("initial_state") or {}))
        clarification = TravelClarificationService()
        turn_results: list[dict[str, Any]] = []

        for turn_index, turn in enumerate(case.get("turns") or [], start=1):
            turn_count += 1
            if turn.get("clarification_action"):
                snapshot, actual = _evaluate_clarification_turn(
                    turn=turn,
                    snapshot=snapshot,
                    service=clarification,
                )
            else:
                snapshot, actual = _evaluate_decision_turn(
                    turn=turn,
                    snapshot=snapshot,
                    decision_service=decision_service,
                )
            errors = _match_expected(actual, dict(turn.get("expected") or {}))
            turn_result = {
                "turn_index": turn_index,
                "query": turn.get("query"),
                "status": "passed" if not errors else "failed",
                "errors": errors,
                "actual": actual,
            }
            turn_results.append(turn_result)
            if errors:
                failures.append(
                    {
                        "case_id": case_id,
                        "category": category,
                        "turn_index": turn_index,
                        "query": turn.get("query"),
                        "errors": errors,
                        "actual": actual,
                    }
                )

        case_passed = all(item["status"] == "passed" for item in turn_results)
        if case_passed:
            category_passed[category] += 1
        case_results.append(
            {
                "case_id": case_id,
                "category": category,
                "status": "passed" if case_passed else "failed",
                "turns": turn_results,
            }
        )

    passed_cases = sum(item["status"] == "passed" for item in case_results)
    return {
        "schema_version": "multi_turn_conversation_eval_v1",
        "status": "passed" if not failures else "failed",
        "case_count": len(case_results),
        "passed_cases": passed_cases,
        "failed_cases": len(case_results) - passed_cases,
        "turn_count": turn_count,
        "failed_turns": len(failures),
        "category_summary": {
            category: {
                "total": category_counts[category],
                "passed": category_passed[category],
                "failed": category_counts[category] - category_passed[category],
            }
            for category in sorted(category_counts)
        },
        "failures": failures,
        "cases": case_results,
    }


def is_passing(report: dict[str, Any]) -> bool:
    return (
        report.get("status") == "passed"
        and int(report.get("case_count") or 0) == 24
        and int(report.get("passed_cases") or 0) == 24
        and int(report.get("failed_turns") or 0) == 0
    )


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# TravelMind Multi-Turn Conversation Eval",
        "",
        f"- Status: `{report['status']}`",
        f"- Cases: {report['passed_cases']}/{report['case_count']} passed",
        f"- Turns: {report['turn_count'] - report['failed_turns']}/{report['turn_count']} passed",
        "",
        "| Category | Total | Passed | Failed |",
        "| --- | ---: | ---: | ---: |",
    ]
    for category, summary in (report.get("category_summary") or {}).items():
        lines.append(
            f"| {category} | {summary['total']} | {summary['passed']} | {summary['failed']} |"
        )
    if report.get("failures"):
        lines.extend(
            [
                "",
                "## Failures",
                "",
                "| Case | Category | Turn | Query | Errors |",
                "| --- | --- | ---: | --- | --- |",
            ]
        )
        for failure in report["failures"]:
            lines.append(
                "| {case_id} | {category} | {turn_index} | {query} | {errors} |".format(
                    case_id=failure["case_id"],
                    category=failure["category"],
                    turn_index=failure["turn_index"],
                    query=str(failure.get("query") or "").replace("|", "/"),
                    errors="; ".join(failure.get("errors") or []).replace("|", "/"),
                )
            )
    lines.append("")
    return "\n".join(lines)


def write_outputs(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "multi-turn-conversation-eval.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "multi-turn-conversation-eval.md").write_text(
        render_markdown(report),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    report = evaluate_cases(load_cases(args.cases))
    write_outputs(report, args.output_dir)
    print(
        "multi_turn_conversation_eval="
        f"{report['status']} ({report['passed_cases']}/{report['case_count']} cases, "
        f"{report['turn_count'] - report['failed_turns']}/{report['turn_count']} turns)"
    )
    return 0 if is_passing(report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
