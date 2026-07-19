from scripts.structured_qp_shadow_eval import DEFAULT_CASES_PATH, _load_jsonl


def test_structured_qp_shadow_case_set_is_bounded_and_includes_rule_controls():
    cases = _load_jsonl(DEFAULT_CASES_PATH)

    assert len(cases) == 12
    assert sum(case["expected"]["model_calls"] for case in cases) == 7
    assert {case["id"] for case in cases}.issuperset(
        {"readonly_qa", "readonly_mutation_status", "explicit_local_edit", "reset"}
    )
