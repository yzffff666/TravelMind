from scripts.live_destination_grounding_probe import apply_targeted_criteria


def test_targeted_probe_uses_selected_case_expectations_instead_of_global_thresholds():
    report = {
        "status": "failed",
        "criteria": {"min_resolved_profiles": 6, "min_ready_destinations": 4},
        "results": [
            {"case_id": "unseen_dunhuang", "status": "ready"},
            {"case_id": "unseen_kashgar_insufficient", "status": "insufficient_candidates"},
        ],
    }
    cases = [
        {"case_id": "unseen_dunhuang", "expected_outcome": "ready"},
        {"case_id": "unseen_kashgar_insufficient", "expected_outcome": "insufficient_candidates"},
    ]

    result = apply_targeted_criteria(report, cases)

    assert result["status"] == "passed"
    assert result["criteria"]["mode"] == "targeted"
    assert result["mismatches"] == []


def test_targeted_probe_reports_outcome_mismatch():
    report = {
        "status": "passed",
        "results": [{"case_id": "unseen_dunhuang", "status": "insufficient_candidates"}],
    }
    result = apply_targeted_criteria(
        report,
        [{"case_id": "unseen_dunhuang", "expected_outcome": "ready"}],
    )

    assert result["status"] == "failed"
    assert result["mismatches"] == [
        {"case_id": "unseen_dunhuang", "expected": "ready", "actual": "insufficient_candidates"}
    ]
