"""Offline acceptance gate for Structured QP -> local replan command routing."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.travel.patch_engine import PatchOpType, apply_patch
from app.domain.travel.structured_edit_command import build_structured_edit_command


DEFAULT_CASES_PATH = Path("evaluation/structured_edit_replan_cases.json")


def _fixture_itinerary() -> dict[str, Any]:
    return {
        "schema_version": "itinerary.v1",
        "itinerary_id": "structured-edit-eval",
        "revision_id": "rev-base",
        "base_revision_id": None,
        "trip_profile": {"destination_city": "上海", "constraints": {"preferences": ["文化"]}},
        "days": [
            {
                "day_index": day_index,
                "theme": f"第{day_index}天",
                "slots": [
                    {"slot": "上午", "activity": f"第{day_index}天上午", "place": f"地点{day_index}A"},
                    {"slot": "下午", "activity": f"第{day_index}天下午", "place": f"地点{day_index}B"},
                    {"slot": "晚上", "activity": f"第{day_index}天晚上", "place": f"地点{day_index}C"},
                ],
            }
            for day_index in range(1, 4)
        ],
        "budget_summary": {"total_estimate": 6000},
        "validation": {"assumptions": []},
    }


def load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Structured edit evaluation cases must be a JSON list")
    return payload


def evaluate_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    accepted_cases = 0
    rejected_cases = 0
    for case in cases:
        expected = case.get("expected") or {}
        should_accept = bool(expected.get("accepted"))
        itinerary = _fixture_itinerary()
        original_days = itinerary["days"]
        command = build_structured_edit_command(
            case.get("qp_output"),
            utterance=str(case.get("utterance") or ""),
            current_itinerary=itinerary,
        )
        passed = (command is not None) == should_accept
        details: dict[str, Any] = {}
        if command is not None:
            accepted_cases += 1
            op = command.to_patch_op()
            patch_result = apply_patch(itinerary, [op])
            details = {
                "target_day": command.target_day,
                "target_slot": command.target_slot,
                "constraints": list(command.constraints),
                "patch_success": patch_result.success,
                "patch_op": op.op.value,
            }
            passed = passed and patch_result.success and op.op == PatchOpType.REPLAN_DAY
            passed = passed and patch_result.new_itinerary is not None and patch_result.new_itinerary["days"] == original_days
            for key in ("target_day", "target_slot", "constraints"):
                if key in expected and details[key] != expected[key]:
                    passed = False
        else:
            rejected_cases += 1
            details = {"command": None}
        if not passed:
            failures.append({
                "case_id": case.get("case_id"),
                "expected": expected,
                "actual": details,
            })

    total_cases = len(cases)
    passed_cases = total_cases - len(failures)
    return {
        "case_count": total_cases,
        "passed_cases": passed_cases,
        "failed_cases": len(failures),
        "accepted_cases": accepted_cases,
        "rejected_cases": rejected_cases,
        "unsafe_revision_failures": sum(
            1
            for failure in failures
            if (failure.get("expected") or {}).get("accepted") is False
        ),
        "failures": failures,
    }


def is_passing(summary: dict[str, Any]) -> bool:
    return (
        int(summary.get("case_count") or 0) >= 15
        and int(summary.get("failed_cases") or 0) == 0
        and int(summary.get("unsafe_revision_failures") or 0) == 0
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    summary = evaluate_cases(load_cases(args.cases))
    payload = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if is_passing(summary) else 1


if __name__ == "__main__":
    raise SystemExit(main())
