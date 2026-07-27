"""Deterministic acceptance gate for destination-safe itinerary inputs.

This evaluator is deliberately not a provider benchmark. It uses fixture
profiles and POIs to verify the product contract before a candidate reaches
the LLM: local coordinates are required, cross-city decoys are rejected, and
evidence/media coverage is visible as a separate quality signal.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.services.destination_grounding import (
    DestinationProfile,
    DestinationResolver,
    filter_candidates_for_destination,
    has_valid_coordinates,
)
from app.services.providers.base import ProviderCandidate


DEFAULT_CASES_PATH = Path("evaluation/destination_readiness_cases.json")
DEFAULT_OUTPUT_ROOT = Path("reports/destination-readiness-eval")
MIN_PUBLISHABLE_CANDIDATES = 3
MIN_EVIDENCE_COVERAGE = 0.67
MIN_IMAGE_COVERAGE = 0.67


_DEFAULT_DECOYS = (
    {
        "candidate_id": "tokyo_tower",
        "title": "Tokyo Tower",
        "lat": 35.6586,
        "lng": 139.7454,
        "city": "Tokyo",
    },
    {
        "candidate_id": "kyoto_station",
        "title": "Kyoto Station",
        "lat": 34.9858,
        "lng": 135.7580,
        "city": "Kyoto",
    },
    {
        "candidate_id": "eiffel_tower",
        "title": "Eiffel Tower",
        "lat": 48.8584,
        "lng": 2.2945,
        "city": "Paris",
    },
    {
        "candidate_id": "bund",
        "title": "外滩",
        "lat": 31.2400,
        "lng": 121.4900,
        "city": "上海市",
    },
)


@dataclass
class FixtureLookup:
    cases: dict[str, dict[str, Any]]
    name: str = "fixture_destination_geocoder"

    async def lookup(self, destination: str) -> DestinationProfile | None:
        case = self.cases.get(destination)
        if case is None or case.get("profile_mode") != "dynamic":
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
        raise ValueError("destination readiness cases must be a JSON list")
    return payload


def _candidate(payload: dict[str, Any], *, default_id: str) -> ProviderCandidate:
    extra: dict[str, Any] = {"city": str(payload.get("city") or "")}
    if payload.get("lat") is not None:
        extra["lat"] = float(payload["lat"])
    if payload.get("lng") is not None:
        extra["lng"] = float(payload["lng"])
    if payload.get("evidence"):
        title = str(payload.get("title") or default_id)
        extra.update(
            {
                "url": f"https://example.test/poi/{default_id}",
                "address": f"{extra['city']} {title}",
                "rating": 4.5,
            }
        )
    if payload.get("image"):
        extra["photos"] = [f"https://images.example.test/poi/{default_id}.jpg"]
    return ProviderCandidate(
        candidate_id=str(payload.get("candidate_id") or default_id),
        source="fixture_map",
        title=str(payload.get("title") or default_id),
        snippet=f"Fixture evidence for {payload.get('title') or default_id}" if payload.get("evidence") else "",
        score=0.9,
        tags=["travel"],
        extra=extra,
    )


def _has_evidence(candidate: ProviderCandidate) -> bool:
    return bool(
        candidate.title
        and candidate.snippet
        and candidate.extra.get("url")
        and candidate.extra.get("address")
    )


def _has_image(candidate: ProviderCandidate) -> bool:
    photos = candidate.extra.get("photos") or []
    return bool(candidate.extra.get("image_url") or candidate.extra.get("thumbnail") or photos)


def _quality_status(candidates: list[ProviderCandidate], *, outcome: str) -> tuple[str, dict[str, float], list[str]]:
    if outcome != "ready":
        return "not_applicable", {"evidence_coverage": 0.0, "image_coverage": 0.0}, []
    total = len(candidates)
    evidence_coverage = sum(_has_evidence(candidate) for candidate in candidates) / total
    image_coverage = sum(_has_image(candidate) for candidate in candidates) / total
    flags: list[str] = []
    if evidence_coverage < MIN_EVIDENCE_COVERAGE:
        flags.append("low_evidence_coverage")
    if image_coverage < MIN_IMAGE_COVERAGE:
        flags.append("low_image_coverage")
    return (
        "ready" if not flags else "quality_degraded",
        {
            "evidence_coverage": round(evidence_coverage, 3),
            "image_coverage": round(image_coverage, 3),
        },
        flags,
    )


def _decoys(case: dict[str, Any]) -> list[ProviderCandidate]:
    excluded = set(case.get("exclude_default_decoys") or [])
    return [
        _candidate(payload, default_id=str(payload["candidate_id"]))
        for payload in _DEFAULT_DECOYS
        if payload["candidate_id"] not in excluded
    ]


async def _evaluate_case(case: dict[str, Any], resolver: DestinationResolver) -> dict[str, Any]:
    destination = str(case["destination"])
    profile = await resolver.resolve(destination)
    local_candidates = [
        _candidate(payload, default_id=f"{case['case_id']}-local-{index}")
        for index, payload in enumerate(case.get("locals") or [], start=1)
    ]
    legacy_candidates = [
        _candidate(payload, default_id=f"{case['case_id']}-legacy-{index}")
        for index, payload in enumerate(case.get("legacy_no_geo") or [], start=1)
    ]
    decoys = _decoys(case)
    accepted, decisions = filter_candidates_for_destination(
        [*local_candidates, *legacy_candidates, *decoys],
        profile,
    )
    publishable = [candidate for candidate in accepted if has_valid_coordinates(candidate)]
    local_titles = {candidate.title for candidate in local_candidates if has_valid_coordinates(candidate)}
    publishable_titles = {candidate.title for candidate in publishable}
    decoy_titles = {candidate.title for candidate in decoys}
    accepted_decoy_titles = sorted(decoy_titles.intersection(publishable_titles))
    actual_outcome = "ready" if len(publishable) >= MIN_PUBLISHABLE_CANDIDATES else "insufficient_candidates"
    quality_status, coverage, quality_flags = _quality_status(publishable, outcome=actual_outcome)
    reject_counts = Counter(decision.reason for decision in decisions if not decision.accepted)
    errors: list[str] = []

    if not profile.resolved:
        errors.append("destination profile did not resolve")
    if profile.is_dynamic != (case.get("profile_mode") == "dynamic"):
        errors.append("profile mode mismatch")
    if publishable_titles != local_titles:
        errors.append(
            "publishable candidates mismatch: "
            f"expected={sorted(local_titles)} actual={sorted(publishable_titles)}"
        )
    if accepted_decoy_titles:
        errors.append(f"cross-city decoys were publishable: {accepted_decoy_titles}")
    if any(not has_valid_coordinates(candidate) for candidate in publishable):
        errors.append("coordinate-less candidate became publishable")
    if actual_outcome != case["expected_outcome"]:
        errors.append(f"expected {case['expected_outcome']}, got {actual_outcome}")
    if quality_status != case["expected_quality_status"]:
        errors.append(f"expected quality {case['expected_quality_status']}, got {quality_status}")

    return {
        "case_id": case["case_id"],
        "destination": destination,
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "profile_mode": case["profile_mode"],
        "profile": profile.to_dict(),
        "expected_outcome": case["expected_outcome"],
        "actual_outcome": actual_outcome,
        "expected_quality_status": case["expected_quality_status"],
        "quality_status": quality_status,
        "quality_flags": quality_flags,
        "coverage": coverage,
        "publishable_candidate_count": len(publishable),
        "publishable_titles": sorted(publishable_titles),
        "legacy_accepted_count": sum(candidate in accepted for candidate in legacy_candidates),
        "reject_reason_counts": dict(reject_counts),
    }


async def _evaluate_all(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    resolver = DestinationResolver(
        lookups=[FixtureLookup({str(case["destination"]): case for case in cases})]
    )
    return [await _evaluate_case(case, resolver) for case in cases]


def build_report(cases: list[dict[str, Any]]) -> dict[str, Any]:
    results = asyncio.run(_evaluate_all(cases))
    failures = [result for result in results if result["status"] != "passed"]
    ready = [result for result in results if result["actual_outcome"] == "ready"]
    safe_degraded = [result for result in results if result["actual_outcome"] == "insufficient_candidates"]
    dynamic = [result for result in results if result["profile_mode"] == "dynamic"]
    return {
        "schema_version": "destination_readiness_eval_v1",
        "status": "passed" if not failures else "failed",
        "case_count": len(results),
        "passed_cases": len(results) - len(failures),
        "failed_cases": len(failures),
        "ready_cases": len(ready),
        "safe_degradation_cases": len(safe_degraded),
        "dynamic_cases": len(dynamic),
        "static_cases": len(results) - len(dynamic),
        "failures": failures,
        "cases": results,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Destination Readiness Eval",
        "",
        f"- Status: `{report['status']}`",
        f"- Cases: {report['passed_cases']}/{report['case_count']} passed",
        f"- Ready: {report['ready_cases']}; safe degradation: {report['safe_degradation_cases']}",
        f"- Static/dynamic: {report['static_cases']}/{report['dynamic_cases']}",
        "",
        "| Case | Destination | Outcome | Quality | Candidates | Status |",
        "| --- | --- | --- | --- | ---: | --- |",
    ]
    for case in report["cases"]:
        lines.append(
            f"| {case['case_id']} | {case['destination']} | {case['actual_outcome']} | "
            f"{case['quality_status']} | {case['publishable_candidate_count']} | {case['status']} |"
        )
    if report["failures"]:
        lines.extend(["", "## Failures", ""])
        for failure in report["failures"]:
            lines.append(f"- `{failure['case_id']}`: {'; '.join(failure['errors'])}")
    lines.append("")
    return "\n".join(lines)


def write_outputs(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "destination-readiness-eval.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (output_dir / "destination-readiness-eval.md").write_text(
        render_markdown(report), encoding="utf-8", newline="\n"
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate destination readiness without live provider calls.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = build_report(load_cases(args.cases))
    write_outputs(report, args.output_dir)
    print(
        f"destination_readiness_eval={report['status']} "
        f"cases={report['passed_cases']}/{report['case_count']}"
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
