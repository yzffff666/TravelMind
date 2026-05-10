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
            "decision": "accepted",
            "destination": "Phuket",
            "place": "Kata Viewpoint",
            "candidate_title": "Kata Beach Viewpoint",
            "risk_flags": ["bbox_rejected", "score_rejected"],
            "match_score": 0.92,
            "quality_breakdown": {"has_candidate_geo": True, "bbox_valid": True},
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
            "provider_status_counts": {"success": 1},
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
    assert report["total_input_samples"] == 4
    assert report["total_badcases"] == 2
    assert report["total_watchlist"] == 1
    assert report["action_type_counts"] == {
        "alias_or_match_tuning": 1,
        "generic_or_low_value_slot": 1,
    }
    assert report["top_fallback_reasons"] == {"score_rejected": 1, "generic_activity": 1}
    assert report["top_risk_flags"] == {
        "low_confidence": 2,
        "score_rejected": 1,
        "generic_activity": 1,
    }
    assert report["watchlist_risk_flags"] == {"bbox_rejected": 1, "score_rejected": 1}
    assert report["watchlist_action_type_counts"] == {"bbox_policy_review": 1}
    assert report["badcases"][0]["place"] == "Big Buddha Phuket"
    assert report["badcases"][0]["candidate_geo"] == "7.827,98.312"
    assert report["badcases"][0]["action_type"] == "alias_or_match_tuning"
    assert report["watchlist"][0]["place"] == "Kata Viewpoint"


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
    assert "Action Types" in markdown
    assert "bbox_policy_review" in markdown
    assert "bbox_rejected, bbox_rejected" not in markdown
    assert "Accepted Watchlist" in markdown
    assert "not direct failures" in markdown
    assert "How To Use" in markdown


def test_render_markdown_separates_accepted_watchlist_from_badcases():
    report = build_badcase_report(
        [
            {
                "decision": "accepted",
                "place": "Phi Phi Islands",
                "candidate_title": "Phi Phi Island Tour",
                "risk_flags": ["bbox_rejected"],
                "quality_breakdown": {"has_candidate_geo": True, "bbox_valid": True},
            },
            {
                "decision": "rejected",
                "place": "Patong Beach",
                "fallback_reason": "score_rejected",
                "risk_flags": ["score_rejected"],
            },
        ]
    )

    markdown = render_markdown(report)
    badcase_section = markdown.split("## Accepted Watchlist", 1)[0]
    watchlist_section = markdown.split("## Accepted Watchlist", 1)[1]

    assert "Patong Beach" in badcase_section
    assert "Phi Phi Islands" not in badcase_section
    assert "Phi Phi Islands" in watchlist_section


def test_build_badcase_report_classifies_provider_and_budget_actions():
    report = build_badcase_report(
        [
            {
                "decision": "rejected",
                "place": "Patong Beach",
                "candidate_title": None,
                "fallback_reason": "score_rejected",
                "risk_flags": ["score_rejected", "low_confidence"],
                "provider_status_counts": {"empty": 2, "timeout": 1},
                "quality_breakdown": {"has_candidate_geo": False},
            },
            {
                "decision": "rejected",
                "place": "Bangla Road",
                "fallback_reason": "total_budget_exhausted",
                "risk_flags": ["total_budget_exhausted", "low_confidence"],
                "provider_status_counts": {"success": 1},
                "quality_breakdown": {"has_candidate_geo": False},
            },
        ]
    )

    assert [item["action_type"] for item in report["badcases"]] == [
        "provider_recall_or_timeout",
        "budget_exhaustion",
    ]
    assert report["action_type_counts"] == {
        "provider_recall_or_timeout": 1,
        "budget_exhaustion": 1,
    }


def test_build_badcase_report_prefers_score_rejected_alias_action_over_bbox_hint():
    report = build_badcase_report(
        [
            {
                "decision": "rejected",
                "place": "Thalang Road",
                "candidate_title": "Thanon Talang",
                "fallback_reason": "score_rejected",
                "risk_flags": ["score_rejected", "low_confidence"],
                "quality_breakdown": {
                    "has_candidate_geo": True,
                    "bbox_valid": False,
                    "title_similarity": 0.6087,
                },
            }
        ]
    )

    assert report["badcases"][0]["action_type"] == "alias_or_match_tuning"
    assert report["action_type_counts"] == {"alias_or_match_tuning": 1}


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
