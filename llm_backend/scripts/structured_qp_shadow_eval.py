"""Run a bounded live shadow replay against the configured Structured QP model.

This is deliberately separate from CI: it uses the configured DeepSeek key but
never changes the effective QP result or itinerary state. The output is a small
JSON artifact suitable for comparing two manual shadow rounds.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any, Iterable

from app.core.config import settings
from app.domain.travel.query_processor import TravelQueryProcessor
from app.domain.travel.structured_qp import LLMStructuredQPStrategy, StructuredQPResult


DEFAULT_CASES_PATH = Path("evaluation/structured_qp_shadow_cases.jsonl")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip() and not line.lstrip().startswith("#")]


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * 0.95))]


class _RecordingStructuredQPStrategy:
    def __init__(self) -> None:
        self._delegate = LLMStructuredQPStrategy()
        self.call_count = 0
        self.elapsed_ms: list[float] = []
        self.results: list[StructuredQPResult] = []

    async def classify(self, query: str, *, context=None) -> StructuredQPResult:
        self.call_count += 1
        start = time.perf_counter()
        try:
            result = await self._delegate.classify(query, context=context)
        finally:
            self.elapsed_ms.append((time.perf_counter() - start) * 1000)
        self.results.append(result)
        return result


async def _evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    strategy = _RecordingStructuredQPStrategy()
    processor = TravelQueryProcessor(
        structured_strategy=strategy,
        structured_qp_mode="shadow",
    )
    started = time.perf_counter()
    actual = await processor.process_async(
        str(case["query"]),
        context=case.get("context"),
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    expected = case.get("expected") or {}
    errors: list[str] = []
    for key in ("intent", "intent_detail", "route_reason"):
        if key in expected and actual.get(key) != expected[key]:
            errors.append(f"{key}: expected {expected[key]!r}, got {actual.get(key)!r}")
    expected_calls = int(expected.get("model_calls") or 0)
    if strategy.call_count != expected_calls:
        errors.append(f"model_calls: expected {expected_calls}, got {strategy.call_count}")
    if expected_calls:
        if actual.get("qp_source") != "rule":
            errors.append(f"shadow must retain rule result, got qp_source={actual.get('qp_source')!r}")
        if actual.get("safety_level") != "safe":
            errors.append(
                f"unsafe shadow result: safety_level={actual.get('safety_level')!r}, "
                f"fallback_reason={actual.get('fallback_reason')!r}"
            )
        if actual.get("shadow_intent") != expected.get("shadow_intent"):
            errors.append(
                f"shadow_intent: expected {expected.get('shadow_intent')!r}, "
                f"got {actual.get('shadow_intent')!r}"
            )
        result = strategy.results[0] if strategy.results else None
        for key, value in (expected.get("shadow_constraints") or {}).items():
            actual_value = getattr(result.constraints, key, None) if result else None
            if actual_value != value:
                errors.append(f"shadow_constraints.{key}: expected {value!r}, got {actual_value!r}")

    return {
        "id": case["id"],
        "passed": not errors,
        "errors": errors,
        "elapsed_ms": round(elapsed_ms, 3),
        "model_calls": strategy.call_count,
        "model_elapsed_ms": round(strategy.elapsed_ms[0], 3) if strategy.elapsed_ms else None,
        "actual": {
            "intent": actual.get("intent"),
            "intent_detail": actual.get("intent_detail"),
            "route_reason": actual.get("route_reason"),
            "qp_source": actual.get("qp_source"),
            "safety_level": actual.get("safety_level"),
            "fallback_reason": actual.get("fallback_reason"),
            "shadow_intent": actual.get("shadow_intent"),
            "shadow_confidence": actual.get("shadow_confidence"),
        },
    }


async def evaluate_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [await _evaluate_case(case) for case in cases]
    failures = [row for row in rows if not row["passed"]]
    model_latencies = [float(row["model_elapsed_ms"]) for row in rows if row["model_elapsed_ms"] is not None]
    return {
        "schema_version": "structured_qp_shadow_eval_v1",
        "case_count": len(rows),
        "passed_cases": len(rows) - len(failures),
        "failed_cases": len(failures),
        "model_call_count": sum(int(row["model_calls"]) for row in rows),
        "model_p95_ms": round(_p95(model_latencies), 3),
        "model_timeout_ms": settings.STRUCTURED_QP_TIMEOUT_SECONDS * 1000,
        "rows": rows,
        "failures": failures,
    }


def is_passing(summary: dict[str, Any]) -> bool:
    return bool(
        summary["case_count"] >= 12
        and summary["failed_cases"] == 0
        and float(summary["model_p95_ms"]) <= float(summary["model_timeout_ms"])
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run bounded live Structured QP shadow replay.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    summary = asyncio.run(evaluate_cases(_load_jsonl(args.cases)))
    _write_json(args.output, summary)
    print(
        "Structured QP shadow: "
        f"{summary['passed_cases']}/{summary['case_count']} passed; "
        f"model_calls={summary['model_call_count']}; p95={summary['model_p95_ms']}ms"
    )
    return 0 if is_passing(summary) else 1


if __name__ == "__main__":
    raise SystemExit(main())
