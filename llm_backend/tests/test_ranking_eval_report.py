from pathlib import Path

from scripts.ranking_eval_report import (
    build_report,
    load_cases,
    render_markdown,
    write_outputs,
)


def test_default_ranking_eval_cases_pass():
    report = build_report(load_cases())

    assert report["schema_version"] == "ranking_eval_report_v1"
    assert report["status"] == "passed"
    assert report["passed_cases"] == report["case_count"]
    assert report["case_count"] >= 20
    assert report["destination_count"] >= 10
    assert report["summary"]["good_hit_rate"] == 1.0
    assert report["summary"]["policy_good_hit_rate"] >= report["summary"]["legacy_good_hit_rate"]
    assert report["summary"]["rejected_expected_rate"] == 1.0
    assert report["summary"]["unsafe_accepted_count"] == 0
    assert report["summary"]["policy_evidence_coverage"] >= 0.8
    assert report["summary"]["ranking_latency_p95_ms"] < 50
    assert report["summary"]["reject_reason_counts"]["bbox_invalid"] >= 1
    assert report["summary"]["reject_reason_counts"]["generic_activity"] >= 1


def test_policy_ranking_improves_badcase_top_order():
    report = build_report(load_cases())
    phuket = next(case for case in report["cases"] if case["case_id"] == "phuket_bbox_and_alias_quality")

    assert "kata_beach_duplicate" in phuket["legacy_top_ids"]
    assert phuket["policy_top_ids"][:2] == ["kata_beach", "old_phuket_town"]
    assert "eiffel_tower" in phuket["policy_rejected_ids"]
    assert "kata_beach_duplicate" in phuket["policy_rejected_ids"]


def test_markdown_and_artifacts_are_written(tmp_path: Path):
    report = build_report(load_cases())

    write_outputs(report, tmp_path)
    markdown = render_markdown(report)

    assert (tmp_path / "ranking-eval-report.json").exists()
    assert (tmp_path / "ranking-eval-report.md").exists()
    assert "TravelMind Ranking Eval Report" in markdown
    assert "phuket_bbox_and_alias_quality" in markdown
