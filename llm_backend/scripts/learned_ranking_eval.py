"""Evaluate rule and learned POI ranking on destination-isolated holdouts."""

from __future__ import annotations

import argparse
import json
import math
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from app.services.learned_poi_ranker import PairwiseLinearRanker, dataset_fingerprint
from scripts.build_learned_ranking_dataset import DEFAULT_DATASET_PATH
from scripts.train_poi_ranker import DEFAULT_MODEL_PATH, read_rows


DEFAULT_OUTPUT_ROOT = Path("reports/learned-ranking-eval")
EXPECTED_DATASET_COUNTS = {
    "rows": 576,
    "queries": 48,
    "destinations": 12,
    "train_rows": 384,
    "validation_rows": 96,
    "test_rows": 96,
    "train_destinations": 8,
    "validation_destinations": 2,
    "test_destinations": 2,
}


def _dcg(labels: list[int], *, top_k: int) -> float:
    return sum(
        (2**label - 1) / math.log2(index + 2)
        for index, label in enumerate(labels[:top_k])
    )


def _ndcg(labels: list[int], *, top_k: int) -> float:
    denominator = _dcg(sorted(labels, reverse=True), top_k=top_k)
    return _dcg(labels, top_k=top_k) / denominator if denominator else 1.0


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def _group_rows(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["query_id"])].append(row)
    return dict(grouped)


def _query_metrics(
    rows: list[dict[str, Any]],
    scores: list[float],
) -> tuple[float, float]:
    accepted = [
        (float(score), int(row["label"]))
        for row, score in zip(rows, scores, strict=True)
        if bool(row.get("hard_gate_passed", True))
    ]
    ranked_labels = [
        label
        for _score, label in sorted(
            accepted,
            key=lambda item: item[0],
            reverse=True,
        )
    ]
    ndcg_at_5 = _ndcg(ranked_labels, top_k=5)
    available_strong = min(3, sum(label == 2 for label in ranked_labels))
    captured_strong = sum(label == 2 for label in ranked_labels[:3])
    top3_rate = captured_strong / available_strong if available_strong else 1.0
    return ndcg_at_5, top3_rate


def evaluate_rankers(
    rows: list[dict[str, Any]],
    model: PairwiseLinearRanker,
) -> dict[str, Any]:
    split_destinations = {
        split: sorted(
            {
                str(row["destination_id"])
                for row in rows
                if row.get("split") == split
            }
        )
        for split in ("train", "validation", "test")
    }
    split_pairs = (
        ("train", "validation"),
        ("train", "test"),
        ("validation", "test"),
    )
    split_overlaps = {
        f"{left}_{right}": sorted(
            set(split_destinations[left]) & set(split_destinations[right])
        )
        for left, right in split_pairs
    }
    train_rows = [row for row in rows if row.get("split") == "train"]
    test_rows = [row for row in rows if row.get("split") == "test"]
    grouped = _group_rows(test_rows)
    rule_ndcgs: list[float] = []
    learned_ndcgs: list[float] = []
    rule_top3_rates: list[float] = []
    learned_top3_rates: list[float] = []
    latencies_ms: list[float] = []
    cases: list[dict[str, Any]] = []
    unsafe_accepted_count = 0
    hard_gate_rejected_count = 0
    model_scored_unsafe_count = 0

    for query_id, query_rows in sorted(grouped.items()):
        rule_scores = [float(row["rule_score"]) for row in query_rows]
        accepted_rows = [
            row
            for row in query_rows
            if bool(row.get("hard_gate_passed", True))
        ]
        started = time.perf_counter()
        learned_scores_array = model.predict_scores(accepted_rows)
        latencies_ms.append((time.perf_counter() - started) * 1000)
        learned_scores = [float(score) for score in learned_scores_array]

        rule_ndcg, rule_top3 = _query_metrics(query_rows, rule_scores)
        learned_ndcg, learned_top3 = _query_metrics(
            accepted_rows,
            learned_scores,
        )
        rule_ndcgs.append(rule_ndcg)
        learned_ndcgs.append(learned_ndcg)
        rule_top3_rates.append(rule_top3)
        learned_top3_rates.append(learned_top3)

        learned_order = sorted(
            zip(accepted_rows, learned_scores, strict=True),
            key=lambda item: item[1],
            reverse=True,
        )
        hard_gate_rejected_count += sum(
            not bool(row.get("hard_gate_passed", True))
            for row in query_rows
        )
        model_scored_unsafe_count += sum(
            not bool(row.get("hard_gate_passed", True))
            for row in accepted_rows
        )
        unsafe_accepted_count += sum(
            not bool(row.get("hard_gate_passed", True))
            for row, _score in learned_order
        )
        cases.append(
            {
                "query_id": query_id,
                "destination": query_rows[0]["destination"],
                "query_profile": query_rows[0]["query_profile"],
                "rule_ndcg_at_5": round(rule_ndcg, 6),
                "learned_ndcg_at_5": round(learned_ndcg, 6),
                "rule_preference_top3_rate": round(rule_top3, 6),
                "learned_preference_top3_rate": round(learned_top3, 6),
                "learned_top3": [
                    row["candidate_id"]
                    for row, _score in learned_order
                ][:3],
            }
        )

    average = lambda values: sum(values) / len(values) if values else 0.0
    split_row_counts = {
        split: sum(row.get("split") == split for row in rows)
        for split in ("train", "validation", "test")
    }
    actual_contract = {
        "rows": len(rows),
        "queries": len({row["query_id"] for row in rows}),
        "destinations": len({row["destination_id"] for row in rows}),
        "train_rows": split_row_counts["train"],
        "validation_rows": split_row_counts["validation"],
        "test_rows": split_row_counts["test"],
        "train_destinations": len(split_destinations["train"]),
        "validation_destinations": len(split_destinations["validation"]),
        "test_destinations": len(split_destinations["test"]),
    }
    current_train_fingerprint = dataset_fingerprint(train_rows)
    model_train_destinations = sorted(
        str(item) for item in model.training.get("train_destinations") or []
    )
    metrics = {
        "rule_ndcg_at_5": round(average(rule_ndcgs), 6),
        "learned_ndcg_at_5": round(average(learned_ndcgs), 6),
        "rule_preference_top3_rate": round(average(rule_top3_rates), 6),
        "learned_preference_top3_rate": round(average(learned_top3_rates), 6),
        "unsafe_accepted_count": unsafe_accepted_count,
        "hard_gate_rejected_count": hard_gate_rejected_count,
        "model_scored_unsafe_count": model_scored_unsafe_count,
        "inference_p95_ms": round(_percentile(latencies_ms, 0.95), 6),
    }
    failures: list[str] = []
    if actual_contract != EXPECTED_DATASET_COUNTS:
        failures.append("dataset contract mismatch")
    if any(split_overlaps.values()):
        failures.append("split destination overlap")
    if model.training.get("dataset_sha256") != current_train_fingerprint:
        failures.append("model/dataset training fingerprint mismatch")
    if model_train_destinations != split_destinations["train"]:
        failures.append("model training destination provenance mismatch")
    if model.training.get("test_row_count") != 0:
        failures.append("model metadata indicates test rows were used")
    if metrics["learned_ndcg_at_5"] < metrics["rule_ndcg_at_5"]:
        failures.append("learned NDCG@5 regressed")
    if (
        metrics["learned_preference_top3_rate"]
        < metrics["rule_preference_top3_rate"] + 0.05
    ):
        failures.append("learned preference Top-3 gain is below 0.05")
    if unsafe_accepted_count:
        failures.append("unsafe candidate bypassed the hard gate")
    if model_scored_unsafe_count:
        failures.append("unsafe candidate was sent to learned inference")
    if metrics["inference_p95_ms"] >= 100:
        failures.append("learned inference P95 exceeded 100ms")

    return {
        "schema_version": "learned_ranking_eval_v1",
        "status": "passed" if not failures else "failed",
        "failures": failures,
        "dataset": {
            "row_count": len(rows),
            "query_count": len({row["query_id"] for row in rows}),
            "destination_count": len({row["destination_id"] for row in rows}),
            "test_query_count": len(grouped),
            "split_destinations": split_destinations,
            "split_destination_overlaps": split_overlaps,
            "train_test_destination_overlap": split_overlaps["train_test"],
            "contract": actual_contract,
            "contract_expected": dict(EXPECTED_DATASET_COUNTS),
            "label_source": "curated_rubric_v1",
            "benchmark_scope": "destination_id_isolated_curated_rubric",
            "feature_source": "curated_feature_values",
        },
        "metrics": metrics,
        "model": {
            "schema_version": "poi_pairwise_linear_ranker_v1",
            "feature_names": list(model.feature_names),
            "training": dict(model.training),
        },
        "cases": cases,
    }


def render_markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    lines = [
        "# Hybrid Learned Ranking Eval",
        "",
        f"- Status: `{report['status']}`",
        f"- Dataset: {report['dataset']['row_count']} rows / "
        f"{report['dataset']['query_count']} queries / "
        f"{report['dataset']['destination_count']} destinations",
        f"- Rule vs learned NDCG@5: "
        f"{metrics['rule_ndcg_at_5']} -> {metrics['learned_ndcg_at_5']}",
        f"- Rule vs learned preference Top-3: "
        f"{metrics['rule_preference_top3_rate']} -> "
        f"{metrics['learned_preference_top3_rate']}",
        f"- Inference P95: {metrics['inference_p95_ms']} ms",
        f"- Unsafe accepted: {metrics['unsafe_accepted_count']}",
        f"- Hard-gate rejected: {metrics['hard_gate_rejected_count']}",
        f"- Unsafe scored by model: {metrics['model_scored_unsafe_count']}",
        "- Scope: destination-ID-isolated curated-rubric engineering benchmark",
        "- Caveat: shared POI archetypes do not establish real-world city generalization",
        "",
    ]
    if report["failures"]:
        lines.extend(["## Failures", ""])
        lines.extend(f"- {failure}" for failure in report["failures"])
        lines.append("")
    return "\n".join(lines)


def write_outputs(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "learned-ranking-eval.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (output_dir / "learned-ranking-eval.md").write_text(
        render_markdown(report),
        encoding="utf-8",
        newline="\n",
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare TravelMind rule and learned POI ranking."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args(list(argv) if argv is not None else None)

    report = evaluate_rankers(
        read_rows(args.dataset),
        PairwiseLinearRanker.load(args.model),
    )
    write_outputs(report, args.output_dir)
    print(
        f"learned_ranking_eval={report['status']} "
        f"ndcg={report['metrics']['rule_ndcg_at_5']}->"
        f"{report['metrics']['learned_ndcg_at_5']} "
        f"top3={report['metrics']['rule_preference_top3_rate']}->"
        f"{report['metrics']['learned_preference_top3_rate']}"
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
