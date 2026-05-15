import json

from scripts.observability_summary import parse_log_line, render_markdown, summarize_events


def _loguru_json(message: str, extra: dict):
    return json.dumps(
        {
            "text": "",
            "record": {
                "message": message,
                "extra": extra,
            },
        }
    )


def test_parse_loguru_json_extra_event():
    event = parse_log_line(
        _loguru_json(
            "semantic_cache_lookup",
            {
                "service": "cache",
                "cache_source": "faiss",
                "lookup_ms": 4.2,
                "scanned_count": 12,
                "similarity": 0.91,
            },
        )
    )

    assert event is not None
    assert event.event_type == "semantic_cache_lookup"
    assert event.payload["cache_source"] == "faiss"
    assert event.payload["lookup_ms"] == 4.2


def test_parse_loguru_json_nested_extra_from_standard_logging_style():
    event = parse_log_line(
        _loguru_json(
            "deepseek_llm_call",
            {
                "service": "deepseek",
                "extra": {
                    "attempt": 1,
                    "max_attempts": 2,
                    "elapsed_ms": 1389.59,
                    "status": "ok",
                },
            },
        )
    )

    assert event is not None
    assert event.event_type == "deepseek_llm_call"
    assert event.payload["service"] == "deepseek"
    assert event.payload["attempt"] == 1
    assert event.payload["elapsed_ms"] == 1389.59


def test_parse_loguru_json_ignores_non_observability_messages():
    event = parse_log_line(_loguru_json("Initializing Deepseek Service", {"service": "deepseek"}))

    assert event is None


def test_parse_legacy_text_event_with_python_dict():
    line = (
        "2026-05-01 10:00:00.000 | INFO     | app.services.providers.orchestrator:_log:367 - "
        "provider_call {'event_type': 'provider_call', 'provider_name': 'amap', "
        "'provider_kind': 'map', 'elapsed_ms': 25.5, 'status': 'ok', 'result_count': 3}"
    )

    event = parse_log_line(line)

    assert event is not None
    assert event.event_type == "provider_call"
    assert event.payload["provider_name"] == "amap"
    assert event.payload["elapsed_ms"] == 25.5


def test_parse_legacy_qp_message_normalizes_event_type():
    event = parse_log_line(
        _loguru_json(
            "QP parsed",
            {"qp_source": "llm", "confidence": 0.91, "fallback_reason": None},
        )
    )

    assert event is not None
    assert event.event_type == "qp_parsed"
    assert event.payload["qp_source"] == "llm"


def test_summarize_events_groups_core_metrics():
    events = [
        parse_log_line(
            _loguru_json(
                "llm_draft_call",
                {
                    "attempt": 2,
                    "max_attempts": 3,
                    "elapsed_ms": 1200,
                    "ttft_ms": 300,
                    "destination": "Phuket",
                    "days_count": 3,
                    "prompt_chars": 4200,
                    "user_prompt_chars": 3200,
                    "candidate_section_chars": 900,
                    "candidate_count": 10,
                    "response_language": "zh-CN",
                    "output_chars": 1800,
                    "parse_status": "parsed",
                    "status": "ok",
                    "stream": True,
                },
            )
        ),
        parse_log_line(
            _loguru_json(
                "deepseek_llm_call_failed",
                {
                    "attempt": 1,
                    "max_attempts": 3,
                    "elapsed_ms": 900,
                    "status": "failed",
                    "error_type": "TimeoutError",
                    "error_status_code": 504,
                    "error_message": "Gateway timeout",
                    "llm_model": "deepseek-chat",
                    "retryable": True,
                },
            )
        ),
        parse_log_line(
            _loguru_json(
                "llm_draft_call_failed",
                {
                    "attempt": 1,
                    "max_attempts": 3,
                    "elapsed_ms": 800,
                    "destination": "Chengdu",
                    "days_count": 3,
                    "prompt_chars": 2100,
                    "user_prompt_chars": 1800,
                    "candidate_section_chars": 300,
                    "candidate_count": 3,
                    "response_language": "en",
                    "output_chars": 0,
                    "parse_status": "stream_failed",
                    "status": "failed",
                    "error_type": "APIConnectionError",
                    "error_status_code": 402,
                    "error_message": "Insufficient Balance",
                    "llm_model": "deepseek-chat",
                    "retryable": True,
                },
            )
        ),
        parse_log_line(
            _loguru_json(
                "semantic_cache_lookup",
                {"cache_source": "exact", "lookup_ms": 1.1, "scanned_count": 0},
            )
        ),
        parse_log_line(
            "2026-05-01 10:00:00.000 | INFO | x:y:1 - "
            "provider_call {'event_type': 'provider_call', 'provider_name': 'serp', "
            "'provider_kind': 'search', 'elapsed_ms': 81, 'status': 'timeout', "
            "'degraded': True, 'cache_source': 'live'}"
        ),
        parse_log_line(
            "2026-05-01 10:00:00.000 | INFO | x:y:1 - "
            "provider_call {'event_type': 'provider_call', 'provider_name': 'serp', "
            "'provider_kind': 'search', 'elapsed_ms': 12, 'status': 'success', "
            "'result_count': 3, 'cache_source': 'cache'}"
        ),
        parse_log_line(
            "2026-05-01 10:00:00.000 | INFO | x:y:1 - "
            "location_backfill {'event_type': 'location_backfill', 'source': 'unresolved', "
            "'place': 'Unknown Place', 'activity': 'Visit Unknown Place', 'destination': 'Phuket', "
            "'day_index': 2, 'slot_label': 'afternoon', "
            "'confidence': 'low', 'elapsed_ms': 33, 'fallback_reason': 'score_rejected', "
            "'bbox_valid': False, 'provider_status_counts': {'success': 1}, "
            "'candidate_count': 3, 'best_candidate_title': 'Wrong Place', "
            "'best_candidate_provider': 'serp_map', 'best_candidate_lat': 43.95, "
            "'best_candidate_lng': 125.54, 'best_candidate_address': 'Changchun', "
            "'best_match_score': 0.61, 'rejected_score_count': 2, "
            "'cache_negative_hit_count': 1, 'variant_limit_reached': True}"
        ),
        parse_log_line(
            "2026-05-01 10:00:00.000 | INFO | x:y:1 - "
            "location_backfill {'event_type': 'location_backfill', 'source': 'provider', "
            "'confidence': 'low', 'elapsed_ms': 12, 'bbox_valid': False}"
        ),
        parse_log_line(
            "2026-05-01 10:00:00.000 | INFO | x:y:1 - "
            "location_backfill {'event_type': 'location_backfill', 'source': 'skipped', "
            "'confidence': 'low', 'elapsed_ms': 1, 'fallback_reason': 'generic_activity'}"
        ),
        parse_log_line(
            "2026-05-01 10:00:00.000 | INFO | x:y:1 - "
            "itinerary_quality_summary {'event_type': 'itinerary_quality_summary', "
            "'backfill_attempted': 3, 'backfill_filled': 2, 'backfill_skipped': 1, "
            "'backfill_unresolved': 1}"
        ),
        parse_log_line(
            _loguru_json(
                "qp_parsed",
                {"qp_source": "fallback", "confidence": 0.4, "fallback_reason": "low_confidence"},
            )
        ),
        parse_log_line(
            _loguru_json(
                "qa_local_fast_path",
                {"qa_source": "local_itinerary", "qa_elapsed_ms": 18.5},
            )
        ),
        parse_log_line(
            _loguru_json(
                "poi_ranking_shadow",
                {
                    "event_type": "poi_ranking_shadow",
                    "destination": "Phuket",
                    "recalled_count": 4,
                    "policy_accepted_count": 3,
                    "policy_rejected_count": 1,
                    "top_k_overlap_rate": 0.5,
                    "reject_reason_counts": {"bbox_invalid": 1},
                    "rejected_samples": [
                        {
                            "title": "Wrong Place",
                            "source": "serp_map",
                            "rank_score": 0.12,
                            "reject_reasons": ["bbox_invalid"],
                            "risk_flags": ["bbox_invalid"],
                        }
                    ],
                },
            )
        ),
    ]

    summary = summarize_events(event for event in events if event is not None)

    assert summary["llm"]["status_counts"] == {"failed": 2, "ok": 1}
    assert summary["llm"]["error_status_counts"] == {"504": 1, "402": 1}
    assert summary["llm"]["error_message_counts"] == {"Gateway timeout": 1, "Insufficient Balance": 1}
    assert summary["llm"]["model_counts"] == {"deepseek-chat": 2}
    assert summary["llm"]["retryable_failures"] == 2
    assert summary["llm"]["draft"]["parse_status_counts"] == {"parsed": 1, "stream_failed": 1}
    assert summary["llm"]["draft"]["destination_counts"] == {"Phuket": 1, "Chengdu": 1}
    assert summary["llm"]["draft"]["response_language_counts"] == {"zh-CN": 1, "en": 1}
    assert summary["llm"]["draft"]["prompt_chars"]["p50"] == 2100.0
    assert summary["llm"]["draft"]["prompt_chars"]["p95"] == 4200.0
    assert summary["llm"]["draft"]["candidate_section_chars"]["p50"] == 300.0
    assert summary["llm"]["draft"]["candidate_count"]["p50"] == 3.0
    assert summary["llm"]["draft"]["output_chars"]["p50"] == 0.0
    assert summary["cache"]["source_counts"] == {"exact": 1}
    assert summary["cache"]["hit_rate"] == 1.0
    assert summary["providers"]["by_provider"]["serp:search"]["degraded_count"] == 1
    assert summary["providers"]["by_provider"]["serp:search"]["cache_source_counts"] == {"live": 1, "cache": 1}
    assert summary["providers"]["by_provider"]["serp:search"]["live_call_count"] == 1
    assert summary["providers"]["by_provider"]["serp:search"]["cached_call_count"] == 1
    assert summary["backfill"]["attempted"] == 3
    assert summary["backfill"]["skipped"] == 1
    assert summary["backfill"]["skipped_events"] == 1
    assert summary["backfill"]["bbox_invalid_count"] == 1
    assert summary["backfill"]["fallback_reasons"] == {"score_rejected": 1, "generic_activity": 1}
    assert summary["backfill"]["provider_status_counts"] == {"success": 1}
    assert summary["backfill"]["rejected_score_count"] == 2
    assert summary["backfill"]["cache_negative_hit_count"] == 1
    assert summary["backfill"]["variant_limit_reached_count"] == 1
    assert summary["backfill"]["best_match_score"]["p50"] == 0.61
    assert summary["backfill"]["unresolved_samples"] == [
        {
            "place": "Unknown Place",
            "activity": "Visit Unknown Place",
            "destination": "Phuket",
            "day_index": 2,
            "slot_label": "afternoon",
            "fallback_reason": "score_rejected",
            "provider_status_counts": {"success": 1},
            "candidate_count": 3,
            "best_candidate_title": "Wrong Place",
            "best_candidate_provider": "serp_map",
            "best_candidate_lat": 43.95,
            "best_candidate_lng": 125.54,
            "best_candidate_address": "Changchun",
            "best_match_score": 0.61,
            "elapsed_ms": 33.0,
        }
    ]
    assert summary["qp"]["source_counts"] == {"fallback": 1}
    assert summary["qa"]["events"] == 1
    assert summary["qa"]["source_counts"] == {"local_itinerary": 1}
    assert summary["qa"]["elapsed_ms"]["p50"] == 18.5
    assert summary["poi_ranking"]["events"] == 1
    assert summary["poi_ranking"]["destination_counts"] == {"Phuket": 1}
    assert summary["poi_ranking"]["reject_reason_counts"] == {"bbox_invalid": 1}
    assert summary["poi_ranking"]["top_k_overlap_rate"]["p50"] == 0.5
    assert summary["poi_ranking"]["rejected_samples"][0]["title"] == "Wrong Place"


def test_render_markdown_includes_major_sections():
    summary = summarize_events(
        [
            parse_log_line(
                _loguru_json(
                    "semantic_cache_lookup",
                    {"cache_source": "miss", "lookup_ms": 2.0, "scanned_count": 5},
                )
            )
        ]
    )

    markdown = render_markdown(summary)

    assert "# TravelMind Observability Summary" in markdown
    assert "Draft prompt chars" in markdown
    assert "Error status counts" in markdown
    assert "Model counts" in markdown
    assert "## Semantic Cache" in markdown
    assert '"miss": 1' in markdown
    assert "### Backfill Unresolved Samples" in markdown
    assert "- No unresolved backfill samples." in markdown
    assert "## POI Ranking Shadow" in markdown
    assert "- No POI ranking rejected samples." in markdown


def test_render_markdown_includes_backfill_unresolved_samples_table():
    summary = summarize_events(
        [
            parse_log_line(
                "2026-05-01 10:00:00.000 | INFO | x:y:1 - "
                "location_backfill {'event_type': 'location_backfill', 'source': 'unresolved', "
                "'place': 'Cafe | Alias', 'destination': 'Chengdu', 'day_index': 1, "
                "'slot_label': 'morning', 'elapsed_ms': 1820.5, "
                "'fallback_reason': 'provider_empty', 'provider_status_counts': {'empty': 2}, "
                "'candidate_count': 0, 'best_candidate_provider': 'serp_map', "
                "'best_candidate_lat': 31.2, 'best_candidate_lng': 121.4, "
                "'best_candidate_address': 'Shanghai', 'best_match_score': 0.0}"
            )
        ]
    )

    markdown = render_markdown(summary)

    assert "| Place | Day | Slot | Destination | Reason | Provider Status | Candidates | Best Candidate | Candidate Geo | Candidate Address | Best Score | Elapsed ms |" in markdown
    assert "Cafe \\| Alias" in markdown
    assert "31.2,121.4 / serp_map" in markdown
    assert "Shanghai" in markdown
    assert "provider_empty" in markdown
    assert '{"empty": 2}' in markdown


def test_render_markdown_includes_provider_cache_source_counts():
    summary = summarize_events(
        [
            parse_log_line(
                "2026-05-01 10:00:00.000 | INFO | x:y:1 - "
                "provider_call {'event_type': 'provider_call', 'provider_name': 'serp', "
                "'provider_kind': 'map', 'elapsed_ms': 120, 'status': 'success', "
                "'result_count': 3, 'cache_source': 'live'}"
            ),
            parse_log_line(
                "2026-05-01 10:00:00.000 | INFO | x:y:1 - "
                "provider_call {'event_type': 'provider_call', 'provider_name': 'serp', "
                "'provider_kind': 'map', 'elapsed_ms': 8, 'status': 'success', "
                "'result_count': 3, 'cache_source': 'cache'}"
            ),
        ]
    )

    markdown = render_markdown(summary)

    assert "### serp:map" in markdown
    assert "Cache source counts" in markdown
    assert '"live": 1' in markdown
    assert '"cache": 1' in markdown
    assert "Live/Cached calls: 1/1" in markdown
