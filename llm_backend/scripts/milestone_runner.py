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
    "tests/test_travel_m2_011.py",
    "tests/test_travel_sse_envelope.py",
)
DEFAULT_CONFIG: dict[str, Any] = {
    "name": "local-quality-gate",
    "gates": [
        {"type": "qp_eval", "name": "qp_eval", "cases": str(DEFAULT_CASES_PATH)},
        {"type": "pytest", "name": "backend_core_tests", "targets": list(DEFAULT_PYTEST_TARGETS)},
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
