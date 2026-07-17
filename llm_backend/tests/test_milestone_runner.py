import sys

from scripts.milestone_runner import (
    DEFAULT_CONFIG,
    build_status,
    render_summary,
    run_command_gate,
    run_golden_demo_eval_gate,
    run_qp_eval_gate,
    run_ranking_eval_gate,
    write_artifacts,
)


def test_qp_eval_gate_passes_default_cases():
    result = run_qp_eval_gate({"type": "qp_eval", "name": "qp_eval"})

    assert result.status == "passed"
    assert result.summary["strict_failed"] == 0
    assert result.summary["strict_passed"] == result.summary["strict_cases"]
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
    assert result.summary["case_count"] >= 1
    assert result.summary["good_hit_rate"] == 1.0
    assert result.summary["rejected_expected_rate"] == 1.0
    assert result.failures == []


def test_golden_demo_eval_gate_passes_default_cases():
    result = run_golden_demo_eval_gate({"type": "golden_demo_eval", "name": "golden_demo_eval"})

    assert result.status == "passed"
    assert result.summary["case_count"] >= 1
    assert result.summary["failed_cases"] == 0
    assert result.failures == []


def test_default_config_covers_core_integration_gates():
    gate_names = {gate["name"] for gate in DEFAULT_CONFIG["gates"]}

    assert DEFAULT_CONFIG["name"] == "travelmind-core-integration-gate"
    assert {
        "qp_eval",
        "golden_demo_eval",
        "ranking_eval",
        "backend_core_integration_tests",
        "frontend_chat_component_tests",
        "frontend_type_check",
        "frontend_production_build",
    }.issubset(gate_names)

    backend_gate = next(gate for gate in DEFAULT_CONFIG["gates"] if gate["name"] == "backend_core_integration_tests")
    assert "tests/test_golden_demo_eval.py" in backend_gate["targets"]
    assert "tests/test_ranking_eval_report.py" in backend_gate["targets"]
    assert "tests/test_geo_bounds.py" in backend_gate["targets"]
    assert "tests/test_patch_engine.py" in backend_gate["targets"]
    assert "tests/test_day_replan_service.py" in backend_gate["targets"]
    assert "tests/test_travel_m2_012_013.py" in backend_gate["targets"]


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
