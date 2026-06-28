from scripts.milestone_runner import build_status, render_summary, run_qp_eval_gate, write_artifacts


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
