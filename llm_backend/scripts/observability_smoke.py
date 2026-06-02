"""Run a small TravelMind API smoke set and collect observability artifacts.

This is an observation-oriented performance analysis helper, not a load test.
It sends a few realistic requests, stores SSE events, and optionally generates
the structured-log summary produced by scripts.observability_summary.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from scripts.candidate_dataset_manifest import (
    collect_manifest,
    write_json as write_manifest_json,
    write_markdown as write_manifest_markdown,
)
from scripts.candidate_badcase_report import (
    build_badcase_report,
    write_json as write_badcase_json,
    write_markdown as write_badcase_markdown,
)
from scripts.export_candidate_decisions import (
    export_candidate_decisions,
    summarize_candidate_decisions,
    write_json as write_candidate_json,
    write_jsonl,
)
from scripts.observability_summary import parse_log_line, render_markdown, summarize_events


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_QUERY_PATH = "/api/travel/query"
DEFAULT_REPORT_DIR = Path("reports/observability-runs")


@dataclass(frozen=True)
class SmokeCase:
    name: str
    query: str
    conversation_alias: str
    reset_conversation: bool = False
    expect_events: tuple[str, ...] = ()
    forbid_events: tuple[str, ...] = ()


CASE_SETS: dict[str, list[SmokeCase]] = {
    "mini": [
        SmokeCase(
            name="clarify_missing_fields",
            query="想去海边玩几天，轻松一点",
            conversation_alias="clarify",
            reset_conversation=True,
            expect_events=("intent_routed", "final_text"),
        ),
        SmokeCase(
            name="domestic_create",
            query="帮我规划 3 天成都亲子游，预算中等，节奏轻松",
            conversation_alias="domestic",
            reset_conversation=True,
            expect_events=("intent_routed", "final_itinerary"),
        ),
        SmokeCase(
            name="domestic_edit",
            query="把第二天下午改成更轻松的室内活动",
            conversation_alias="domestic",
            expect_events=("intent_routed", "edit_diff", "final_itinerary"),
        ),
        SmokeCase(
            name="domestic_edit_missing_target",
            query="把第99天上午改成去博物馆",
            conversation_alias="domestic",
            expect_events=("intent_routed", "final_text"),
            forbid_events=("edit_diff", "final_itinerary"),
        ),
        SmokeCase(
            name="domestic_qa",
            query="第 2 天安排是什么？",
            conversation_alias="domestic",
            expect_events=("intent_routed", "final_text"),
        ),
    ],
    "extended": [
        SmokeCase(
            name="clarify_missing_fields",
            query="想去海边玩几天，轻松一点",
            conversation_alias="clarify",
            reset_conversation=True,
            expect_events=("intent_routed", "final_text"),
        ),
        SmokeCase(
            name="domestic_create",
            query="帮我规划 3 天成都亲子游，预算中等，节奏轻松",
            conversation_alias="domestic",
            reset_conversation=True,
            expect_events=("intent_routed", "final_itinerary"),
        ),
        SmokeCase(
            name="overseas_create",
            query="帮我规划 4 天普吉岛轻松游，预算中等，偏好海岛和美食",
            conversation_alias="overseas",
            reset_conversation=True,
            expect_events=("intent_routed",),
        ),
        SmokeCase(
            name="domestic_edit",
            query="把第二天下午改成更轻松的室内活动",
            conversation_alias="domestic",
            expect_events=("intent_routed", "edit_diff", "final_itinerary"),
        ),
        SmokeCase(
            name="domestic_edit_missing_target",
            query="把第99天上午改成去博物馆",
            conversation_alias="domestic",
            expect_events=("intent_routed", "final_text"),
            forbid_events=("edit_diff", "final_itinerary"),
        ),
        SmokeCase(
            name="domestic_qa",
            query="第 2 天安排是什么？",
            conversation_alias="domestic",
            expect_events=("intent_routed", "final_text"),
        ),
    ],
    "bilingual": [
        SmokeCase(
            name="english_create",
            query="Plan a 3 day trip to Phuket with budget 6000 CNY, relaxed food and beaches",
            conversation_alias="english",
            reset_conversation=True,
            expect_events=("intent_routed", "final_itinerary"),
        ),
        SmokeCase(
            name="english_qa",
            query="What is the plan for day 2?",
            conversation_alias="english",
            expect_events=("intent_routed", "final_text"),
        ),
        SmokeCase(
            name="english_edit",
            query="Change day 2 afternoon to an indoor activity",
            conversation_alias="english",
            expect_events=("intent_routed", "edit_diff", "final_itinerary"),
        ),
        SmokeCase(
            name="mixed_poi_create",
            query="帮我规划 3 天 Phuket Old Town + 查龙寺 + Maya Bay 的轻松行程，预算 6000，偏好美食",
            conversation_alias="mixed",
            reset_conversation=True,
            expect_events=("intent_routed", "final_itinerary"),
        ),
    ],
    "live_probe": [
        SmokeCase(
            name="serpapi_live_probe_phuket",
            query="Plan a 2 day trip to Phuket with budget 4000 CNY, relaxed beaches and food",
            conversation_alias="live_probe",
            reset_conversation=True,
            expect_events=("intent_routed",),
        ),
    ],
}


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _parse_sse_events(lines: list[str]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    event_name: str | None = None
    data_lines: list[str] = []

    def flush() -> None:
        nonlocal event_name, data_lines
        if not data_lines:
            event_name = None
            return
        raw_data = "\n".join(data_lines)
        try:
            payload = json.loads(raw_data)
        except json.JSONDecodeError:
            payload = {"raw": raw_data}
        events.append({"event": event_name, "data": payload})
        event_name = None
        data_lines = []

    for line in lines:
        if not line:
            flush()
            continue
        if line.startswith("event:"):
            event_name = line.replace("event:", "", 1).strip()
            continue
        if line.startswith("data:"):
            data_lines.append(line.replace("data:", "", 1).strip())
            continue
    flush()
    return events


def _conversation_id_from_events(events: list[dict[str, Any]]) -> str | None:
    for event in reversed(events):
        data = event.get("data")
        if isinstance(data, dict):
            conversation_id = data.get("conversation_id")
            if conversation_id:
                return str(conversation_id)
    return None


def _event_names(events: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for event in events:
        if event.get("event"):
            names.append(str(event["event"]))
            continue
        data = event.get("data")
        if isinstance(data, dict) and data.get("event"):
            names.append(str(data["event"]))
    return names


def _write_jsonl(path: Path, events: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for event in events:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")


def _file_size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def _iter_log_events_since(path: Path, offset: int, end_offset: int | None = None):
    if not path.exists():
        return
    with path.open("rb") as file:
        file.seek(offset)
        for raw_line in file:
            if end_offset is not None and file.tell() > end_offset:
                break
            line = raw_line.decode("utf-8", errors="replace")
            event = parse_log_line(line, source=str(path))
            if event is not None:
                yield event


def write_candidate_decision_artifact(
    events: list[Any],
    output_path: Path,
    summary_path: Path | None = None,
    run_metadata: dict[str, Any] | None = None,
    badcase_markdown_path: Path | None = None,
    badcase_json_path: Path | None = None,
    badcase_limit: int = 20,
) -> int:
    samples = export_candidate_decisions(events)
    count = write_jsonl(output_path, samples)
    if summary_path:
        summary = summarize_candidate_decisions(samples)
        if run_metadata:
            summary["run_metadata"] = run_metadata
        write_candidate_json(summary_path, summary)
    if badcase_markdown_path or badcase_json_path:
        badcase_report = build_badcase_report(samples, limit=badcase_limit)
        if badcase_markdown_path:
            write_badcase_markdown(badcase_markdown_path, badcase_report)
        if badcase_json_path:
            write_badcase_json(badcase_json_path, badcase_report)
    return count


def write_candidate_dataset_manifest_artifacts(root: Path) -> dict[str, Any]:
    manifest = collect_manifest(root)
    write_manifest_json(root / "candidate-dataset-manifest.json", manifest)
    write_manifest_markdown(root / "candidate-dataset-manifest.md", manifest)
    return manifest


def build_run_metadata(
    *,
    run_dir: Path,
    base_url: str,
    query_path: str,
    case_set: str,
    user_id: int,
    timeout_seconds: float,
    structured_log: Path,
    structured_log_start_offset: int,
    structured_log_end_offset: int | None,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "run_id": run_dir.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "query_path": query_path,
        "case_set": case_set,
        "user_id": user_id,
        "timeout_seconds": timeout_seconds,
        "structured_log": str(structured_log),
        "structured_log_start_offset": structured_log_start_offset,
        "structured_log_end_offset": structured_log_end_offset,
        "case_count": len(results),
        "cases": [
            {
                "name": result.get("name"),
                "conversation_alias": result.get("conversation_alias"),
                "conversation_id": result.get("conversation_id"),
                "elapsed_ms": result.get("elapsed_ms"),
                "event_count": result.get("event_count"),
                "missing_expected_events": result.get("missing_expected_events") or [],
                "forbidden_observed_events": result.get("forbidden_observed_events") or [],
            }
            for result in results
        ],
    }


def run_case(
    client: httpx.Client,
    case: SmokeCase,
    *,
    user_id: int,
    query_path: str,
    conversation_ids: dict[str, str],
    output_dir: Path,
) -> dict[str, Any]:
    conversation_id = None if case.reset_conversation else conversation_ids.get(case.conversation_alias)
    started = time.perf_counter()
    lines: list[str] = []

    with client.stream(
        "POST",
        query_path,
        data={
            "query": case.query,
            "user_id": str(user_id),
            "conversation_id": conversation_id or "",
        },
    ) as response:
        response.raise_for_status()
        header_conversation_id = response.headers.get("X-Conversation-ID")
        for line in response.iter_lines():
            lines.append(line)

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    events = _parse_sse_events(lines)
    observed_conversation_id = header_conversation_id or _conversation_id_from_events(events)
    if observed_conversation_id:
        conversation_ids[case.conversation_alias] = observed_conversation_id

    event_names = _event_names(events)
    missing_events = [name for name in case.expect_events if name not in event_names]
    forbidden_observed_events = [name for name in case.forbid_events if name in event_names]
    events_path = output_dir / f"{case.name}.events.jsonl"
    _write_jsonl(events_path, events)

    return {
        "name": case.name,
        "query": case.query,
        "conversation_alias": case.conversation_alias,
        "conversation_id": observed_conversation_id,
        "elapsed_ms": elapsed_ms,
        "event_count": len(events),
        "event_names": event_names,
        "missing_expected_events": missing_events,
        "forbidden_observed_events": forbidden_observed_events,
        "events_path": str(events_path),
    }


def render_run_report(results: list[dict[str, Any]], *, base_url: str, query_path: str, case_set: str) -> str:
    lines = [
        "# TravelMind Observability Smoke Run",
        "",
        f"- Base URL: `{base_url}`",
        f"- Query path: `{query_path}`",
        f"- Case set: `{case_set}`",
        f"- Cases: {len(results)}",
        "",
        "## Case Results",
        "",
        "| Case | Elapsed ms | Events | Missing expected events | Forbidden observed events |",
        "|------|------------|--------|-------------------------|---------------------------|",
    ]
    for result in results:
        missing = ", ".join(result["missing_expected_events"]) or "-"
        forbidden = ", ".join(result.get("forbidden_observed_events") or []) or "-"
        lines.append(
            f"| `{result['name']}` | {result['elapsed_ms']} | {result['event_count']} | {missing} | {forbidden} |"
        )

    lines.extend(["", "## Event Names", ""])
    for result in results:
        lines.append(f"- `{result['name']}`: `{', '.join(result['event_names'])}`")

    lines.extend(
        [
            "",
            "## Next Step",
            "",
            "Run `scripts.observability_summary` against `logs/structured.log` to convert backend structured logs into the stage-level performance report.",
            "",
        ]
    )
    return "\n".join(lines)


def has_contract_failures(results: list[dict[str, Any]]) -> bool:
    return any(
        result.get("missing_expected_events") or result.get("forbidden_observed_events")
        for result in results
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run TravelMind observation smoke cases.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Backend base URL.")
    parser.add_argument("--query-path", default=DEFAULT_QUERY_PATH, help="Travel query endpoint path.")
    parser.add_argument("--user-id", type=int, default=1, help="TravelMind user id.")
    parser.add_argument("--case-set", choices=sorted(CASE_SETS), default="mini")
    parser.add_argument("--timeout", type=float, default=180.0, help="Per-request timeout seconds.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument(
        "--structured-log",
        type=Path,
        default=Path("logs/structured.log"),
        help="Structured log path used to generate summary if present.",
    )
    parser.add_argument(
        "--allow-contract-failures",
        action="store_true",
        help="Write artifacts but return 0 even when expected/forbidden event contracts fail.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_dir = args.output_dir / _timestamp()
    run_dir.mkdir(parents=True, exist_ok=True)
    structured_log_offset = _file_size(args.structured_log)

    conversation_ids: dict[str, str] = {}
    results: list[dict[str, Any]] = []
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=args.timeout) as client:
        for case in CASE_SETS[args.case_set]:
            results.append(
                run_case(
                    client,
                    case,
                    user_id=args.user_id,
                    query_path=args.query_path,
                    conversation_ids=conversation_ids,
                    output_dir=run_dir,
                )
            )

    (run_dir / "smoke-results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (run_dir / "smoke-report.md").write_text(
        render_run_report(
            results,
            base_url=args.base_url,
            query_path=args.query_path,
            case_set=args.case_set,
        ),
        encoding="utf-8",
        newline="\n",
    )

    structured_log_end_offset: int | None = None
    run_metadata = build_run_metadata(
        run_dir=run_dir,
        base_url=args.base_url,
        query_path=args.query_path,
        case_set=args.case_set,
        user_id=args.user_id,
        timeout_seconds=args.timeout,
        structured_log=args.structured_log,
        structured_log_start_offset=structured_log_offset,
        structured_log_end_offset=None,
        results=results,
    )

    if args.structured_log.exists():
        structured_log_end_offset = _file_size(args.structured_log)
        run_metadata["structured_log_end_offset"] = structured_log_end_offset
        run_events = list(
            _iter_log_events_since(
                args.structured_log,
                structured_log_offset,
                structured_log_end_offset,
            )
        )
        summary = summarize_events(run_events)
        (run_dir / "observability-summary.md").write_text(
            render_markdown(summary),
            encoding="utf-8",
            newline="\n",
        )
        write_candidate_decision_artifact(
            run_events,
            run_dir / "candidate-decisions.jsonl",
            run_dir / "candidate-decisions-summary.json",
            run_metadata=run_metadata,
            badcase_markdown_path=run_dir / "candidate-badcase-report.md",
            badcase_json_path=run_dir / "candidate-badcase-report.json",
        )
        (run_dir / "structured-log-window.json").write_text(
            json.dumps(
                {
                    "structured_log": str(args.structured_log),
                    "start_offset": structured_log_offset,
                    "end_offset": structured_log_end_offset,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )

    (run_dir / "run-metadata.json").write_text(
        json.dumps(run_metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    write_candidate_dataset_manifest_artifacts(args.output_dir)

    print(f"Observation smoke artifacts written to: {run_dir}")
    if has_contract_failures(results) and not args.allow_contract_failures:
        print("Observation smoke event contract failed; inspect smoke-report.md.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
