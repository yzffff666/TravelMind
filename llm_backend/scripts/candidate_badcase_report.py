"""Build a prioritized badcase report from candidate decision samples."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "candidate_badcase_report_v1"

ACTIONABLE_FALLBACK_WEIGHTS = {
    "score_rejected": 70,
    "bbox_rejected": 65,
    "provider_empty_or_timeout": 55,
    "total_budget_exhausted": 35,
    "generic_activity": 20,
}
RISK_FLAG_WEIGHTS = {
    "score_rejected": 30,
    "bbox_rejected": 30,
    "provider_empty_or_timeout": 24,
    "low_confidence": 16,
    "variant_limit_reached": 10,
    "cache_negative_hit": 8,
    "generic_activity": 4,
}


def read_jsonl(paths: list[Path]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                sample = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}") from exc
            if isinstance(sample, dict):
                sample["_source_path"] = str(path)
                samples.append(sample)
    return samples


def _bool_score(value: Any) -> int:
    return 1 if value is True else 0


def _risk_priority(sample: dict[str, Any]) -> int:
    quality = sample.get("quality_breakdown") if isinstance(sample.get("quality_breakdown"), dict) else {}
    risk_flags = sample.get("risk_flags") if isinstance(sample.get("risk_flags"), list) else []
    fallback_reason = sample.get("fallback_reason")
    score = ACTIONABLE_FALLBACK_WEIGHTS.get(str(fallback_reason), 0)
    score += sum(RISK_FLAG_WEIGHTS.get(str(flag), 0) for flag in risk_flags)

    if sample.get("decision") == "rejected":
        score += 35
    elif sample.get("decision") == "skipped":
        score += 12

    if sample.get("candidate_title"):
        score += 16
    if quality.get("has_candidate_geo") is True:
        score += 12
    if quality.get("bbox_valid") is False:
        score += 10
    if quality.get("address_contains_destination") is True:
        score += 6
    if sample.get("match_score") is not None:
        score += 5
    if not sample.get("candidate_title"):
        score -= 8
    return score


def _should_include(sample: dict[str, Any]) -> bool:
    if sample.get("decision") in {"rejected", "skipped"}:
        return True
    risk_flags = sample.get("risk_flags")
    return isinstance(risk_flags, list) and bool(risk_flags)


def _to_badcase(sample: dict[str, Any]) -> dict[str, Any]:
    quality = sample.get("quality_breakdown") if isinstance(sample.get("quality_breakdown"), dict) else {}
    risk_flags = sample.get("risk_flags") if isinstance(sample.get("risk_flags"), list) else []
    return {
        "priority": _risk_priority(sample),
        "decision": sample.get("decision"),
        "label": sample.get("label"),
        "destination": sample.get("destination"),
        "place": sample.get("place"),
        "candidate_title": sample.get("candidate_title"),
        "candidate_provider": sample.get("candidate_provider"),
        "fallback_reason": sample.get("fallback_reason"),
        "risk_flags": risk_flags,
        "match_score": sample.get("match_score"),
        "title_similarity": quality.get("title_similarity"),
        "english_token_overlap": quality.get("english_token_overlap"),
        "address_contains_destination": quality.get("address_contains_destination"),
        "has_candidate_geo": quality.get("has_candidate_geo"),
        "bbox_valid": quality.get("bbox_valid"),
        "confidence": quality.get("confidence") or sample.get("confidence"),
        "elapsed_ms": sample.get("elapsed_ms"),
        "candidate_geo": _candidate_geo(sample),
        "source_log": sample.get("source_log"),
        "source_path": sample.get("_source_path"),
    }


def _candidate_geo(sample: dict[str, Any]) -> str | None:
    lat = sample.get("candidate_lat")
    lng = sample.get("candidate_lng")
    if lat is None or lng is None:
        return None
    return f"{lat},{lng}"


def build_badcase_report(samples: list[dict[str, Any]], limit: int = 20) -> dict[str, Any]:
    badcases = [_to_badcase(sample) for sample in samples if _should_include(sample)]
    badcases.sort(
        key=lambda item: (
            item["priority"],
            _bool_score(item.get("has_candidate_geo")),
            item.get("match_score") if item.get("match_score") is not None else -1,
        ),
        reverse=True,
    )
    selected = badcases[:limit]
    risk_counts = Counter(flag for item in badcases for flag in item.get("risk_flags", []))
    fallback_counts = Counter(
        str(item["fallback_reason"]) for item in badcases if item.get("fallback_reason")
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "total_input_samples": len(samples),
        "total_badcases": len(badcases),
        "reported_badcases": len(selected),
        "top_risk_flags": dict(risk_counts.most_common()),
        "top_fallback_reasons": dict(fallback_counts.most_common()),
        "badcases": selected,
    }


def _md(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        text = f"{value:.4f}".rstrip("0").rstrip(".")
    elif isinstance(value, list):
        text = ", ".join(str(item) for item in value) or "-"
    else:
        text = str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _unique_reason_text(item: dict[str, Any]) -> str:
    reasons: list[str] = []
    for reason in [item.get("fallback_reason")] + list(item.get("risk_flags") or []):
        if reason and str(reason) not in reasons:
            reasons.append(str(reason))
    return ", ".join(reasons)


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Candidate Badcase Report",
        "",
        f"- Schema: `{report['schema_version']}`",
        f"- Input samples: {report['total_input_samples']}",
        f"- Badcases: {report['total_badcases']}",
        f"- Reported: {report['reported_badcases']}",
        "",
        "## Top Fallback Reasons",
        "",
    ]
    fallback_reasons = report.get("top_fallback_reasons") or {}
    if fallback_reasons:
        for reason, count in fallback_reasons.items():
            lines.append(f"- `{reason}`: {count}")
    else:
        lines.append("- None")

    lines.extend(["", "## Top Risk Flags", ""])
    risk_flags = report.get("top_risk_flags") or {}
    if risk_flags:
        for flag, count in risk_flags.items():
            lines.append(f"- `{flag}`: {count}")
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Prioritized Badcases",
            "",
            "| Priority | Decision | Place | Candidate | Destination | Reason | Score | Title Sim | BBox | Geo | Elapsed ms |",
            "|----------|----------|-------|-----------|-------------|--------|-------|-----------|------|-----|------------|",
        ]
    )
    for item in report.get("badcases", []):
        reason = _unique_reason_text(item)
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(item.get("priority")),
                    _md(item.get("decision")),
                    _md(item.get("place")),
                    _md(item.get("candidate_title")),
                    _md(item.get("destination")),
                    _md(reason),
                    _md(item.get("match_score")),
                    _md(item.get("title_similarity")),
                    _md(item.get("bbox_valid")),
                    _md(item.get("candidate_geo")),
                    _md(item.get("elapsed_ms")),
                ]
            )
            + " |"
        )
    if not report.get("badcases"):
        lines.append("| - | - | - | - | - | - | - | - | - | - | - |")

    lines.extend(
        [
            "",
            "## How To Use",
            "",
            "- Prefer high-priority rows with a candidate title and geo for manual audit.",
            "- `score_rejected` with plausible geo usually points to alias/query-string tuning.",
            "- `bbox_rejected` usually points to destination normalization or bbox policy tuning.",
            "- Missing candidate title usually means provider recall or timeout needs investigation first.",
            "",
        ]
    )
    return "\n".join(lines)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(report), encoding="utf-8", newline="\n")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a prioritized candidate badcase report.")
    parser.add_argument("--input", type=Path, nargs="+", required=True, help="candidate-decisions JSONL file(s).")
    parser.add_argument("--output", type=Path, required=True, help="Markdown report output path.")
    parser.add_argument("--json-output", type=Path, help="Optional JSON report output path.")
    parser.add_argument("--limit", type=int, default=20, help="Maximum badcases to show in the report.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    samples = read_jsonl(args.input)
    report = build_badcase_report(samples, limit=args.limit)
    write_markdown(args.output, report)
    if args.json_output:
        write_json(args.json_output, report)
    print(f"Candidate badcase report written to: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
