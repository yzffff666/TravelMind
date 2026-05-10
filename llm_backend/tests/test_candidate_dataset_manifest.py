import json

from scripts.candidate_dataset_manifest import collect_manifest, render_markdown, run_entry_from_summary


def _write_summary(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")


def test_run_entry_from_summary_flattens_core_quality_fields(tmp_path):
    summary_path = tmp_path / "observability-bilingual" / "20260509-211839" / "candidate-decisions-summary.json"
    _write_summary(
        summary_path,
        {
            "total_samples": 13,
            "decision_rates": {"accepted": 0.53846, "rejected": 0.46154},
            "match_score_avg": 0.6918,
            "match_score_avg_by_decision": {"accepted": 0.9529, "rejected": 0.3873},
            "elapsed_ms_avg": 7775.891,
            "quality_breakdown_avg": {
                "bbox_valid": 0.53846,
                "has_candidate_geo": 0.84615,
                "is_low_confidence": 0.53846,
            },
            "risk_flag_counts": {"score_rejected": 11, "low_confidence": 7, "bbox_rejected": 5},
            "fallback_reason_counts": {"bbox_rejected": 3, "score_rejected": 2},
            "run_metadata": {
                "run_id": "20260509-211839",
                "generated_at": "2026-05-10T00:00:00+00:00",
                "case_set": "bilingual",
                "case_count": 4,
            },
        },
    )

    entry = run_entry_from_summary(summary_path, root=tmp_path)

    assert entry["run_id"] == "20260509-211839"
    assert entry["case_set"] == "bilingual"
    assert entry["case_count"] == 4
    assert entry["total_samples"] == 13
    assert entry["accepted_rate"] == 0.5385
    assert entry["rejected_rate"] == 0.4615
    assert entry["elapsed_ms_avg"] == 7775.89
    assert entry["top_risk_flags"] == {
        "score_rejected": 11,
        "low_confidence": 7,
        "bbox_rejected": 5,
    }


def test_collect_manifest_indexes_multiple_runs(tmp_path):
    _write_summary(
        tmp_path / "run-a" / "candidate-decisions-summary.json",
        {
            "total_samples": 2,
            "decision_rates": {"accepted": 0.5, "rejected": 0.5},
            "run_metadata": {"run_id": "run-a", "case_set": "mini"},
        },
    )
    _write_summary(
        tmp_path / "nested" / "run-b" / "candidate-decisions-summary.json",
        {
            "total_samples": 3,
            "decision_rates": {"accepted": 1.0},
            "run_metadata": {"run_id": "run-b", "case_set": "bilingual"},
        },
    )

    manifest = collect_manifest(tmp_path)

    assert manifest["schema_version"] == "candidate_dataset_manifest_v1"
    assert manifest["total_runs"] == 2
    assert manifest["total_samples"] == 5
    assert [run["run_id"] for run in manifest["runs"]] == ["run-a", "run-b"]


def test_render_markdown_includes_run_rows():
    markdown = render_markdown(
        {
            "total_runs": 1,
            "total_samples": 13,
            "runs": [
                {
                    "run_id": "20260509-211839",
                    "case_set": "bilingual",
                    "total_samples": 13,
                    "accepted_rate": 0.5385,
                    "rejected_rate": 0.4615,
                    "is_low_confidence_avg": 0.5385,
                    "bbox_valid_avg": 0.5385,
                    "top_risk_flags": {"score_rejected": 11},
                }
            ],
        }
    )

    assert "# Candidate Decision Dataset Manifest" in markdown
    assert "| `20260509-211839`" not in markdown
    assert "20260509-211839" in markdown
    assert "score_rejected:11" in markdown
