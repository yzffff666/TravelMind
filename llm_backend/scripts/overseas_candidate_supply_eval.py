"""Deterministic replay gate for overseas provider-shaped candidate supply."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Iterable

from app.services.candidate_publishability import evaluate_candidate_publishability
from app.services.destination_grounding import (
    DestinationProfile,
    GeoapifyDestinationLookup,
)
from app.services.geo_bounds import destination_bounds
from app.services.providers.base import ProviderCandidate, ProviderResponse
from app.services.providers.geoapify_provider import (
    _candidate_from_item,
    _iter_place_features,
)


DEFAULT_CASES_PATH = Path("evaluation/overseas_candidate_supply_cases.json")
DEFAULT_OUTPUT_ROOT = Path("reports/overseas-candidate-supply-eval")
REQUIRED_CANDIDATES = 3


def load_cases(path: Path = DEFAULT_CASES_PATH) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("overseas candidate supply cases must be a JSON list")
    return payload


def _geocode_candidates(
    items: list[dict[str, Any]],
    *,
    destination: str,
) -> list[ProviderCandidate]:
    return [
        candidate
        for item in items
        if (
            candidate := _candidate_from_item(
                item,
                source="geoapify_search_snapshot",
                location_hint=destination,
            )
        )
        is not None
    ]


class _SnapshotGeoapifyProvider:
    def __init__(self, case: dict[str, Any]) -> None:
        self._case = case

    async def search(self, *, query: str, top_k: int = 5) -> ProviderResponse:
        return ProviderResponse(
            candidates=_geocode_candidates(
                self._case.get("geocode_text_items") or [],
                destination=query,
            )[:top_k]
        )

    async def search_city(self, *, city: str, top_k: int = 5) -> ProviderResponse:
        return ProviderResponse(
            candidates=_geocode_candidates(
                self._case.get("geocode_city_items") or [],
                destination=city,
            )[:top_k]
        )


async def _resolve_profile(case: dict[str, Any]) -> DestinationProfile:
    lookup = GeoapifyDestinationLookup("snapshot-key", radius_km=40.0)
    lookup._provider = _SnapshotGeoapifyProvider(case)  # type: ignore[assignment]
    profile = await lookup.lookup(str(case["destination"]))
    return profile or DestinationProfile(requested_name=str(case["destination"]))


def _snapshot_candidates(case: dict[str, Any]) -> list[ProviderCandidate]:
    payload = {"features": case.get("provider_items") or []}
    return [
        candidate
        for item in _iter_place_features(payload)
        if (
            candidate := _candidate_from_item(
                item,
                source="geoapify_map_snapshot",
                location_hint=str(case["destination"]),
            )
        )
        is not None
    ]


def _cross_city_decoys(profile: DestinationProfile) -> list[ProviderCandidate]:
    return [
        ProviderCandidate(
            candidate_id="snapshot-cross-city-tokyo-tower",
            source="geoapify_map_snapshot",
            title="Tokyo Tower",
            extra={
                "lat": 35.6586,
                "lng": 139.7454,
                "city": "Tokyo",
                "country": "Japan",
                "locality_terms": ["Tokyo", "Japan"],
            },
        ),
        ProviderCandidate(
            candidate_id=f"snapshot-nearby-wrong-city-{profile.requested_name}",
            source="geoapify_map_snapshot",
            title="Nearby Wrong City Attraction",
            extra={
                "lat": (profile.center_lat or 0.0) + 0.01,
                "lng": (profile.center_lng or 0.0) + 0.01,
                "city": "Neighbor City",
                "state": profile.admin_area,
                "country": profile.country,
                "locality_terms": [
                    "Neighbor City",
                    profile.admin_area,
                    profile.country,
                ],
            },
        ),
    ]


def _mock_decoy(profile: DestinationProfile) -> ProviderCandidate:
    return ProviderCandidate(
        candidate_id=f"mock-{profile.requested_name}",
        source="mock_map",
        title=f"Mock {profile.requested_name} Attraction",
        extra={
            "lat": profile.center_lat,
            "lng": profile.center_lng,
            "city": profile.canonical_name,
            "locality_terms": [profile.canonical_name],
        },
    )


async def _evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    profile = await _resolve_profile(case)
    local_candidates = _snapshot_candidates(case)
    cross_city_candidates = _cross_city_decoys(profile)
    mock_candidate = _mock_decoy(profile)
    result = evaluate_candidate_publishability(
        [*local_candidates, *cross_city_candidates, mock_candidate],
        profile,
        required_count=REQUIRED_CANDIDATES,
    )

    accepted_ids = {candidate.candidate_id for candidate in result.accepted}
    cross_city_published = sum(
        candidate.candidate_id in accepted_ids
        for candidate in cross_city_candidates
    )
    nearby_cross_city_published = int(
        cross_city_candidates[1].candidate_id in accepted_ids
    )
    mock_published = int(mock_candidate.candidate_id in accepted_ids)
    expected = str(case["expected_outcome"])
    errors: list[str] = []
    if destination_bounds(str(case["destination"])) is not None:
        errors.append("holdout destination has production static bounds")
    if not profile.resolved:
        errors.append("destination profile did not resolve")
    expected_center = case["center"]
    if profile.canonical_name != str(case["canonical_name"]):
        errors.append(
            "canonical destination mismatch: "
            f"expected={case['canonical_name']} actual={profile.canonical_name}"
        )
    if profile.country != str(case["country"]):
        errors.append(
            f"country mismatch: expected={case['country']} actual={profile.country}"
        )
    if (
        profile.center_lat is None
        or profile.center_lng is None
        or abs(profile.center_lat - float(expected_center[0])) > 0.01
        or abs(profile.center_lng - float(expected_center[1])) > 0.01
    ):
        errors.append("destination center mismatch")
    if result.status != expected:
        errors.append(f"expected {expected}, got {result.status}")
    if cross_city_published:
        errors.append("cross-city candidate became publishable")
    if mock_published:
        errors.append("Mock candidate became publishable")
    if len(result.accepted) != len(local_candidates):
        errors.append(
            "local publishable mismatch: "
            f"expected={len(local_candidates)} actual={len(result.accepted)}"
        )

    return {
        "case_id": case["case_id"],
        "destination": case["destination"],
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "expected_outcome": expected,
        "actual_outcome": result.status,
        "profile": profile.to_dict(),
        "provider_candidate_count": len(local_candidates),
        "publishable_candidate_count": len(result.accepted),
        "publishable_titles": [candidate.title for candidate in result.accepted],
        "cross_city_published": cross_city_published,
        "nearby_cross_city_published": nearby_cross_city_published,
        "mock_published": mock_published,
        "reject_reason_counts": result.reject_reason_counts,
    }


def build_report(cases: list[dict[str, Any]]) -> dict[str, Any]:
    async def evaluate_all() -> list[dict[str, Any]]:
        return list(await asyncio.gather(*(_evaluate_case(case) for case in cases)))

    results = asyncio.run(evaluate_all())
    failures = [result for result in results if result["status"] != "passed"]
    return {
        "schema_version": "overseas_candidate_supply_eval_v1",
        "status": "passed" if not failures else "failed",
        "case_count": len(results),
        "passed_cases": len(results) - len(failures),
        "failed_cases": len(failures),
        "resolved_profiles": sum(bool(result["profile"]["resolved"]) for result in results),
        "ready_destinations": sum(result["actual_outcome"] == "ready" for result in results),
        "safe_degradation_destinations": sum(
            result["actual_outcome"] == "insufficient_candidates" for result in results
        ),
        "cross_city_published": sum(result["cross_city_published"] for result in results),
        "nearby_cross_city_published": sum(
            result["nearby_cross_city_published"] for result in results
        ),
        "mock_published": sum(result["mock_published"] for result in results),
        "failures": failures,
        "cases": results,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Overseas Candidate Supply Eval",
        "",
        f"- Status: `{report['status']}`",
        f"- Cases: {report['passed_cases']}/{report['case_count']} passed",
        f"- Resolved profiles: {report['resolved_profiles']}",
        f"- Ready/safe degradation: {report['ready_destinations']}/{report['safe_degradation_destinations']}",
        f"- Cross-city/Mock published: {report['cross_city_published']}/{report['mock_published']}",
        f"- Nearby cross-city published: {report['nearby_cross_city_published']}",
        "",
        "| Destination | Expected | Actual | Publishable | Status |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for case in report["cases"]:
        lines.append(
            f"| {case['destination']} | {case['expected_outcome']} | "
            f"{case['actual_outcome']} | {case['publishable_candidate_count']} | "
            f"{case['status']} |"
        )
    if report["failures"]:
        lines.extend(["", "## Failures", ""])
        for failure in report["failures"]:
            lines.append(f"- `{failure['case_id']}`: {'; '.join(failure['errors'])}")
    lines.append("")
    return "\n".join(lines)


def write_outputs(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "overseas-candidate-supply-eval.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (output_dir / "overseas-candidate-supply-eval.md").write_text(
        render_markdown(report),
        encoding="utf-8",
        newline="\n",
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay sanitized overseas provider candidate snapshots."
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = build_report(load_cases(args.cases))
    write_outputs(report, args.output_dir)
    print(
        f"overseas_candidate_supply_eval={report['status']} "
        f"cases={report['passed_cases']}/{report['case_count']} "
        f"ready={report['ready_destinations']}"
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
