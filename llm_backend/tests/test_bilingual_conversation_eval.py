from __future__ import annotations

from copy import deepcopy

from scripts.bilingual_conversation_eval import (
    evaluate_cases,
    is_passing,
    load_cases,
    validate_case_contract,
)


def test_checked_in_bilingual_cases_pass_hard_gate():
    cases = load_cases()
    report = evaluate_cases(cases)

    assert report["summary"]["case_count"] == 20
    assert report["summary"]["language_case_counts"] == {
        "en": 10,
        "zh-CN": 10,
    }
    assert report["metrics"] == {
        "language_drift": 0,
        "wrong_language_final_responses": 0,
        "state_persistence_failures": 0,
        "missing_language_metadata": 0,
    }
    assert is_passing(report)


def test_contract_rejects_an_unbalanced_or_too_small_corpus():
    cases = load_cases()[:5]

    errors = validate_case_contract(cases)

    assert any("expected 20" in error for error in errors)
    assert any("10 Chinese and 10 English" in error for error in errors)


def test_hard_gate_rejects_any_language_drift():
    report = evaluate_cases(load_cases())
    broken = deepcopy(report)
    broken["metrics"]["language_drift"] = 1

    assert not is_passing(broken)
