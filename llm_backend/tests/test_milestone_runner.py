import sys
import json

from scripts.milestone_runner import (
    DEFAULT_CONFIG,
    build_status,
    render_summary,
    run_command_gate,
    run_golden_demo_eval_gate,
    run_hybrid_qp_eval_gate,
    run_multi_turn_conversation_eval_gate,
    run_explicit_poi_edit_eval_gate,
    run_structured_edit_replan_eval_gate,
    run_qp_eval_gate,
    run_ranking_eval_gate,
    run_planner_eval_gate,
    run_destination_readiness_eval_gate,
    run_unseen_destination_eval_gate,
    write_artifacts,
)


def test_qp_eval_gate_passes_default_cases():
    result = run_qp_eval_gate({"type": "qp_eval", "name": "qp_eval"})

    assert result.status == "passed"
    assert result.summary["strict_failed"] == 0
    assert result.summary["strict_passed"] == result.summary["strict_cases"]
    assert result.failures == []


def test_hybrid_qp_eval_gate_passes_default_cases():
    result = run_hybrid_qp_eval_gate({"type": "hybrid_qp_eval", "name": "hybrid_qp_eval"})

    assert result.status == "passed"
    assert result.summary["case_count"] >= 30
    assert result.summary["failed_cases"] == 0
    assert result.summary["critical_safety_failed"] == 0
    assert result.failures == []


def test_structured_edit_replan_eval_gate_passes_default_cases():
    result = run_structured_edit_replan_eval_gate(
        {"type": "structured_edit_replan_eval", "name": "structured_edit_replan_eval"}
    )

    assert result.status == "passed"
    assert result.summary["case_count"] >= 15
    assert result.summary["failed_cases"] == 0
    assert result.summary["unsafe_revision_failures"] == 0
    assert result.failures == []


def test_explicit_poi_edit_eval_gate_passes_default_cases():
    result = run_explicit_poi_edit_eval_gate(
        {"type": "explicit_poi_edit_eval", "name": "explicit_poi_edit_eval"}
    )

    assert result.status == "passed"
    assert result.summary["case_count"] >= 16
    assert result.summary["explicit_cases"] >= 7
    assert result.summary["failed_cases"] == 0
    assert result.summary["unsafe_revision_failures"] == 0
    assert result.failures == []


def test_status_and_artifacts_are_compact(tmp_path):
    gate = run_qp_eval_gate({"type": "qp_eval", "name": "qp_eval"})
    status = build_status({"name": "test-milestone"}, [gate], run_id="run-1")

    write_artifacts(status, tmp_path)

    assert status["status"] == "passed"
    assert (tmp_path / "status.json").exists()
    assert (tmp_path / "failures.json").exists()
    assert (tmp_path / "summary.txt").read_text(encoding="utf-8").startswith("milestone=test-milestone")
    assert not (tmp_path / "milestone-report.md").exists()


def test_summary_includes_gate_status():
    gate = run_qp_eval_gate({"type": "qp_eval", "name": "qp_eval"})
    status = build_status({"name": "test-milestone"}, [gate], run_id="run-1")

    summary = render_summary(status)

    assert "status=passed" in summary
    assert "- qp_eval: passed" in summary


def test_ranking_eval_gate_passes_default_cases():
    result = run_ranking_eval_gate({"type": "ranking_eval", "name": "ranking_eval"})

    assert result.status == "passed"
    assert result.summary["case_count"] >= 20
    assert result.summary["destination_count"] >= 10
    assert result.summary["good_hit_rate"] == 1.0
    assert result.summary["policy_good_hit_rate"] >= result.summary["legacy_good_hit_rate"]
    assert result.summary["rejected_expected_rate"] == 1.0
    assert result.summary["unsafe_accepted_count"] == 0
    assert result.summary["ranking_latency_p95_ms"] < 50
    assert result.failures == []


def test_golden_demo_eval_gate_passes_default_cases():
    result = run_golden_demo_eval_gate({"type": "golden_demo_eval", "name": "golden_demo_eval"})

    assert result.status == "passed"
    assert result.summary["case_count"] >= 1
    assert result.summary["failed_cases"] == 0
    assert result.failures == []


def test_unseen_destination_eval_gate_passes_default_cases():
    result = run_unseen_destination_eval_gate(
        {"type": "unseen_destination_eval", "name": "unseen_destination_eval"}
    )

    assert result.status == "passed"
    assert result.summary["case_count"] == 10
    assert result.summary["ready_cases"] == 8
    assert result.summary["insufficient_candidate_cases"] == 2
    assert result.failures == []


def test_destination_readiness_eval_gate_passes_mixed_city_matrix():
    result = run_destination_readiness_eval_gate(
        {"type": "destination_readiness_eval", "name": "destination_readiness_eval"}
    )

    assert result.status == "passed"
    assert result.summary["case_count"] == 12
    assert result.summary["ready_cases"] == 10
    assert result.summary["safe_degradation_cases"] == 2
    assert result.summary["static_cases"] == 6
    assert result.summary["dynamic_cases"] == 6
    assert result.failures == []


def test_planner_eval_gate_passes_default_cases():
    result = run_planner_eval_gate({"type": "planner_eval", "name": "planner_eval"})

    assert result.status == "passed"
    assert result.summary["case_count"] == 12
    assert result.summary["planner_p95_ms"] < 200
    assert result.failures == []


def test_multi_turn_conversation_eval_gate_passes_24_transcripts():
    result = run_multi_turn_conversation_eval_gate(
        {
            "type": "multi_turn_conversation_eval",
            "name": "multi_turn_conversation_eval",
        }
    )

    assert result.status == "passed"
    assert result.summary["case_count"] == 24
    assert result.summary["passed_cases"] == 24
    assert result.summary["failed_turns"] == 0
    assert result.failures == []


def test_multi_turn_conversation_eval_gate_fails_on_turn_regression(tmp_path):
    from scripts.multi_turn_conversation_eval import load_cases

    cases = load_cases()
    cases[0]["turns"][0]["expected"]["intent"] = "edit"
    cases_path = tmp_path / "multi-turn-regression.json"
    cases_path.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")

    result = run_multi_turn_conversation_eval_gate(
        {
            "type": "multi_turn_conversation_eval",
            "name": "multi_turn_conversation_eval",
            "cases": str(cases_path),
        }
    )

    assert result.status == "failed"
    assert result.summary["failed_cases"] == 1
    assert result.summary["failed_turns"] == 1
    assert result.failures[0]["case_id"] == cases[0]["case_id"]


def test_default_config_covers_core_integration_gates():
    gate_names = {gate["name"] for gate in DEFAULT_CONFIG["gates"]}

    assert DEFAULT_CONFIG["name"] == "travelmind-core-integration-gate"
    assert {
        "qp_eval",
        "hybrid_qp_eval",
        "structured_edit_replan_eval",
        "explicit_poi_edit_eval",
        "golden_demo_eval",
        "ranking_eval",
        "planner_eval",
        "unseen_destination_eval",
        "destination_readiness_eval",
        "multi_turn_conversation_eval",
        "backend_core_integration_tests",
        "frontend_chat_component_tests",
        "frontend_type_check",
        "frontend_production_build",
    }.issubset(gate_names)

    backend_gate = next(gate for gate in DEFAULT_CONFIG["gates"] if gate["name"] == "backend_core_integration_tests")
    assert "tests/test_golden_demo_eval.py" in backend_gate["targets"]
    assert "tests/test_hybrid_qp_eval.py" in backend_gate["targets"]
    assert "tests/test_structured_edit_replan_eval.py" in backend_gate["targets"]
    assert "tests/test_explicit_poi_edit_eval.py" in backend_gate["targets"]
    assert "tests/test_structured_qp_shadow_eval.py" in backend_gate["targets"]
    assert "tests/test_ranking_eval_report.py" in backend_gate["targets"]
    assert "tests/test_destination_grounding.py" in backend_gate["targets"]
    assert "tests/test_destination_grounding_graph.py" in backend_gate["targets"]
    assert "tests/test_itinerary_planner.py" in backend_gate["targets"]
    assert "tests/test_planner_eval.py" in backend_gate["targets"]
    assert "tests/test_unseen_destination_eval.py" in backend_gate["targets"]
    assert "tests/test_destination_readiness_eval.py" in backend_gate["targets"]
    assert "tests/test_geo_bounds.py" in backend_gate["targets"]
    assert "tests/test_patch_engine.py" in backend_gate["targets"]
    assert "tests/test_day_replan_service.py" in backend_gate["targets"]
    assert "tests/test_travel_m2_012_013.py" in backend_gate["targets"]
    assert "tests/test_observability_summary.py" in backend_gate["targets"]
    assert "tests/test_conversation_runtime.py" in backend_gate["targets"]
    assert "tests/test_conversation_runtime_integration.py" in backend_gate["targets"]
    assert "tests/test_multi_turn_conversation_eval.py" in backend_gate["targets"]


def test_command_gate_passes_and_captures_output():
    result = run_command_gate(
        {
            "type": "command",
            "name": "command_smoke",
            "cmd": [sys.executable, "-c", "print('command gate ok')"],
        }
    )

    assert result.status == "passed"
    assert result.summary["returncode"] == 0
    assert "command gate ok" in result.summary["output_tail"]
    assert result.failures == []


def test_command_gate_reports_failure_output():
    result = run_command_gate(
        {
            "type": "command",
            "name": "command_failure",
            "cmd": [sys.executable, "-c", "import sys; print('bad gate'); sys.exit(3)"],
        }
    )

    assert result.status == "failed"
    assert result.summary["returncode"] == 3
    assert result.failures[0]["returncode"] == 3
    assert "bad gate" in result.failures[0]["output_tail"]
