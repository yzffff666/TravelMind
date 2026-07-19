"""Offline acceptance gate for Hybrid Structured QP routing.

The evaluation uses fixture Structured QP responses instead of a live LLM. It
therefore validates the deterministic part we own: routing, schema merge,
fallback behavior, and the no-unsafe-mutation policy without spending API quota.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from app.domain.travel.query_processor import TravelQueryProcessor
from app.domain.travel.structured_qp import StructuredQPResult


DEFAULT_CASES_PATH = Path("evaluation/hybrid_qp_holdout_cases.jsonl")
MAX_ROUTING_P95_MS = 50.0


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            raw = line.strip()
            if raw and not raw.startswith("#"):
                payload = json.loads(raw)
                payload.setdefault("_line", line_number)
                cases.append(payload)
    return cases


class _FixtureStructuredQPStrategy:
    def __init__(self, fixture: dict[str, Any] | None) -> None:
        self.fixture = fixture or {}
        self.call_count = 0

    async def classify(self, query: str, *, context=None) -> StructuredQPResult:  # noqa: ARG002
        self.call_count += 1
        if self.fixture.get("exception"):
            raise RuntimeError(str(self.fixture["exception"]))
        return StructuredQPResult.model_validate(self.fixture)


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * 0.95))
    return ordered[index]


def _matches(actual: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in (
        "intent",
        "intent_detail",
        "qp_source",
        "structured_qp_mode",
        "route_reason",
        "safety_level",
        "fallback_reason",
    ):
        if key in expected and actual.get(key) != expected[key]:
            errors.append(f"{key}: expected {expected[key]!r}, got {actual.get(key)!r}")

    expected_constraints = expected.get("constraints") or {}
    actual_constraints = actual.get("constraints") or {}
    for key, value in expected_constraints.items():
        if actual_constraints.get(key) != value:
            errors.append(
                f"constraints.{key}: expected {value!r}, got {actual_constraints.get(key)!r}"
            )
    return errors


def evaluate_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    timings: list[float] = []
    categories: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0})

    for case in cases:
        strategy = _FixtureStructuredQPStrategy(case.get("structured_result"))
        processor = TravelQueryProcessor(
            structured_strategy=strategy,
            structured_qp_mode=str(case.get("mode") or "selective"),
            confidence_threshold=float(case.get("confidence_threshold") or 0.65),
        )
        start = time.perf_counter()
        actual = asyncio.run(
            processor.process_async(
                str(case.get("query") or ""),
                context=case.get("context"),
            )
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        timings.append(elapsed_ms)
        expected = case.get("expected") or {}
        errors = _matches(actual, expected)
        expected_calls = int(case.get("expected_model_calls") or 0)
        if strategy.call_count != expected_calls:
            errors.append(f"model_calls: expected {expected_calls}, got {strategy.call_count}")
        passed = not errors
        category = str(case.get("category") or "uncategorized")
        categories[category]["total"] += 1
        categories[category]["passed" if passed else "failed"] += 1
        rows.append(
            {
                "id": case.get("id"),
                "category": category,
                "critical_safety": bool(case.get("critical_safety")),
                "passed": passed,
                "errors": errors,
                "elapsed_ms": round(elapsed_ms, 3),
                "expected_model_calls": expected_calls,
                "actual_model_calls": strategy.call_count,
                "expected": expected,
                "actual": {
                    "intent": actual.get("intent"),
                    "intent_detail": actual.get("intent_detail"),
                    "qp_source": actual.get("qp_source"),
                    "structured_qp_mode": actual.get("structured_qp_mode"),
                    "route_reason": actual.get("route_reason"),
                    "safety_level": actual.get("safety_level"),
                    "fallback_reason": actual.get("fallback_reason"),
                    "constraints": actual.get("constraints"),
                },
            }
        )

    failures = [row for row in rows if not row["passed"]]
    critical_rows = [row for row in rows if row["critical_safety"]]
    critical_failures = [row for row in critical_rows if not row["passed"]]
    p95_ms = _p95(timings)
    return {
        "schema_version": "hybrid_qp_eval_v1",
        "case_count": len(rows),
        "passed_cases": len(rows) - len(failures),
        "failed_cases": len(failures),
        "critical_safety_cases": len(critical_rows),
        "critical_safety_passed": len(critical_rows) - len(critical_failures),
        "critical_safety_failed": len(critical_failures),
        "routing_p95_ms": round(p95_ms, 3),
        "routing_p95_target_ms": MAX_ROUTING_P95_MS,
        "by_category": dict(sorted(categories.items())),
        "failures": failures,
        "rows": rows,
    }


def is_passing(summary: dict[str, Any]) -> bool:
    return bool(
        summary["case_count"] >= 30
        and summary["failed_cases"] == 0
        and summary["critical_safety_failed"] == 0
        and float(summary["routing_p95_ms"]) < MAX_ROUTING_P95_MS
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate Hybrid Structured QP routing and safety behavior.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(list(argv) if argv is not None else None)
    summary = evaluate_cases(_load_jsonl(args.cases))
    if args.output:
        _write_json(args.output, summary)
    print(
        "Hybrid QP eval: "
        f"{summary['passed_cases']}/{summary['case_count']} passed; "
        f"critical={summary['critical_safety_passed']}/{summary['critical_safety_cases']}; "
        f"routing_p95={summary['routing_p95_ms']}ms"
    )
    return 0 if is_passing(summary) else 1


if __name__ == "__main__":
    raise SystemExit(main())
