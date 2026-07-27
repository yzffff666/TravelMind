import json
from pathlib import Path

import pytest

from app.services.learned_poi_ranker import PairwiseLinearRanker
from scripts.build_learned_ranking_dataset import build_dataset, load_catalog
from scripts.learned_ranking_eval import (
    evaluate_rankers,
    render_markdown,
    write_outputs,
)
from scripts.train_poi_ranker import train_from_rows


def _trained() -> tuple[list[dict], PairwiseLinearRanker]:
    rows, _manifest = build_dataset(load_catalog())
    model = train_from_rows(rows)
    return rows, model


def test_learned_ranker_beats_rule_baseline_on_destination_holdout():
    rows, model = _trained()

    report = evaluate_rankers(rows, model)

    assert report["schema_version"] == "learned_ranking_eval_v1"
    assert report["status"] == "passed"
    assert report["dataset"]["row_count"] == 576
    assert report["dataset"]["query_count"] == 48
    assert report["dataset"]["destination_count"] == 12
    assert report["dataset"]["train_test_destination_overlap"] == []
    assert report["metrics"]["learned_ndcg_at_5"] >= report["metrics"]["rule_ndcg_at_5"]
    assert (
        report["metrics"]["learned_preference_top3_rate"]
        >= report["metrics"]["rule_preference_top3_rate"] + 0.05
    )
    assert report["metrics"]["unsafe_accepted_count"] == 0
    assert report["metrics"]["hard_gate_rejected_count"] == 8
    assert report["metrics"]["model_scored_unsafe_count"] == 0
    assert all(
        "wrong_city_generic" not in candidate_id
        for case in report["cases"]
        for candidate_id in case["learned_top3"]
    )
    assert report["metrics"]["inference_p95_ms"] < 100


def test_training_uses_no_test_rows_and_produces_auditable_metadata():
    rows, model = _trained()

    assert model.training["row_count"] == 384
    assert model.training["validation_row_count"] == 96
    assert model.training["test_row_count"] == 0
    assert model.training["train_destinations"] == [
        "bangkok",
        "berlin",
        "chengdu",
        "lisbon",
        "qingdao",
        "shenzhen",
        "tokyo",
        "xian",
    ]
    assert model.training["validation_destinations"] == ["kashgar", "valletta"]


def test_training_rejects_destination_overlap_between_train_and_validation():
    rows, _manifest = build_dataset(load_catalog())
    train_row = next(row for row in rows if row["split"] == "train")
    validation_row = {
        **train_row,
        "query_id": "validation-overlap",
        "split": "validation",
    }

    with pytest.raises(ValueError, match="destination overlap"):
        train_from_rows([train_row, validation_row])


def test_eval_rejects_model_trained_from_a_different_training_dataset():
    rows, model = _trained()
    changed_rows = [dict(row) for row in rows]
    training_index = next(
        index for index, row in enumerate(changed_rows) if row["split"] == "train"
    )
    changed_rows[training_index] = {
        **changed_rows[training_index],
        "label": (int(changed_rows[training_index]["label"]) + 1) % 3,
    }

    report = evaluate_rankers(changed_rows, model)

    assert report["status"] == "failed"
    assert "model/dataset training fingerprint mismatch" in report["failures"]


def test_eval_rejects_incomplete_or_overlapping_split_contracts():
    rows, model = _trained()
    incomplete = rows[:-1]
    report = evaluate_rankers(incomplete, model)
    assert report["status"] == "failed"
    assert "dataset contract mismatch" in report["failures"]

    overlap = [dict(row) for row in rows]
    test_index = next(
        index for index, row in enumerate(overlap) if row["split"] == "test"
    )
    overlap[test_index] = {
        **overlap[test_index],
        "destination_id": "shenzhen",
    }
    report = evaluate_rankers(overlap, model)
    assert report["status"] == "failed"
    assert "split destination overlap" in report["failures"]


def test_eval_report_artifacts_are_written(tmp_path: Path):
    rows, model = _trained()
    report = evaluate_rankers(rows, model)

    write_outputs(report, tmp_path)
    markdown = render_markdown(report)

    payload = json.loads(
        (tmp_path / "learned-ranking-eval.json").read_text(encoding="utf-8")
    )
    assert payload["status"] == "passed"
    assert (tmp_path / "learned-ranking-eval.md").exists()
    assert "Hybrid Learned Ranking Eval" in markdown
