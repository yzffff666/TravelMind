"""Run a budget-aware real-provider probe for unseen destination grounding.

This command intentionally never calls an LLM. It uses the configured map
providers, respects their existing cache/cost switches, and requires an
explicit ``--allow-live`` acknowledgement before making network requests.
"""

from __future__ import annotations

import argparse
import asyncio
import json
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

from scripts.unseen_destination_eval import DEFAULT_CASES_PATH, load_cases


DEFAULT_CASE_IDS = (
    "unseen_jingdezhen",
    "unseen_yanji",
    "unseen_dunhuang",
    "unseen_zigong",
    "unseen_kashgar_insufficient",
    "unseen_quanzhou",
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
            "evidence_candidate_count": 0,
            "image_candidate_count": 0,
            "source_counts": {},
            "quality_flags": [],
            "health_status": "not_ready",
            "degradation_reasons": [],
            "reject_reason_counts": {},
            "accepted_candidates": [],
        }
        if profile.resolved:
            recall = await recall_service.recall_simple(
                query=f"{profile.canonical_name} 文化 景点",
                city=profile.canonical_name,
                preferences=["文化"],
            )
            accepted, decisions = filter_candidates_for_destination(recall.candidates, profile)
            publishable = [candidate for candidate in accepted if has_valid_coordinates(candidate)]
            reject_counts = Counter(decision.reason for decision in decisions if not decision.accepted)
            source_counts = Counter(candidate.source for candidate in recall.candidates)
            evidence_count = sum(_has_evidence(candidate) for candidate in publishable)
            image_count = sum(_has_image(candidate) for candidate in publishable)
            quality_flags: list[str] = []
            if publishable and evidence_count / len(publishable) < 0.67:
                quality_flags.append("low_evidence_coverage")
            if publishable and image_count / len(publishable) < 0.67:
                quality_flags.append("low_image_coverage")
            status = "ready" if len(publishable) >= 3 else "insufficient_candidates"
            provider_degraded = bool(recall.degraded)
            degradation_reasons = [
                *recall.assumptions,
                *quality_flags,
            ]
            result.update(
                {
                    "status": status,
                    "validated_candidate_count": len(publishable),
                    "provider_candidate_count": len(recall.candidates),
                    "evidence_candidate_count": evidence_count,
                    "image_candidate_count": image_count,
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

    resolved = [item for item in results if item["profile"]["resolved"]]
    ready = [item for item in results if item["status"] == "ready"]
    healthy = [item for item in ready if item["health_status"] == "healthy"]
    degraded = [item for item in ready if item["health_status"] == "degraded"]
    return {
        "schema_version": "live_destination_grounding_probe_v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider_capabilities": configured_provider_capabilities(),
        "status": "passed" if len(resolved) >= 6 and len(ready) >= 4 else "failed",
        "criteria": {"min_resolved_profiles": 6, "min_ready_destinations": 4},
        "resolved_profiles": len(resolved),
        "ready_destinations": len(ready),
        "healthy_ready_destinations": len(healthy),
        "degraded_ready_destinations": len(degraded),
        "results": results,
    }


def apply_targeted_criteria(report: dict[str, Any], cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate a manually selected subset against its fixture expectation.

    The default six-city probe is an acceptance gate with aggregate thresholds.
    A one-city probe is diagnostic, so it must not be marked failed solely
    because it cannot possibly reach the six-city threshold.
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
    if args.case_ids:
        report = apply_targeted_criteria(report, selected_cases)
    write_report(report, args.output)
    print(
        f"live_destination_grounding_probe={report['status']} "
        f"resolved={report['resolved_profiles']} ready={report['ready_destinations']} output={args.output}"
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
