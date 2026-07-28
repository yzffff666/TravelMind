from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.demo_journey_eval import (
    _empty_metrics,
    _record_publication_safety,
    evaluate_cases,
    is_passing,
    load_cases,
    render_markdown,
    validate_case_contract,
)


EXPECTED_CATEGORIES = {
    "domestic_long_tail",
    "overseas_unseen",
    "destination_switch_edits",
    "insufficient_candidates",
}


def _run(report: dict, case_id: str, repetition: int = 1) -> dict:
    return next(
        item
        for item in report["runs"]
        if item["case_id"] == case_id and item["repetition"] == repetition
    )


def test_default_fixture_contract():
    cases = load_cases()

    assert len(cases) == 4
    assert {case["category"] for case in cases} == EXPECTED_CATEGORIES
    assert validate_case_contract(cases) == []


def test_ready_journeys_compose_production_layers():
    report = evaluate_cases(load_cases(), repetitions=1)
    domestic = _run(report, "domestic_long_tail_jingdezhen")
    overseas = _run(report, "overseas_unseen_tromso")

    assert domestic["status"] == "passed"
    assert overseas["status"] == "passed"
    assert domestic["metrics"]["qa_revision_mutations"] == 0
    assert domestic["metrics"]["wrong_edit_targets"] == 0
    assert overseas["metrics"]["cross_city_published"] == 0
    assert overseas["metrics"]["mock_published"] == 0
    assert overseas["coverage"]["evidence"] == 1.0
    assert overseas["coverage"]["image"] == 1.0


def test_switch_and_degradation_are_safe():
    report = evaluate_cases(load_cases(), repetitions=1)
    switch = _run(report, "destination_switch_shenzhen_hongkong")
    degrade = _run(report, "insufficient_candidates_oaxaca")

    assert switch["status"] == "passed"
    assert switch["metrics"]["revision_lineage_failures"] == 0
    assert switch["metrics"]["stale_destination_candidates"] == 0
    assert switch["metrics"]["non_target_mutations"] == 0
    assert degrade["status"] == "passed"
    assert degrade["metrics"]["unsafe_final_itinerary_on_degrade"] == 0
    assert degrade["terminal_event"] in {"quality_warning", "final_text"}
    assert degrade["final_revision_id"] is None


def test_two_repetition_acceptance_gate_passes_8_of_8():
    report = evaluate_cases(load_cases(), repetitions=2)

    assert report["schema_version"] == "demo_journey_eval_v1"
    assert report["scenario_count"] == 4
    assert report["repetitions"] == 2
    assert report["journey_runs"] == 8
    assert report["passed_journey_runs"] == 8
    assert report["failed_journey_runs"] == 0
    assert report["turn_count"] >= 24
    assert all(value == 0 for value in report["safety_metrics"].values())
    assert is_passing(report) is True


def test_fixture_contract_rejects_mock_candidate_labeled_as_local():
    cases = deepcopy(load_cases())
    cases[0]["candidates"][0]["source"] = "mock"

    errors = validate_case_contract(cases)

    assert any("local candidate source must not be mock" in error for error in errors)


def test_publication_safety_is_recorded_for_each_emitted_itinerary():
    metrics = _empty_metrics()
    itinerary = {
        "days": [
            {
                "slots": [
                    {"candidate_role": "cross_city", "candidate_source": "serpapi"},
                    {"candidate_role": "local", "candidate_source": "mock"},
                ]
            }
        ]
    }

    _record_publication_safety(itinerary, metrics)

    assert metrics["cross_city_published"] == 1
    assert metrics["mock_published"] == 1


def test_edit_replan_failure_is_not_mislabeled_as_wrong_target():
    cases = deepcopy(load_cases())
    overseas = next(
        case for case in cases if case["case_id"] == "overseas_unseen_tromso"
    )
    overseas["edit_candidates"] = []

    report = evaluate_cases(cases, repetitions=1)
    run = _run(report, "overseas_unseen_tromso")

    assert run["status"] == "failed"
    assert run["metrics"]["wrong_edit_targets"] == 0
    assert any(error.startswith("edit_replan_failed:") for error in run["errors"])


@pytest.mark.parametrize(
    "metric",
    [
        "qa_revision_mutations",
        "wrong_edit_targets",
        "non_target_mutations",
        "stale_destination_candidates",
        "cross_city_published",
        "mock_published",
        "unsafe_final_itinerary_on_degrade",
        "missing_terminal_events",
        "revision_lineage_failures",
    ],
)
def test_any_safety_regression_fails_gate(metric):
    report = evaluate_cases(load_cases(), repetitions=2)
    report["safety_metrics"][metric] = 1

    assert is_passing(report) is False


def test_markdown_report_contains_scenario_and_safety_summary():
    markdown = render_markdown(evaluate_cases(load_cases(), repetitions=2))

    assert "8/8" in markdown
    assert "domestic_long_tail_jingdezhen" in markdown
    assert "insufficient_candidates_oaxaca" in markdown
    assert "revision_lineage_failures" in markdown
