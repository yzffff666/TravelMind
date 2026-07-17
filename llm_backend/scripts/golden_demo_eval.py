"""Golden demo regression gate for TravelMind.

This evaluator captures user-visible scenarios that are risky in demos:
create queries should not loop clarification, QA should stay read-only, day
edits should become structured replans, and destination bounds should reject
obvious cross-city POIs.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.domain.travel.patch_engine import has_mutation_intent, parse_edit_ops
from app.domain.travel.query_processor import TravelQueryProcessor
from app.services.geo_bounds import is_coord_within_destination


DEFAULT_CASES_PATH = Path("evaluation/golden_demo_cases.json")
DEFAULT_OUTPUT_ROOT = Path("reports/golden-demo-eval")


def _make_itinerary(days: int = 3) -> dict[str, Any]:
    return {
        "schema_version": "itinerary.v1",
        "itinerary_id": "golden-demo-itinerary",
        "revision_id": "rev-golden-demo",
        "trip_profile": {
            "destination_city": "澳门",
            "constraints": {"preferences": ["文化", "美食"]},
        },
        "days": [
            {
                "day_index": i,
                "theme": f"第{i}天",
                "slots": [
                    {"slot": "上午", "activity": f"Day{i} 上午", "place": f"POI{i}A"},
                    {"slot": "下午", "activity": f"Day{i} 下午", "place": f"POI{i}B"},
                    {"slot": "晚上", "activity": f"Day{i} 晚上", "place": f"POI{i}C"},
                ],
            }
            for i in range(1, days + 1)
        ],
        "budget_summary": {"total_estimate": 5000},
        "validation": {"assumptions": []},
    }


@dataclass(slots=True)
class GoldenCaseResult:
    case_id: str
    type: str
    status: str
    errors: list[str]
    actual: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "type": self.type,
            "status": self.status,
            "errors": self.errors,
            "actual": self.actual,
        }


def load_cases(path: Path = DEFAULT_CASES_PATH) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("golden demo cases must be a JSON list")
    return payload


def _match_expected(actual: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("intent", "intent_detail", "missing_required"):
        if key in expected and actual.get(key) != expected[key]:
            errors.append(f"{key}: expected {expected[key]!r}, got {actual.get(key)!r}")

    expected_constraints = expected.get("constraints") or {}
    actual_constraints = actual.get("constraints") or {}
    for key, expected_value in expected_constraints.items():
        actual_value = actual_constraints.get(key)
        if isinstance(expected_value, float):
            try:
                actual_number = float(actual_value)
            except (TypeError, ValueError):
                errors.append(f"constraints.{key}: expected {expected_value!r}, got {actual_value!r}")
                continue
            if abs(actual_number - expected_value) > 1e-6:
                errors.append(f"constraints.{key}: expected {expected_value!r}, got {actual_value!r}")
        elif actual_value != expected_value:
            errors.append(f"constraints.{key}: expected {expected_value!r}, got {actual_value!r}")
    return errors


def _eval_qp(case: dict[str, Any], processor: TravelQueryProcessor) -> GoldenCaseResult:
    actual = processor.process(str(case.get("query") or ""))
    compact_actual = {
        "intent": actual.get("intent"),
        "intent_detail": actual.get("intent_detail"),
        "constraints": actual.get("constraints") or {},
        "missing_required": actual.get("missing_required") or [],
    }
    errors = _match_expected(compact_actual, case.get("expected") or {})
    return GoldenCaseResult(
        case_id=str(case.get("case_id")),
        type="qp",
        status="passed" if not errors else "failed",
        errors=errors,
        actual=compact_actual,
    )


def _eval_patch(case: dict[str, Any]) -> GoldenCaseResult:
    utterance = str(case.get("utterance") or "")
    itinerary = _make_itinerary()
    ops = parse_edit_ops(utterance, itinerary)
    actual_ops = [
        {
            "op": op.op.value,
            "day_index": op.day_index,
            "slot_label": op.slot_label,
            "constraints": list(op.payload.get("constraints") or []),
        }
        for op in ops
    ]
    actual = {
        "has_mutation_intent": has_mutation_intent(utterance),
        "ops": actual_ops,
    }
    expected = case.get("expected") or {}
    errors: list[str] = []
    if "has_mutation_intent" in expected and actual["has_mutation_intent"] != expected["has_mutation_intent"]:
        errors.append(
            "has_mutation_intent: expected "
            f"{expected['has_mutation_intent']!r}, got {actual['has_mutation_intent']!r}"
        )
    expected_ops = list(expected.get("ops") or [])
    if len(actual_ops) != len(expected_ops):
        errors.append(f"ops length: expected {len(expected_ops)}, got {len(actual_ops)}")
    for index, expected_op in enumerate(expected_ops):
        if index >= len(actual_ops):
            break
        actual_op = actual_ops[index]
        for key in ("op", "day_index", "slot_label"):
            if key in expected_op and actual_op.get(key) != expected_op[key]:
                errors.append(f"ops[{index}].{key}: expected {expected_op[key]!r}, got {actual_op.get(key)!r}")
        for constraint in expected_op.get("constraints_contains") or []:
            if constraint not in actual_op.get("constraints", []):
                errors.append(f"ops[{index}].constraints missing {constraint!r}")

    return GoldenCaseResult(
        case_id=str(case.get("case_id")),
        type="patch",
        status="passed" if not errors else "failed",
        errors=errors,
        actual=actual,
    )


def _eval_bbox(case: dict[str, Any]) -> GoldenCaseResult:
    destination = str(case.get("destination") or "")
    errors: list[str] = []
    accepted_results: list[dict[str, Any]] = []
    rejected_results: list[dict[str, Any]] = []
    for coord in case.get("accepted") or []:
        ok = is_coord_within_destination(destination, float(coord["lat"]), float(coord["lng"]))
        accepted_results.append({**coord, "within_destination": ok})
        if not ok:
            errors.append(f"accepted coord rejected: {coord}")
    for coord in case.get("rejected") or []:
        ok = is_coord_within_destination(destination, float(coord["lat"]), float(coord["lng"]))
        rejected_results.append({**coord, "within_destination": ok})
        if ok:
            errors.append(f"rejected coord accepted: {coord}")

    return GoldenCaseResult(
        case_id=str(case.get("case_id")),
        type="bbox",
        status="passed" if not errors else "failed",
        errors=errors,
        actual={"destination": destination, "accepted": accepted_results, "rejected": rejected_results},
    )


def evaluate_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    processor = TravelQueryProcessor(enable_structured_qp=False)
    results: list[GoldenCaseResult] = []
    for case in cases:
        case_type = str(case.get("type") or "")
        if case_type == "qp":
            results.append(_eval_qp(case, processor))
        elif case_type == "patch":
            results.append(_eval_patch(case))
        elif case_type == "bbox":
            results.append(_eval_bbox(case))
        else:
            results.append(
                GoldenCaseResult(
                    case_id=str(case.get("case_id") or "unknown"),
                    type=case_type or "unknown",
                    status="failed",
                    errors=[f"unsupported case type: {case_type!r}"],
                    actual={},
                )
            )

    failed = [item for item in results if item.status != "passed"]
    by_type: dict[str, dict[str, int]] = {}
    for result in results:
        stats = by_type.setdefault(result.type, {"total": 0, "passed": 0, "failed": 0})
        stats["total"] += 1
        stats["passed" if result.status == "passed" else "failed"] += 1
    return {
        "schema_version": "golden_demo_eval_v1",
        "status": "passed" if not failed else "failed",
        "case_count": len(results),
        "passed_cases": len(results) - len(failed),
        "failed_cases": len(failed),
        "by_type": dict(sorted(by_type.items())),
        "failures": [item.to_dict() for item in failed],
        "cases": [item.to_dict() for item in results],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# TravelMind Golden Demo Eval",
        "",
        f"- Status: `{report['status']}`",
        f"- Cases: {report['passed_cases']}/{report['case_count']} passed",
        "",
        "| Type | Total | Passed | Failed |",
        "| --- | --- | --- | --- |",
    ]
    for case_type, stats in (report.get("by_type") or {}).items():
        lines.append(f"| {case_type} | {stats['total']} | {stats['passed']} | {stats['failed']} |")

    if report.get("failures"):
        lines.extend(["", "## Failures", "", "| Case | Type | Errors |", "| --- | --- | --- |"])
        for failure in report["failures"]:
            errors = "; ".join(failure.get("errors") or [])
            lines.append(f"| {failure['case_id']} | {failure['type']} | {errors} |")
    lines.append("")
    return "\n".join(lines)


def write_outputs(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "golden-demo-eval.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (output_dir / "golden-demo-eval.md").write_text(
        render_markdown(report),
        encoding="utf-8",
        newline="\n",
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run TravelMind golden demo evaluation.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT / "latest")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(list(argv) if argv is not None else None)

    report = evaluate_cases(load_cases(args.cases))
    write_outputs(report, args.output_dir)
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            "golden_demo_eval={status} cases={passed}/{total} artifacts={artifacts}".format(
                status=report["status"],
                passed=report["passed_cases"],
                total=report["case_count"],
                artifacts=args.output_dir,
            )
        )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
