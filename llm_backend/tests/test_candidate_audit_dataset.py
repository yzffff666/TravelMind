import json

from scripts.candidate_audit_dataset import (
    PENDING,
    REVIEWED,
    build_audit_queue,
    labeled_rows,
    main,
    summarize_audit_queue,
)


def _sample(**overrides):
    sample = {
        "decision": "rejected",
        "label": "rejected",
        "label_source": "rule",
        "destination": "普吉岛",
        "place": "大佛",
        "candidate_title": "Big Buddha Phuket",
        "candidate_provider": "geoapify",
        "candidate_lat": 7.827,
        "candidate_lng": 98.312,
        "fallback_reason": "score_rejected",
        "risk_flags": ["score_rejected", "low_confidence"],
        "match_score": 0.61,
        "quality_breakdown": {
            "has_candidate_geo": True,
            "bbox_valid": True,
            "address_contains_destination": True,
        },
    }
    sample.update(overrides)
    return sample


def test_build_audit_queue_prioritizes_deduplicates_and_keeps_review_template():
    queue = build_audit_queue(
        [
            _sample(),
            _sample(risk_flags=["score_rejected", "bbox_rejected"]),
            _sample(
                decision="accepted",
                label="accepted",
                place="芭东海滩",
                candidate_title="Patong Beach",
                fallback_reason=None,
                risk_flags=["bbox_rejected"],
            ),
            _sample(
                decision="accepted",
                label="accepted",
                place="普吉老镇",
                candidate_title="Old Phuket Town",
                fallback_reason=None,
                risk_flags=[],
            ),
        ]
    )

    assert len(queue) == 2
    assert queue[0]["source_count"] == 2
    assert queue[0]["action_type"] == "alias_or_match_tuning"
    assert queue[0]["audit"]["status"] == PENDING
    assert queue[0]["audit"]["human_label"] is None
    assert queue[1]["place"] == "芭东海滩"


def test_summarize_audit_queue_validates_review_and_exports_binary_labels():
    queue = build_audit_queue([_sample()])
    row = queue[0]
    row["audit"] = {
        "status": REVIEWED,
        "human_label": "accepted",
        "reviewer": "zifeng",
        "rationale": "候选地点和普吉大佛指向同一景点，bbox 和地址均正确。",
        "reviewed_at": "2026-07-17T10:00:00+08:00",
    }

    summary = summarize_audit_queue([row])
    labels = labeled_rows([row])

    assert summary["status"] == "passed"
    assert summary["reviewed_rows"] == 1
    assert summary["human_label_counts"] == {"accepted": 1}
    assert summary["weak_label_agreement"] == {
        "comparable_rows": 1,
        "matching_rows": 0,
        "agreement_rate": 0.0,
    }
    assert summary["model_ready"]["binary_labeled_rows"] == 1
    assert labels[0]["label"] == "accepted"
    assert labels[0]["weak_label"] == "rejected"


def test_summarize_marks_incomplete_review_invalid():
    row = build_audit_queue([_sample()])[0]
    row["audit"] = {"status": REVIEWED, "human_label": "accepted", "reviewer": "", "rationale": "", "reviewed_at": None}

    summary = summarize_audit_queue([row])

    assert summary["status"] == "failed"
    assert summary["invalid_rows"][0]["audit_id"] == row["audit_id"]
    assert "reviewed audit requires reviewer" in summary["invalid_rows"][0]["errors"]


def test_cli_queue_then_summarize(tmp_path):
    source = tmp_path / "candidate-decisions.jsonl"
    source.write_text(json.dumps(_sample(), ensure_ascii=False) + "\n", encoding="utf-8")
    queue_path = tmp_path / "candidate-audit-queue.jsonl"
    summary_path = tmp_path / "candidate-audit-summary.json"
    labels_path = tmp_path / "candidate-audit-labeled.jsonl"

    assert main(["queue", "--input", str(source), "--output", str(queue_path)]) == 0
    assert main([
        "summarize",
        "--input",
        str(queue_path),
        "--output",
        str(summary_path),
        "--labeled-output",
        str(labels_path),
    ]) == 0
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["pending_rows"] == 1
    assert labels_path.read_text(encoding="utf-8") == ""
