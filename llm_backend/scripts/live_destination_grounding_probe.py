"""Run a budget-aware real-provider probe for unseen destination grounding.

This command intentionally never calls an LLM. It uses the configured map
providers, respects their existing cache/cost switches, and requires an
explicit ``--allow-live`` acknowledgement before making network requests.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.core.config import settings
from app.services.destination_grounding import (
    DestinationResolver,
    filter_candidates_for_destination,
    has_valid_coordinates,
)
from app.services.recall_service import RecallService

from scripts.unseen_destination_eval import load_cases


DEFAULT_CASES_PATH = Path(__file__).resolve().parents[1] / "evaluation" / "live_destination_grounding_cases.json"
DEFAULT_CASE_IDS = (
    "live_tromso",
    "live_hobart",
    "live_valletta",
    "live_san_francisco",
    "live_oaxaca",
)


def configured_provider_capabilities() -> dict[str, dict[str, bool]]:
    """Report provider readiness without exposing provider credentials.

    A configured SerpAPI key can intentionally be cache-only. Keep key,
    cache, and live-call state separate so a cost guard is not mistaken for a
    missing overseas integration.
    """
    return {
        "amap": {
            "key_configured": bool(settings.AMAP_API_KEY.strip()),
            "enabled": bool(settings.AMAP_ENABLED),
            "live_enabled": bool(settings.AMAP_ENABLED and settings.AMAP_API_KEY.strip()),
            "cache_enabled": False,
        },
        "geoapify": {
            "key_configured": bool(settings.GEOAPIFY_KEY.strip()),
            "enabled": bool(settings.GEOAPIFY_ENABLED),
            "live_enabled": bool(settings.GEOAPIFY_LIVE_ENABLED),
            "cache_enabled": bool(settings.GEOAPIFY_RESPONSE_CACHE_ENABLED),
        },
        "serpapi": {
            "key_configured": bool(settings.SERPAPI_KEY.strip()),
            "enabled": bool(settings.SERPAPI_ENABLED),
            "live_enabled": bool(
                settings.SERPAPI_LIVE_ENABLED
                or str(settings.PROVIDER_COST_MODE).lower() == "full"
            ),
            "cache_enabled": bool(settings.SERPAPI_RESPONSE_CACHE_ENABLED),
        },
    }


def _has_evidence(candidate: Any) -> bool:
    extra = getattr(candidate, "extra", {}) or {}
    return bool(candidate.title and (candidate.snippet or extra.get("url") or extra.get("address")))


def _has_image(candidate: Any) -> bool:
    extra = getattr(candidate, "extra", {}) or {}
    return bool(extra.get("image_url") or extra.get("thumbnail") or extra.get("photos"))


def _health_status(*, status: str, provider_degraded: bool, quality_flags: list[str]) -> str:
    if status != "ready":
        return "not_ready"
    if provider_degraded or quality_flags:
        return "degraded"
    return "healthy"


def _p95(values: list[float]) -> float | None:
    return _percentile(values, 0.95)


def summarize_probe_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate publishability and safety invariants for a live probe."""
    provider_candidates = sum(int(result.get("provider_candidate_count", 0)) for result in results)
    coordinate_candidates = sum(int(result.get("coordinate_candidate_count", 0)) for result in results)
    image_candidates = sum(int(result.get("image_candidate_count", 0)) for result in results)
    publishable_candidates = sum(int(result.get("validated_candidate_count", 0)) for result in results)
    evidence_candidates = sum(int(result.get("evidence_candidate_count", 0)) for result in results)
    resolved_profiles = sum(bool((result.get("profile") or {}).get("resolved")) for result in results)
    ready_destinations = sum(result.get("status") == "ready" for result in results)
    safe_degraded_destinations = sum(
        result.get("status") == "insufficient_candidates" and bool((result.get("profile") or {}).get("resolved"))
        for result in results
    )
    provider_unavailable_destinations = sum(result.get("status") == "provider_unavailable" for result in results)
    return {
        "total_cases": len(results),
        "resolved_profiles": resolved_profiles,
        "ready_destinations": ready_destinations,
        "safe_degraded_destinations": safe_degraded_destinations,
        "provider_unavailable_destinations": provider_unavailable_destinations,
        "profile_unresolved_destinations": sum(result.get("status") == "profile_unresolved" for result in results),
        "provider_candidates": provider_candidates,
        "publishable_candidates": publishable_candidates,
        "coordinate_coverage": round(coordinate_candidates / provider_candidates, 4) if provider_candidates else 0.0,
        "published_coordinate_coverage": 1.0 if publishable_candidates else 0.0,
        "evidence_coverage": round(evidence_candidates / publishable_candidates, 4) if publishable_candidates else 0.0,
        "image_coverage": round(image_candidates / publishable_candidates, 4) if publishable_candidates else 0.0,
        "image_candidates": image_candidates,
        "cross_city_published": sum(int(result.get("cross_city_published_count", 0)) for result in results),
        "cross_city_rejected": sum(int(result.get("cross_city_rejected_count", 0)) for result in results),
        "mock_candidates": sum(int(result.get("mock_candidate_count", 0)) for result in results),
        "mock_published": sum(int(result.get("mock_published_count", 0)) for result in results),
        "latency_p50_ms": _percentile([float(result.get("elapsed_ms", 0.0)) for result in results], 0.50),
        "latency_p95_ms": _p95([float(result.get("elapsed_ms", 0.0)) for result in results]),
    }


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * quantile) - 1)
    return round(ordered[index], 2)


def evaluate_live_acceptance(report: dict[str, Any], cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply the v1 live destination grounding acceptance contract."""
    summary = summarize_probe_results(list(report.get("results") or []))
    expected_cases = len(cases)
    failed_checks: list[str] = []
    if summary["total_cases"] != expected_cases:
        failed_checks.append("case_coverage")
    if summary["resolved_profiles"] != expected_cases:
        failed_checks.append("destination_profiles_resolved")
    if summary["ready_destinations"] < max(1, expected_cases - 1):
        failed_checks.append("minimum_ready_destinations")
    if summary["safe_degraded_destinations"] > 1:
        failed_checks.append("safe_degradation_limit")
    if summary["provider_unavailable_destinations"]:
        failed_checks.append("provider_availability")
    if summary["cross_city_published"] != 0:
        failed_checks.append("cross_city_published_zero")
    if summary["mock_published"] != 0:
        failed_checks.append("mock_published_zero")
    if summary["publishable_candidates"] and summary["published_coordinate_coverage"] < 1.0:
        failed_checks.append("publishable_coordinates_complete")
    if summary["publishable_candidates"] and summary["evidence_coverage"] < 0.67:
        failed_checks.append("evidence_coverage")
    if summary["image_candidates"] and summary["image_coverage"] < 0.8:
        failed_checks.append("photo_coverage_when_available")

    baseline_p95_ms = report.get("baseline_p95_ms")
    if baseline_p95_ms is not None and summary["latency_p95_ms"] is not None:
        if summary["latency_p95_ms"] > float(baseline_p95_ms) * 1.2:
            failed_checks.append("latency_p95_regression")

    return {
        "status": "passed" if not failed_checks else "failed",
        "criteria": {
            "required_cases": expected_cases,
            "minimum_ready_destinations": max(1, expected_cases - 1),
            "maximum_safe_degraded_destinations": 1,
            "cross_city_published": 0,
            "mock_published": 0,
            "minimum_coordinate_coverage": 1.0,
            "minimum_evidence_coverage": 0.67,
            "minimum_photo_coverage_when_available": 0.8,
            "maximum_latency_regression_ratio": 1.2,
        },
        "summary": summary,
        "failed_checks": failed_checks,
    }


async def probe_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    resolver = DestinationResolver()
    recall_service = RecallService(include_mock_fallback=False)
    results: list[dict[str, Any]] = []
    for case in cases:
        destination = str(case["destination"])
        started = asyncio.get_running_loop().time()
        profile = await resolver.resolve(destination)
        result: dict[str, Any] = {
            "case_id": case["case_id"],
            "destination": destination,
            "profile": profile.to_dict(),
            "status": "profile_unresolved",
            "validated_candidate_count": 0,
            "provider_candidate_count": 0,
            "coordinate_candidate_count": 0,
            "evidence_candidate_count": 0,
            "image_candidate_count": 0,
            "cross_city_published_count": 0,
            "cross_city_rejected_count": 0,
            "mock_candidate_count": 0,
            "mock_published_count": 0,
            "source_counts": {},
            "quality_flags": [],
            "health_status": "not_ready",
            "degradation_reasons": [],
            "reject_reason_counts": {},
            "accepted_candidates": [],
        }
        if profile.resolved:
            recall = await recall_service.recall_simple(
                query=str(case.get("query") or f"{profile.canonical_name} tourist attractions"),
                city=profile.canonical_name,
                preferences=list(case.get("preferences") or []),
            )
            accepted, decisions = filter_candidates_for_destination(recall.candidates, profile)
            publishable = [candidate for candidate in accepted if has_valid_coordinates(candidate)]
            reject_counts = Counter(decision.reason for decision in decisions if not decision.accepted)
            source_counts = Counter(candidate.source for candidate in recall.candidates)
            evidence_count = sum(_has_evidence(candidate) for candidate in publishable)
            image_count = sum(_has_image(candidate) for candidate in publishable)
            coordinate_count = sum(has_valid_coordinates(candidate) for candidate in recall.candidates)
            cross_city_rejected = sum(
                decision.reason in {"candidate_city_mismatch", "outside_destination_radius", "outside_destination_bounds"}
                for decision in decisions
                if not decision.accepted
            )
            cross_city_published = sum(
                (candidate.extra.get("destination_grounding") or {}).get("city_match") is False
                for candidate in publishable
            )
            mock_count = sum(str(candidate.source).lower().startswith("mock") for candidate in recall.candidates)
            mock_published = sum(str(candidate.source).lower().startswith("mock") for candidate in publishable)
            quality_flags: list[str] = []
            if publishable and evidence_count / len(publishable) < 0.67:
                quality_flags.append("low_evidence_coverage")
            if publishable and image_count / len(publishable) < 0.67:
                quality_flags.append("low_image_coverage")
            min_candidates = int(case.get("min_validated_candidates") or settings.DESTINATION_GROUNDING_MIN_CANDIDATES)
            provider_degraded = bool(recall.degraded)
            provider_unavailable = (
                not recall.candidates
                and any("调用失败" in assumption for assumption in recall.assumptions)
            )
            status = (
                "provider_unavailable"
                if provider_unavailable
                else "ready"
                if len(publishable) >= min_candidates
                else "insufficient_candidates"
            )
            degradation_reasons = [
                *recall.assumptions,
                *quality_flags,
            ]
            result.update(
                {
                    "status": status,
                    "validated_candidate_count": len(publishable),
                    "provider_candidate_count": len(recall.candidates),
                    "coordinate_candidate_count": coordinate_count,
                    "evidence_candidate_count": evidence_count,
                    "image_candidate_count": image_count,
                    "cross_city_published_count": cross_city_published,
                    "cross_city_rejected_count": cross_city_rejected,
                    "mock_candidate_count": mock_count,
                    "mock_published_count": mock_published,
                    "source_counts": dict(source_counts),
                    "quality_flags": quality_flags,
                    "provider_degraded": provider_degraded,
                    "provider_assumptions": recall.assumptions,
                    "health_status": _health_status(
                        status=status,
                        provider_degraded=provider_degraded,
                        quality_flags=quality_flags,
                    ),
                    "degradation_reasons": degradation_reasons,
                    "reject_reason_counts": dict(reject_counts),
                    "accepted_candidates": [
                        {
                            "title": candidate.title,
                            "source": candidate.source,
                            "city": candidate.extra.get("city"),
                            "lat": candidate.extra.get("lat"),
                            "lng": candidate.extra.get("lng"),
                        }
                        for candidate in publishable[:5]
                    ],
                }
            )
        result["elapsed_ms"] = round((asyncio.get_running_loop().time() - started) * 1000, 2)
        results.append(result)

    summary = summarize_probe_results(results)
    resolved = [item for item in results if item["profile"]["resolved"]]
    ready = [item for item in results if item["status"] == "ready"]
    healthy = [item for item in ready if item["health_status"] == "healthy"]
    degraded = [item for item in ready if item["health_status"] == "degraded"]
    return {
        "schema_version": "live_destination_grounding_probe_v3",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider_capabilities": configured_provider_capabilities(),
        "status": "passed" if len(resolved) >= len(cases) and len(ready) >= max(1, len(cases) - 1) else "failed",
        "criteria": {"min_resolved_profiles": len(cases), "min_ready_destinations": max(1, len(cases) - 1)},
        "resolved_profiles": len(resolved),
        "ready_destinations": len(ready),
        "healthy_ready_destinations": len(healthy),
        "degraded_ready_destinations": len(degraded),
        "summary": summary,
        "results": results,
    }


def apply_targeted_criteria(report: dict[str, Any], cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate a manually selected subset against its fixture expectation.

    The default five-city probe is an acceptance gate with aggregate thresholds.
    A one-city probe is diagnostic, so it must not be marked failed solely
    because it cannot possibly reach the five-city threshold.
    """
    expected_by_id = {
        str(case["case_id"]): str(case.get("expected_outcome") or "ready")
        for case in cases
    }

    def meets_expectation(*, expected: str, actual: str) -> bool:
        if actual == expected:
            return True
        return expected == "insufficient_candidates" and actual == "ready"

    mismatches = [
        {
            "case_id": result["case_id"],
            "expected": expected_by_id[result["case_id"]],
            "actual": result["status"],
        }
        for result in report["results"]
        if not meets_expectation(
            expected=expected_by_id[result["case_id"]],
            actual=result["status"],
        )
    ]
    report["criteria"] = {
        "mode": "targeted",
        "expected_outcomes": expected_by_id,
        "require_resolved_profile": True,
        "ready_satisfies_safe_degradation": True,
    }
    report["mismatches"] = mismatches
    report["status"] = "passed" if not mismatches else "failed"
    return report


def _selected_cases(all_cases: list[dict[str, Any]], case_ids: list[str]) -> list[dict[str, Any]]:
    indexed = {str(case["case_id"]): case for case in all_cases}
    missing = [case_id for case_id in case_ids if case_id not in indexed]
    if missing:
        raise ValueError(f"Unknown case ids: {', '.join(missing)}")
    return [indexed[case_id] for case_id in case_ids]


def write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe dynamic destination grounding with real map providers.")
    parser.add_argument("--allow-live", action="store_true", help="Required acknowledgement before network calls.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--case-id", action="append", dest="case_ids")
    parser.add_argument("--output", type=Path, default=Path("reports/live-destination-grounding-probe.json"))
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not args.allow_live:
        parser.error("--allow-live is required because this probe can call configured map providers")

    selected_ids = args.case_ids or list(DEFAULT_CASE_IDS)
    selected_cases = _selected_cases(load_cases(args.cases), selected_ids)
    report = asyncio.run(probe_cases(selected_cases))
    acceptance = evaluate_live_acceptance(report, selected_cases)
    report["acceptance"] = acceptance
    report["status"] = acceptance["status"]
    if args.case_ids:
        report = apply_targeted_criteria(report, selected_cases)
        report["acceptance"] = {
            **acceptance,
            "mode": "targeted",
            "status": report["status"],
        }
    write_report(report, args.output)
    print(
        f"live_destination_grounding_probe={report['status']} "
        f"resolved={report['resolved_profiles']} ready={report['ready_destinations']} output={args.output}"
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
