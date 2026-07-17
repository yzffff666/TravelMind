"""Build and summarize the human-audit dataset for POI candidate decisions.

The online pipeline emits weak labels from its current ranking policy.  This
script turns the risky subset into a small, reviewable queue and then validates
the completed queue before it is used as an evaluation or training asset.

Examples:
    python -m scripts.candidate_audit_dataset queue \
      --input reports/.../candidate-decisions.jsonl \
      --output reports/.../candidate-audit-queue.jsonl

    python -m scripts.candidate_audit_dataset summarize \
      --input reports/.../candidate-audit-queue.jsonl \
      --output reports/.../candidate-audit-summary.json \
      --labeled-output reports/.../candidate-audit-labeled.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from scripts.candidate_badcase_report import classify_action_type, risk_priority


QUEUE_SCHEMA_VERSION = "candidate_audit_queue_v1"
SUMMARY_SCHEMA_VERSION = "candidate_audit_summary_v1"
PENDING = "pending"
REVIEWED = "reviewed"
VALID_AUDIT_STATUSES = {PENDING, REVIEWED}
VALID_HUMAN_LABELS = {"accepted", "rejected", "uncertain", "not_reviewable"}


def read_jsonl(paths: Iterable[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"Expected object JSONL row at {path}:{line_number}")
            rows.append(row)
    return rows


def _compact_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _weak_label(sample: dict[str, Any]) -> str:
    value = str(
        sample.get("weak_label") or sample.get("label") or sample.get("decision") or ""
    ).strip().lower()
    return value if value in {"accepted", "rejected"} else ""


def _audit_id(sample: dict[str, Any]) -> str:
    identity = {
        "destination": _compact_text(sample.get("destination")).lower(),
        "place": _compact_text(sample.get("place")).lower(),
        "candidate_title": _compact_text(sample.get("candidate_title")).lower(),
        "candidate_provider": _compact_text(sample.get("candidate_provider")).lower(),
        "candidate_lat": sample.get("candidate_lat"),
        "candidate_lng": sample.get("candidate_lng"),
    }
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return f"poi-audit-{digest}"


def _should_queue(sample: dict[str, Any]) -> bool:
    decision = str(sample.get("decision") or "")
    risk_flags = sample.get("risk_flags")
    return decision in {"rejected", "skipped"} or (decision == "accepted" and bool(risk_flags))


def _audit_reason(sample: dict[str, Any]) -> str:
    decision = str(sample.get("decision") or "")
    fallback_reason = _compact_text(sample.get("fallback_reason"))
    risk_flags = [str(flag) for flag in (sample.get("risk_flags") or []) if flag]
    reasons = [fallback_reason, *risk_flags]
    unique = list(dict.fromkeys(reason for reason in reasons if reason))
    if decision in {"rejected", "skipped"}:
        return ", ".join(unique) or "ranking_rejected"
    return ", ".join(unique) or "accepted_with_risk_flag"


def _action(sample: dict[str, Any]) -> str:
    quality = sample.get("quality_breakdown")
    return classify_action_type(
        sample,
        quality if isinstance(quality, dict) else {},
        sample.get("risk_flags") if isinstance(sample.get("risk_flags"), list) else [],
    )


def _queue_row(sample: dict[str, Any]) -> dict[str, Any]:
    quality = sample.get("quality_breakdown")
    quality = quality if isinstance(quality, dict) else {}
    return {
        "schema_version": QUEUE_SCHEMA_VERSION,
        "audit_id": _audit_id(sample),
        "audit_priority": risk_priority(sample),
        "audit_reason": _audit_reason(sample),
        "action_type": _action(sample),
        "source_count": 1,
        "source_decisions": [str(sample.get("decision") or "")],
        "weak_label": _weak_label(sample),
        "label_source": str(sample.get("label_source") or "rule"),
        "destination": sample.get("destination"),
        "place": sample.get("place"),
        "activity": sample.get("activity"),
        "candidate_title": sample.get("candidate_title"),
        "candidate_provider": sample.get("candidate_provider"),
        "candidate_address": sample.get("candidate_address"),
        "candidate_lat": sample.get("candidate_lat"),
        "candidate_lng": sample.get("candidate_lng"),
        "fallback_reason": sample.get("fallback_reason"),
        "risk_flags": list(sample.get("risk_flags") or []),
        "match_score": sample.get("match_score"),
        "quality_breakdown": quality,
        "audit": {
            "status": PENDING,
            "human_label": None,
            "reviewer": "",
            "rationale": "",
            "reviewed_at": None,
        },
    }


def build_audit_queue(samples: Iterable[dict[str, Any]], *, limit: int = 100) -> list[dict[str, Any]]:
    """Build a deduplicated, risk-prioritized review queue from weak labels."""
    deduplicated: dict[str, dict[str, Any]] = {}
    for sample in samples:
        if not _should_queue(sample):
            continue
        row = _queue_row(sample)
        existing = deduplicated.get(row["audit_id"])
        if existing is None:
            deduplicated[row["audit_id"]] = row
            continue

        existing["source_count"] += 1
        existing["audit_priority"] = max(existing["audit_priority"], row["audit_priority"])
        existing["source_decisions"] = sorted(
            set(existing["source_decisions"]) | set(row["source_decisions"])
        )
        existing["risk_flags"] = sorted(set(existing["risk_flags"]) | set(row["risk_flags"]))
        if row["audit_reason"] not in existing["audit_reason"].split(", "):
            existing["audit_reason"] = ", ".join(
                filter(None, [existing["audit_reason"], row["audit_reason"]])
            )

    ordered = sorted(
        deduplicated.values(),
        key=lambda row: (int(row["audit_priority"]), int(row["source_count"])),
        reverse=True,
    )
    return ordered[: max(0, limit)]


def validate_audit_row(row: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if row.get("schema_version") != QUEUE_SCHEMA_VERSION:
        errors.append(f"schema_version must be {QUEUE_SCHEMA_VERSION}")
    if not _compact_text(row.get("audit_id")):
        errors.append("audit_id is required")
    audit = row.get("audit")
    if not isinstance(audit, dict):
        return [*errors, "audit must be an object"]
    status = str(audit.get("status") or "")
    if status not in VALID_AUDIT_STATUSES:
        errors.append(f"audit.status must be one of {sorted(VALID_AUDIT_STATUSES)}")
    label = audit.get("human_label")
    if status == PENDING and label is not None:
        errors.append("pending audit must not have human_label")
    if status == REVIEWED:
        if label not in VALID_HUMAN_LABELS:
            errors.append(f"reviewed audit.human_label must be one of {sorted(VALID_HUMAN_LABELS)}")
        if not _compact_text(audit.get("reviewer")):
            errors.append("reviewed audit requires reviewer")
        if not _compact_text(audit.get("rationale")):
            errors.append("reviewed audit requires rationale")
        if not _compact_text(audit.get("reviewed_at")):
            errors.append("reviewed audit requires reviewed_at")
    return errors


def summarize_audit_queue(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    row_list = list(rows)
    invalid_rows: list[dict[str, Any]] = []
    reviewed: list[dict[str, Any]] = []
    pending_count = 0
    for row in row_list:
        errors = validate_audit_row(row)
        if errors:
            invalid_rows.append({"audit_id": row.get("audit_id"), "errors": errors})
            continue
        if (row.get("audit") or {}).get("status") == REVIEWED:
            reviewed.append(row)
        else:
            pending_count += 1

    label_counts = Counter(
        str((row.get("audit") or {}).get("human_label")) for row in reviewed
    )
    action_counts = Counter(str(row.get("action_type") or "unknown") for row in reviewed)
    agreement_total = 0
    agreement_matches = 0
    for row in reviewed:
        label = str((row.get("audit") or {}).get("human_label"))
        weak_label = _weak_label(row)
        if label not in {"accepted", "rejected"} or not weak_label:
            continue
        agreement_total += 1
        agreement_matches += int(label == weak_label)

    binary_labeled = [
        row
        for row in reviewed
        if (row.get("audit") or {}).get("human_label") in {"accepted", "rejected"}
    ]
    binary_counts = Counter(str((row.get("audit") or {}).get("human_label")) for row in binary_labeled)
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "status": "passed" if not invalid_rows else "failed",
        "total_rows": len(row_list),
        "pending_rows": pending_count,
        "reviewed_rows": len(reviewed),
        "invalid_rows": invalid_rows,
        "human_label_counts": dict(sorted(label_counts.items())),
        "action_type_counts": dict(sorted(action_counts.items())),
        "weak_label_agreement": {
            "comparable_rows": agreement_total,
            "matching_rows": agreement_matches,
            "agreement_rate": round(agreement_matches / agreement_total, 4) if agreement_total else None,
        },
        "model_ready": {
            "binary_labeled_rows": len(binary_labeled),
            "accepted_rows": binary_counts.get("accepted", 0),
            "rejected_rows": binary_counts.get("rejected", 0),
            "ready_for_small_offline_probe": len(binary_labeled) >= 100,
            "ready_for_stable_model_comparison": len(binary_labeled) >= 500,
        },
    }


def labeled_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Emit only validated binary human labels, preserving ranking features."""
    output: list[dict[str, Any]] = []
    for row in rows:
        if validate_audit_row(row):
            continue
        audit = row.get("audit") or {}
        label = audit.get("human_label")
        if audit.get("status") != REVIEWED or label not in {"accepted", "rejected"}:
            continue
        output.append(
            {
                "schema_version": "candidate_audit_label_v1",
                "audit_id": row.get("audit_id"),
                "label": label,
                "weak_label": _weak_label(row),
                "destination": row.get("destination"),
                "place": row.get("place"),
                "candidate_title": row.get("candidate_title"),
                "candidate_provider": row.get("candidate_provider"),
                "action_type": row.get("action_type"),
                "risk_flags": row.get("risk_flags") or [],
                "match_score": row.get("match_score"),
                "quality_breakdown": row.get("quality_breakdown") or {},
                "reviewer": audit.get("reviewer"),
                "reviewed_at": audit.get("reviewed_at"),
            }
        )
    return output


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or summarize TravelMind candidate audit data.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    queue_parser = subparsers.add_parser("queue", help="Create a human-review queue from candidate decision JSONL.")
    queue_parser.add_argument("--input", type=Path, nargs="+", required=True)
    queue_parser.add_argument("--output", type=Path, required=True)
    queue_parser.add_argument("--limit", type=int, default=100)

    summary_parser = subparsers.add_parser("summarize", help="Validate completed audits and produce label statistics.")
    summary_parser.add_argument("--input", type=Path, nargs="+", required=True)
    summary_parser.add_argument("--output", type=Path, required=True)
    summary_parser.add_argument("--labeled-output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    rows = read_jsonl(args.input)
    if args.command == "queue":
        queue = build_audit_queue(rows, limit=args.limit)
        count = write_jsonl(args.output, queue)
        print(f"Created {count} candidate audit rows at {args.output}")
        return 0

    summary = summarize_audit_queue(rows)
    write_json(args.output, summary)
    labeled_count = 0
    if args.labeled_output:
        labeled_count = write_jsonl(args.labeled_output, labeled_rows(rows))
    print(
        f"candidate_audit_summary={summary['status']} reviewed={summary['reviewed_rows']} "
        f"pending={summary['pending_rows']} labeled={labeled_count}"
    )
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
