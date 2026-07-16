"""Offline ranking evaluation for TravelMind POI candidate decisions.

The evaluator compares the legacy ``RankingScorer`` with the explicit
``POIRankingPolicy`` on deterministic badcase fixtures. It does not call live
providers or LLMs; it is a fast gate for ranking-policy regressions.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.services.poi_ranking_policy import POIRankingPolicy, build_ranking_shadow_report
from app.services.providers.base import ProviderCandidate
from app.services.ranking_scorer import RankingScorer


DEFAULT_CASES_PATH = Path("evaluation/ranking_eval_cases.json")
DEFAULT_OUTPUT_ROOT = Path("reports/ranking-eval")


@dataclass(slots=True)
class RankingEvalCaseResult:
    case_id: str
    destination: str
    recalled_count: int
    top_k: int
    legacy_top_ids: list[str]
    policy_top_ids: list[str]
    policy_rejected_ids: list[str]
    expected_good_ids: list[str]
    expected_rejected: dict[str, list[str]]
    good_hit_count: int
    good_hit_rate: float | None
    rejected_expected_count: int
    rejected_expected_rate: float | None
    unexpected_rejected_good_ids: list[str]
    missing_expected_rejected_ids: list[str]
    reject_reason_mismatches: dict[str, dict[str, list[str]]]
    shadow_report: dict[str, Any]

    @property
    def passed(self) -> bool:
        return (
            self.good_hit_count == len(self.expected_good_ids)
            and not self.unexpected_rejected_good_ids
            and not self.missing_expected_rejected_ids
            and not self.reject_reason_mismatches
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "destination": self.destination,
            "status": "passed" if self.passed else "failed",
            "recalled_count": self.recalled_count,
            "top_k": self.top_k,
            "legacy_top_ids": self.legacy_top_ids,
            "policy_top_ids": self.policy_top_ids,
            "policy_rejected_ids": self.policy_rejected_ids,
            "expected_good_ids": self.expected_good_ids,
            "expected_rejected": self.expected_rejected,
            "good_hit_count": self.good_hit_count,
            "good_hit_rate": self.good_hit_rate,
            "rejected_expected_count": self.rejected_expected_count,
            "rejected_expected_rate": self.rejected_expected_rate,
            "unexpected_rejected_good_ids": self.unexpected_rejected_good_ids,
            "missing_expected_rejected_ids": self.missing_expected_rejected_ids,
            "reject_reason_mismatches": self.reject_reason_mismatches,
            "shadow_report": self.shadow_report,
        }


def load_cases(path: Path = DEFAULT_CASES_PATH) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("ranking eval cases must be a JSON list")
    return payload


def _candidate_from_payload(payload: dict[str, Any]) -> ProviderCandidate:
    return ProviderCandidate(
        candidate_id=str(payload["candidate_id"]),
        source=str(payload.get("source") or "fixture"),
        title=str(payload.get("title") or ""),
        snippet=str(payload.get("snippet") or ""),
        score=float(payload.get("score") or 0.0),
        tags=[str(item) for item in (payload.get("tags") or [])],
        extra=dict(payload.get("extra") or {}),
    )


def _candidate_ids(items: Iterable[Any]) -> list[str]:
    ids: list[str] = []
    for item in items:
        candidate = item.candidate if hasattr(item, "candidate") else item
        ids.append(str(candidate.candidate_id))
    return ids


def evaluate_case(case: dict[str, Any]) -> RankingEvalCaseResult:
    candidates = [_candidate_from_payload(item) for item in case.get("candidates") or []]
    destination = str(case.get("destination") or "")
    preferences = [str(item) for item in (case.get("preferences") or [])]
    budget = case.get("budget")
    days = case.get("days")
    top_k = int(case.get("top_k") or 3)
    expected_good_ids = [str(item) for item in (case.get("expected_good_ids") or [])]
    expected_rejected = {
        str(candidate_id): [str(reason) for reason in reasons]
        for candidate_id, reasons in dict(case.get("expected_rejected") or {}).items()
    }

    legacy_ranked = RankingScorer().rank(
        candidates,
        preferences=preferences,
        budget=float(budget) if budget is not None else None,
        days=int(days) if days is not None else None,
        top_k=max(len(candidates), top_k),
    )
    policy_ranked = POIRankingPolicy().rank(
        candidates,
        destination=destination,
        preferences=preferences,
        budget=float(budget) if budget is not None else None,
        days=int(days) if days is not None else None,
        top_k=max(len(candidates), top_k),
        include_rejected=True,
    )

    accepted = [item for item in policy_ranked if item.accepted]
    rejected = [item for item in policy_ranked if not item.accepted]
    policy_top_ids = _candidate_ids(accepted[:top_k])
    rejected_by_id = {item.candidate.candidate_id: item for item in rejected}

    good_hit_count = sum(1 for candidate_id in expected_good_ids if candidate_id in policy_top_ids)
    rejected_expected_ids = [
        candidate_id for candidate_id in expected_rejected
        if candidate_id in rejected_by_id
    ]
    unexpected_rejected_good_ids = [
        candidate_id for candidate_id in expected_good_ids
        if candidate_id in rejected_by_id
    ]
    missing_expected_rejected_ids = [
        candidate_id for candidate_id in expected_rejected
        if candidate_id not in rejected_by_id
    ]
    reject_reason_mismatches: dict[str, dict[str, list[str]]] = {}
    for candidate_id, expected_reasons in expected_rejected.items():
        item = rejected_by_id.get(candidate_id)
        if item is None:
            continue
        missing = [reason for reason in expected_reasons if reason not in item.reject_reasons]
        if missing:
            reject_reason_mismatches[candidate_id] = {
                "expected": expected_reasons,
                "actual": item.reject_reasons,
            }

    shadow_report = build_ranking_shadow_report(
        destination=destination,
        recalled_count=len(candidates),
        legacy_ranked=legacy_ranked,
        policy_ranked=policy_ranked,
        top_k=top_k,
    )

    return RankingEvalCaseResult(
        case_id=str(case.get("case_id") or "unnamed"),
        destination=destination,
        recalled_count=len(candidates),
        top_k=top_k,
        legacy_top_ids=_candidate_ids(legacy_ranked[:top_k]),
        policy_top_ids=policy_top_ids,
        policy_rejected_ids=_candidate_ids(rejected),
        expected_good_ids=expected_good_ids,
        expected_rejected=expected_rejected,
        good_hit_count=good_hit_count,
        good_hit_rate=round(good_hit_count / len(expected_good_ids), 4) if expected_good_ids else None,
        rejected_expected_count=len(rejected_expected_ids),
        rejected_expected_rate=(
            round(len(rejected_expected_ids) / len(expected_rejected), 4)
            if expected_rejected else None
        ),
        unexpected_rejected_good_ids=unexpected_rejected_good_ids,
        missing_expected_rejected_ids=missing_expected_rejected_ids,
        reject_reason_mismatches=reject_reason_mismatches,
        shadow_report=shadow_report,
    )


def build_report(cases: list[dict[str, Any]]) -> dict[str, Any]:
    results = [evaluate_case(case) for case in cases]
    failed = [result for result in results if not result.passed]
    reason_counts: Counter[str] = Counter()
    for result in results:
        reason_counts.update(result.shadow_report.get("reject_reason_counts") or {})

    expected_good_total = sum(len(result.expected_good_ids) for result in results)
    good_hit_total = sum(result.good_hit_count for result in results)
    expected_rejected_total = sum(len(result.expected_rejected) for result in results)
    rejected_expected_total = sum(result.rejected_expected_count for result in results)

    return {
        "schema_version": "ranking_eval_report_v1",
        "status": "passed" if not failed else "failed",
        "case_count": len(results),
        "passed_cases": len(results) - len(failed),
        "failed_cases": len(failed),
        "summary": {
            "expected_good_total": expected_good_total,
            "good_hit_total": good_hit_total,
            "good_hit_rate": (
                round(good_hit_total / expected_good_total, 4)
                if expected_good_total else None
            ),
            "expected_rejected_total": expected_rejected_total,
            "rejected_expected_total": rejected_expected_total,
            "rejected_expected_rate": (
                round(rejected_expected_total / expected_rejected_total, 4)
                if expected_rejected_total else None
            ),
            "reject_reason_counts": dict(reason_counts),
        },
        "cases": [result.to_dict() for result in results],
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# TravelMind Ranking Eval Report",
        "",
        f"- Status: `{report['status']}`",
        f"- Cases: {report['passed_cases']}/{report['case_count']} passed",
        f"- Good hit rate: {summary.get('good_hit_rate')}",
        f"- Expected reject rate: {summary.get('rejected_expected_rate')}",
        f"- Reject reasons: `{json.dumps(summary.get('reject_reason_counts') or {}, ensure_ascii=False)}`",
        "",
        "| Case | Destination | Status | Legacy Top | Policy Top | Rejected |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for case in report.get("cases") or []:
        lines.append(
            "| {case_id} | {destination} | {status} | {legacy} | {policy} | {rejected} |".format(
                case_id=case["case_id"],
                destination=case["destination"],
                status=case["status"],
                legacy=", ".join(case["legacy_top_ids"]) or "-",
                policy=", ".join(case["policy_top_ids"]) or "-",
                rejected=", ".join(case["policy_rejected_ids"]) or "-",
            )
        )
    lines.append("")
    return "\n".join(lines)


def write_outputs(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "ranking-eval-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (output_dir / "ranking-eval-report.md").write_text(
        render_markdown(report),
        encoding="utf-8",
        newline="\n",
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run offline POI ranking evaluation.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT / "latest")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(list(argv) if argv is not None else None)

    report = build_report(load_cases(args.cases))
    write_outputs(report, args.output_dir)
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        summary = report["summary"]
        print(
            "ranking_eval={status} cases={passed}/{total} good_hit_rate={good} "
            "expected_reject_rate={reject} artifacts={artifacts}".format(
                status=report["status"],
                passed=report["passed_cases"],
                total=report["case_count"],
                good=summary.get("good_hit_rate"),
                reject=summary.get("rejected_expected_rate"),
                artifacts=args.output_dir,
            )
        )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
