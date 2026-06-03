"""Evaluate the deterministic TravelQueryProcessor rule baseline.

The script is intentionally offline: it does not call LLMs, providers, or the
FastAPI app. It turns QP/rule changes into a repeatable regression gate while
still allowing non-blocking known-gap cases to be tracked in the same dataset.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from app.domain.travel.query_processor import TravelQueryProcessor


DEFAULT_CASES_PATH = Path("evaluation/qp_rule_eval_cases.jsonl")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            payload = json.loads(stripped)
            payload.setdefault("_line", line_number)
            cases.append(payload)
    return cases


def _expected_matches(actual: dict[str, Any], expected: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    for key in ("intent", "intent_detail"):
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

    if "missing_required" in expected:
        actual_missing = list(actual.get("missing_required") or [])
        expected_missing = list(expected["missing_required"] or [])
        if actual_missing != expected_missing:
            errors.append(f"missing_required: expected {expected_missing!r}, got {actual_missing!r}")

    return not errors, errors


def evaluate_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    processor = TravelQueryProcessor(enable_structured_qp=False)
    rows: list[dict[str, Any]] = []
    by_category: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0})

    for case in cases:
        expected = case.get("expected") or {}
        actual = processor.process(str(case.get("query") or ""))
        strict = bool(case.get("strict", True))
        passed, errors = _expected_matches(actual, expected)
        category = str(case.get("category") or "uncategorized")
        by_category[category]["total"] += 1
        by_category[category]["passed" if passed else "failed"] += 1
        rows.append(
            {
                "id": case.get("id"),
                "category": category,
                "strict": strict,
                "passed": passed,
                "errors": errors,
                "query": case.get("query"),
                "note": case.get("note"),
                "expected": expected,
                "actual": {
                    "intent": actual.get("intent"),
                    "intent_detail": actual.get("intent_detail"),
                    "constraints": actual.get("constraints"),
                    "missing_required": actual.get("missing_required"),
                },
            }
        )

    strict_rows = [row for row in rows if row["strict"]]
    tracked_rows = [row for row in rows if not row["strict"]]
    strict_failures = [row for row in strict_rows if not row["passed"]]
    tracked_failures = [row for row in tracked_rows if not row["passed"]]
    return {
        "schema_version": "qp_rule_eval_v1",
        "total_cases": len(rows),
        "strict_cases": len(strict_rows),
        "strict_passed": len(strict_rows) - len(strict_failures),
        "strict_failed": len(strict_failures),
        "tracked_cases": len(tracked_rows),
        "tracked_mismatched": len(tracked_failures),
        "strict_accuracy": (len(strict_rows) - len(strict_failures)) / len(strict_rows) if strict_rows else None,
        "by_category": dict(sorted(by_category.items())),
        "failures": strict_failures,
        "tracked_mismatches": tracked_failures,
        "rows": rows,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _cell(value: Any) -> str:
    if value is None:
        return "-"
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# QP Rule Evaluation",
        "",
        f"- Total cases: {summary['total_cases']}",
        f"- Strict gate: {summary['strict_passed']}/{summary['strict_cases']} passed",
        f"- Strict accuracy: {summary['strict_accuracy']:.4f}" if summary["strict_accuracy"] is not None else "- Strict accuracy: -",
        f"- Tracked known-gap mismatches: {summary['tracked_mismatched']}/{summary['tracked_cases']}",
        "",
        "## By Category",
        "",
        "| Category | Total | Passed | Failed |",
        "|----------|-------|--------|--------|",
    ]
    for category, stats in summary["by_category"].items():
        lines.append(f"| {_cell(category)} | {stats['total']} | {stats['passed']} | {stats['failed']} |")

    if summary["failures"]:
        lines.extend(["", "## Strict Failures", "", "| Case | Expected | Actual | Errors |", "|------|----------|--------|--------|"])
        for row in summary["failures"]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _cell(row["id"]),
                        _cell(row["expected"]),
                        _cell(row["actual"]),
                        _cell("; ".join(row["errors"])),
                    ]
                )
                + " |"
            )

    if summary["tracked_mismatches"]:
        lines.extend(["", "## Tracked Known Gaps", "", "| Case | Query | Expected | Actual | Note |", "|------|-------|----------|--------|------|"])
        for row in summary["tracked_mismatches"]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _cell(row["id"]),
                        _cell(row["query"]),
                        _cell(row["expected"]),
                        _cell(row["actual"]),
                        _cell(row["note"]),
                    ]
                )
                + " |"
            )

    lines.append("")
    return "\n".join(lines)


def _write_markdown(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(summary), encoding="utf-8", newline="\n")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate TravelMind QP rule baseline against a JSONL case set.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH, help="QP evaluation JSONL cases.")
    parser.add_argument("--output", type=Path, help="Optional JSON summary output path.")
    parser.add_argument("--markdown-output", type=Path, help="Optional Markdown summary output path.")
    parser.add_argument("--allow-failures", action="store_true", help="Return 0 even when strict cases fail.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    cases = _load_jsonl(args.cases)
    summary = evaluate_cases(cases)
    if args.output:
        _write_json(args.output, summary)
    if args.markdown_output:
        _write_markdown(args.markdown_output, summary)

    print(
        "QP rule eval: "
        f"{summary['strict_passed']}/{summary['strict_cases']} strict passed; "
        f"{summary['tracked_mismatched']}/{summary['tracked_cases']} tracked known gaps mismatched"
    )
    if summary["strict_failed"] and not args.allow_failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
