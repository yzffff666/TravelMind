"""Offline acceptance gate for dynamic destination grounding.

The cases are intentionally absent from ``geo_bounds.py``.  The evaluator
uses a fixture geocoder only to make the contract deterministic: production
must resolve the same profile through Amap/Geoapify rather than a new city map.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.services.destination_grounding import (
    DestinationProfile,
    DestinationResolver,
    filter_candidates_for_destination,
)
from app.services.geo_bounds import destination_bounds
from app.services.providers.base import ProviderCandidate


DEFAULT_CASES_PATH = Path("evaluation/unseen_destination_cases.json")
DEFAULT_OUTPUT_ROOT = Path("reports/unseen-destination-eval")


@dataclass
class FixtureLookup:
    cases: dict[str, dict[str, Any]]
    name: str = "fixture_geocoder"

    async def lookup(self, destination: str) -> DestinationProfile | None:
        case = self.cases.get(destination)
        if case is None:
            return None
        center = case["center"]
        return DestinationProfile(
            requested_name=destination,
            canonical_name=str(case["canonical_name"]),
            country=str(case["country"]),
            center_lat=float(center[0]),
            center_lng=float(center[1]),
            radius_km=45.0,
            confidence=0.92,
            source=self.name,
            is_dynamic=True,
        )


def load_cases(path: Path = DEFAULT_CASES_PATH) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("unseen destination cases must be a JSON list")
    return payload


def _candidate(title: str, lat: float, lng: float, city: str) -> ProviderCandidate:
    return ProviderCandidate(
        candidate_id=f"fixture-{title}",
        source="fixture_map",
        title=title,
        score=0.9,
        tags=["travel"],
        extra={"lat": lat, "lng": lng, "city": city, "address": f"{city} {title}"},
    )


def _decoys() -> list[ProviderCandidate]:
    return [
        _candidate("Tokyo Tower", 35.6586, 139.7454, "Tokyo"),
        _candidate("Eiffel Tower", 48.8584, 2.2945, "Paris"),
    ]


async def _evaluate_case(case: dict[str, Any], resolver: DestinationResolver) -> dict[str, Any]:
    destination = str(case["destination"])
    profile = await resolver.resolve(destination)
    locals_ = [
        _candidate(str(title), float(lat), float(lng), str(city))
        for title, lat, lng, city in case.get("locals") or []
    ]
    accepted, decisions = filter_candidates_for_destination([*locals_, *_decoys()], profile)
    local_titles = {candidate.title for candidate in locals_}
    accepted_titles = {candidate.title for candidate in accepted}
    errors: list[str] = []
    if destination_bounds(destination) is not None:
        errors.append("test destination must not have a static production bbox")
    if not profile.resolved or not profile.is_dynamic:
        errors.append("destination did not resolve dynamically")
    if profile.canonical_name != case["canonical_name"]:
        errors.append("canonical_name mismatch")
    if profile.country != case["country"]:
        errors.append("country mismatch")
    if accepted_titles != local_titles:
        errors.append(f"accepted candidates mismatch: {sorted(accepted_titles)}")
    rejected_decoys = [decision for decision in decisions[len(locals_) :] if not decision.accepted]
    if len(rejected_decoys) != len(_decoys()):
        errors.append("cross-city decoy was accepted")
    expected = str(case["expected_outcome"])
    actual_outcome = "ready" if len(accepted) >= 3 else "insufficient_candidates"
    if actual_outcome != expected:
        errors.append(f"expected {expected}, got {actual_outcome}")
    return {
        "case_id": case["case_id"],
        "destination": destination,
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "expected_outcome": expected,
        "actual_outcome": actual_outcome,
        "profile": profile.to_dict(),
        "accepted_titles": sorted(accepted_titles),
        "reject_reasons": [decision.reason for decision in decisions if not decision.accepted],
    }


async def _evaluate_all(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    resolver = DestinationResolver(lookups=[FixtureLookup({str(case["destination"]): case for case in cases})])
    return [await _evaluate_case(case, resolver) for case in cases]


def build_report(cases: list[dict[str, Any]]) -> dict[str, Any]:
    results = asyncio.run(_evaluate_all(cases))
    failures = [result for result in results if result["status"] != "passed"]
    ready_cases = [result for result in results if result["expected_outcome"] == "ready"]
    insufficient_cases = [result for result in results if result["expected_outcome"] == "insufficient_candidates"]
    return {
        "schema_version": "unseen_destination_eval_v1",
        "status": "passed" if not failures else "failed",
        "case_count": len(results),
        "passed_cases": len(results) - len(failures),
        "failed_cases": len(failures),
        "ready_cases": len(ready_cases),
        "insufficient_candidate_cases": len(insufficient_cases),
        "failures": failures,
        "cases": results,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Unseen Destination Grounding Eval",
        "",
        f"- Status: `{report['status']}`",
        f"- Cases: {report['passed_cases']}/{report['case_count']} passed",
        f"- Ready: {report['ready_cases']}; safe insufficient-candidate cases: {report['insufficient_candidate_cases']}",
        "",
        "| Case | Destination | Expected | Actual | Status |",
        "| --- | --- | --- | --- | --- |",
    ]
    for case in report["cases"]:
        lines.append(
            f"| {case['case_id']} | {case['destination']} | {case['expected_outcome']} | "
            f"{case['actual_outcome']} | {case['status']} |"
        )
    if report["failures"]:
        lines.extend(["", "## Failures", ""])
        for failure in report["failures"]:
            lines.append(f"- `{failure['case_id']}`: {'; '.join(failure['errors'])}")
    lines.append("")
    return "\n".join(lines)


def write_outputs(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "unseen-destination-eval.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (output_dir / "unseen-destination-eval.md").write_text(
        render_markdown(report), encoding="utf-8", newline="\n"
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate unseen destination grounding.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = build_report(load_cases(args.cases))
    write_outputs(report, args.output_dir)
    print(
        f"unseen_destination_eval={report['status']} "
        f"cases={report['passed_cases']}/{report['case_count']}"
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
