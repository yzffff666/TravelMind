from scripts.hybrid_qp_eval import DEFAULT_CASES_PATH, _load_jsonl, evaluate_cases, is_passing


def test_hybrid_qp_holdout_gate_passes_and_covers_safety_cases():
    summary = evaluate_cases(_load_jsonl(DEFAULT_CASES_PATH))

    assert summary["case_count"] >= 30
    assert summary["failed_cases"] == 0
    assert summary["critical_safety_cases"] >= 10
    assert summary["critical_safety_failed"] == 0
    assert summary["routing_p95_ms"] < summary["routing_p95_target_ms"]
    assert is_passing(summary) is True
