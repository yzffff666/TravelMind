"""Build a manifest over TravelMind candidate decision dataset runs.

The manifest indexes per-run candidate decision summaries so multiple smoke
runs can be compared without opening each report directory by hand.

Usage:
    python -m scripts.candidate_dataset_manifest --root reports --output reports/candidate-dataset-manifest.json --markdown-output reports/candidate-dataset-manifest.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable


SUMMARY_FILENAME = "candidate-decisions-summary.json"


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_or_none(value: Any, digits: int = 4) -> float | None:
    number = _as_float(value)
    return round(number, digits) if number is not None else None


def _top_counts(counts: dict[str, Any], limit: int = 5) -> dict[str, int]:
    normalized: list[tuple[str, int]] = []
    for key, value in (counts or {}).items():
        if key in {None, ""}:
            continue
        try:
            normalized.append((str(key), int(value)))
        except (TypeError, ValueError):
            continue
    return dict(sorted(normalized, key=lambda item: item[1], reverse=True)[:limit])


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_entry_from_summary(path: Path, *, root: Path) -> dict[str, Any]:
    summary = _load_json(path)
    metadata = summary.get("run_metadata") or {}
    total_samples = int(summary.get("total_samples") or 0)
    decision_rates = summary.get("decision_rates") or {}
    label_rates = summary.get("label_rates") or {}
    quality_avg = summary.get("quality_breakdown_avg") or {}

    return {
        "run_id": metadata.get("run_id") or path.parent.name,
        "summary_path": str(path.relative_to(root)),
        "run_dir": str(path.parent.relative_to(root)),
        "generated_at": metadata.get("generated_at"),
        "case_set": metadata.get("case_set"),
        "case_count": metadata.get("case_count"),
        "total_samples": total_samples,
        "accepted_rate": _round_or_none(decision_rates.get("accepted")),
        "rejected_rate": _round_or_none(decision_rates.get("rejected") or label_rates.get("rejected")),
        "skipped_rate": _round_or_none(decision_rates.get("skipped")),
        "match_score_avg": _round_or_none(summary.get("match_score_avg")),
        "accepted_match_score_avg": _round_or_none(
            (summary.get("match_score_avg_by_decision") or {}).get("accepted")
        ),
        "rejected_match_score_avg": _round_or_none(
            (summary.get("match_score_avg_by_decision") or {}).get("rejected")
        ),
        "elapsed_ms_avg": _round_or_none(summary.get("elapsed_ms_avg"), digits=2),
        "bbox_valid_avg": _round_or_none(quality_avg.get("bbox_valid")),
        "has_candidate_geo_avg": _round_or_none(quality_avg.get("has_candidate_geo")),
        "is_low_confidence_avg": _round_or_none(quality_avg.get("is_low_confidence")),
        "top_risk_flags": _top_counts(summary.get("risk_flag_counts") or {}),
        "top_fallback_reasons": _top_counts(summary.get("fallback_reason_counts") or {}),
    }


def _metric_delta(current: dict[str, Any], previous: dict[str, Any], key: str) -> float | int | None:
    current_value = current.get(key)
    previous_value = previous.get(key)
    if current_value is None or previous_value is None:
        return None
    if isinstance(current_value, int) and isinstance(previous_value, int):
        return current_value - previous_value
    current_number = _as_float(current_value)
    previous_number = _as_float(previous_value)
    if current_number is None or previous_number is None:
        return None
    return round(current_number - previous_number, 4)


def add_run_deltas(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tracked_metrics = (
        "total_samples",
        "accepted_rate",
        "rejected_rate",
        "is_low_confidence_avg",
        "bbox_valid_avg",
        "match_score_avg",
        "elapsed_ms_avg",
    )
    previous: dict[str, Any] | None = None
    for run in runs:
        if previous is None:
            run["previous_run_id"] = None
            run["deltas"] = {}
        else:
            run["previous_run_id"] = previous.get("run_id")
            run["deltas"] = {
                key: delta
                for key in tracked_metrics
                if (delta := _metric_delta(run, previous, key)) is not None
            }
        previous = run
    return runs


def collect_manifest(root: Path) -> dict[str, Any]:
    root = root.resolve()
    summary_paths = sorted(root.rglob(SUMMARY_FILENAME))
    runs = [run_entry_from_summary(path, root=root) for path in summary_paths]
    runs.sort(key=lambda item: (str(item.get("generated_at") or ""), str(item.get("run_id") or "")))
    add_run_deltas(runs)

    total_runs = len(runs)
    total_samples = sum(int(run.get("total_samples") or 0) for run in runs)
    return {
        "schema_version": "candidate_dataset_manifest_v1",
        "root": str(root),
        "total_runs": total_runs,
        "total_samples": total_samples,
        "runs": runs,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _markdown_cell(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, dict):
        value = ", ".join(f"{key}:{count}" for key, count in value.items()) or "-"
    return str(value).replace("|", "\\|")


def render_markdown(manifest: dict[str, Any]) -> str:
    lines = [
        "# Candidate Decision Dataset Manifest",
        "",
        f"- Runs: {manifest.get('total_runs', 0)}",
        f"- Samples: {manifest.get('total_samples', 0)}",
        "",
        "| Run | Case set | Samples | Accepted | Delta Accepted | Rejected | Delta Rejected | Low conf | BBox valid | Top risks |",
        "|-----|----------|---------|----------|------------|----------|------------|----------|------------|-----------|",
    ]
    for run in manifest.get("runs") or []:
        lines.append(
            "| "
            + " | ".join(
                _markdown_cell(value)
                for value in [
                    run.get("run_id"),
                    run.get("case_set"),
                    run.get("total_samples"),
                    run.get("accepted_rate"),
                    (run.get("deltas") or {}).get("accepted_rate"),
                    run.get("rejected_rate"),
                    (run.get("deltas") or {}).get("rejected_rate"),
                    run.get("is_low_confidence_avg"),
                    run.get("bbox_valid_avg"),
                    run.get("top_risk_flags"),
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def write_markdown(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(manifest), encoding="utf-8", newline="\n")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a manifest for candidate decision dataset runs.")
    parser.add_argument("--root", type=Path, default=Path("reports"), help="Reports root to scan.")
    parser.add_argument("--output", type=Path, required=True, help="Output manifest JSON path.")
    parser.add_argument("--markdown-output", type=Path, help="Optional Markdown manifest path.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    manifest = collect_manifest(args.root)
    write_json(args.output, manifest)
    if args.markdown_output:
        write_markdown(args.markdown_output, manifest)
    print(f"Indexed {manifest['total_runs']} candidate decision runs with {manifest['total_samples']} samples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
