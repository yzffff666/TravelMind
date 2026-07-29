"""Deterministic acceptance gate for persisted bilingual conversations."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from app.domain.travel.conversation_runtime import ConversationRuntimeSnapshot
from app.domain.travel.language_policy import (
    localized_text,
    resolve_response_language,
)
from app.domain.travel.sse_envelope import build_event_envelope


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES_PATH = BACKEND_ROOT / "evaluation/bilingual_conversation_cases.json"
DEFAULT_OUTPUT_DIR = Path("reports/bilingual-conversation-eval/latest")
HARD_METRICS = (
    "language_drift",
    "wrong_language_final_responses",
    "state_persistence_failures",
    "missing_language_metadata",
)
_HAN_PATTERN = re.compile(r"[\u4e00-\u9fff]")


def load_cases(path: Path = DEFAULT_CASES_PATH) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("bilingual conversation cases must be a JSON list")
    return payload


def validate_case_contract(cases: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    buckets = Counter(str(case.get("language_bucket") or "") for case in cases)
    case_ids = [str(case.get("case_id") or "") for case in cases]
    if len(cases) != 20:
        errors.append(f"expected 20 bilingual conversation cases, got {len(cases)}")
    if buckets != Counter({"zh-CN": 10, "en": 10}):
        errors.append(
            "corpus must contain exactly 10 Chinese and 10 English cases"
        )
    if any(not case_id for case_id in case_ids) or len(set(case_ids)) != len(case_ids):
        errors.append("case_id values must be non-empty and unique")

    for case in cases:
        case_id = str(case.get("case_id") or "unknown")
        turns = list(case.get("turns") or [])
        if not 2 <= len(turns) <= 4:
            errors.append(f"{case_id} must contain 2 to 4 turns")
        for turn_index, turn in enumerate(turns, start=1):
            if "query" not in turn:
                errors.append(f"{case_id} turn {turn_index} is missing query")
            if turn.get("expected_language") not in {"en", "zh-CN"}:
                errors.append(
                    f"{case_id} turn {turn_index} has invalid expected_language"
                )
            if not str(turn.get("response_key") or "").strip():
                errors.append(
                    f"{case_id} turn {turn_index} is missing response_key"
                )
    return errors


def _wrong_language(text: str, expected_language: str) -> bool:
    has_han = bool(_HAN_PATTERN.search(text))
    return has_han if expected_language == "en" else not has_han


def evaluate_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    contract_errors = validate_case_contract(cases)
    metrics = {name: 0 for name in HARD_METRICS}
    case_results: list[dict[str, Any]] = []

    for case in cases:
        case_id = str(case.get("case_id") or "unknown")
        snapshot = ConversationRuntimeSnapshot(
            conversation_id=f"bilingual-eval-{case_id}",
            response_language=case.get("initial_language"),
        )
        traces: list[dict[str, Any]] = []
        case_failures: list[str] = []

        for turn_index, turn in enumerate(case.get("turns") or [], start=1):
            query = str(turn.get("query") or "")
            previous_language = snapshot.response_language
            decision = resolve_response_language(
                query,
                current_language=previous_language,
                ui_locale=case.get("ui_locale"),
            )
            expected_language = str(turn.get("expected_language") or "")
            if decision.language != expected_language:
                metrics["language_drift"] += 1
                case_failures.append(
                    f"turn {turn_index}: expected {expected_language}, "
                    f"selected {decision.language}"
                )

            snapshot.response_language = decision.language
            snapshot.last_user_query = query
            restored = ConversationRuntimeSnapshot.model_validate(
                snapshot.model_dump(mode="json")
            )
            if restored.response_language != decision.language:
                metrics["state_persistence_failures"] += 1
                case_failures.append(
                    f"turn {turn_index}: response language was not persisted"
                )
            snapshot = restored

            text = localized_text(
                str(turn.get("response_key") or ""),
                decision.language,
                **dict(turn.get("values") or {}),
            )
            if _wrong_language(text, expected_language):
                metrics["wrong_language_final_responses"] += 1
                case_failures.append(
                    f"turn {turn_index}: final response used the wrong language"
                )

            envelope = build_event_envelope(
                request_id=f"{case_id}-{turn_index}",
                conversation_id=snapshot.conversation_id,
                revision_id=None,
                payload={
                    "text": text,
                    "response_language": decision.language,
                },
            )
            metadata_language = envelope.get("payload", {}).get(
                "response_language"
            )
            if metadata_language != expected_language:
                metrics["missing_language_metadata"] += 1
                case_failures.append(
                    f"turn {turn_index}: SSE language metadata mismatch"
                )

            traces.append(
                {
                    "turn": turn_index,
                    "query": query,
                    "previous_language": previous_language,
                    "selected_language": decision.language,
                    "expected_language": expected_language,
                    "decision_source": decision.source,
                    "response_key": turn.get("response_key"),
                    "response_text": text,
                    "event_metadata": {
                        "response_language": metadata_language,
                    },
                }
            )

        case_results.append(
            {
                "case_id": case_id,
                "language_bucket": case.get("language_bucket"),
                "passed": not case_failures,
                "failures": case_failures,
                "turns": traces,
            }
        )

    bucket_counts = Counter(
        str(case.get("language_bucket") or "") for case in cases
    )
    passed_count = sum(1 for result in case_results if result["passed"])
    report = {
        "summary": {
            "case_count": len(cases),
            "passed_count": passed_count,
            "failed_count": len(cases) - passed_count,
            "turn_count": sum(len(case.get("turns") or []) for case in cases),
            "language_case_counts": {
                "en": bucket_counts.get("en", 0),
                "zh-CN": bucket_counts.get("zh-CN", 0),
            },
        },
        "metrics": metrics,
        "contract_errors": contract_errors,
        "cases": case_results,
    }
    report["passed"] = is_passing(report)
    return report


def is_passing(report: dict[str, Any]) -> bool:
    summary = report.get("summary") or {}
    metrics = report.get("metrics") or {}
    return (
        not report.get("contract_errors")
        and summary.get("case_count") == 20
        and summary.get("language_case_counts") == {"en": 10, "zh-CN": 10}
        and summary.get("failed_count") == 0
        and all(metrics.get(name) == 0 for name in HARD_METRICS)
    )


def _write_report(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary = report["summary"]
    lines = [
        "# Bilingual Conversation Core v1",
        "",
        f"- Result: {'PASS' if report['passed'] else 'FAIL'}",
        f"- Cases: {summary['passed_count']}/{summary['case_count']}",
        f"- Turns: {summary['turn_count']}",
        f"- Chinese cases: {summary['language_case_counts']['zh-CN']}",
        f"- English cases: {summary['language_case_counts']['en']}",
        "",
        "## Hard Metrics",
        "",
    ]
    lines.extend(
        f"- {name}: {report['metrics'][name]}" for name in HARD_METRICS
    )
    (output_dir / "report.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    report = evaluate_cases(load_cases(args.cases))
    _write_report(report, args.output_dir)
    summary = report["summary"]
    print(
        "bilingual conversation eval: "
        f"{summary['passed_count']}/{summary['case_count']} cases, "
        f"{summary['turn_count']} turns, "
        f"result={'PASS' if report['passed'] else 'FAIL'}"
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
