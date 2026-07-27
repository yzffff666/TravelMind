# Multi-Turn Conversation Stability v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make TravelMind's multi-turn routing, state mutation, clarification, destination switching, and consecutive editing deterministic, persisted, and replayable.

**Architecture:** Keep `TravelQueryProcessor` as the utterance parser and insert a pure conversation decision/transition layer before route execution. Persist one JSON dialogue-state snapshot through `ConversationService`, expose clarification snapshot/restore methods, and run runtime and offline transcript evaluation through the same domain contracts.

**Tech Stack:** Python 3.10+, Pydantic v2, FastAPI, SQLAlchemy async, pytest, Loguru structured logs, existing milestone runner.

## Global Constraints

- Use test-driven development: every behavior change starts with a failing test.
- Do not add destination-specific aliases, bbox entries, or query sentence patches.
- QA and chat must always remain read-only.
- Models cannot bypass deterministic mutation guards.
- Failed edit/replan operations cannot create a revision.
- No external Provider or LLM call is required by the deterministic transcript gate.
- Existing 13/13 milestone behavior must not regress.

---

## File Map

**Create**

- `llm_backend/app/domain/travel/conversation_runtime.py`: decision models, decision service, and pure transition policy.
- `llm_backend/evaluation/multi_turn_conversation_cases.json`: 24 multi-turn transcripts.
- `llm_backend/scripts/multi_turn_conversation_eval.py`: deterministic evaluator and JSON/Markdown report writer.
- `llm_backend/tests/test_conversation_runtime.py`: unit tests for decisions and transitions.
- `llm_backend/tests/test_multi_turn_conversation_eval.py`: fixture and report contract tests.
- `llm_backend/tests/test_conversation_runtime_integration.py`: persistence and API-boundary tests.

**Modify**

- `llm_backend/app/models/travel_conversation_state.py`: add `dialogue_state_json`.
- `llm_backend/app/services/conversation_service.py`: read/write/reset dialogue-state snapshots and add compatibility column migration.
- `llm_backend/app/services/travel_clarification_service.py`: snapshot, restore, asked-fields, and flexible-default behavior.
- `llm_backend/app/api/travel.py`: load state, derive a conversation decision, enforce mutation scope, handle destination change, persist snapshots, and emit trace logs.
- `llm_backend/app/domain/travel/structured_qp.py`: document that destination change is finalized by the conversation layer, not directly by the model.
- `llm_backend/scripts/milestone_runner.py`: add the multi-turn gate and focused tests.
- `llm_backend/tests/test_milestone_runner.py`: assert the new gate is part of the milestone.
- `docs/travelmind_core_integration_gate.md`: document the new gate and replay command.

---

### Task 1: Conversation Decision And Transition Domain

**Files:**
- Create: `llm_backend/app/domain/travel/conversation_runtime.py`
- Create: `llm_backend/tests/test_conversation_runtime.py`

**Interfaces:**
- Consumes: QP dictionaries returned by `TravelQueryProcessor.process()`.
- Produces:
  - `ConversationDecision`
  - `ConversationRuntimeSnapshot`
  - `ConversationTransitionResult`
  - `ConversationDecisionService.decide(query: str, qp_output: dict[str, Any], snapshot: ConversationRuntimeSnapshot) -> ConversationDecision`
  - `apply_transition(snapshot: ConversationRuntimeSnapshot, decision: ConversationDecision) -> ConversationTransitionResult`

- [ ] **Step 1: Write failing model and read-only tests**

```python
def test_qa_is_always_read_only():
    snapshot = _snapshot(destination="澳门", revision_id="rev-1")
    qp = _qp(intent="qa")
    decision = ConversationDecisionService().decide(
        "第三天下午去哪里", qp, snapshot
    )
    assert decision.intent == "qa"
    assert decision.mutation_scope == "none"
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
cd llm_backend
./.venv/bin/pytest tests/test_conversation_runtime.py -v
```

Expected: collection/import failure because `conversation_runtime.py` does not
exist.

- [ ] **Step 3: Implement models and read-only mapping**

Implement the exact Pydantic contracts from the design. Map QA/chat to `none`,
reset to `reset_all`, edits with a slot to `single_slot`, edits without a slot to
`single_day`, and initial create to `whole_trip`.

- [ ] **Step 4: Add failing destination-switch tests**

```python
@pytest.mark.parametrize(
    ("query", "incoming", "expected"),
    [
        ("还是改去杭州吧", "杭州", "change_destination"),
        ("不去深圳了，换成厦门", "厦门", "change_destination"),
        ("深圳到香港怎么走", "香港", "qa"),
        ("香港和澳门哪个更适合", "澳门", "qa"),
    ],
)
def test_destination_switch_requires_explicit_replacement(
    query, incoming, expected
):
    snapshot = _snapshot(destination="深圳", revision_id="rev-1")
    qp = _qp(intent="create", destination=incoming)
    decision = ConversationDecisionService().decide(query, qp, snapshot)
    assert decision.intent == expected
```

- [ ] **Step 5: Run and verify destination tests fail for the missing behavior**

Run the same focused pytest command. Confirm switch cases remain `create` and
ordinary city mentions are not safely coerced to QA.

- [ ] **Step 6: Implement destination-switch and transition policy**

Use generic replacement patterns and normalized destination comparison. For
`change_destination`, preserve portable constraint names and clear active
itinerary, revision, and old pending state in `state_after`. Do not add city
names to the implementation.

- [ ] **Step 7: Add and pass transition invariant tests**

Cover:

- QA/chat do not change itinerary or revision;
- destination switch removes active old itinerary;
- failed edit preview does not change revision;
- reset clears itinerary, revision, pending state, and destination;
- the input snapshot is not mutated in place.

- [ ] **Step 8: Run focused tests**

```bash
./.venv/bin/pytest tests/test_conversation_runtime.py -v
```

Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
git add app/domain/travel/conversation_runtime.py tests/test_conversation_runtime.py
git commit -m "Add conversation decision and transition domain"
```

---

### Task 2: Clarification Snapshot And Flexible Defaults

**Files:**
- Modify: `llm_backend/app/services/travel_clarification_service.py`
- Modify: `llm_backend/app/domain/travel/clarification_rules.py`
- Test: `llm_backend/tests/test_travel_sse_envelope.py`

**Interfaces:**
- Produces:
  - `TravelClarificationService.snapshot_pending(thread_id: str) -> dict[str, Any] | None`
  - `TravelClarificationService.restore_pending(thread_id: str, snapshot: dict[str, Any] | None) -> None`
  - pending payload keys `asked_fields` and `assumptions`

- [ ] **Step 1: Write failing snapshot round-trip test**

```python
def test_clarification_snapshot_restores_in_fresh_service():
    first = TravelClarificationService()
    first.start_new("conv-1", "我想去香港")
    snapshot = first.snapshot_pending("conv-1")

    restored = TravelClarificationService()
    restored.restore_pending("conv-1", snapshot)

    assert restored.has_pending("conv-1")
    assert restored.snapshot_pending("conv-1") == snapshot
```

- [ ] **Step 2: Run the focused test and verify RED**

```bash
./.venv/bin/pytest tests/test_travel_sse_envelope.py -v
```

Expected: `snapshot_pending` is missing.

- [ ] **Step 3: Implement defensive snapshot and restore**

Use JSON-compatible deep copies so callers cannot mutate the service's internal
pending state.

- [ ] **Step 4: Write failing flexible-answer tests**

Cover:

```text
initial: "我想去香港"
follow-up: "都可以"
expected: duration=3, budget=6000, no pending

initial: "预算5000"
follow-up: "都可以"
expected: destination remains missing, pending remains
```

- [ ] **Step 5: Verify RED**

Confirm current extraction leaves all missing fields unresolved.

- [ ] **Step 6: Implement generic flexible-default policy**

Add data-only flexible-answer patterns to `clarification_rules.py`. Apply defaults
only when destination is already known. Record assumptions and asked fields.

- [ ] **Step 7: Run focused tests**

```bash
./.venv/bin/pytest tests/test_travel_sse_envelope.py -v
```

Expected: all clarification tests pass.

- [ ] **Step 8: Commit**

```bash
git add app/services/travel_clarification_service.py app/domain/travel/clarification_rules.py tests/test_travel_sse_envelope.py
git commit -m "Persist clarification snapshots and flexible defaults"
```

---

### Task 3: Dialogue-State Persistence

**Files:**
- Modify: `llm_backend/app/models/travel_conversation_state.py`
- Modify: `llm_backend/app/services/conversation_service.py`
- Create: `llm_backend/tests/test_conversation_runtime_integration.py`

**Interfaces:**
- Produces:
  - `dialogue_state_json` model column
  - `ConversationService.upsert_travel_conversation_state(..., dialogue_state: dict[str, Any] | None = None)`
  - `ConversationService.update_dialogue_state(conversation_id: str, dialogue_state: dict[str, Any])`
  - `get_travel_conversation_state()` key `dialogue_state`

- [ ] **Step 1: Write failing model/service contract tests**

Assert:

- the SQLAlchemy model exposes `dialogue_state_json`;
- the state-return mapping includes `dialogue_state`;
- reset clears dialogue state;
- existing callers that omit `dialogue_state` remain valid.

- [ ] **Step 2: Run and verify RED**

```bash
./.venv/bin/pytest tests/test_conversation_runtime_integration.py -v
```

Expected: missing model column and service parameter.

- [ ] **Step 3: Implement the JSON column and compatibility migration**

Add the column to the model. Extend `_ensure_travel_state_table()` to add the
column when upgrading an existing local database. Keep the migration idempotent.

- [ ] **Step 4: Implement read/write/reset behavior**

Only overwrite `dialogue_state_json` when a non-`None` value is supplied. Reset
sets it to `None`.

- [ ] **Step 5: Run focused tests**

```bash
./.venv/bin/pytest tests/test_conversation_runtime_integration.py -v
```

Expected: all persistence contract tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/models/travel_conversation_state.py app/services/conversation_service.py tests/test_conversation_runtime_integration.py
git commit -m "Persist conversation dialogue state"
```

---

### Task 4: 24-Transcript Evaluator And Baseline

**Files:**
- Create: `llm_backend/evaluation/multi_turn_conversation_cases.json`
- Create: `llm_backend/scripts/multi_turn_conversation_eval.py`
- Create: `llm_backend/tests/test_multi_turn_conversation_eval.py`

**Interfaces:**
- Consumes: `ConversationDecisionService` and `apply_transition`.
- Produces:
  - `load_cases(path: Path) -> list[dict[str, Any]]`
  - `evaluate_cases(cases: list[dict[str, Any]]) -> dict[str, Any]`
  - `is_passing(report: dict[str, Any]) -> bool`
  - JSON/Markdown report output

- [ ] **Step 1: Write failing evaluator contract test**

```python
def test_default_multi_turn_fixture_contains_24_balanced_cases():
    cases = load_cases()
    assert len(cases) == 24
    assert Counter(case["category"] for case in cases) == {
        "destination_switch": 4,
        "destination_mention_readonly": 4,
        "qa_readonly": 4,
        "flexible_clarification": 4,
        "chat_goal_retention": 4,
        "edit_reset_recovery": 4,
    }
```

- [ ] **Step 2: Run and verify RED**

```bash
./.venv/bin/pytest tests/test_multi_turn_conversation_eval.py -v
```

Expected: fixture/evaluator import failure.

- [ ] **Step 3: Add the 24 transcript fixtures**

Each case includes:

```json
{
  "case_id": "switch_shenzhen_to_hangzhou",
  "category": "destination_switch",
  "initial_state": {
    "active_destination": "深圳",
    "current_revision_id": "rev-1",
    "has_itinerary": true
  },
  "turns": [
    {
      "query": "还是改去杭州吧",
      "qp": {
        "intent": "create",
        "intent_detail": "first_create",
        "constraints": {"destination_city": "杭州"}
      },
      "expected": {
        "intent": "change_destination",
        "mutation_scope": "whole_trip",
        "active_destination": "杭州",
        "revision_changed": true
      }
    }
  ]
}
```

Use varied Chinese and English wording. Do not repeat one sentence with only city
names changed.

- [ ] **Step 4: Implement the evaluator**

The evaluator:

- creates the initial runtime snapshot;
- processes turns in order;
- calls the production decision and transition functions;
- compares intent, mutation scope, destination, revision behavior, pending state,
  and block reason;
- emits categorized per-turn failures.

- [ ] **Step 5: Run the evaluator and capture the actual baseline**

```bash
./.venv/bin/python -m scripts.multi_turn_conversation_eval \
  --output-dir reports/multi-turn-conversation-eval/baseline
```

Expected before all integration behavior is complete: report may fail, but every
failure must identify a case, turn, expected value, and actual value.

- [ ] **Step 6: Iterate domain behavior until 24/24**

Only change generic decision/transition/clarification behavior. Do not modify
expected outputs merely to match incorrect runtime behavior.

- [ ] **Step 7: Run evaluator tests and report**

```bash
./.venv/bin/pytest tests/test_conversation_runtime.py tests/test_multi_turn_conversation_eval.py tests/test_travel_sse_envelope.py -v
./.venv/bin/python -m scripts.multi_turn_conversation_eval \
  --output-dir reports/multi-turn-conversation-eval/final
```

Expected: 24/24 passed.

- [ ] **Step 8: Commit**

```bash
git add evaluation/multi_turn_conversation_cases.json scripts/multi_turn_conversation_eval.py tests/test_multi_turn_conversation_eval.py
git commit -m "Add multi-turn conversation replay gate"
```

---

### Task 5: Runtime API Integration And Transition Trace

**Files:**
- Modify: `llm_backend/app/api/travel.py`
- Modify: `llm_backend/app/domain/travel/structured_qp.py`
- Modify: `llm_backend/tests/test_conversation_runtime_integration.py`
- Modify: `llm_backend/tests/test_observability_summary.py`

**Interfaces:**
- Consumes: persisted conversation state, QP output, conversation decision.
- Produces: structured log event `conversation_transition`.

- [ ] **Step 1: Write four failing integration tests**

Cover:

1. explicit switch returns `change_destination`, resets active old state, and
   preserves duration/budget in the new create query;
2. a route QA mentioning another city does not call reset/upsert with a new
   destination and does not emit an edit diff;
3. persisted clarification is restored before routing a follow-up;
4. consecutive successful edits read `rev-2` after the first edit commits it.

- [ ] **Step 2: Run and verify RED**

```bash
./.venv/bin/pytest tests/test_conversation_runtime_integration.py -v
```

Expected: runtime helpers and routing behavior are absent.

- [ ] **Step 3: Add focused API helpers**

Add small helpers rather than more inline branching:

```python
def _conversation_snapshot_from_state(
    conversation_id: str,
    state: dict[str, Any] | None,
) -> ConversationRuntimeSnapshot: ...

def _build_destination_change_query(
    destination: str,
    state: dict[str, Any],
) -> str: ...

async def _persist_dialogue_runtime(
    conversation_id: str,
    snapshot: ConversationRuntimeSnapshot,
) -> None: ...
```

- [ ] **Step 4: Integrate decision routing**

Load state and restore pending clarification before local fast-path routing. Run
QP, derive `ConversationDecision`, and branch on the final conversation intent.
Enforce read-only scopes before calling edit/replan paths.

- [ ] **Step 5: Integrate destination change**

Build a create query from the new destination and portable constraints from the
active itinerary. Clear active stale itinerary state before creating the new
plan. Do not reuse old destination candidates or revision as the active state.

- [ ] **Step 6: Persist clarification snapshots**

Persist after `start_new`, after each `continue_pending`, and after clearing.
Restore before checking `has_pending`.

- [ ] **Step 7: Emit structured transition logs**

Log one `conversation_transition` event per routed turn with the exact fields in
the design. Extend observability summary parsing only enough to count transitions,
intents, mutation scopes, blocked reasons, and revision changes.

- [ ] **Step 8: Run focused integration and observability tests**

```bash
./.venv/bin/pytest \
  tests/test_conversation_runtime_integration.py \
  tests/test_observability_summary.py \
  tests/test_travel_sse_envelope.py -v
```

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add app/api/travel.py app/domain/travel/structured_qp.py tests/test_conversation_runtime_integration.py tests/test_observability_summary.py
git commit -m "Integrate conversation transitions into travel runtime"
```

---

### Task 6: Milestone Gate And Documentation

**Files:**
- Modify: `llm_backend/scripts/milestone_runner.py`
- Modify: `llm_backend/tests/test_milestone_runner.py`
- Modify: `docs/travelmind_core_integration_gate.md`

**Interfaces:**
- Produces milestone gate type `multi_turn_conversation_eval`.

- [ ] **Step 1: Write failing milestone-runner test**

Assert:

- the default config includes `multi_turn_conversation_eval`;
- its summary reports `24/24`;
- any transcript failure fails the milestone.

- [ ] **Step 2: Run and verify RED**

```bash
./.venv/bin/pytest tests/test_milestone_runner.py -v
```

Expected: the gate type is unsupported.

- [ ] **Step 3: Add the gate implementation**

Call `scripts.multi_turn_conversation_eval` in process, summarize case counts and
category failures, and include focused conversation tests in the backend pytest
targets.

- [ ] **Step 4: Update the integration-gate documentation**

Document:

- the purpose of the new gate;
- the replay command;
- the 24-case category matrix;
- how to read failure categories; and
- why the gate does not call external Providers or an LLM.

- [ ] **Step 5: Run the focused milestone tests**

```bash
./.venv/bin/pytest tests/test_milestone_runner.py tests/test_multi_turn_conversation_eval.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/milestone_runner.py tests/test_milestone_runner.py ../docs/travelmind_core_integration_gate.md
git commit -m "Add multi-turn stability milestone gate"
```

---

### Task 7: End-To-End Verification And Delivery

**Files:**
- Modify only when a failing verification reveals a scoped defect.

- [ ] **Step 1: Run the multi-turn evaluator**

```bash
./.venv/bin/python -m scripts.multi_turn_conversation_eval \
  --output-dir reports/multi-turn-conversation-eval/acceptance
```

Required: 24/24 passed.

- [ ] **Step 2: Run focused backend tests**

```bash
./.venv/bin/pytest \
  tests/test_conversation_runtime.py \
  tests/test_conversation_runtime_integration.py \
  tests/test_multi_turn_conversation_eval.py \
  tests/test_travel_sse_envelope.py \
  tests/test_observability_summary.py \
  tests/test_milestone_runner.py -v
```

Required: zero failures.

- [ ] **Step 3: Run the complete core integration milestone**

```bash
./.venv/bin/python -m scripts.milestone_runner
```

Required: all gates pass, including the new multi-turn gate and the previous
13/13 baseline.

- [ ] **Step 4: Run the full backend test suite**

```bash
./.venv/bin/pytest tests/ -v
```

Required: zero failures.

- [ ] **Step 5: Run frontend verification**

```bash
cd ../frontend/DsAgentChat_web
npm run test
npm run type-check
npm run build
```

Required: all commands exit 0.

- [ ] **Step 6: Inspect the final diff and secret safety**

```bash
git diff --check
git status --short
git diff --stat main...HEAD
```

Confirm no `.env`, API key, report cache, or runtime log is staged.

- [ ] **Step 7: Commit any verification-driven fix at its owning task**

If verification changed a file, return to the task that owns that file, repeat its
focused red/green test cycle, and commit that exact task scope. Do not create an
empty completion commit and do not stage report caches or runtime logs.

- [ ] **Step 8: Prepare integration**

Use `superpowers:finishing-a-development-branch` to decide whether to merge,
push, or open a pull request. Do not claim completion until every command above
has fresh passing output.
