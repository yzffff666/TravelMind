"""Small reproducible pairwise ranker for accepted TravelMind POI candidates."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import numpy as np


MODEL_SCHEMA_VERSION = "poi_pairwise_linear_ranker_v1"
FEATURE_NAMES = (
    "preference_match",
    "evidence_score",
    "provider_confidence",
    "resolvable_score",
    "distance_feasibility",
    "budget_match",
    "alias_hit",
    "rating_score",
    "review_count_score",
)


class ModelArtifactError(ValueError):
    """Raised when a learned-ranking model cannot be used safely."""


def runtime_feature_values(feature: Any) -> dict[str, float]:
    """Convert a CandidateFeature-like object into the model feature contract."""
    candidate = feature.candidate
    rating = candidate.extra.get("rating")
    review_count = candidate.extra.get("reviews_count") or candidate.extra.get(
        "review_count"
    )
    try:
        rating_score = max(0.0, min(1.0, float(rating) / 5.0))
    except (TypeError, ValueError):
        rating_score = 0.0
    try:
        review_number = max(0.0, float(review_count))
        review_count_score = min(1.0, math.log1p(review_number) / math.log1p(100000))
    except (TypeError, ValueError):
        review_count_score = 0.0
    return {
        "preference_match": float(feature.preference_match),
        "evidence_score": float(feature.evidence_score),
        "provider_confidence": float(feature.provider_confidence),
        "resolvable_score": float(feature.resolvable_score),
        "distance_feasibility": float(feature.distance_feasibility),
        "budget_match": float(feature.budget_match),
        "alias_hit": 1.0 if feature.alias_hit else 0.0,
        "rating_score": rating_score,
        "review_count_score": review_count_score,
    }


def _row_vector(row: dict[str, Any]) -> np.ndarray:
    features = row.get("features")
    if not isinstance(features, dict):
        raise ValueError("ranking row features must be an object")
    try:
        vector = np.asarray(
            [float(features[name]) for name in FEATURE_NAMES],
            dtype=np.float64,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("ranking row has an invalid feature vector") from exc
    if not np.isfinite(vector).all():
        raise ValueError("ranking row features must be finite")
    return vector


def dataset_fingerprint(rows: Iterable[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(
            json.dumps(
                row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def _dcg(labels: list[int], *, top_k: int = 5) -> float:
    return sum(
        (2**label - 1) / np.log2(index + 2)
        for index, label in enumerate(labels[:top_k])
    )


def _mean_ndcg(rows: list[dict[str, Any]], scores: np.ndarray, *, top_k: int = 5) -> float:
    grouped: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for row, score in zip(rows, scores, strict=True):
        if not bool(row.get("hard_gate_passed", True)):
            continue
        grouped[str(row["query_id"])].append((float(score), int(row["label"])))
    values: list[float] = []
    for items in grouped.values():
        ranked = [
            label
            for _score, label in sorted(
                items,
                key=lambda item: item[0],
                reverse=True,
            )
        ]
        ideal = sorted(ranked, reverse=True)
        denominator = _dcg(ideal, top_k=top_k)
        values.append(_dcg(ranked, top_k=top_k) / denominator if denominator else 1.0)
    return float(sum(values) / len(values)) if values else 0.0


def _pair_differences(rows: list[dict[str, Any]], matrix: np.ndarray) -> np.ndarray:
    grouped_indices: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        if bool(row.get("hard_gate_passed", True)):
            grouped_indices[str(row["query_id"])].append(index)

    differences: list[np.ndarray] = []
    for indices in grouped_indices.values():
        for left_position, left_index in enumerate(indices):
            left_label = int(rows[left_index]["label"])
            for right_index in indices[left_position + 1 :]:
                right_label = int(rows[right_index]["label"])
                if left_label == right_label:
                    continue
                if left_label > right_label:
                    differences.append(matrix[left_index] - matrix[right_index])
                else:
                    differences.append(matrix[right_index] - matrix[left_index])
    if not differences:
        raise ValueError("pairwise training requires at least one graded pair")
    return np.vstack(differences)


@dataclass(slots=True)
class PairwiseLinearRanker:
    means: np.ndarray
    scales: np.ndarray
    weights: np.ndarray
    training: dict[str, Any] = field(default_factory=dict)
    feature_names: tuple[str, ...] = FEATURE_NAMES

    @classmethod
    def fit(
        cls,
        rows: list[dict[str, Any]],
        *,
        validation_rows: list[dict[str, Any]] | None = None,
        learning_rate: float = 0.08,
        epochs: int = 500,
        l2: float = 0.01,
    ) -> "PairwiseLinearRanker":
        if not rows:
            raise ValueError("pairwise training rows cannot be empty")
        matrix = np.vstack([_row_vector(row) for row in rows])
        accepted_indices = [
            index
            for index, row in enumerate(rows)
            if bool(row.get("hard_gate_passed", True))
        ]
        if not accepted_indices:
            raise ValueError("pairwise training requires hard-gate-passing rows")
        accepted_matrix = matrix[accepted_indices]
        means = accepted_matrix.mean(axis=0)
        scales = accepted_matrix.std(axis=0)
        scales = np.where(scales < 1e-8, 1.0, scales)
        normalized = (matrix - means) / scales
        differences = _pair_differences(rows, normalized)

        weights = np.zeros(len(FEATURE_NAMES), dtype=np.float64)
        best_weights = weights.copy()
        best_validation_ndcg = -1.0
        validation_rows = list(validation_rows or [])
        validation_matrix = (
            np.vstack([_row_vector(row) for row in validation_rows])
            if validation_rows
            else np.empty((0, len(FEATURE_NAMES)), dtype=np.float64)
        )

        for _epoch in range(max(1, int(epochs))):
            margins = np.clip(differences @ weights, -50.0, 50.0)
            error = 1.0 / (1.0 + np.exp(margins))
            gradient = -(differences.T @ error) / len(differences) + 2 * l2 * weights
            weights -= learning_rate * gradient

            if validation_rows:
                validation_scores = (
                    (validation_matrix - means) / scales
                ) @ weights
                validation_ndcg = _mean_ndcg(
                    validation_rows,
                    validation_scores,
                    top_k=5,
                )
                if validation_ndcg > best_validation_ndcg + 1e-12:
                    best_validation_ndcg = validation_ndcg
                    best_weights = weights.copy()
            else:
                best_weights = weights.copy()

        training = {
            "algorithm": "full_batch_pairwise_logistic",
            "dataset_sha256": dataset_fingerprint(rows),
            "row_count": len(rows),
            "accepted_row_count": len(accepted_indices),
            "pair_count": len(differences),
            "epochs": max(1, int(epochs)),
            "learning_rate": float(learning_rate),
            "l2": float(l2),
            "best_validation_ndcg_at_5": (
                round(best_validation_ndcg, 8)
                if validation_rows
                else None
            ),
        }
        return cls(
            means=means,
            scales=scales,
            weights=best_weights,
            training=training,
        )

    def predict_row(self, row: dict[str, Any]) -> float:
        return float(self.predict_scores([row])[0])

    def predict_scores(self, rows: list[dict[str, Any]]) -> np.ndarray:
        if not rows:
            return np.asarray([], dtype=np.float64)
        matrix = np.vstack([_row_vector(row) for row in rows])
        margins = np.clip(((matrix - self.means) / self.scales) @ self.weights, -50.0, 50.0)
        return 1.0 / (1.0 + np.exp(-margins))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": MODEL_SCHEMA_VERSION,
            "feature_names": list(self.feature_names),
            "means": self.means.tolist(),
            "scales": self.scales.tolist(),
            "weights": self.weights.tolist(),
            "training": dict(self.training),
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
            newline="\n",
        )

    @classmethod
    def load(cls, path: Path) -> "PairwiseLinearRanker":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ModelArtifactError(f"invalid JSON model artifact: {path}") from exc
        except OSError as exc:
            raise ModelArtifactError(f"model artifact is unavailable: {path}") from exc
        if not isinstance(payload, dict):
            raise ModelArtifactError("model artifact must be a JSON object")
        if payload.get("schema_version") != MODEL_SCHEMA_VERSION:
            raise ModelArtifactError("model schema version mismatch")
        if tuple(payload.get("feature_names") or []) != FEATURE_NAMES:
            raise ModelArtifactError("feature schema mismatch")
        training = payload.get("training")
        if not isinstance(training, dict):
            raise ModelArtifactError("invalid model training metadata")
        try:
            means = np.asarray(payload["means"], dtype=np.float64)
            scales = np.asarray(payload["scales"], dtype=np.float64)
            weights = np.asarray(payload["weights"], dtype=np.float64)
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelArtifactError("invalid model vectors") from exc
        expected_shape = (len(FEATURE_NAMES),)
        if (
            means.shape != expected_shape
            or scales.shape != expected_shape
            or weights.shape != expected_shape
            or not np.isfinite(means).all()
            or not np.isfinite(scales).all()
            or not np.isfinite(weights).all()
            or np.any(scales <= 0)
        ):
            raise ModelArtifactError("invalid model vector shape or values")
        return cls(
            means=means,
            scales=scales,
            weights=weights,
            training=dict(training),
        )


@lru_cache(maxsize=8)
def _load_cached(path_text: str, modified_ns: int) -> PairwiseLinearRanker:
    del modified_ns
    return PairwiseLinearRanker.load(Path(path_text))


def load_runtime_ranker(path: Path) -> PairwiseLinearRanker:
    try:
        modified_ns = path.stat().st_mtime_ns
    except OSError as exc:
        raise ModelArtifactError(f"model artifact is unavailable: {path}") from exc
    return _load_cached(str(path.resolve()), modified_ns)
