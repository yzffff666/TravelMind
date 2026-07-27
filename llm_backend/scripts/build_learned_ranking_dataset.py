"""Build TravelMind's deterministic model-ready POI ranking dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from app.services.learned_poi_ranker import FEATURE_NAMES

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG_PATH = BACKEND_ROOT / "evaluation/learned_ranking_catalog_v1.json"
DEFAULT_DATASET_PATH = BACKEND_ROOT / "evaluation/learned_ranking_dataset_v1.jsonl"
DEFAULT_MANIFEST_PATH = (
    BACKEND_ROOT / "evaluation/learned_ranking_dataset_manifest_v1.json"
)
RULE_WEIGHTS = {
    "preference_match": 0.20,
    "evidence_score": 0.20,
    "provider_confidence": 0.15,
    "resolvable_score": 0.25,
    "distance_feasibility": 0.10,
    "budget_match": 0.10,
    "alias_hit": 0.05,
    "rating_score": 0.0,
    "review_count_score": 0.0,
}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def load_catalog(path: Path = DEFAULT_CATALOG_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "learned_ranking_catalog_v1":
        raise ValueError("unsupported learned ranking catalog schema")
    return payload


def _feature_values(
    archetype: dict[str, Any],
    *,
    profile_id: str,
    quality_offset: float,
) -> dict[str, float]:
    values = {
        name: float((archetype.get("features") or {}).get(name) or 0.0)
        for name in FEATURE_NAMES
    }
    values["preference_match"] = float(
        (archetype.get("preference_match") or {}).get(profile_id) or 0.0
    )
    for name in (
        "evidence_score",
        "provider_confidence",
        "resolvable_score",
        "rating_score",
        "review_count_score",
    ):
        values[name] = _clamp01(values[name] + quality_offset)
    return {name: round(_clamp01(values[name]), 4) for name in FEATURE_NAMES}


def _rule_score(features: dict[str, float], *, hard_gate_passed: bool) -> float:
    score = sum(RULE_WEIGHTS[name] * features[name] for name in FEATURE_NAMES)
    if not hard_gate_passed:
        score *= 0.25
    return round(_clamp01(score), 6)


def _dataset_bytes(rows: Iterable[dict[str, Any]]) -> bytes:
    content = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
        for row in rows
    )
    return content.encode("utf-8")


def build_dataset(catalog: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    label_source = str(catalog.get("label_source") or "curated_rubric_v1")
    destinations = list(catalog.get("destinations") or [])
    profiles = list(catalog.get("query_profiles") or [])
    archetypes = list(catalog.get("candidate_archetypes") or [])

    for destination in destinations:
        destination_id = str(destination["id"])
        destination_name = str(destination["name"])
        split = str(destination["split"])
        quality_offset = float(destination.get("quality_offset") or 0.0)
        for profile in profiles:
            profile_id = str(profile["id"])
            query_id = f"{split}-{destination_id}-{profile_id}"
            for archetype in archetypes:
                archetype_id = str(archetype["id"])
                hard_gate_passed = bool(archetype.get("hard_gate_passed", True))
                features = _feature_values(
                    archetype,
                    profile_id=profile_id,
                    quality_offset=quality_offset,
                )
                rows.append(
                    {
                        "schema_version": "learned_ranking_sample_v1",
                        "query_id": query_id,
                        "destination_id": destination_id,
                        "destination": destination_name,
                        "split": split,
                        "query_profile": profile_id,
                        "preferences": list(profile.get("preferences") or []),
                        "candidate_id": f"{destination_id}-{archetype_id}",
                        "candidate_title": str(archetype["title"]).format(
                            destination=destination_name
                        ),
                        "candidate_archetype": archetype_id,
                        "label": int((archetype.get("relevance") or {})[profile_id]),
                        "label_source": label_source,
                        "hard_gate_passed": hard_gate_passed,
                        "features": features,
                        "rule_score": _rule_score(
                            features,
                            hard_gate_passed=hard_gate_passed,
                        ),
                    }
                )

    rows.sort(
        key=lambda row: (
            row["split"],
            row["destination_id"],
            row["query_profile"],
            row["candidate_id"],
        )
    )
    split_rows = Counter(str(row["split"]) for row in rows)
    split_destinations: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        split_destinations[str(row["split"])].add(str(row["destination_id"]))
    dataset_sha256 = hashlib.sha256(_dataset_bytes(rows)).hexdigest()
    manifest = {
        "schema_version": "learned_ranking_dataset_manifest_v1",
        "dataset_schema_version": "learned_ranking_sample_v1",
        "catalog_schema_version": catalog.get("schema_version"),
        "label_source": label_source,
        "row_count": len(rows),
        "query_count": len({row["query_id"] for row in rows}),
        "destination_count": len({row["destination_id"] for row in rows}),
        "feature_names": list(FEATURE_NAMES),
        "label_counts": dict(sorted(Counter(row["label"] for row in rows).items())),
        "split_row_counts": {
            split: split_rows.get(split, 0)
            for split in ("train", "validation", "test")
        },
        "split_destination_counts": {
            split: len(split_destinations.get(split, set()))
            for split in ("train", "validation", "test")
        },
        "split_destinations": {
            split: sorted(split_destinations.get(split, set()))
            for split in ("train", "validation", "test")
        },
        "dataset_sha256": dataset_sha256,
    }
    return rows, manifest


def write_artifacts(
    rows: list[dict[str, Any]],
    manifest: dict[str, Any],
    *,
    dataset_path: Path = DEFAULT_DATASET_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
) -> None:
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_path.write_bytes(_dataset_bytes(rows))
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the deterministic TravelMind learned-ranking dataset."
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    args = parser.parse_args(list(argv) if argv is not None else None)

    rows, manifest = build_dataset(load_catalog(args.catalog))
    write_artifacts(
        rows,
        manifest,
        dataset_path=args.dataset,
        manifest_path=args.manifest,
    )
    print(
        "learned_ranking_dataset=passed "
        f"rows={manifest['row_count']} "
        f"queries={manifest['query_count']} "
        f"destinations={manifest['destination_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
