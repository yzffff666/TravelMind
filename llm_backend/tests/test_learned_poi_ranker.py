import json
import os
from pathlib import Path

import numpy as np
import pytest

from app.services.learned_poi_ranker import (
    FEATURE_NAMES,
    ModelArtifactError,
    PairwiseLinearRanker,
    _mean_ndcg,
    load_runtime_ranker,
)
from scripts.build_learned_ranking_dataset import build_dataset, load_catalog


def _split_rows() -> tuple[list[dict], list[dict], list[dict]]:
    rows, _manifest = build_dataset(load_catalog())
    return (
        [row for row in rows if row["split"] == "train"],
        [row for row in rows if row["split"] == "validation"],
        [row for row in rows if row["split"] == "test"],
    )


def test_pairwise_training_is_deterministic_and_prefers_relevant_candidate():
    train_rows, validation_rows, test_rows = _split_rows()

    first = PairwiseLinearRanker.fit(train_rows, validation_rows=validation_rows)
    second = PairwiseLinearRanker.fit(train_rows, validation_rows=validation_rows)

    assert np.allclose(first.weights, second.weights)
    culture = [
        row
        for row in test_rows
        if row["query_profile"] == "culture"
        and row["destination_id"] == "hobart"
    ]
    by_archetype = {row["candidate_archetype"]: row for row in culture}
    scores = {
        name: first.predict_row(row)
        for name, row in by_archetype.items()
    }
    assert scores["museum"] > scores["premium_landmark"]
    assert scores["heritage_district"] > scores["wrong_city_generic"]


def test_model_artifact_round_trip_preserves_predictions(tmp_path: Path):
    train_rows, validation_rows, test_rows = _split_rows()
    model = PairwiseLinearRanker.fit(train_rows, validation_rows=validation_rows)
    path = tmp_path / "ranker.json"

    model.save(path)
    loaded = PairwiseLinearRanker.load(path)

    expected = model.predict_scores(test_rows[:20])
    actual = loaded.predict_scores(test_rows[:20])
    assert np.allclose(expected, actual)
    assert loaded.feature_names == FEATURE_NAMES
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "poi_pairwise_linear_ranker_v1"
    assert payload["training"]["pair_count"] > 0


def test_model_loader_rejects_corrupt_and_incompatible_artifacts(tmp_path: Path):
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{", encoding="utf-8")
    with pytest.raises(ModelArtifactError, match="invalid JSON"):
        PairwiseLinearRanker.load(corrupt)

    wrong_shape = tmp_path / "wrong-shape.json"
    wrong_shape.write_text("[]", encoding="utf-8")
    with pytest.raises(ModelArtifactError, match="object"):
        PairwiseLinearRanker.load(wrong_shape)

    incompatible = tmp_path / "incompatible.json"
    incompatible.write_text(
        json.dumps(
            {
                "schema_version": "poi_pairwise_linear_ranker_v1",
                "feature_names": ["unexpected_feature"],
                "means": [0.0],
                "scales": [1.0],
                "weights": [1.0],
                "training": {},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ModelArtifactError, match="feature schema mismatch"):
        PairwiseLinearRanker.load(incompatible)

    invalid_training = tmp_path / "invalid-training.json"
    payload = {
        "schema_version": "poi_pairwise_linear_ranker_v1",
        "feature_names": list(FEATURE_NAMES),
        "means": [0.0] * len(FEATURE_NAMES),
        "scales": [1.0] * len(FEATURE_NAMES),
        "weights": [1.0] * len(FEATURE_NAMES),
        "training": [],
    }
    invalid_training.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ModelArtifactError, match="training metadata"):
        PairwiseLinearRanker.load(invalid_training)


def test_ndcg_ties_preserve_input_order_instead_of_using_hidden_labels():
    rows = [
        {
            "query_id": "q-1",
            "label": label,
            "hard_gate_passed": True,
        }
        for label in (0, 2, 1)
    ]

    score = _mean_ndcg(rows, np.zeros(3, dtype=np.float64), top_k=3)

    assert score < 1.0


def test_zero_variance_features_produce_finite_weights_and_predictions():
    rows = []
    for query_index in range(3):
        for label in (0, 1, 2):
            rows.append(
                {
                    "query_id": f"q-{query_index}",
                    "label": label,
                    "hard_gate_passed": True,
                    "features": {
                        name: (float(label) / 2 if name == "preference_match" else 0.5)
                        for name in FEATURE_NAMES
                    },
                }
            )

    model = PairwiseLinearRanker.fit(rows, epochs=100)
    predictions = model.predict_scores(rows)

    assert np.isfinite(model.weights).all()
    assert np.isfinite(predictions).all()


def test_runtime_model_cache_reloads_after_artifact_changes(tmp_path: Path):
    path = tmp_path / "ranker.json"
    first = PairwiseLinearRanker(
        means=np.zeros(len(FEATURE_NAMES)),
        scales=np.ones(len(FEATURE_NAMES)),
        weights=np.zeros(len(FEATURE_NAMES)),
        training={"version": 1},
    )
    second = PairwiseLinearRanker(
        means=np.zeros(len(FEATURE_NAMES)),
        scales=np.ones(len(FEATURE_NAMES)),
        weights=np.ones(len(FEATURE_NAMES)),
        training={"version": 2},
    )
    first.save(path)
    loaded_first = load_runtime_ranker(path)
    second.save(path)
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1))

    loaded_second = load_runtime_ranker(path)

    assert loaded_first.training["version"] == 1
    assert loaded_second.training["version"] == 2
