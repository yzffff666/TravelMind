"""Summarize TravelMind structured logs into Markdown or JSON.

Usage:
    python -m scripts.observability_summary --log logs/structured.log --output reports/observability-summary.md
    python -m scripts.observability_summary --log logs/app.log --format json
"""

from __future__ import annotations

import argparse
import ast
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


KNOWN_EVENTS = {
    "deepseek_llm_call",
    "deepseek_llm_call_failed",
    "llm_draft_call",
    "llm_draft_call_failed",
    "semantic_cache_lookup",
    "provider_call",
    "location_backfill",
    "itinerary_quality_summary",
    "qp_parsed",
    "qa_local_fast_path",
}

MAX_BACKFILL_SAMPLE_ROWS = 10


def _normalize_event_type(event_type: str) -> str:
    normalized = event_type.strip()
    if normalized.lower() in {"qp parsed", "qp_parsed"}:
        return "qp_parsed"
    return normalized


@dataclass(frozen=True)
class ObservabilityEvent:
    event_type: str
    payload: dict[str, Any]
    source: str


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _percentile(values: Iterable[float], percentile: float) -> float | None:
    sorted_values = sorted(v for v in values if v is not None)
    if not sorted_values:
        return None
    index = max(0, math.ceil((percentile / 100) * len(sorted_values)) - 1)
    return round(sorted_values[index], 2)


def _mean(values: Iterable[float]) -> float | None:
    items = [v for v in values if v is not None]
    if not items:
        return None
    return round(sum(items) / len(items), 2)


def _compact_counter(counter: Counter) -> dict[str, int]:
    return {str(key): count for key, count in counter.most_common() if key not in {None, ""}}


def _compact_text(value: Any, *, max_length: int = 80) -> str:
    text = "" if value is None else str(value)
    text = " ".join(text.split())
    if len(text) <= max_length:
        return text
    return text[: max_length - 1] + "..."


def _markdown_cell(value: Any, *, max_length: int = 80) -> str:
    text = _compact_text(value, max_length=max_length)
    return text.replace("|", "\\|") if text else "-"


def _merge_count_mappings(events: Iterable[ObservabilityEvent], field_name: str) -> dict[str, int]:
    merged: Counter = Counter()
    for event in events:
        value = event.payload.get(field_name)
        if not isinstance(value, dict):
            continue
        for key, count in value.items():
            merged[str(key)] += int(_as_float(count) or 0)
    return _compact_counter(merged)


def _parse_mapping(text: str) -> dict[str, Any] | None:
    candidate = text.strip()
    if not candidate:
        return None
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        try:
            parsed = ast.literal_eval(candidate)
        except (SyntaxError, ValueError):
            return None
    return parsed if isinstance(parsed, dict) else None


def _message_from_plain_line(line: str) -> str:
    return line.split(" - ", 1)[1].strip() if " - " in line else line.strip()


def _event_from_payload(payload: dict[str, Any], fallback: str, source: str) -> ObservabilityEvent | None:
    event_type = _normalize_event_type(str(payload.get("event_type") or fallback or ""))
    if not event_type:
        return None
    return ObservabilityEvent(event_type=event_type, payload=payload, source=source)


def parse_log_line(line: str, *, source: str = "") -> ObservabilityEvent | None:
    """Parse one Loguru JSON line or legacy text line."""
    stripped = line.strip()
    if not stripped:
        return None

    parsed_json = _parse_mapping(stripped)
    if parsed_json and "record" in parsed_json:
        record = parsed_json.get("record") or {}
        if not isinstance(record, dict):
            return None
        message = str(record.get("message") or "").strip()
        extra = record.get("extra") if isinstance(record.get("extra"), dict) else {}
        payload: dict[str, Any] = dict(extra)
        nested_extra = payload.pop("extra", None)
        if isinstance(nested_extra, dict):
            payload.update(nested_extra)

        embedded = _parse_mapping(message)
        if embedded:
            payload.update(embedded.get("data") if isinstance(embedded.get("data"), dict) else embedded)
        else:
            event_type = payload.get("event_type") or (
                _normalize_event_type(message)
                if message in KNOWN_EVENTS or message.lower() == "qp parsed"
                else ""
            )
            if not event_type:
                return None
            payload.setdefault("event_type", event_type)
        return _event_from_payload(payload, str(payload.get("event_type") or message), source)

    message = _message_from_plain_line(stripped)
    embedded = _parse_mapping(message)
    if embedded:
        payload = embedded.get("data") if isinstance(embedded.get("data"), dict) else embedded
        return _event_from_payload(payload, message, source)

    for event_name in KNOWN_EVENTS:
        prefix = f"{event_name} "
        if message.startswith(prefix):
            payload = _parse_mapping(message[len(prefix) :]) or {}
            payload.setdefault("event_type", event_name)
            return _event_from_payload(payload, event_name, source)
        if message == event_name:
            return ObservabilityEvent(
                event_type=event_name,
                payload={"event_type": event_name},
                source=source,
            )

    return None


def iter_events(log_paths: Iterable[Path]) -> Iterable[ObservabilityEvent]:
    for path in log_paths:
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                event = parse_log_line(line, source=str(path))
                if event is not None:
                    yield event


def summarize_events(events: Iterable[ObservabilityEvent]) -> dict[str, Any]:
    event_list = list(events)
    event_counts = Counter(event.event_type for event in event_list)

    return {
        "total_events": len(event_list),
        "event_counts": _compact_counter(event_counts),
        "llm": _summarize_llm(event_list),
        "cache": _summarize_cache(event_list),
        "providers": _summarize_providers(event_list),
        "backfill": _summarize_backfill(event_list),
        "qp": _summarize_qp(event_list),
        "qa": _summarize_qa(event_list),
    }


def _summarize_llm(events: list[ObservabilityEvent]) -> dict[str, Any]:
    relevant = [
        event
        for event in events
        if event.event_type in {
            "deepseek_llm_call",
            "deepseek_llm_call_failed",
            "llm_draft_call",
            "llm_draft_call_failed",
        }
        or event.payload.get("llm_status")
    ]
    draft_events = [
        event for event in relevant if event.event_type in {"llm_draft_call", "llm_draft_call_failed"}
    ]
    latencies = [_as_float(event.payload.get("elapsed_ms") or event.payload.get("llm_ms")) for event in relevant]
    attempts = [_as_float(event.payload.get("attempt") or event.payload.get("llm_attempts")) for event in relevant]
    status_counts = Counter(event.payload.get("status") or event.payload.get("llm_status") for event in relevant)
    error_counts = Counter(event.payload.get("error_type") for event in relevant)
    retryable_failures = sum(1 for event in relevant if _as_bool(event.payload.get("retryable")))

    return {
        "calls": len(relevant),
        "status_counts": _compact_counter(status_counts),
        "error_counts": _compact_counter(error_counts),
        "retryable_failures": retryable_failures,
        "attempt_p95": _percentile([v for v in attempts if v is not None], 95),
        "latency_ms": {
            "p50": _percentile([v for v in latencies if v is not None], 50),
            "p95": _percentile([v for v in latencies if v is not None], 95),
            "avg": _mean([v for v in latencies if v is not None]),
        },
        "draft": _summarize_llm_draft(draft_events),
    }


def _summarize_llm_draft(events: list[ObservabilityEvent]) -> dict[str, Any]:
    prompt_chars = [_as_float(event.payload.get("prompt_chars")) for event in events]
    user_prompt_chars = [_as_float(event.payload.get("user_prompt_chars")) for event in events]
    candidate_section_chars = [_as_float(event.payload.get("candidate_section_chars")) for event in events]
    candidate_counts = [_as_float(event.payload.get("candidate_count")) for event in events]
    output_chars = [_as_float(event.payload.get("output_chars")) for event in events]
    days_counts = [_as_float(event.payload.get("days_count")) for event in events]

    def stats(values: list[float | None]) -> dict[str, float | None]:
        present = [v for v in values if v is not None]
        return {
            "p50": _percentile(present, 50),
            "p95": _percentile(present, 95),
            "avg": _mean(present),
        }

    return {
        "calls": len(events),
        "parse_status_counts": _compact_counter(Counter(event.payload.get("parse_status") for event in events)),
        "destination_counts": _compact_counter(Counter(event.payload.get("destination") for event in events)),
        "response_language_counts": _compact_counter(
            Counter(event.payload.get("response_language") for event in events)
        ),
        "days_count": stats(days_counts),
        "prompt_chars": stats(prompt_chars),
        "user_prompt_chars": stats(user_prompt_chars),
        "candidate_section_chars": stats(candidate_section_chars),
        "candidate_count": stats(candidate_counts),
        "output_chars": stats(output_chars),
    }


def _summarize_cache(events: list[ObservabilityEvent]) -> dict[str, Any]:
    relevant = [event for event in events if event.event_type == "semantic_cache_lookup"]
    latencies = [_as_float(event.payload.get("lookup_ms")) for event in relevant]
    scanned = [_as_float(event.payload.get("scanned_count")) for event in relevant]
    source_counts = Counter(event.payload.get("cache_source") for event in relevant)
    total = sum(source_counts.values())
    hit_count = sum(source_counts.get(key, 0) for key in ("exact", "faiss", "semantic_scan"))

    return {
        "lookups": len(relevant),
        "source_counts": _compact_counter(source_counts),
        "hit_rate": round(hit_count / total, 4) if total else None,
        "lookup_ms": {
            "p50": _percentile([v for v in latencies if v is not None], 50),
            "p95": _percentile([v for v in latencies if v is not None], 95),
            "avg": _mean([v for v in latencies if v is not None]),
        },
        "max_scanned_count": max([v for v in scanned if v is not None], default=None),
    }


def _summarize_providers(events: list[ObservabilityEvent]) -> dict[str, Any]:
    relevant = [event for event in events if event.event_type == "provider_call"]
    grouped: dict[str, list[ObservabilityEvent]] = defaultdict(list)
    for event in relevant:
        provider = event.payload.get("provider_name") or "unknown"
        kind = event.payload.get("provider_kind") or "unknown"
        grouped[f"{provider}:{kind}"].append(event)

    by_provider = {}
    for key, items in grouped.items():
        latencies = [_as_float(item.payload.get("elapsed_ms")) for item in items]
        by_provider[key] = {
            "calls": len(items),
            "status_counts": _compact_counter(Counter(item.payload.get("status") for item in items)),
            "error_counts": _compact_counter(Counter(item.payload.get("error_type") for item in items)),
            "degraded_count": sum(1 for item in items if _as_bool(item.payload.get("degraded"))),
            "elapsed_ms": {
                "p50": _percentile([v for v in latencies if v is not None], 50),
                "p95": _percentile([v for v in latencies if v is not None], 95),
                "avg": _mean([v for v in latencies if v is not None]),
            },
        }

    return {"calls": len(relevant), "by_provider": by_provider}


def _summarize_backfill(events: list[ObservabilityEvent]) -> dict[str, Any]:
    fills = [event for event in events if event.event_type == "location_backfill"]
    summaries = [event for event in events if event.event_type == "itinerary_quality_summary"]
    fill_latencies = [_as_float(event.payload.get("elapsed_ms")) for event in fills]
    best_scores = [_as_float(event.payload.get("best_match_score")) for event in fills]
    unresolved_samples = _build_backfill_unresolved_samples(fills)

    return {
        "location_events": len(fills),
        "summary_events": len(summaries),
        "source_counts": _compact_counter(Counter(event.payload.get("source") for event in fills)),
        "confidence_counts": _compact_counter(Counter(event.payload.get("confidence") for event in fills)),
        "fallback_reasons": _compact_counter(Counter(event.payload.get("fallback_reason") for event in fills)),
        "provider_status_counts": _merge_count_mappings(fills, "provider_status_counts"),
        "variant_limit_reached_count": sum(1 for event in fills if _as_bool(event.payload.get("variant_limit_reached"))),
        "rejected_bbox_count": sum(int(_as_float(event.payload.get("rejected_bbox_count")) or 0) for event in fills),
        "rejected_score_count": sum(int(_as_float(event.payload.get("rejected_score_count")) or 0) for event in fills),
        "rejected_missing_coord_count": sum(
            int(_as_float(event.payload.get("rejected_missing_coord_count")) or 0) for event in fills
        ),
        "cache_negative_hit_count": sum(
            int(_as_float(event.payload.get("cache_negative_hit_count")) or 0) for event in fills
        ),
        "bbox_invalid_count": sum(
            1
            for event in fills
            if event.payload.get("source") == "provider" and event.payload.get("bbox_valid") is False
        ),
        "attempted": sum(int(_as_float(event.payload.get("backfill_attempted")) or 0) for event in summaries),
        "filled": sum(int(_as_float(event.payload.get("backfill_filled")) or 0) for event in summaries),
        "skipped": sum(int(_as_float(event.payload.get("backfill_skipped")) or 0) for event in summaries),
        "skipped_events": sum(1 for event in fills if event.payload.get("source") == "skipped"),
        "unresolved": sum(int(_as_float(event.payload.get("backfill_unresolved")) or 0) for event in summaries),
        "elapsed_ms": {
            "p50": _percentile([v for v in fill_latencies if v is not None], 50),
            "p95": _percentile([v for v in fill_latencies if v is not None], 95),
            "avg": _mean([v for v in fill_latencies if v is not None]),
        },
        "best_match_score": {
            "p50": _percentile([v for v in best_scores if v is not None], 50),
            "p95": _percentile([v for v in best_scores if v is not None], 95),
            "avg": _mean([v for v in best_scores if v is not None]),
        },
        "unresolved_samples": unresolved_samples,
    }


def _build_backfill_unresolved_samples(events: list[ObservabilityEvent]) -> list[dict[str, Any]]:
    unresolved = [event for event in events if event.payload.get("source") == "unresolved"]
    sorted_events = sorted(
        unresolved,
        key=lambda event: _as_float(event.payload.get("elapsed_ms")) or 0.0,
        reverse=True,
    )
    samples: list[dict[str, Any]] = []
    for event in sorted_events[:MAX_BACKFILL_SAMPLE_ROWS]:
        payload = event.payload
        best_match_score = _as_float(payload.get("best_match_score"))
        samples.append(
            {
                "place": payload.get("place") or payload.get("activity"),
                "activity": payload.get("activity"),
                "destination": payload.get("destination"),
                "day_index": payload.get("day_index"),
                "slot_label": payload.get("slot_label"),
                "fallback_reason": payload.get("fallback_reason"),
                "provider_status_counts": payload.get("provider_status_counts") or {},
                "candidate_count": int(_as_float(payload.get("candidate_count")) or 0),
                "best_candidate_title": payload.get("best_candidate_title"),
                "best_match_score": round(best_match_score, 4) if best_match_score is not None else None,
                "elapsed_ms": _as_float(payload.get("elapsed_ms")),
            }
        )
    return samples


def _summarize_qp(events: list[ObservabilityEvent]) -> dict[str, Any]:
    relevant = [event for event in events if event.event_type == "qp_parsed" or event.payload.get("qp_source")]
    confidences = [_as_float(event.payload.get("confidence")) for event in relevant]
    return {
        "events": len(relevant),
        "source_counts": _compact_counter(Counter(event.payload.get("qp_source") for event in relevant)),
        "fallback_reasons": _compact_counter(Counter(event.payload.get("fallback_reason") for event in relevant)),
        "confidence": {
            "p50": _percentile([v for v in confidences if v is not None], 50),
            "p95": _percentile([v for v in confidences if v is not None], 95),
            "avg": _mean([v for v in confidences if v is not None]),
        },
    }


def _summarize_qa(events: list[ObservabilityEvent]) -> dict[str, Any]:
    relevant = [event for event in events if event.event_type == "qa_local_fast_path"]
    latencies = [_as_float(event.payload.get("qa_elapsed_ms")) for event in relevant]
    return {
        "events": len(relevant),
        "source_counts": _compact_counter(Counter(event.payload.get("qa_source") for event in relevant)),
        "elapsed_ms": {
            "p50": _percentile([v for v in latencies if v is not None], 50),
            "p95": _percentile([v for v in latencies if v is not None], 95),
            "avg": _mean([v for v in latencies if v is not None]),
        },
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# TravelMind Observability Summary",
        "",
        f"- Total parsed events: {summary['total_events']}",
        f"- Event counts: `{json.dumps(summary['event_counts'], ensure_ascii=False)}`",
        "",
        "## LLM",
        "",
        f"- Calls: {summary['llm']['calls']}",
        f"- Status counts: `{json.dumps(summary['llm']['status_counts'], ensure_ascii=False)}`",
        f"- Error counts: `{json.dumps(summary['llm']['error_counts'], ensure_ascii=False)}`",
        f"- Retryable failures: {summary['llm']['retryable_failures']}",
        f"- Latency ms: `{json.dumps(summary['llm']['latency_ms'], ensure_ascii=False)}`",
        f"- Draft parse status counts: `{json.dumps(summary['llm']['draft']['parse_status_counts'], ensure_ascii=False)}`",
        f"- Draft destination counts: `{json.dumps(summary['llm']['draft']['destination_counts'], ensure_ascii=False)}`",
        f"- Draft response language counts: `{json.dumps(summary['llm']['draft']['response_language_counts'], ensure_ascii=False)}`",
        f"- Draft days count: `{json.dumps(summary['llm']['draft']['days_count'], ensure_ascii=False)}`",
        f"- Draft prompt chars: `{json.dumps(summary['llm']['draft']['prompt_chars'], ensure_ascii=False)}`",
        f"- Draft user prompt chars: `{json.dumps(summary['llm']['draft']['user_prompt_chars'], ensure_ascii=False)}`",
        f"- Draft candidate section chars: `{json.dumps(summary['llm']['draft']['candidate_section_chars'], ensure_ascii=False)}`",
        f"- Draft candidate count: `{json.dumps(summary['llm']['draft']['candidate_count'], ensure_ascii=False)}`",
        f"- Draft output chars: `{json.dumps(summary['llm']['draft']['output_chars'], ensure_ascii=False)}`",
        "",
        "## Semantic Cache",
        "",
        f"- Lookups: {summary['cache']['lookups']}",
        f"- Source counts: `{json.dumps(summary['cache']['source_counts'], ensure_ascii=False)}`",
        f"- Hit rate: {summary['cache']['hit_rate']}",
        f"- Lookup ms: `{json.dumps(summary['cache']['lookup_ms'], ensure_ascii=False)}`",
        f"- Max scanned count: {summary['cache']['max_scanned_count']}",
        "",
        "## Providers",
        "",
    ]

    if summary["providers"]["by_provider"]:
        for provider_key, provider in summary["providers"]["by_provider"].items():
            lines.extend(
                [
                    f"### {provider_key}",
                    "",
                    f"- Calls: {provider['calls']}",
                    f"- Status counts: `{json.dumps(provider['status_counts'], ensure_ascii=False)}`",
                    f"- Error counts: `{json.dumps(provider['error_counts'], ensure_ascii=False)}`",
                    f"- Degraded count: {provider['degraded_count']}",
                    f"- Elapsed ms: `{json.dumps(provider['elapsed_ms'], ensure_ascii=False)}`",
                    "",
                ]
            )
    else:
        lines.extend(["- No provider events parsed.", ""])

    lines.extend(
        [
            "## Location Backfill",
            "",
            f"- Location events: {summary['backfill']['location_events']}",
            f"- Summary events: {summary['backfill']['summary_events']}",
            f"- Source counts: `{json.dumps(summary['backfill']['source_counts'], ensure_ascii=False)}`",
            f"- Confidence counts: `{json.dumps(summary['backfill']['confidence_counts'], ensure_ascii=False)}`",
            f"- Fallback reasons: `{json.dumps(summary['backfill']['fallback_reasons'], ensure_ascii=False)}`",
            f"- Provider status counts: `{json.dumps(summary['backfill']['provider_status_counts'], ensure_ascii=False)}`",
            f"- Variant limit reached count: {summary['backfill']['variant_limit_reached_count']}",
            f"- Rejected bbox/score/missing coord: {summary['backfill']['rejected_bbox_count']}/{summary['backfill']['rejected_score_count']}/{summary['backfill']['rejected_missing_coord_count']}",
            f"- Cache negative hits: {summary['backfill']['cache_negative_hit_count']}",
            f"- BBox invalid count: {summary['backfill']['bbox_invalid_count']}",
            f"- Attempted/Filled/Skipped/Unresolved: {summary['backfill']['attempted']}/{summary['backfill']['filled']}/{summary['backfill']['skipped']}/{summary['backfill']['unresolved']}",
            f"- Skipped events: {summary['backfill']['skipped_events']}",
            f"- Elapsed ms: `{json.dumps(summary['backfill']['elapsed_ms'], ensure_ascii=False)}`",
            f"- Best match score: `{json.dumps(summary['backfill']['best_match_score'], ensure_ascii=False)}`",
            "",
        ]
    )
    if summary["backfill"]["unresolved_samples"]:
        lines.extend(
            [
                "### Backfill Unresolved Samples",
                "",
                "| Place | Day | Slot | Destination | Reason | Provider Status | Candidates | Best Candidate | Best Score | Elapsed ms |",
                "|-------|-----|------|-------------|--------|-----------------|------------|----------------|------------|------------|",
            ]
        )
        for sample in summary["backfill"]["unresolved_samples"]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _markdown_cell(sample.get("place")),
                        _markdown_cell(sample.get("day_index")),
                        _markdown_cell(sample.get("slot_label")),
                        _markdown_cell(sample.get("destination")),
                        _markdown_cell(sample.get("fallback_reason")),
                        _markdown_cell(json.dumps(sample.get("provider_status_counts") or {}, ensure_ascii=False)),
                        _markdown_cell(sample.get("candidate_count")),
                        _markdown_cell(sample.get("best_candidate_title")),
                        _markdown_cell(sample.get("best_match_score")),
                        _markdown_cell(sample.get("elapsed_ms")),
                    ]
                )
                + " |"
            )
        lines.append("")
    else:
        lines.extend(["### Backfill Unresolved Samples", "", "- No unresolved backfill samples.", ""])

    lines.extend(
        [
            "## QP",
            "",
            f"- Events: {summary['qp']['events']}",
            f"- Source counts: `{json.dumps(summary['qp']['source_counts'], ensure_ascii=False)}`",
            f"- Fallback reasons: `{json.dumps(summary['qp']['fallback_reasons'], ensure_ascii=False)}`",
            f"- Confidence: `{json.dumps(summary['qp']['confidence'], ensure_ascii=False)}`",
            "",
            "## QA",
            "",
            f"- Events: {summary['qa']['events']}",
            f"- Source counts: `{json.dumps(summary['qa']['source_counts'], ensure_ascii=False)}`",
            f"- Elapsed ms: `{json.dumps(summary['qa']['elapsed_ms'], ensure_ascii=False)}`",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize TravelMind observability logs.")
    parser.add_argument(
        "--log",
        dest="logs",
        action="append",
        type=Path,
        required=True,
        help="Log file to parse. Can be passed more than once.",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Output format.",
    )
    parser.add_argument("--output", type=Path, help="Output file. Defaults to stdout.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    missing = [str(path) for path in args.logs if not path.exists()]
    if missing:
        raise SystemExit(f"Log file not found: {', '.join(missing)}")

    summary = summarize_events(iter_events(args.logs))
    output = (
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
        if args.format == "json"
        else render_markdown(summary)
    )

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8", newline="\n")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
