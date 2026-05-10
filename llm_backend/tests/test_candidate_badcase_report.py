import json

from scripts.candidate_badcase_report import (
    build_badcase_report,
    read_jsonl,
    render_markdown,
    write_json,
    write_markdown,
)


def test_build_badcase_report_prioritizes_actionable_rejections():
    samples = [
        {
            "decision": "accepted",
            "place": "Old Phuket Town",
            "risk_flags": [],
        },
        {
            "decision": "skipped",
            "place": "relaxed indoor activity",
            "fallback_reason": "generic_activity",
            "risk_flags": ["generic_activity", "low_confidence"],
            "quality_breakdown": {"has_candidate_geo": False},
        },
        {
            "decision": "rejected",
            "destination": "Phuket",
            "place": "Big Buddha Phuket",
            "candidate_title": "Big Buddha Temple",
            "candidate_provider": "serp_map",
            "fallback_reason": "score_rejected",
            "risk_flags": ["score_rejected", "low_confidence"],
            "match_score": 0.61,
            "candidate_lat": 7.827,
            "candidate_lng": 98.312,
            "elapsed_ms": 80,
            "quality_breakdown": {
                "title_similarity": 0.58,
                "has_candidate_geo": True,
                "bbox_valid": True,
                "address_contains_destination": True,
            },
        },
    ]

    report = build_badcase_report(samples, limit=10)

    assert report["schema_version"] == "candidate_badcase_report_v1"
    assert report["total_input_samples"] == 3
    assert report["total_badcases"] == 2
    assert report["top_fallback_reasons"] == {"score_rejected": 1, "generic_activity": 1}
    assert report["top_risk_flags"] == {
        "low_confidence": 2,
        "score_rejected": 1,
        "generic_activity": 1,
    }
    assert report["badcases"][0]["place"] == "Big Buddha Phuket"
    assert report["badcases"][0]["candidate_geo"] == "7.827,98.312"


def test_render_markdown_escapes_table_cells_and_includes_guidance():
    report = build_badcase_report(
        [
            {
                "decision": "rejected",
                "destination": "Phuket",
                "place": "A | B",
                "candidate_title": "Candidate | Name",
                "fallback_reason": "bbox_rejected",
                "risk_flags": ["bbox_rejected"],
                "quality_breakdown": {"bbox_valid": False, "has_candidate_geo": True},
            }
        ]
    )

    markdown = render_markdown(report)

    assert "# Candidate Badcase Report" in markdown
    assert "A \\| B" in markdown
    assert "Candidate \\| Name" in markdown
    assert "`bbox_rejected`: 1" in markdown
    assert "bbox_rejected, bbox_rejected" not in markdown
    assert "How To Use" in markdown


def test_read_jsonl_and_writers_roundtrip(tmp_path):
    input_path = tmp_path / "candidate-decisions.jsonl"
    input_path.write_text(
        json.dumps({"decision": "rejected", "risk_flags": ["score_rejected"]}) + "\n",
        encoding="utf-8",
    )

    samples = read_jsonl([input_path])
    report = build_badcase_report(samples)
    json_path = tmp_path / "candidate-badcase-report.json"
    markdown_path = tmp_path / "candidate-badcase-report.md"

    write_json(json_path, report)
    write_markdown(markdown_path, report)

    assert samples[0]["_source_path"] == str(input_path)
    assert json.loads(json_path.read_text(encoding="utf-8"))["total_badcases"] == 1
    assert "Candidate Badcase Report" in markdown_path.read_text(encoding="utf-8")
