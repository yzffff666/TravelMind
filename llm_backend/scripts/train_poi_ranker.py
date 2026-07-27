"""Train TravelMind's deterministic pairwise POI ranker."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

from app.services.learned_poi_ranker import PairwiseLinearRanker
from scripts.build_learned_ranking_dataset import DEFAULT_DATASET_PATH


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_PATH = BACKEND_ROOT / "models/poi_pairwise_ranker_v1.json"


def read_rows(path: Path = DEFAULT_DATASET_PATH) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def train_from_rows(rows: list[dict[str, Any]]) -> PairwiseLinearRanker:
    train_rows = [row for row in rows if row.get("split") == "train"]
    validation_rows = [row for row in rows if row.get("split") == "validation"]
    if not train_rows or not validation_rows:
        raise ValueError("training requires non-empty train and validation splits")
    train_destinations = {
        str(row["destination_id"]) for row in train_rows
    }
    validation_destinations = {
        str(row["destination_id"]) for row in validation_rows
    }
    overlap = sorted(train_destinations & validation_destinations)
    if overlap:
        raise ValueError(
            "train/validation destination overlap: " + ", ".join(overlap)
        )
    model = PairwiseLinearRanker.fit(
        train_rows,
        validation_rows=validation_rows,
    )
    model.training.update(
        {
            "validation_row_count": len(validation_rows),
            "test_row_count": 0,
            "train_destinations": sorted(train_destinations),
            "validation_destinations": sorted(validation_destinations),
            "label_source": "curated_rubric_v1",
        }
    )
    return model


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Train the TravelMind pairwise linear POI ranker."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL_PATH)
    args = parser.parse_args(list(argv) if argv is not None else None)

    model = train_from_rows(read_rows(args.dataset))
    model.save(args.model)
    print(
        "poi_pairwise_ranker=trained "
        f"rows={model.training['row_count']} "
        f"pairs={model.training['pair_count']} "
        f"validation_ndcg_at_5={model.training['best_validation_ndcg_at_5']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
