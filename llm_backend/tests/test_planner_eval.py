from scripts.planner_eval import build_report, default_cases, render_markdown, write_outputs


def test_default_planner_eval_covers_twelve_decision_cases(tmp_path):
    report = build_report()

    assert len(default_cases()) == 12
    assert report["status"] == "passed"
    assert report["passed_cases"] == 12
    assert report["planner_p95_ms"] < 200

    write_outputs(report, tmp_path)
    assert (tmp_path / "planner-eval.json").exists()
    assert "12/12 passed" in render_markdown(report)
