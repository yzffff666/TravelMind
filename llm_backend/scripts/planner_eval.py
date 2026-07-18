"""Deterministic offline acceptance tests for Constraint-aware POI Planner v1."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.services.itinerary_planner import ConstraintAwareItineraryPlanner
from app.services.providers.base import ProviderCandidate
from app.services.ranking_scorer import ScoredCandidate


DEFAULT_OUTPUT_ROOT = Path("reports/planner-eval")


@dataclass(frozen=True, slots=True)
class PlannerEvalCase:
    case_id: str
    candidates: tuple[ScoredCandidate, ...]
    days: int
    budget: float
    pace: str = "moderate"
    constraints: tuple[str, ...] = ()
    excluded_titles: tuple[str, ...] = ()
    anchor_location: tuple[float, float] | None = None
    expected_feasible: bool = True
    expected_slots_per_day: int | None = None
    forbidden_titles: tuple[str, ...] = ()


def _candidate(
    title: str,
    *,
    score: float,
    lat: float,
    lng: float,
    cost: float = 30,
    tags: tuple[str, ...] = ("文化",),
    snippet: str = "",
) -> ScoredCandidate:
    candidate = ProviderCandidate(
        candidate_id=f"eval-{title}",
        source="planner_eval",
        title=title,
        snippet=snippet or f"{title} 候选地点",
        score=score,
        tags=list(tags),
        extra={"lat": lat, "lng": lng, "cost_estimate": cost, "rating": 4.6, "address": f"{title}地址"},
    )
    return ScoredCandidate(candidate=candidate, total_score=score)


def _cluster(prefix: str, *, lat: float, lng: float, count: int, offset: float = 0.002) -> tuple[ScoredCandidate, ...]:
    return tuple(
        _candidate(f"{prefix}{index + 1}", score=0.95 - index * 0.02, lat=lat + index * offset, lng=lng + index * offset)
        for index in range(count)
    )


def default_cases() -> list[PlannerEvalCase]:
    compact = (*_cluster("老城", lat=31.230, lng=121.470, count=3), *_cluster("滨江", lat=31.128, lng=121.604, count=3))
    dense = _cluster("中心", lat=31.230, lng=121.470, count=9, offset=0.001)
    indoor = (
        _candidate("城市博物馆", score=0.95, lat=31.230, lng=121.470, tags=("室内", "博物馆", "文化")),
        _candidate("当代艺术馆", score=0.93, lat=31.231, lng=121.471, tags=("室内", "艺术", "文化")),
        _candidate("历史图书馆", score=0.91, lat=31.232, lng=121.472, tags=("室内", "图书馆", "文化")),
        _candidate("外滩", score=0.99, lat=31.240, lng=121.490, tags=("夜景", "地标"), snippet="户外江边地标"),
    )
    sparse = _cluster("稀疏", lat=31.230, lng=121.470, count=4)
    far = (
        *_cluster("近处", lat=31.230, lng=121.470, count=3),
        _candidate("远郊高分公园", score=0.99, lat=31.450, lng=121.700, tags=("自然",)),
    )
    return [
        PlannerEvalCase("compact_culture_2d", compact, days=2, budget=3000, expected_slots_per_day=3),
        PlannerEvalCase("relaxed_three_day", _cluster("慢游", lat=31.230, lng=121.470, count=6), days=3, budget=3000, pace="relaxed", expected_slots_per_day=2),
        PlannerEvalCase("intensive_three_day", dense, days=3, budget=5000, pace="intensive", expected_slots_per_day=3),
        PlannerEvalCase("indoor_only", indoor, days=1, budget=1000, constraints=("indoor",), forbidden_titles=("外滩",)),
        PlannerEvalCase(
            "generic_title_rejected",
            (
                _candidate("自由活动", score=0.99, lat=31.230, lng=121.470),
                *_cluster("可用", lat=31.230, lng=121.470, count=3),
            ),
            days=1,
            budget=1000,
            forbidden_titles=("自由活动",),
        ),
        PlannerEvalCase(
            "locked_day_exclusion",
            (
                _candidate("锁定博物馆", score=0.99, lat=31.230, lng=121.470, tags=("室内", "文化")),
                *_cluster("替换室内", lat=31.230, lng=121.470, count=3),
            ),
            days=1,
            budget=1000,
            excluded_titles=("锁定博物馆",),
            forbidden_titles=("锁定博物馆",),
        ),
        PlannerEvalCase(
            "budget_cap",
            (
                _candidate("昂贵主题乐园", score=0.99, lat=31.230, lng=121.470, cost=900),
                *_cluster("平价", lat=31.230, lng=121.470, count=3),
            ),
            days=1,
            budget=1000,
            expected_slots_per_day=3,
            forbidden_titles=("昂贵主题乐园",),
        ),
        PlannerEvalCase(
            "anchor_compactness",
            far,
            days=1,
            budget=1000,
            anchor_location=(31.230, 121.470),
            forbidden_titles=("远郊高分公园",),
        ),
        PlannerEvalCase("sparse_auto_pacing", sparse, days=3, budget=3000, expected_slots_per_day=1),
        PlannerEvalCase("insufficient_unique", _cluster("不足", lat=31.230, lng=121.470, count=2), days=3, budget=3000, expected_feasible=False),
        PlannerEvalCase(
            "indoor_impossible",
            _cluster("户外", lat=31.230, lng=121.470, count=3),
            days=1,
            budget=1000,
            constraints=("indoor",),
            expected_feasible=False,
        ),
        PlannerEvalCase(
            "distance_sparse_auto_pacing",
            (
                _candidate("北区", score=0.95, lat=31.230, lng=121.470),
                _candidate("南区", score=0.94, lat=31.020, lng=121.680),
                _candidate("西区", score=0.93, lat=31.300, lng=121.050),
                _candidate("东区", score=0.92, lat=31.100, lng=121.850),
            ),
            days=2,
            budget=3000,
            expected_slots_per_day=1,
        ),
    ]


def evaluate_case(case: PlannerEvalCase) -> dict[str, Any]:
    result = ConstraintAwareItineraryPlanner().plan(
        list(case.candidates),
        destination="评测城市",
        days=case.days,
        total_budget=case.budget,
        pace=case.pace,
        constraints=case.constraints,
        excluded_titles=case.excluded_titles,
        anchor_location=case.anchor_location,
    )
    errors: list[str] = []
    if result.feasible != case.expected_feasible:
        errors.append(f"expected feasible={case.expected_feasible}, got {result.feasible}")
    selected_titles: list[str] = []
    if result.skeleton:
        selected_titles = [selection.title for selection in result.skeleton.selections]
        if len(selected_titles) != len(set(selected_titles)):
            errors.append("duplicate POI selected")
        if len(result.skeleton.days) != case.days:
            errors.append("day count mismatch")
        if case.expected_slots_per_day is not None and result.skeleton.slots_per_day != case.expected_slots_per_day:
            errors.append(
                f"expected slots_per_day={case.expected_slots_per_day}, got {result.skeleton.slots_per_day}"
            )
        if any(
            selection.distance_from_previous_km is not None and selection.distance_from_previous_km > 18.0
            for selection in result.skeleton.selections
        ):
            errors.append("daily distance jump exceeded")
    forbidden = set(case.forbidden_titles)
    if forbidden & set(selected_titles):
        errors.append(f"forbidden POIs selected: {sorted(forbidden & set(selected_titles))}")
    return {
        "case_id": case.case_id,
        "status": "passed" if not errors else "failed",
        "expected_feasible": case.expected_feasible,
        "actual_feasible": result.feasible,
        "slots_per_day": result.skeleton.slots_per_day if result.skeleton else None,
        "selected_titles": selected_titles,
        "reason": result.reason,
        "elapsed_ms": round(result.elapsed_ms, 3),
        "errors": errors,
    }


def build_report(cases: list[PlannerEvalCase] | None = None) -> dict[str, Any]:
    results = [evaluate_case(case) for case in (cases or default_cases())]
    failures = [result for result in results if result["status"] != "passed"]
    return {
        "schema_version": "planner_eval_v1",
        "status": "passed" if not failures else "failed",
        "case_count": len(results),
        "passed_cases": len(results) - len(failures),
        "failed_cases": len(failures),
        "planner_p95_ms": _percentile([float(result["elapsed_ms"]) for result in results], 0.95),
        "failures": failures,
        "cases": results,
    }


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * percentile))
    return round(ordered[index], 3)


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Constraint-aware Planner Eval",
        "",
        f"- Status: `{report['status']}`",
        f"- Cases: {report['passed_cases']}/{report['case_count']} passed",
        f"- Planner P95: {report['planner_p95_ms']} ms",
        "",
        "| Case | Status | Feasible | Slots/day | Selected |",
        "| --- | --- | --- | --- | --- |",
    ]
    for case in report["cases"]:
        lines.append(
            f"| {case['case_id']} | {case['status']} | {case['actual_feasible']} | "
            f"{case['slots_per_day'] or '-'} | {', '.join(case['selected_titles']) or '-'} |"
        )
    if report["failures"]:
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- `{case['case_id']}`: {'; '.join(case['errors'])}" for case in report["failures"])
    lines.append("")
    return "\n".join(lines)


def write_outputs(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "planner-eval.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    (output_dir / "planner-eval.md").write_text(render_markdown(report), encoding="utf-8", newline="\n")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate Constraint-aware POI Planner.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = build_report()
    write_outputs(report, args.output_dir)
    print(f"planner_eval={report['status']} cases={report['passed_cases']}/{report['case_count']} p95={report['planner_p95_ms']}ms")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
