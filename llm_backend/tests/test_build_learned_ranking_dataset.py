import json
from pathlib import Path

from scripts.build_learned_ranking_dataset import (
    build_dataset,
    load_catalog,
    write_artifacts,
)


def test_default_catalog_builds_model_ready_destination_isolated_dataset():
    rows, manifest = build_dataset(load_catalog())

    assert len(rows) == 576
    assert manifest["row_count"] == 576
    assert manifest["query_count"] == 48
    assert manifest["destination_count"] == 12
    assert manifest["split_row_counts"] == {
        "train": 384,
        "validation": 96,
        "test": 96,
    }
    assert manifest["split_destination_counts"] == {
        "train": 8,
        "validation": 2,
        "test": 2,
    }
    split_destinations = {
        split: set(destinations)
        for split, destinations in manifest["split_destinations"].items()
    }
    assert split_destinations["train"].isdisjoint(split_destinations["validation"])
    assert split_destinations["train"].isdisjoint(split_destinations["test"])
    assert split_destinations["validation"].isdisjoint(split_destinations["test"])


def test_every_query_has_twelve_candidates_and_graded_ranking_signal():
    rows, _manifest = build_dataset(load_catalog())
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["query_id"], []).append(row)

    assert len(grouped) == 48
    assert all(len(group) == 12 for group in grouped.values())
    assert all({0, 1, 2}.issuperset({row["label"] for row in group}) for group in grouped.values())
    assert all(any(row["label"] == 2 for row in group) for group in grouped.values())
    assert all(any(row["label"] == 0 for row in group) for group in grouped.values())
    assert all(row["label_source"] == "curated_rubric_v1" for row in rows)
    assert all(len(row["features"]) == 9 for row in rows)


def test_generated_artifacts_are_stable_and_self_describing(tmp_path: Path):
    rows, manifest = build_dataset(load_catalog())

    dataset_path = tmp_path / "dataset.jsonl"
    manifest_path = tmp_path / "manifest.json"
    write_artifacts(
        rows,
        manifest,
        dataset_path=dataset_path,
        manifest_path=manifest_path,
    )

    written_rows = [
        json.loads(line)
        for line in dataset_path.read_text(encoding="utf-8").splitlines()
    ]
    written_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert written_rows == rows
    assert written_manifest["dataset_sha256"] == manifest["dataset_sha256"]
    assert written_manifest["feature_names"] == [
        "preference_match",
        "evidence_score",
        "provider_confidence",
        "resolvable_score",
        "distance_feasibility",
        "budget_match",
        "alias_hit",
        "rating_score",
        "review_count_score",
    ]
