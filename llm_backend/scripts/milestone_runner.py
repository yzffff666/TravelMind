"""Run lightweight milestone gates and emit compact machine-readable status.

This runner is intentionally small and conservative:
- no live Provider/API calls by default;
- no long Markdown report by default;
- JSON/status artifacts are enough for tight iterate-test-fix loops.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from scripts.evaluate_qp_rules import DEFAULT_CASES_PATH, _load_jsonl, evaluate_cases


DEFAULT_OUTPUT_ROOT = Path("reports/milestone-runs")
DEFAULT_PYTEST_TARGETS = (
    "tests/test_qp_rule_evaluation.py",
    "tests/test_hybrid_qp_eval.py",
    "tests/test_structured_edit_replan_eval.py",
    "tests/test_explicit_poi_edit_eval.py",
    "tests/test_structured_qp_shadow_eval.py",
    "tests/test_travel_m2_011.py",
    "tests/test_golden_demo_eval.py",
    "tests/test_ranking_eval_report.py",
    "tests/test_candidate_audit_dataset.py",
    "tests/test_destination_grounding.py",
    "tests/test_destination_grounding_graph.py",
    "tests/test_itinerary_planner.py",
    "tests/test_planner_eval.py",
    "tests/test_unseen_destination_eval.py",
    "tests/test_destination_readiness_eval.py",
    "tests/test_geo_bounds.py",
    "tests/test_patch_engine.py",
    "tests/test_day_replan_service.py",
    "tests/test_travel_m2_012_013.py",
    "tests/test_travel_sse_envelope.py",
    "tests/test_observability_summary.py",
    "tests/test_milestone_runner.py",
)
DEFAULT_CONFIG: dict[str, Any] = {
    "name": "travelmind-core-integration-gate",
    "gates": [
        {"type": "qp_eval", "name": "qp_eval", "cases": str(DEFAULT_CASES_PATH)},
        {
            "type": "hybrid_qp_eval",
            "name": "hybrid_qp_eval",
            "cases": "evaluation/hybrid_qp_holdout_cases.jsonl",
        },
        {
            "type": "structured_edit_replan_eval",
            "name": "structured_edit_replan_eval",
            "cases": "evaluation/structured_edit_replan_cases.json",
        },
        {
            "type": "explicit_poi_edit_eval",
            "name": "explicit_poi_edit_eval",
            "cases": "evaluation/explicit_poi_edit_cases.json",
        },
        {"type": "golden_demo_eval", "name": "golden_demo_eval", "cases": "evaluation/golden_demo_cases.json"},
        {"type": "ranking_eval", "name": "ranking_eval", "cases": "evaluation/ranking_eval_cases.json"},
        {"type": "planner_eval", "name": "planner_eval"},
        {
            "type": "unseen_destination_eval",
            "name": "unseen_destination_eval",
            "cases": "evaluation/unseen_destination_cases.json",
        },
        {
            "type": "destination_readiness_eval",
            "name": "destination_readiness_eval",
            "cases": "evaluation/destination_readiness_cases.json",
        },
        {"type": "pytest", "name": "backend_core_integration_tests", "targets": list(DEFAULT_PYTEST_TARGETS)},
        {
            "type": "command",
            "name": "frontend_chat_component_tests",
            "cwd": "../frontend/DsAgentChat_web",
            "cmd": ["npm", "run", "test", "--", "DiffCard", "PhaseIndicator"],
            "timeout_sec": 60,
        },
        {
            "type": "command",
            "name": "frontend_type_check",
            "cwd": "../frontend/DsAgentChat_web",
            "cmd": ["npm", "run", "type-check"],
            "timeout_sec": 120,
        },
        {
            "type": "command",
            "name": "frontend_production_build",
            "cwd": "../frontend/DsAgentChat_web",
            "cmd": ["npm", "run", "build"],
            "timeout_sec": 120,
        },
    ],
}


@dataclass(slots=True)
class GateResult:
    name: str
    type: str
    status: str
    elapsed_ms: float
    summary: dict[str, Any]
    failures: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "status": self.status,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "summary": self.summary,
            "failures": self.failures,
        }


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _load_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return DEFAULT_CONFIG
    return json.loads(path.read_text(encoding="utf-8"))


def _tail(text: str, *, max_lines: int = 40) -> str:
    lines = (text or "").splitlines()
    return "\n".join(lines[-max_lines:])


def run_qp_eval_gate(gate: dict[str, Any]) -> GateResult:
    start = time.perf_counter()
    cases_path = Path(gate.get("cases") or DEFAULT_CASES_PATH)
    summary = evaluate_cases(_load_jsonl(cases_path))
    failures = list(summary.get("failures") or [])
    status = "passed" if int(summary.get("strict_failed") or 0) == 0 else "failed"
    elapsed_ms = (time.perf_counter() - start) * 1000
    return GateResult(
        name=str(gate.get("name") or "qp_eval"),
        type="qp_eval",
        status=status,
        elapsed_ms=elapsed_ms,
        summary={
            "total_cases": summary.get("total_cases"),
            "strict_cases": summary.get("strict_cases"),
            "strict_passed": summary.get("strict_passed"),
            "strict_failed": summary.get("strict_failed"),
            "tracked_cases": summary.get("tracked_cases"),
            "tracked_mismatched": summary.get("tracked_mismatched"),
            "strict_accuracy": summary.get("strict_accuracy"),
        },
        failures=failures,
    )


def run_hybrid_qp_eval_gate(gate: dict[str, Any]) -> GateResult:
    from scripts.hybrid_qp_eval import DEFAULT_CASES_PATH as DEFAULT_HYBRID_QP_CASES_PATH
    from scripts.hybrid_qp_eval import _load_jsonl as load_hybrid_qp_cases
    from scripts.hybrid_qp_eval import evaluate_cases as evaluate_hybrid_qp_cases
    from scripts.hybrid_qp_eval import is_passing

    start = time.perf_counter()
    cases_path = Path(gate.get("cases") or DEFAULT_HYBRID_QP_CASES_PATH)
    summary = evaluate_hybrid_qp_cases(load_hybrid_qp_cases(cases_path))
    elapsed_ms = (time.perf_counter() - start) * 1000
    return GateResult(
        name=str(gate.get("name") or "hybrid_qp_eval"),
        type="hybrid_qp_eval",
        status="passed" if is_passing(summary) else "failed",
        elapsed_ms=elapsed_ms,
        summary={
            "case_count": summary.get("case_count"),
            "passed_cases": summary.get("passed_cases"),
            "failed_cases": summary.get("failed_cases"),
            "critical_safety_cases": summary.get("critical_safety_cases"),
            "critical_safety_passed": summary.get("critical_safety_passed"),
            "critical_safety_failed": summary.get("critical_safety_failed"),
            "routing_p95_ms": summary.get("routing_p95_ms"),
            "routing_p95_target_ms": summary.get("routing_p95_target_ms"),
        },
        failures=list(summary.get("failures") or []),
    )


def run_structured_edit_replan_eval_gate(gate: dict[str, Any]) -> GateResult:
    from scripts.structured_edit_replan_eval import (
        DEFAULT_CASES_PATH as DEFAULT_STRUCTURED_EDIT_REPLAN_CASES_PATH,
        evaluate_cases as evaluate_structured_edit_replan_cases,
        is_passing,
        load_cases,
    )

    start = time.perf_counter()
    cases_path = Path(gate.get("cases") or DEFAULT_STRUCTURED_EDIT_REPLAN_CASES_PATH)
    summary = evaluate_structured_edit_replan_cases(load_cases(cases_path))
    elapsed_ms = (time.perf_counter() - start) * 1000
    return GateResult(
        name=str(gate.get("name") or "structured_edit_replan_eval"),
        type="structured_edit_replan_eval",
        status="passed" if is_passing(summary) else "failed",
        elapsed_ms=elapsed_ms,
        summary={
            "case_count": summary.get("case_count"),
            "passed_cases": summary.get("passed_cases"),
            "failed_cases": summary.get("failed_cases"),
            "accepted_cases": summary.get("accepted_cases"),
            "rejected_cases": summary.get("rejected_cases"),
            "unsafe_revision_failures": summary.get("unsafe_revision_failures"),
        },
        failures=list(summary.get("failures") or []),
    )


def run_explicit_poi_edit_eval_gate(gate: dict[str, Any]) -> GateResult:
    from scripts.explicit_poi_edit_eval import (
        DEFAULT_CASES_PATH as DEFAULT_EXPLICIT_POI_EDIT_CASES_PATH,
        evaluate_cases as evaluate_explicit_poi_edit_cases,
        is_passing,
        load_cases,
    )

    start = time.perf_counter()
    cases_path = Path(gate.get("cases") or DEFAULT_EXPLICIT_POI_EDIT_CASES_PATH)
    summary = evaluate_explicit_poi_edit_cases(load_cases(cases_path))
    elapsed_ms = (time.perf_counter() - start) * 1000
    return GateResult(
        name=str(gate.get("name") or "explicit_poi_edit_eval"),
        type="explicit_poi_edit_eval",
        status="passed" if is_passing(summary) else "failed",
        elapsed_ms=elapsed_ms,
        summary={
            "case_count": summary.get("case_count"),
            "passed_cases": summary.get("passed_cases"),
            "failed_cases": summary.get("failed_cases"),
            "explicit_cases": summary.get("explicit_cases"),
            "unsafe_revision_failures": summary.get("unsafe_revision_failures"),
        },
        failures=list(summary.get("failures") or []),
    )


def run_ranking_eval_gate(gate: dict[str, Any]) -> GateResult:
    from scripts.ranking_eval_report import build_report, load_cases

    start = time.perf_counter()
    cases_path = Path(gate.get("cases") or "evaluation/ranking_eval_cases.json")
    report = build_report(load_cases(cases_path))
    elapsed_ms = (time.perf_counter() - start) * 1000
    report_summary = report.get("summary") or {}
    guardrails = {
        "case_count": int(report.get("case_count") or 0) >= 20,
        "destination_count": int(report.get("destination_count") or 0) >= 10,
        "unsafe_accepted_count": int(report_summary.get("unsafe_accepted_count") or 0) == 0,
        "non_regressing_good_hit_rate": (
            float(report_summary.get("policy_good_hit_rate") or 0.0)
            >= float(report_summary.get("legacy_good_hit_rate") or 0.0)
        ),
        "ranking_latency_p95": float(report_summary.get("ranking_latency_p95_ms") or 0.0) < 50.0,
    }
    gate_passed = report.get("status") == "passed" and all(guardrails.values())
    failures: list[dict[str, Any]] = []
    if report.get("status") != "passed":
        failures = [
            {
                "case_id": case.get("case_id"),
                "missing_expected_rejected_ids": case.get("missing_expected_rejected_ids"),
                "unexpected_rejected_good_ids": case.get("unexpected_rejected_good_ids"),
                "reject_reason_mismatches": case.get("reject_reason_mismatches"),
            }
            for case in report.get("cases") or []
            if case.get("status") != "passed"
        ]
    if not all(guardrails.values()):
        failures.append({"type": "ranking_guardrail", "guardrails": guardrails})
    return GateResult(
        name=str(gate.get("name") or "ranking_eval"),
        type="ranking_eval",
        status="passed" if gate_passed else "failed",
        elapsed_ms=elapsed_ms,
        summary={
            "case_count": report.get("case_count"),
            "destination_count": report.get("destination_count"),
            "passed_cases": report.get("passed_cases"),
            "failed_cases": report.get("failed_cases"),
            "guardrails": guardrails,
            **report_summary,
        },
        failures=failures,
    )


def run_golden_demo_eval_gate(gate: dict[str, Any]) -> GateResult:
    from scripts.golden_demo_eval import evaluate_cases, load_cases

    start = time.perf_counter()
    cases_path = Path(gate.get("cases") or "evaluation/golden_demo_cases.json")
    report = evaluate_cases(load_cases(cases_path))
    elapsed_ms = (time.perf_counter() - start) * 1000
    failures = [
        {
            "case_id": item.get("case_id"),
            "type": item.get("type"),
            "errors": item.get("errors") or [],
            "actual": item.get("actual") or {},
        }
        for item in report.get("failures") or []
    ]
    return GateResult(
        name=str(gate.get("name") or "golden_demo_eval"),
        type="golden_demo_eval",
        status="passed" if report.get("status") == "passed" else "failed",
        elapsed_ms=elapsed_ms,
        summary={
            "case_count": report.get("case_count"),
            "passed_cases": report.get("passed_cases"),
            "failed_cases": report.get("failed_cases"),
            "by_type": report.get("by_type") or {},
        },
        failures=failures,
    )


def run_unseen_destination_eval_gate(gate: dict[str, Any]) -> GateResult:
    from scripts.unseen_destination_eval import build_report, load_cases

    start = time.perf_counter()
    cases_path = Path(gate.get("cases") or "evaluation/unseen_destination_cases.json")
    report = build_report(load_cases(cases_path))
    elapsed_ms = (time.perf_counter() - start) * 1000
    failures = [
        {
            "case_id": item.get("case_id"),
            "destination": item.get("destination"),
            "errors": item.get("errors") or [],
            "actual_outcome": item.get("actual_outcome"),
        }
        for item in report.get("failures") or []
    ]
    return GateResult(
        name=str(gate.get("name") or "unseen_destination_eval"),
        type="unseen_destination_eval",
        status="passed" if report.get("status") == "passed" else "failed",
        elapsed_ms=elapsed_ms,
        summary={
            "case_count": report.get("case_count"),
            "passed_cases": report.get("passed_cases"),
            "failed_cases": report.get("failed_cases"),
            "ready_cases": report.get("ready_cases"),
            "insufficient_candidate_cases": report.get("insufficient_candidate_cases"),
        },
        failures=failures,
    )


def run_destination_readiness_eval_gate(gate: dict[str, Any]) -> GateResult:
    from scripts.destination_readiness_eval import build_report, load_cases

    start = time.perf_counter()
    cases_path = Path(gate.get("cases") or "evaluation/destination_readiness_cases.json")
    report = build_report(load_cases(cases_path))
    elapsed_ms = (time.perf_counter() - start) * 1000
    failures = [
        {
            "case_id": item.get("case_id"),
            "destination": item.get("destination"),
            "errors": item.get("errors") or [],
            "actual_outcome": item.get("actual_outcome"),
            "quality_status": item.get("quality_status"),
        }
        for item in report.get("failures") or []
    ]
    return GateResult(
        name=str(gate.get("name") or "destination_readiness_eval"),
        type="destination_readiness_eval",
        status="passed" if report.get("status") == "passed" else "failed",
        elapsed_ms=elapsed_ms,
        summary={
            "case_count": report.get("case_count"),
            "passed_cases": report.get("passed_cases"),
            "failed_cases": report.get("failed_cases"),
            "ready_cases": report.get("ready_cases"),
            "safe_degradation_cases": report.get("safe_degradation_cases"),
            "static_cases": report.get("static_cases"),
            "dynamic_cases": report.get("dynamic_cases"),
        },
        failures=failures,
    )


def run_planner_eval_gate(gate: dict[str, Any]) -> GateResult:
    from scripts.planner_eval import build_report

    start = time.perf_counter()
    report = build_report()
    elapsed_ms = (time.perf_counter() - start) * 1000
    failures = [
        {
            "case_id": item.get("case_id"),
            "errors": item.get("errors") or [],
            "actual_feasible": item.get("actual_feasible"),
        }
        for item in report.get("failures") or []
    ]
    return GateResult(
        name=str(gate.get("name") or "planner_eval"),
        type="planner_eval",
        status="passed" if report.get("status") == "passed" else "failed",
        elapsed_ms=elapsed_ms,
        summary={
            "case_count": report.get("case_count"),
            "passed_cases": report.get("passed_cases"),
            "failed_cases": report.get("failed_cases"),
            "planner_p95_ms": report.get("planner_p95_ms"),
        },
        failures=failures,
    )


def run_pytest_gate(gate: dict[str, Any]) -> GateResult:
    start = time.perf_counter()
    targets = [str(item) for item in gate.get("targets") or []]
    cmd = [sys.executable, "-m", "pytest", *targets]
    completed = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    output_tail = _tail((completed.stdout or "") + "\n" + (completed.stderr or ""))
    failures: list[dict[str, Any]] = []
    if completed.returncode != 0:
        failures.append(
            {
                "command": " ".join(cmd),
                "returncode": completed.returncode,
                "output_tail": output_tail,
            }
        )
    return GateResult(
        name=str(gate.get("name") or "pytest"),
        type="pytest",
        status="passed" if completed.returncode == 0 else "failed",
        elapsed_ms=elapsed_ms,
        summary={
            "command": " ".join(cmd),
            "returncode": completed.returncode,
            "output_tail": output_tail,
        },
        failures=failures,
    )


def _command_display(cmd: Any) -> str:
    if isinstance(cmd, list):
        return " ".join(str(item) for item in cmd)
    return str(cmd)


def run_command_gate(gate: dict[str, Any]) -> GateResult:
    """Run a trusted local command as a generic milestone gate.

    This is intentionally config-driven so the same runner can gate backend tests,
    frontend builds, smoke scripts, dataset checks, or model evaluations.
    """

    start = time.perf_counter()
    cmd = gate.get("cmd")
    command = _command_display(cmd)
    timeout_sec = float(gate.get("timeout_sec") or 300)
    cwd = Path(str(gate["cwd"])) if gate.get("cwd") else None
    env = os.environ.copy()
    env.update({str(key): str(value) for key, value in (gate.get("env") or {}).items()})

    failures: list[dict[str, Any]] = []
    if not isinstance(cmd, (str, list)) or (isinstance(cmd, list) and not cmd):
        elapsed_ms = (time.perf_counter() - start) * 1000
        failure = {"error": "command gate requires a non-empty 'cmd' string or list"}
        return GateResult(
            name=str(gate.get("name") or "command"),
            type="command",
            status="failed",
            elapsed_ms=elapsed_ms,
            summary=failure,
            failures=[failure],
        )

    shell = bool(gate.get("shell")) or isinstance(cmd, str)
    try:
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            env=env,
            shell=shell,
            timeout=timeout_sec,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        output_tail = _tail((completed.stdout or "") + "\n" + (completed.stderr or ""))
        if completed.returncode != 0:
            failures.append(
                {
                    "command": command,
                    "cwd": str(cwd) if cwd else None,
                    "returncode": completed.returncode,
                    "output_tail": output_tail,
                }
            )
        return GateResult(
            name=str(gate.get("name") or "command"),
            type="command",
            status="passed" if completed.returncode == 0 else "failed",
            elapsed_ms=elapsed_ms,
            summary={
                "command": command,
                "cwd": str(cwd) if cwd else None,
                "returncode": completed.returncode,
                "timeout_sec": timeout_sec,
                "output_tail": output_tail,
            },
            failures=failures,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        output_tail = _tail((exc.stdout or "") + "\n" + (exc.stderr or ""))
        failure = {
            "command": command,
            "cwd": str(cwd) if cwd else None,
            "timeout_sec": timeout_sec,
            "timeout": True,
            "output_tail": output_tail,
        }
        return GateResult(
            name=str(gate.get("name") or "command"),
            type="command",
            status="failed",
            elapsed_ms=elapsed_ms,
            summary=failure,
            failures=[failure],
        )


def run_gate(gate: dict[str, Any]) -> GateResult:
    gate_type = str(gate.get("type") or "")
    if gate_type == "qp_eval":
        return run_qp_eval_gate(gate)
    if gate_type == "hybrid_qp_eval":
        return run_hybrid_qp_eval_gate(gate)
    if gate_type == "structured_edit_replan_eval":
        return run_structured_edit_replan_eval_gate(gate)
    if gate_type == "explicit_poi_edit_eval":
        return run_explicit_poi_edit_eval_gate(gate)
    if gate_type == "golden_demo_eval":
        return run_golden_demo_eval_gate(gate)
    if gate_type == "ranking_eval":
        return run_ranking_eval_gate(gate)
    if gate_type == "unseen_destination_eval":
        return run_unseen_destination_eval_gate(gate)
    if gate_type == "destination_readiness_eval":
        return run_destination_readiness_eval_gate(gate)
    if gate_type == "planner_eval":
        return run_planner_eval_gate(gate)
    if gate_type == "pytest":
        return run_pytest_gate(gate)
    if gate_type == "command":
        return run_command_gate(gate)
    return GateResult(
        name=str(gate.get("name") or gate_type or "unknown"),
        type=gate_type or "unknown",
        status="failed",
        elapsed_ms=0.0,
        summary={"error": f"Unsupported gate type: {gate_type!r}"},
        failures=[{"error": f"Unsupported gate type: {gate_type!r}"}],
    )


def build_status(config: dict[str, Any], gate_results: list[GateResult], *, run_id: str) -> dict[str, Any]:
    failed = [gate for gate in gate_results if gate.status != "passed"]
    return {
        "schema_version": "milestone_status_v1",
        "run_id": run_id,
        "milestone": config.get("name") or "unnamed",
        "status": "passed" if not failed else "failed",
        "gate_count": len(gate_results),
        "passed_gates": sum(1 for gate in gate_results if gate.status == "passed"),
        "failed_gates": len(failed),
        "gates": [gate.to_dict() for gate in gate_results],
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def render_summary(status: dict[str, Any]) -> str:
    lines = [
        f"milestone={status['milestone']}",
        f"status={status['status']}",
        f"gates={status['passed_gates']}/{status['gate_count']} passed",
    ]
    for gate in status.get("gates") or []:
        summary = gate.get("summary") or {}
        if gate.get("type") == "qp_eval":
            lines.append(
                f"- {gate['name']}: {gate['status']} "
                f"({summary.get('strict_passed')}/{summary.get('strict_cases')} strict)"
            )
        elif gate.get("type") == "hybrid_qp_eval":
            lines.append(
                f"- {gate['name']}: {gate['status']} "
                f"({summary.get('passed_cases')}/{summary.get('case_count')} cases, "
                f"critical={summary.get('critical_safety_passed')}/"
                f"{summary.get('critical_safety_cases')}, "
                f"p95={summary.get('routing_p95_ms')}ms)"
            )
        elif gate.get("type") == "structured_edit_replan_eval":
            lines.append(
                f"- {gate['name']}: {gate['status']} "
                f"({summary.get('passed_cases')}/{summary.get('case_count')} cases, "
                f"unsafe_revision_failures={summary.get('unsafe_revision_failures')})"
            )
        elif gate.get("type") == "explicit_poi_edit_eval":
            lines.append(
                f"- {gate['name']}: {gate['status']} "
                f"({summary.get('passed_cases')}/{summary.get('case_count')} cases, "
                f"explicit={summary.get('explicit_cases')}, "
                f"unsafe_revision_failures={summary.get('unsafe_revision_failures')})"
            )
        elif gate.get("type") == "golden_demo_eval":
            lines.append(
                f"- {gate['name']}: {gate['status']} "
                f"({summary.get('passed_cases')}/{summary.get('case_count')} cases)"
            )
        elif gate.get("type") == "ranking_eval":
            lines.append(
                f"- {gate['name']}: {gate['status']} "
                f"({summary.get('passed_cases')}/{summary.get('case_count')} cases, "
                f"good_hit={summary.get('good_hit_rate')}, "
                f"expected_reject={summary.get('rejected_expected_rate')})"
            )
        elif gate.get("type") == "destination_readiness_eval":
            lines.append(
                f"- {gate['name']}: {gate['status']} "
                f"({summary.get('passed_cases')}/{summary.get('case_count')} cases, "
                f"ready={summary.get('ready_cases')}, "
                f"safe_degrade={summary.get('safe_degradation_cases')})"
            )
        elif gate.get("type") == "planner_eval":
            lines.append(
                f"- {gate['name']}: {gate['status']} "
                f"({summary.get('passed_cases')}/{summary.get('case_count')} cases, "
                f"p95={summary.get('planner_p95_ms')}ms)"
            )
        else:
            lines.append(f"- {gate['name']}: {gate['status']} ({round(gate.get('elapsed_ms', 0))} ms)")
    return "\n".join(lines) + "\n"


def write_artifacts(status: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "status.json", status)
    failures = {
        "run_id": status["run_id"],
        "milestone": status["milestone"],
        "failures": [
            {"gate": gate["name"], "type": gate["type"], "failures": gate.get("failures") or []}
            for gate in status.get("gates") or []
            if gate.get("status") != "passed"
        ],
    }
    _write_json(output_dir / "failures.json", failures)
    (output_dir / "summary.txt").write_text(render_summary(status), encoding="utf-8", newline="\n")


def run_milestone(config: dict[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
    actual_run_id = run_id or _timestamp()
    gate_results = [run_gate(gate) for gate in config.get("gates") or []]
    return build_status(config, gate_results, run_id=actual_run_id)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run compact TravelMind milestone quality gates.")
    parser.add_argument("--config", type=Path, help="Optional milestone config JSON.")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", help="Optional stable run id, useful for tests.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    config = _load_config(args.config)
    status = run_milestone(config, run_id=args.run_id)
    run_dir = args.output_root / status["run_id"]
    write_artifacts(status, run_dir)
    print(render_summary(status).strip())
    print(f"artifacts={run_dir}")
    return 0 if status["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
