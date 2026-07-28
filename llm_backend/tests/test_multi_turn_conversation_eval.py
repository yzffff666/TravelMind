from __future__ import annotations

from collections import Counter

import pytest

from scripts.multi_turn_conversation_eval import (
    evaluate_cases,
    is_passing,
    load_cases,
    render_markdown,
    validate_case_contract,
)


EXPECTED_CATEGORIES = {
    "destination_switch": 6,
    "destination_mention_readonly": 6,
    "qa_readonly": 6,
    "flexible_clarification": 6,
    "chat_goal_retention": 6,
    "consecutive_local_edit": 6,
    "reset_recovery": 6,
    "malformed_ambiguous": 6,
}


def test_v2_contract_rejects_fixture_provided_qp():
    cases = [
        {
            "case_id": "leaky",
            "category": "qa_readonly",
            "initial_state": {
                "active_destination": "澳门",
                "current_revision_id": "rev-1",
                "has_itinerary": True,
            },
            "turns": [
                {
                    "query": "第三天下午去哪里？",
                    "qp": {"intent": "qa"},
                    "expected": {"intent": "qa"},
                }
            ],
        }
    ]

    assert "must not provide qp" in " ".join(validate_case_contract(cases))


def test_normal_turn_runs_real_qp_and_records_decision_trace():
    report = evaluate_cases(
        [
            {
                "case_id": "natural-qa",
                "category": "qa_readonly",
                "initial_state": {
                    "active_destination": "澳门",
                    "current_revision_id": "rev-1",
                    "has_itinerary": True,
                },
                "turns": [
                    {
                        "query": "第三天下午去哪里？",
                        "expected": {
                            "intent": "qa",
                            "mutation_scope": "none",
                            "target_day": 3,
                            "target_slot": "下午",
                            "revision_after": "rev-1",
                        },
                    }
                ],
            }
        ]
    )

    turn = report["cases"][0]["turns"][0]
    assert turn["qp_output"]["intent"] == "qa"
    assert turn["decision"]["mutation_scope"] == "none"
    assert turn["state_before"]["current_revision_id"] == "rev-1"
    assert turn["state_after"]["current_revision_id"] == "rev-1"


def test_default_multi_turn_fixture_contains_48_natural_language_cases():
    cases = load_cases()

    assert len(cases) == 48
    assert Counter(case["category"] for case in cases) == EXPECTED_CATEGORIES
    assert all(3 <= len(case["turns"]) <= 6 for case in cases)
    assert sum(len(case["turns"]) for case in cases) >= 144
    assert validate_case_contract(cases) == []


def test_default_multi_turn_fixture_passes_v2_safety_gate():
    report = evaluate_cases(load_cases())

    assert report["schema_version"] == "multi_turn_conversation_eval_v2"
    assert report["status"] == "passed"
    assert report["case_count"] == 48
    assert report["passed_cases"] == 48
    assert report["failed_cases"] == 0
    assert report["turn_count"] >= 144
    assert report["failed_turns"] == 0
    assert report["metrics"] == {
        "overall_case_pass_rate": 1.0,
        "critical_case_pass_rate": 1.0,
        "qa_chat_unintended_mutations": 0,
        "false_destination_switches": 0,
        "explicit_destination_switch_failures": 0,
        "stale_itinerary_after_switch": 0,
        "consecutive_edit_target_failures": 0,
        "repeated_clarification_loops": 0,
    }
    assert is_passing(report) is True


def test_evaluator_reports_exact_failed_turn_and_category():
    cases = [
        {
            "case_id": "bad-readonly",
            "category": "qa_readonly",
            "initial_state": {
                "active_destination": "澳门",
                "current_revision_id": "rev-1",
                "has_itinerary": True,
            },
            "turns": [
                {
                    "query": "第三天下午去哪里",
                    "expected": {
                        "intent": "edit",
                        "mutation_scope": "single_slot",
                    },
                }
            ],
        }
    ]

    report = evaluate_cases(cases)

    assert report["status"] == "failed"
    assert report["failed_cases"] == 1
    assert report["failed_turns"] == 1
    failure = report["failures"][0]
    assert failure["case_id"] == "bad-readonly"
    assert failure["category"] == "qa_readonly"
    assert failure["turn_index"] == 1
    assert "intent" in failure["errors"][0]
    assert is_passing(report) is False


@pytest.mark.parametrize(
    ("metric", "value"),
    [
        ("qa_chat_unintended_mutations", 1),
        ("false_destination_switches", 1),
        ("explicit_destination_switch_failures", 1),
        ("stale_itinerary_after_switch", 1),
        ("consecutive_edit_target_failures", 1),
        ("repeated_clarification_loops", 1),
    ],
)
def test_v2_safety_metric_regression_fails_gate(metric, value):
    report = evaluate_cases(load_cases())
    report["metrics"][metric] = value

    assert is_passing(report) is False


def test_markdown_report_contains_category_summary_and_failures():
    report = evaluate_cases(load_cases())
    markdown = render_markdown(report)

    assert "# TravelMind Multi-Turn Conversation Eval" in markdown
    assert "48/48" in markdown
    assert "destination_switch" in markdown
    assert "consecutive_local_edit" in markdown
