import json

from scripts.export_candidate_decisions import (
    export_candidate_decisions,
    summarize_candidate_decisions,
    write_json,
    write_jsonl,
)
from scripts.observability_summary import parse_log_line


def _line(message: str, extra: dict):
    return json.dumps(
        {
            "text": "",
            "record": {
                "message": message,
                "extra": extra,
            },
        }
    )


def test_exports_accepted_provider_backfill_sample():
    event = parse_log_line(
        _line(
            "location_backfill",
            {
                "event_type": "location_backfill",
                "itinerary_id": "it-1",
                "revision_id": "rev-1",
                "source": "provider",
                "destination": "Phuket",
                "day_index": 1,
                "slot_label": "morning",
                "activity": "Visit Old Phuket Town",
                "place": "Old Phuket Town",
                "candidate_title": "Old Phuket Town",
                "provider": "serp_map",
                "lat": 7.884,
                "lng": 98.389,
                "address": "Phuket",
                "bbox_valid": True,
                "confidence": "high",
                "match_score": 0.92,
                "elapsed_ms": 120,
            },
        ),
        source="logs/structured.log",
    )

    samples = export_candidate_decisions([event])

    assert len(samples) == 1
    sample = samples[0]
    assert sample["schema_version"] == "candidate_decision_v1"
    assert sample["decision"] == "accepted"
    assert sample["label"] == "accepted"
    assert sample["label_source"] == "rule"
    assert sample["risk_flags"] == []
    assert sample["candidate_title"] == "Old Phuket Town"
    assert sample["candidate_provider"] == "serp_map"
    assert sample["bbox_valid"] is True
    assert sample["match_score"] == 0.92
    assert sample["quality_breakdown"] == {
        "decision": "accepted",
        "match_score": 0.92,
        "title_similarity": 1.0,
        "english_token_overlap": 1.0,
        "title_contains_place": True,
        "place_contains_title": True,
        "address_contains_destination": True,
        "has_candidate_geo": True,
        "bbox_valid": True,
        "confidence": "high",
        "is_low_confidence": False,
        "fallback_reason": None,
        "candidate_provider": "serp_map",
    }
    assert sample["source_log"] == "logs/structured.log"


def test_exports_rejected_unresolved_sample_with_risk_flags():
    event = parse_log_line(
        _line(
            "location_backfill",
            {
                "event_type": "location_backfill",
                "source": "unresolved",
                "destination": "Phuket",
                "place": "Big Buddha Phuket",
                "fallback_reason": "score_rejected",
                "provider_status_counts": {"success": 1},
                "candidate_count": 3,
                "best_candidate_title": "Big Buddha Temple",
                "best_candidate_provider": "serp_map",
                "best_candidate_lat": 7.827,
                "best_candidate_lng": 98.312,
                "best_candidate_address": "Phuket",
                "best_match_score": 0.61,
                "rejected_score_count": 2,
                "cache_negative_hit_count": 1,
                "variant_limit_reached": True,
                "confidence": "low",
            },
        )
    )

    sample = export_candidate_decisions([event])[0]

    assert sample["decision"] == "rejected"
    assert sample["label"] == "rejected"
    assert sample["candidate_title"] == "Big Buddha Temple"
    assert sample["candidate_provider"] == "serp_map"
    assert sample["match_score"] == 0.61
    assert sample["provider_status_counts"] == {"success": 1}
    assert sample["risk_flags"] == [
        "score_rejected",
        "low_confidence",
        "cache_negative_hit",
        "variant_limit_reached",
    ]
    assert sample["quality_breakdown"]["address_contains_destination"] is True
    assert sample["quality_breakdown"]["has_candidate_geo"] is True
    assert sample["quality_breakdown"]["is_low_confidence"] is True


def test_exports_skipped_generic_activity_sample():
    event = parse_log_line(
        _line(
            "location_backfill",
            {
                "event_type": "location_backfill",
                "source": "skipped",
                "destination": "Chengdu",
                "activity": "更轻松的室内活动",
                "fallback_reason": "generic_activity",
                "confidence": "low",
                "elapsed_ms": 1,
            },
        )
    )

    sample = export_candidate_decisions([event])[0]

    assert sample["decision"] == "skipped"
    assert sample["label"] == "rejected"
    assert sample["place"] == "更轻松的室内活动"
    assert sample["risk_flags"] == ["generic_activity", "low_confidence"]


def test_write_jsonl_creates_parent_and_writes_samples(tmp_path):
    output = tmp_path / "candidate-decisions" / "samples.jsonl"
    count = write_jsonl(output, [{"decision": "accepted"}, {"decision": "rejected"}])

    assert count == 2
    lines = output.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"decision": "accepted"}
    assert json.loads(lines[1]) == {"decision": "rejected"}


def test_summarize_candidate_decisions_counts_quality_dimensions():
    summary = summarize_candidate_decisions(
        [
            {
                "decision": "accepted",
                "label": "accepted",
                "destination": "Phuket",
                "candidate_provider": "serp_map",
                "risk_flags": [],
                "quality_breakdown": {
                    "title_similarity": 0.9,
                    "has_candidate_geo": True,
                    "bbox_valid": True,
                    "is_low_confidence": False,
                },
                "match_score": 0.92,
                "elapsed_ms": 120,
            },
            {
                "decision": "rejected",
                "label": "rejected",
                "destination": "Phuket",
                "candidate_provider": "serp_map",
                "fallback_reason": "score_rejected",
                "risk_flags": ["score_rejected", "low_confidence"],
                "quality_breakdown": {
                    "title_similarity": 0.4,
                    "has_candidate_geo": True,
                    "bbox_valid": False,
                    "is_low_confidence": True,
                },
                "match_score": 0.61,
                "elapsed_ms": 80,
            },
            {
                "decision": "skipped",
                "label": "rejected",
                "destination": "Chengdu",
                "candidate_provider": "skipped",
                "fallback_reason": "generic_activity",
                "risk_flags": ["generic_activity", "low_confidence"],
                "quality_breakdown": {
                    "has_candidate_geo": False,
                    "is_low_confidence": True,
                },
            },
        ]
    )

    assert summary["total_samples"] == 3
    assert summary["decision_counts"] == {"accepted": 1, "rejected": 1, "skipped": 1}
    assert summary["decision_rates"] == {"accepted": 0.3333, "rejected": 0.3333, "skipped": 0.3333}
    assert summary["label_counts"] == {"rejected": 2, "accepted": 1}
    assert summary["label_rates"] == {"rejected": 0.6667, "accepted": 0.3333}
    assert summary["risk_flag_counts"] == {
        "low_confidence": 2,
        "score_rejected": 1,
        "generic_activity": 1,
    }
    assert summary["risk_flag_rates"] == {
        "low_confidence": 0.6667,
        "score_rejected": 0.3333,
        "generic_activity": 0.3333,
    }
    assert summary["destination_counts"] == {"Phuket": 2, "Chengdu": 1}
    assert summary["fallback_reason_counts"] == {"score_rejected": 1, "generic_activity": 1}
    assert summary["fallback_reason_rates"] == {"score_rejected": 0.3333, "generic_activity": 0.3333}
    assert summary["match_score_avg"] == 0.765
    assert summary["match_score_avg_by_decision"] == {"accepted": 0.92, "rejected": 0.61}
    assert summary["elapsed_ms_avg"] == 100.0
    assert summary["elapsed_ms_avg_by_decision"] == {"accepted": 120.0, "rejected": 80.0}
    assert summary["quality_breakdown_avg"] == {
        "title_similarity": 0.65,
        "has_candidate_geo": 0.6667,
        "bbox_valid": 0.5,
        "is_low_confidence": 0.6667,
    }


def test_write_json_creates_parent_and_writes_payload(tmp_path):
    output = tmp_path / "candidate-decisions" / "summary.json"
    write_json(output, {"total_samples": 2})

    assert json.loads(output.read_text(encoding="utf-8")) == {"total_samples": 2}
