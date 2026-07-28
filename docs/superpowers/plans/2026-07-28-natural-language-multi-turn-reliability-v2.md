# Natural-Language Multi-Turn Reliability v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the QP-precomputed 24-case conversation fixture with a 48-transcript, natural-language-driven reliability gate that exercises real rule QP, conversation decisions, clarification state, and transitions.

**Architecture:** `multi_turn_conversation_eval.py` remains the single deterministic replay engine. Normal turns call `TravelQueryProcessor.process()` before `ConversationDecisionService.decide()`; clarification turns keep using `TravelClarificationService`. A checked-in 48-transcript corpus drives the evaluator, and the existing milestone runner enforces structural, pass-rate, and state-safety guardrails.

**Tech Stack:** Python 3.10+, pytest, Pydantic, existing TravelMind QP/conversation services, JSON evaluation fixtures.

## Global Constraints

- The default evaluator makes no DeepSeek, Provider, database, Redis, or network calls.
- The corpus contains exactly 48 transcripts, eight categories with six cases each.
- Every transcript contains 3 to 6 turns and the corpus contains at least 144 turns.
- Normal turns must not contain a fixture-provided `qp` field.
- Critical categories pass at 100%; overall case pass rate is at least 95%.
- QA/chat mutation, false destination switch, stale itinerary after switch, consecutive-edit target failure, and repeated clarification loop counts are all zero.
- Fix general parsing or state mechanisms; do not add full-query equality branches.

---

### Task 1: Make Replay Consume Real Query Processor Output

**Files:**
- Modify: `llm_backend/scripts/multi_turn_conversation_eval.py`
- Modify: `llm_backend/tests/test_multi_turn_conversation_eval.py`

**Interfaces:**
- Consumes: `TravelQueryProcessor.process(query: str) -> dict[str, Any]`
- Produces: `evaluate_cases(cases: list[dict[str, Any]]) -> dict[str, Any]` with per-turn `qp_output`, `decision`, `state_before`, and `state_after`
- Produces: `validate_case_contract(cases: list[dict[str, Any]]) -> list[str]`

- [ ] **Step 1: Write failing tests for the natural-language fixture contract**

Add tests that:

```python
def test_v2_contract_rejects_fixture_provided_qp():
    cases = [{
        "case_id": "leaky",
        "category": "qa_readonly",
        "initial_state": {
            "active_destination": "澳门",
            "current_revision_id": "rev-1",
            "has_itinerary": True,
        },
        "turns": [{
            "query": "第三天下午去哪里？",
            "qp": {"intent": "qa"},
            "expected": {"intent": "qa"},
        }],
    }]

    assert "must not provide qp" in " ".join(validate_case_contract(cases))
```

and:

```python
def test_normal_turn_runs_real_qp_and_records_decision_trace():
    report = evaluate_cases([{
        "case_id": "natural-qa",
        "category": "qa_readonly",
        "initial_state": {
            "active_destination": "澳门",
            "current_revision_id": "rev-1",
            "has_itinerary": True,
        },
        "turns": [{
            "query": "第三天下午去哪里？",
            "expected": {
                "intent": "qa",
                "mutation_scope": "none",
                "target_day": 3,
                "target_slot": "下午",
                "revision_after": "rev-1",
            },
        }],
    }])

    turn = report["cases"][0]["turns"][0]
    assert turn["qp_output"]["intent"] == "qa"
    assert turn["decision"]["mutation_scope"] == "none"
    assert turn["state_before"]["current_revision_id"] == "rev-1"
    assert turn["state_after"]["current_revision_id"] == "rev-1"
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
cd llm_backend
./.venv/bin/pytest \
  tests/test_multi_turn_conversation_eval.py::test_v2_contract_rejects_fixture_provided_qp \
  tests/test_multi_turn_conversation_eval.py::test_normal_turn_runs_real_qp_and_records_decision_trace -q
```

Expected: failures because `validate_case_contract` and real-QP trace fields do not exist.

- [ ] **Step 3: Implement contract validation and real-QP replay**

In `multi_turn_conversation_eval.py`:

```python
from app.domain.travel.query_processor import TravelQueryProcessor


def validate_case_contract(cases: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for case in cases:
        case_id = str(case.get("case_id") or "unknown")
        for turn_index, turn in enumerate(case.get("turns") or [], start=1):
            if not turn.get("clarification_action") and "qp" in turn:
                errors.append(
                    f"{case_id} turn {turn_index} must not provide qp"
                )
    return errors
```

Change normal-turn evaluation to:

```python
qp_output = query_processor.process(query)
decision = decision_service.decide(query, qp_output, snapshot)
transition = apply_transition(snapshot, decision)
```

Record deep JSON snapshots for `qp_output`, `decision`, `state_before`, and
`state_after` in each turn result. Return contract errors as evaluator failures
instead of silently accepting leaky fixtures.

- [ ] **Step 4: Run focused tests and existing conversation tests**

Run:

```bash
./.venv/bin/pytest tests/test_multi_turn_conversation_eval.py -q
```

Expected: new tests pass; old 24-case fixture tests fail until Task 2 removes
precomputed `qp` fields and updates the v2 corpus.

---

### Task 2: Replace The Fixture With 48 Natural-Language Transcripts

**Files:**
- Modify: `llm_backend/evaluation/multi_turn_conversation_cases.json`
- Modify: `llm_backend/tests/test_multi_turn_conversation_eval.py`

**Interfaces:**
- Consumes: v2 fixture contract from Task 1
- Produces: exactly 48 transcripts, at least 144 turns, six cases per category

- [ ] **Step 1: Replace the old structural assertions with v2 assertions**

Define:

```python
EXPECTED_CATEGORIES = {
    "destination_switch": 6,
    "destination_mention_readonly": 6,
    "qa_readonly": 6,
    "flexible_clarification": 6,
    "chat_goal_retention": 6,
    "consecutive_local_edit": 6,
    "reset_recovery": 6,
    "malformed_ambiguous": 6,
}
```

Assert:

```python
assert len(cases) == 48
assert Counter(case["category"] for case in cases) == EXPECTED_CATEGORIES
assert all(3 <= len(case["turns"]) <= 6 for case in cases)
assert sum(len(case["turns"]) for case in cases) >= 144
assert not validate_case_contract(cases)
```

- [ ] **Step 2: Run the structural test and verify RED**

Run:

```bash
./.venv/bin/pytest \
  tests/test_multi_turn_conversation_eval.py::test_default_multi_turn_fixture_contains_48_natural_language_cases -q
```

Expected: failure because the fixture still has 24 mostly two-turn cases.

- [ ] **Step 3: Build the 48-transcript corpus**

Update the JSON corpus so every normal turn contains only:

```json
{
  "query": "真实用户表达",
  "expected": {
    "intent": "qa",
    "mutation_scope": "none"
  }
}
```

Use `clarification_action` only for production clarification-service calls, and
`commit_revision_id` only after a turn is expected to route as an edit.

Coverage requirements:

- destination switch: explicit replacement in Chinese and English, then verify
  new active destination and no old revision;
- destination mention read-only: comparisons, transit questions, and “只是问问”;
- QA read-only: day/slot, budget, transport, evidence, and fatigue questions;
- flexible clarification: “都可以”, “你安排”, short budget/duration replies,
  and destination never invented;
- chat retention: weather-like small talk, greetings, and unrelated comments
  followed by itinerary QA/edit;
- consecutive local edit: two successful edits consume `rev-1 -> rev-2 -> rev-3`
  and preserve day/slot targets;
- reset recovery: reset clears state, then a new trip starts or clarifies;
- malformed ambiguous: empty punctuation, unclear pronouns, conflicting wording,
  and polite non-mutation questions must fail safely.

- [ ] **Step 4: Run the corpus evaluator and capture real failures**

Run:

```bash
./.venv/bin/python -m scripts.multi_turn_conversation_eval \
  --output-dir reports/multi-turn-conversation-eval/v2-red
```

Expected: structural contract passes. Behavioral failures are allowed at this
step and become the debug list for Task 3.

---

### Task 3: Add Explicit Safety Metrics And Fix General Routing Failures

**Files:**
- Modify: `llm_backend/scripts/multi_turn_conversation_eval.py`
- Modify: `llm_backend/app/domain/travel/query_processor.py` only when corpus failures prove a general QP defect
- Modify: `llm_backend/app/domain/travel/conversation_runtime.py` only when corpus failures prove a decision/transition defect
- Modify: `llm_backend/app/services/travel_clarification_service.py` only when corpus failures prove a clarification-state defect
- Modify: corresponding focused tests under `llm_backend/tests/`

**Interfaces:**
- Produces report metrics:
  `overall_case_pass_rate`, `critical_case_pass_rate`,
  `qa_chat_unintended_mutations`, `false_destination_switches`,
  `explicit_destination_switch_failures`, `stale_itinerary_after_switch`,
  `consecutive_edit_target_failures`, and `repeated_clarification_loops`
- Produces: `is_passing(report: dict[str, Any]) -> bool` enforcing every v2 guardrail

- [ ] **Step 1: Write failing metric guardrail tests**

Create a passing minimal report and mutate one metric at a time:

```python
@pytest.mark.parametrize(
    ("metric", "value"),
    [
        ("qa_chat_unintended_mutations", 1),
        ("false_destination_switches", 1),
        ("explicit_destination_switch_failures", 1),
        ("stale_itinerary_after_switch", 1),
        ("consecutive_edit_target_failures", 1),
        ("repeated_clarification_loops", 1),
    ],
)
def test_v2_safety_metric_regression_fails_gate(metric, value):
    report = evaluate_cases(load_cases())
    report["metrics"][metric] = value
    assert is_passing(report) is False
```

- [ ] **Step 2: Run metric tests and verify RED**

Run:

```bash
./.venv/bin/pytest \
  tests/test_multi_turn_conversation_eval.py::test_v2_safety_metric_regression_fails_gate -q
```

Expected: failure because v1 `is_passing` does not enforce these metrics.

- [ ] **Step 3: Implement metrics from actual state transitions**

Calculate metrics from recorded decisions and snapshots, not from expected
labels alone:

- QA/chat unintended mutation: final decision is `qa` or `chat` and revision or
  itinerary identity changed;
- false switch: non-`change_destination` expected turn produced
  `change_destination`;
- explicit switch failure: expected `change_destination` did not produce it;
- stale itinerary: successful destination switch leaves a current itinerary or
  revision;
- consecutive edit target failure: edit target day/slot differs from expected,
  or successful commit does not advance from the current revision;
- repeated clarification loop: a flexible reply expected to finish
  clarification remains pending.

`is_passing` must enforce the exact v2 structural requirements and the safety
thresholds from the design.

- [ ] **Step 4: Debug failing corpus cases one mechanism at a time**

For each failure:

```text
inspect qp_output
  -> inspect decision
  -> inspect state_before/state_after
  -> classify layer
  -> add focused failing unit test
  -> make the smallest general fix
  -> rerun focused test and corpus
```

Do not relax expected behavior to make the report green unless the design itself
is contradictory.

- [ ] **Step 5: Run v2 evaluator until all acceptance criteria pass**

Run:

```bash
./.venv/bin/python -m scripts.multi_turn_conversation_eval \
  --output-dir reports/multi-turn-conversation-eval/v2-final
```

Expected:

```text
status=passed
cases=48/48
turns>=144
critical_case_pass_rate=1.0
all safety counters=0
```

---

### Task 4: Upgrade The Project Milestone Gate

**Files:**
- Modify: `llm_backend/scripts/milestone_runner.py`
- Modify: `llm_backend/tests/test_milestone_runner.py`
- Modify: `docs/travelmind_core_integration_gate.md`
- Modify: `docs/superpowers/specs/2026-07-27-travelmind-v1-final-delivery-goal-design.md`
- Modify: `docs/简历-项目描述-旅行规划系统.md`

**Interfaces:**
- Consumes: v2 report from Task 3
- Produces: default `multi_turn_conversation_eval` milestone summary with 48-case
  structural and safety metrics

- [ ] **Step 1: Update milestone tests to require v2**

Assert:

```python
assert result.summary["case_count"] == 48
assert result.summary["turn_count"] >= 144
assert result.summary["critical_case_pass_rate"] == 1.0
assert result.summary["qa_chat_unintended_mutations"] == 0
assert result.summary["false_destination_switches"] == 0
assert result.summary["stale_itinerary_after_switch"] == 0
assert result.summary["consecutive_edit_target_failures"] == 0
assert result.summary["repeated_clarification_loops"] == 0
```

- [ ] **Step 2: Run milestone tests and verify RED**

Run:

```bash
./.venv/bin/pytest tests/test_milestone_runner.py -q
```

Expected: old 24-case summary assertions fail.

- [ ] **Step 3: Expose v2 summary fields and update documentation**

Update milestone summary rendering to show:

```text
48/48 cases
turns
critical pass rate
unsafe mutation count
false switch count
clarification loop count
```

Document that v2 uses real rule QP from raw natural-language queries while
remaining offline and deterministic.

- [ ] **Step 4: Run milestone-focused tests**

Run:

```bash
./.venv/bin/pytest \
  tests/test_multi_turn_conversation_eval.py \
  tests/test_milestone_runner.py \
  tests/test_query_processor.py \
  tests/test_conversation_runtime.py \
  tests/test_conversation_runtime_integration.py -q
```

Expected: all pass.

---

### Task 5: Full Verification And Delivery

**Files:**
- Verify all files changed by Tasks 1–4

**Interfaces:**
- Produces: a clean, reproducible v2 gate ready for commit and push

- [ ] **Step 1: Run static checks**

Run:

```bash
cd llm_backend
./.venv/bin/python -m compileall -q app scripts
cd ..
git diff --check
```

Expected: no output and exit code 0.

- [ ] **Step 2: Run all backend tests**

Run:

```bash
cd llm_backend
./.venv/bin/pytest tests/ -q
```

Expected: all tests pass, with only documented skips.

- [ ] **Step 3: Run the full project milestone**

Run:

```bash
./.venv/bin/python -m scripts.milestone_runner \
  --run-id natural-language-multi-turn-v2-final
```

Expected: every default gate passes, including frontend tests, type checking,
and production build.

- [ ] **Step 4: Review generated report and repository scope**

Verify:

```text
48 transcripts
at least 144 turns
100% critical pass
zero safety counters
reports remain ignored
no secret appears in staged content
```

- [ ] **Step 5: Commit and push**

```bash
git add \
  docs/superpowers/plans/2026-07-28-natural-language-multi-turn-reliability-v2.md \
  docs/superpowers/specs/2026-07-27-travelmind-v1-final-delivery-goal-design.md \
  docs/travelmind_core_integration_gate.md \
  docs/简历-项目描述-旅行规划系统.md \
  llm_backend/app/domain/travel/query_processor.py \
  llm_backend/app/domain/travel/conversation_runtime.py \
  llm_backend/app/services/travel_clarification_service.py \
  llm_backend/evaluation/multi_turn_conversation_cases.json \
  llm_backend/scripts/multi_turn_conversation_eval.py \
  llm_backend/scripts/milestone_runner.py \
  llm_backend/tests/test_multi_turn_conversation_eval.py \
  llm_backend/tests/test_milestone_runner.py \
  llm_backend/tests/test_query_processor.py \
  llm_backend/tests/test_conversation_runtime.py
git commit -m "feat: close natural language multi-turn reliability gate"
git push origin main
```

Only stage files that actually changed.

