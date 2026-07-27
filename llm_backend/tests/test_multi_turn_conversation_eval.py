from __future__ import annotations

from collections import Counter

from scripts.multi_turn_conversation_eval import (
    evaluate_cases,
    is_passing,
    load_cases,
    render_markdown,
)


EXPECTED_CATEGORIES = {
    "destination_switch": 4,
    "destination_mention_readonly": 4,
    "qa_readonly": 4,
    "flexible_clarification": 4,
    "chat_goal_retention": 4,
    "edit_reset_recovery": 4,
}


def test_default_multi_turn_fixture_contains_24_balanced_cases():
    cases = load_cases()

    assert len(cases) == 24
    assert Counter(case["category"] for case in cases) == EXPECTED_CATEGORIES
    assert all(2 <= len(case["turns"]) <= 6 for case in cases)


def test_default_multi_turn_fixture_passes_every_turn():
    report = evaluate_cases(load_cases())

    assert report["schema_version"] == "multi_turn_conversation_eval_v1"
    assert report["status"] == "passed"
    assert report["case_count"] == 24
    assert report["passed_cases"] == 24
    assert report["failed_cases"] == 0
    assert report["turn_count"] >= 48
    assert report["failed_turns"] == 0
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
                    "qp": {
                        "intent": "qa",
                        "intent_detail": "qa_local",
                        "constraints": {},
                        "target_day": 3,
                        "target_slot": "下午",
                    },
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


def test_markdown_report_contains_category_summary_and_failures():
    report = evaluate_cases(load_cases())
    markdown = render_markdown(report)

    assert "# TravelMind Multi-Turn Conversation Eval" in markdown
    assert "24/24" in markdown
    assert "destination_switch" in markdown
    assert "edit_reset_recovery" in markdown
