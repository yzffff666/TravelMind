import json

from scripts.observability_smoke import (
    CASE_SETS,
    _conversation_id_from_events,
    _event_names,
    _file_size,
    _iter_log_events_since,
    _parse_sse_events,
    render_run_report,
    write_candidate_decision_artifact,
)


def test_case_sets_include_bilingual_language_coverage():
    cases = {case.name: case for case in CASE_SETS["bilingual"]}

    assert set(cases) == {
        "english_create",
        "english_qa",
        "english_edit",
        "mixed_poi_create",
    }
    assert cases["english_create"].reset_conversation is True
    assert cases["english_create"].conversation_alias == cases["english_qa"].conversation_alias
    assert cases["english_create"].conversation_alias == cases["english_edit"].conversation_alias
    assert "Phuket" in cases["english_create"].query
    assert "What is the plan" in cases["english_qa"].query
    assert "Phuket Old Town" in cases["mixed_poi_create"].query
    assert "查龙寺" in cases["mixed_poi_create"].query


def test_parse_sse_events_handles_named_and_data_events():
    lines = [
        "event: intent_routed",
        'data: {"conversation_id": "conv_1", "payload": {"intent": "create"}}',
        "",
        'data: {"event": "stage_progress", "conversation_id": "conv_1"}',
        "",
    ]

    events = _parse_sse_events(lines)

    assert events == [
        {
            "event": "intent_routed",
            "data": {"conversation_id": "conv_1", "payload": {"intent": "create"}},
        },
        {
            "event": None,
            "data": {"event": "stage_progress", "conversation_id": "conv_1"},
        },
    ]


def test_parse_sse_events_preserves_raw_invalid_json():
    events = _parse_sse_events(["data: plain text", ""])

    assert events == [{"event": None, "data": {"raw": "plain text"}}]


def test_conversation_id_prefers_latest_event():
    events = [
        {"event": "intent_routed", "data": {"conversation_id": "conv_old"}},
        {"event": "final_text", "data": {"conversation_id": "conv_new"}},
    ]

    assert _conversation_id_from_events(events) == "conv_new"


def test_event_names_supports_named_and_payload_event_shapes():
    events = [
        {"event": "intent_routed", "data": {}},
        {"event": None, "data": {"event": "stage_progress"}},
        {"event": None, "data": {"raw": "ignored"}},
    ]

    assert _event_names(events) == ["intent_routed", "stage_progress"]


def test_render_run_report_contains_case_summary():
    report = render_run_report(
        [
            {
                "name": "domestic_create",
                "elapsed_ms": 123.45,
                "event_count": 2,
                "event_names": ["intent_routed", "final_itinerary"],
                "missing_expected_events": [],
            },
            {
                "name": "domestic_qa",
                "elapsed_ms": 23.0,
                "event_count": 1,
                "event_names": ["intent_routed"],
                "missing_expected_events": ["final_text"],
            },
        ],
        base_url="http://127.0.0.1:8000",
        query_path="/api/travel/query",
        case_set="mini",
    )

    assert "# TravelMind Observability Smoke Run" in report
    assert "`/api/travel/query`" in report
    assert "`domestic_create`" in report
    assert "final_text" in report


def test_json_serializable_result_shape():
    payload = {
        "name": "case",
        "elapsed_ms": 1.0,
        "event_names": ["intent_routed"],
    }

    assert json.loads(json.dumps(payload))["name"] == "case"


def test_iter_log_events_since_reads_only_new_lines(tmp_path):
    log_path = tmp_path / "structured.log"
    old_line = json.dumps(
        {
            "record": {
                "message": "deepseek_llm_call",
                "extra": {"extra": {"event_type": "deepseek_llm_call", "status": "ok"}},
            }
        }
    )
    log_path.write_text(old_line + "\n", encoding="utf-8")
    offset = _file_size(log_path)

    new_line = json.dumps(
        {
            "record": {
                "message": "qp_parsed",
                "extra": {"extra": {"event_type": "qp_parsed", "qp_source": "llm"}},
            }
        }
    )
    with log_path.open("a", encoding="utf-8", newline="\n") as file:
        file.write(new_line + "\n")

    events = list(_iter_log_events_since(log_path, offset))

    assert len(events) == 1
    assert events[0].event_type == "qp_parsed"
    assert events[0].payload["qp_source"] == "llm"


def test_iter_log_events_since_respects_end_offset(tmp_path):
    log_path = tmp_path / "structured.log"
    old_line = json.dumps(
        {"record": {"message": "qp_parsed", "extra": {"extra": {"event_type": "qp_parsed"}}}}
    )
    in_window = json.dumps(
        {
            "record": {
                "message": "llm_draft_call",
                "extra": {"extra": {"event_type": "llm_draft_call", "status": "ok"}},
            }
        }
    )
    after_window = json.dumps(
        {
            "record": {
                "message": "location_backfill",
                "extra": {"extra": {"event_type": "location_backfill", "source": "provider"}},
            }
        }
    )
    log_path.write_text(old_line + "\n", encoding="utf-8")
    start = _file_size(log_path)
    with log_path.open("a", encoding="utf-8", newline="\n") as file:
        file.write(in_window + "\n")
    end = _file_size(log_path)
    with log_path.open("a", encoding="utf-8", newline="\n") as file:
        file.write(after_window + "\n")

    events = list(_iter_log_events_since(log_path, start, end))

    assert [event.event_type for event in events] == ["llm_draft_call"]


def test_write_candidate_decision_artifact_exports_window_backfill_samples(tmp_path):
    log_path = tmp_path / "structured.log"
    old_line = json.dumps(
        {
            "record": {
                "message": "location_backfill",
                "extra": {"extra": {"event_type": "location_backfill", "source": "provider"}},
            }
        }
    )
    in_window = json.dumps(
        {
            "record": {
                "message": "location_backfill",
                "extra": {
                    "extra": {
                        "event_type": "location_backfill",
                        "source": "unresolved",
                        "place": "Big Buddha Phuket",
                        "fallback_reason": "score_rejected",
                        "best_candidate_title": "Big Buddha Temple",
                        "best_match_score": 0.61,
                    }
                },
            }
        }
    )
    log_path.write_text(old_line + "\n", encoding="utf-8")
    offset = _file_size(log_path)
    with log_path.open("a", encoding="utf-8", newline="\n") as file:
        file.write(in_window + "\n")

    events = list(_iter_log_events_since(log_path, offset))
    output_path = tmp_path / "candidate-decisions.jsonl"
    summary_path = tmp_path / "candidate-decisions-summary.json"
    count = write_candidate_decision_artifact(events, output_path, summary_path)

    assert count == 1
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["schema_version"] == "candidate_decision_v1"
    assert rows[0]["decision"] == "rejected"
    assert rows[0]["place"] == "Big Buddha Phuket"
    assert rows[0]["risk_flags"] == ["score_rejected"]
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["total_samples"] == 1
    assert summary["decision_counts"] == {"rejected": 1}
    assert summary["risk_flag_counts"] == {"score_rejected": 1}
