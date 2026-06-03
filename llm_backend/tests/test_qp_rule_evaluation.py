import json

from scripts.evaluate_qp_rules import DEFAULT_CASES_PATH, evaluate_cases, render_markdown


def _load_cases(path=DEFAULT_CASES_PATH):
    cases = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                cases.append(json.loads(line))
    return cases


def test_default_qp_rule_eval_strict_gate_passes():
    summary = evaluate_cases(_load_cases())

    assert summary["total_cases"] >= 40
    assert summary["strict_cases"] >= 35
    assert summary["strict_failed"] == 0
    assert summary["strict_accuracy"] == 1.0
    assert summary["tracked_cases"] > 0


def test_qp_rule_eval_tracks_known_gaps_without_blocking_gate():
    summary = evaluate_cases(
        [
            {
                "id": "known_gap_en_edit",
                "category": "known_gap",
                "strict": False,
                "query": "Change day 2 afternoon to an indoor activity",
                "expected": {"intent": "edit", "intent_detail": "edit_day"},
            }
        ]
    )

    assert summary["strict_cases"] == 0
    assert summary["strict_failed"] == 0
    assert summary["tracked_cases"] == 1
    assert summary["tracked_mismatched"] == 1


def test_qp_rule_eval_markdown_includes_known_gap_section():
    summary = evaluate_cases(
        [
            {
                "id": "known_gap_chat_question",
                "category": "known_gap",
                "strict": False,
                "query": "今天天气怎么样？",
                "expected": {"intent": "chat", "intent_detail": "general_chat"},
                "note": "Generic question should not be itinerary QA.",
            }
        ]
    )

    markdown = render_markdown(summary)

    assert "# QP Rule Evaluation" in markdown
    assert "Tracked Known Gaps" in markdown
    assert "known_gap_chat_question" in markdown
