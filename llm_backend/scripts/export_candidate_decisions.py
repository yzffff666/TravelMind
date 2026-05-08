"""Export candidate decision samples from TravelMind observability logs.

This is the first lightweight data-asset step for the Travel Decision Agent
roadmap: convert backfill decision traces into candidate-level JSONL samples.

Usage:
    python -m scripts.export_candidate_decisions --log logs/structured.log --output reports/candidate-decisions.jsonl
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from scripts.observability_summary import ObservabilityEvent, _as_bool, _as_float, iter_events


SCHEMA_VERSION = "candidate_decision_v1"


def _risk_flags(payload: dict[str, Any], decision: str) -> list[str]:
    flags: list[str] = []
    fallback_reason = str(payload.get("fallback_reason") or "").strip()
    source = str(payload.get("source") or "").strip()

    if fallback_reason:
        flags.append(fallback_reason)
    if decision == "accepted" and not _as_bool(payload.get("bbox_valid")):
        flags.append("bbox_invalid")
    if payload.get("confidence") == "low":
        flags.append("low_confidence")
    if int(_as_float(payload.get("rejected_bbox_count")) or 0) > 0:
        flags.append("bbox_rejected")
    if int(_as_float(payload.get("rejected_score_count")) or 0) > 0:
        flags.append("score_rejected")
    if int(_as_float(payload.get("rejected_missing_coord_count")) or 0) > 0:
        flags.append("missing_coord")
    if int(_as_float(payload.get("cache_negative_hit_count")) or 0) > 0:
        flags.append("cache_negative_hit")
    if _as_bool(payload.get("variant_limit_reached")):
        flags.append("variant_limit_reached")
    if source == "skipped" and "generic_activity" not in flags:
        flags.append("generic_activity")

    return list(dict.fromkeys(flag for flag in flags if flag))


def _decision_from_source(payload: dict[str, Any]) -> str:
    source = str(payload.get("source") or "").strip()
    if source == "provider":
        return "accepted"
    if source == "skipped":
        return "skipped"
    return "rejected"


def _label_from_decision(decision: str) -> str:
    if decision == "accepted":
        return "accepted"
    return "rejected"


def event_to_candidate_decision(event: ObservabilityEvent) -> dict[str, Any] | None:
    """Convert one location_backfill event to a candidate decision sample."""
    if event.event_type != "location_backfill":
        return None

    payload = event.payload
    decision = _decision_from_source(payload)
    best_match_score = _as_float(payload.get("best_match_score"))
    match_score = _as_float(payload.get("match_score"))

    return {
        "schema_version": SCHEMA_VERSION,
        "decision": decision,
        "label": _label_from_decision(decision),
        "label_source": "rule",
        "risk_flags": _risk_flags(payload, decision),
        "source_log": event.source,
        "itinerary_id": payload.get("itinerary_id"),
        "revision_id": payload.get("revision_id"),
        "destination": payload.get("destination"),
        "day_index": payload.get("day_index"),
        "slot_label": payload.get("slot_label"),
        "activity": payload.get("activity"),
        "place": payload.get("place") or payload.get("activity"),
        "candidate_title": payload.get("candidate_title") or payload.get("best_candidate_title"),
        "candidate_provider": payload.get("provider")
        or payload.get("best_candidate_provider")
        or payload.get("source"),
        "candidate_lat": _as_float(payload.get("lat") or payload.get("best_candidate_lat")),
        "candidate_lng": _as_float(payload.get("lng") or payload.get("best_candidate_lng")),
        "candidate_address": payload.get("address") or payload.get("best_candidate_address"),
        "bbox_valid": _as_bool(payload.get("bbox_valid")),
        "confidence": payload.get("confidence"),
        "match_score": match_score if match_score is not None else best_match_score,
        "fallback_reason": payload.get("fallback_reason"),
        "provider_status_counts": payload.get("provider_status_counts") or {},
        "candidate_count": int(_as_float(payload.get("candidate_count")) or 0),
        "rejected_bbox_count": int(_as_float(payload.get("rejected_bbox_count")) or 0),
        "rejected_score_count": int(_as_float(payload.get("rejected_score_count")) or 0),
        "rejected_missing_coord_count": int(_as_float(payload.get("rejected_missing_coord_count")) or 0),
        "cache_hit_count": int(_as_float(payload.get("cache_hit_count")) or 0),
        "cache_negative_hit_count": int(_as_float(payload.get("cache_negative_hit_count")) or 0),
        "variant_limit_reached": _as_bool(payload.get("variant_limit_reached")),
        "variants_tried": payload.get("variants_tried") or [],
        "elapsed_ms": _as_float(payload.get("elapsed_ms")),
    }


def export_candidate_decisions(events: Iterable[ObservabilityEvent]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for event in events:
        sample = event_to_candidate_decision(event)
        if sample is not None:
            samples.append(sample)
    return samples


def _compact_counter(counter: Counter) -> dict[str, int]:
    return {str(key): count for key, count in counter.most_common() if key not in {None, ""}}


def summarize_candidate_decisions(samples: Iterable[dict[str, Any]]) -> dict[str, Any]:
    sample_list = list(samples)
    risk_flags: Counter = Counter()
    for sample in sample_list:
        for flag in sample.get("risk_flags") or []:
            risk_flags[flag] += 1

    match_scores = [
        score
        for sample in sample_list
        if (score := _as_float(sample.get("match_score"))) is not None
    ]
    elapsed_values = [
        elapsed
        for sample in sample_list
        if (elapsed := _as_float(sample.get("elapsed_ms"))) is not None
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "total_samples": len(sample_list),
        "decision_counts": _compact_counter(Counter(sample.get("decision") for sample in sample_list)),
        "label_counts": _compact_counter(Counter(sample.get("label") for sample in sample_list)),
        "risk_flag_counts": _compact_counter(risk_flags),
        "destination_counts": _compact_counter(Counter(sample.get("destination") for sample in sample_list)),
        "candidate_provider_counts": _compact_counter(
            Counter(sample.get("candidate_provider") for sample in sample_list)
        ),
        "fallback_reason_counts": _compact_counter(
            Counter(sample.get("fallback_reason") for sample in sample_list)
        ),
        "match_score_avg": round(sum(match_scores) / len(match_scores), 4) if match_scores else None,
        "elapsed_ms_avg": round(sum(elapsed_values) / len(elapsed_values), 2) if elapsed_values else None,
    }


def write_jsonl(path: Path, samples: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for sample in samples:
            file.write(json.dumps(sample, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Export TravelMind candidate decision samples.")
    parser.add_argument("--log", nargs="+", type=Path, required=True, help="Structured log file(s).")
    parser.add_argument("--output", type=Path, required=True, help="Output JSONL path.")
    parser.add_argument(
        "--summary-output",
        type=Path,
        help="Optional JSON summary path for exported candidate decision samples.",
    )
    args = parser.parse_args()

    samples = export_candidate_decisions(iter_events(args.log))
    count = write_jsonl(args.output, samples)
    if args.summary_output:
        write_json(args.summary_output, summarize_candidate_decisions(samples))
    print(f"Exported {count} candidate decision samples to {args.output}")


if __name__ == "__main__":
    main()
