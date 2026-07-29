from __future__ import annotations

import pytest

from app.domain.travel.language_policy import (
    localized_text,
    normalize_ui_locale,
    resolve_response_language,
)


@pytest.mark.parametrize(
    ("query", "current", "ui_locale", "expected_language", "expected_source"),
    [
        ("我想去香港三天", None, None, "zh-CN", "query_signal"),
        ("Plan a three day trip to Hong Kong", None, None, "en", "query_signal"),
        ("ok", "zh-CN", "en", "zh-CN", "conversation_state"),
        ("好的", "en", "zh-CN", "en", "conversation_state"),
        ("都可以", "zh-CN", None, "zh-CN", "conversation_state"),
        ("either is fine", "en", None, "en", "conversation_state"),
        (
            "please reply in English",
            "zh-CN",
            None,
            "en",
            "explicit_override",
        ),
        ("请用中文回答", "en", None, "zh-CN", "explicit_override"),
        ("", None, "zh-CN", "zh-CN", "ui_locale"),
        ("", None, None, "en", "default"),
    ],
)
def test_response_language_resolution_precedence(
    query,
    current,
    ui_locale,
    expected_language,
    expected_source,
):
    decision = resolve_response_language(
        query,
        current_language=current,
        ui_locale=ui_locale,
    )

    assert decision.language == expected_language
    assert decision.source == expected_source
    assert decision.changed is (
        current in {"en", "zh-CN"} and current != expected_language
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("en", "en"),
        ("EN", "en"),
        ("en-US", "en"),
        ("zh", "zh-CN"),
        ("zh-cn", "zh-CN"),
        ("ZH_CN", "zh-CN"),
        ("fr", None),
        (None, None),
    ],
)
def test_normalize_ui_locale(value, expected):
    assert normalize_ui_locale(value) == expected


def test_localized_text_formats_both_languages():
    assert "destination" in localized_text(
        "clarification_hard_only",
        "en",
        hard_text="destination",
    )
    assert "目的地" in localized_text(
        "clarification_hard_only",
        "zh-CN",
        hard_text="目的地",
    )


def test_unknown_copy_key_falls_back_to_english_key_name():
    assert localized_text("unknown_copy_key", "zh-CN") == "unknown_copy_key"
