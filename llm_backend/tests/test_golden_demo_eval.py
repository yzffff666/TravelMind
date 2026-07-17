from pathlib import Path

from scripts.golden_demo_eval import evaluate_cases, load_cases, render_markdown, write_outputs


def test_default_golden_demo_cases_pass():
    report = evaluate_cases(load_cases())

    assert report["schema_version"] == "golden_demo_eval_v1"
    assert report["status"] == "passed"
    assert report["passed_cases"] == report["case_count"]
    assert report["by_type"]["qp"]["failed"] == 0
    assert report["by_type"]["patch"]["failed"] == 0
    assert report["by_type"]["bbox"]["failed"] == 0


def test_golden_demo_eval_catches_qa_edit_boundary():
    report = evaluate_cases(load_cases())
    qa_case = next(case for case in report["cases"] if case["case_id"] == "demo_qa_macau_day3_afternoon_readonly")
    patch_case = next(case for case in report["cases"] if case["case_id"] == "demo_patch_day3_afternoon_question_not_mutation")

    assert qa_case["actual"]["intent"] == "qa"
    assert qa_case["actual"]["missing_required"] == []
    assert patch_case["actual"]["has_mutation_intent"] is False
    assert patch_case["actual"]["ops"] == []


def test_golden_demo_eval_writes_artifacts(tmp_path: Path):
    report = evaluate_cases(load_cases())

    write_outputs(report, tmp_path)
    markdown = render_markdown(report)

    assert (tmp_path / "golden-demo-eval.json").exists()
    assert (tmp_path / "golden-demo-eval.md").exists()
    assert "TravelMind Golden Demo Eval" in markdown
    assert "Cases:" in markdown
