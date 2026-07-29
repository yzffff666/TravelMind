# Bilingual Conversation Core v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** Completed on 2026-07-29. Backend acceptance: `20/20` cases,
`42` turns, all four hard language-consistency metrics at zero. Full backend:
`771 passed, 2 skipped`. Existing project milestone: `17/17`.

**Goal:** Build one persisted, deterministic response-language policy so TravelMind keeps Chinese and English conversations consistent across create, clarification, QA, edit, reset, and safe fallback paths.

**Architecture:** Add a focused language-policy module that resolves `en` or `zh-CN` from explicit overrides, substantive input, persisted conversation language, and `ui_locale`. Persist the decision in the existing dialogue state, pass it through API/SSE and the draft graph, and centralize the core backend user-visible copy. Validate the behavior with checked-in bilingual multi-turn fixtures and focused integration tests.

**Tech Stack:** Python 3.13, FastAPI, Pydantic, LangGraph, pytest, JSON evaluation fixtures

## Global Constraints

- English is the final default when no reliable signal or persisted language exists.
- Chinese substantive input produces Chinese output; English substantive input produces English output.
- Short acknowledgements such as `ok`, `好的`, and `都可以` preserve the conversation language.
- `ui_locale` is only a fallback hint and accepts `en` or `zh-CN`.
- Existing conversations without `response_language` remain readable.
- POI proper names are not machine-translated.
- Existing conversation, ranking, planning, and SSE tests must remain green.
- This phase does not translate the Vue interface; it prepares the stable backend contract for the next frontend-i18n phase.

---

### Task 1: Deterministic Language Policy

**Files:**
- Create: `llm_backend/app/domain/travel/language_policy.py`
- Create: `llm_backend/tests/test_language_policy.py`

**Interfaces:**
- Produces: `ResponseLanguage = Literal["en", "zh-CN"]`
- Produces: `LanguageDecision(language, source, changed)`
- Produces: `normalize_ui_locale(value) -> ResponseLanguage | None`
- Produces: `resolve_response_language(query, current_language=None, ui_locale=None) -> LanguageDecision`
- Produces: `localized_text(key, language, **values) -> str`

- [ ] **Step 1: Write failing policy tests**

Cover:

```python
resolve_response_language("我想去香港三天").language == "zh-CN"
resolve_response_language("Plan a three day trip to Hong Kong").language == "en"
resolve_response_language("ok", current_language="zh-CN").language == "zh-CN"
resolve_response_language("好的", current_language="en").language == "en"
resolve_response_language("please reply in English", current_language="zh-CN").language == "en"
resolve_response_language("请用中文", current_language="en").language == "zh-CN"
resolve_response_language("", ui_locale="zh-CN").language == "zh-CN"
resolve_response_language("").language == "en"
```

Also verify invalid locale normalization and English fallback for an unknown
copy key.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
cd llm_backend
./.venv/bin/pytest tests/test_language_policy.py -q
```

Expected: collection fails because `language_policy` does not exist.

- [ ] **Step 3: Implement the minimal policy**

Use explicit override regexes first, Han-character detection for substantive
Chinese, ASCII word detection for substantive English, and a compact
acknowledgement set for ambiguous replies. Return a decision source from:

```text
explicit_override
query_signal
conversation_state
ui_locale
default
```

Add localized copy keys for the core paths:

```text
clarification_hard_only
clarification_hard_and_soft
missing_itinerary
reset_done
draft_failed
draft_missing_fields
edit_not_confirmed
edit_target_missing
edit_failed
edit_replan_unverified
edit_provider_failed
edit_exception
candidate_insufficient
chat_fallback
```

- [ ] **Step 4: Run tests and verify GREEN**

Run the Task 1 command and require all tests to pass.

### Task 2: Persist Response Language In Conversation State

**Files:**
- Modify: `llm_backend/app/domain/travel/conversation_runtime.py`
- Modify: `llm_backend/app/api/travel.py`
- Modify: `llm_backend/tests/test_conversation_runtime.py`
- Modify: `llm_backend/tests/test_conversation_runtime_integration.py`

**Interfaces:**
- Consumes: `ResponseLanguage`, `resolve_response_language`
- Produces: `ConversationRuntimeSnapshot.response_language`
- Produces: dialogue-state JSON key `response_language`

- [ ] **Step 1: Write failing persistence tests**

Verify:

```python
snapshot.response_language == "en"
_conversation_snapshot_from_state(...dialogue_state={"response_language": "zh-CN"})
_dialogue_state_from_snapshot(snapshot)["response_language"] == "zh-CN"
apply_transition(snapshot, read_only_decision).state_after.response_language == "zh-CN"
```

Add an async load/persist round-trip test using the existing fake conversation
state.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
cd llm_backend
./.venv/bin/pytest \
  tests/test_conversation_runtime.py \
  tests/test_conversation_runtime_integration.py -q
```

Expected: assertions fail because the snapshot and mapping do not yet expose
`response_language`.

- [ ] **Step 3: Add the backward-compatible state field**

Add:

```python
response_language: Literal["en", "zh-CN"] | None = None
```

Load and save it through `dialogue_state_json`. Do not add a database column;
the existing JSON field is the ownership boundary.

- [ ] **Step 4: Run tests and verify GREEN**

Run the Task 2 command and require all tests to pass.

### Task 3: Resolve Language At The API Boundary

**Files:**
- Modify: `llm_backend/app/api/travel.py`
- Modify: `llm_backend/app/lg_agent/travel_draft_graph.py`
- Modify: `llm_backend/app/domain/travel/sse_envelope.py` only if an existing helper cannot carry metadata
- Modify: `llm_backend/tests/test_travel_sse_envelope.py`
- Modify: `llm_backend/tests/test_conversation_runtime_integration.py`
- Modify: `llm_backend/tests/test_draft_pipeline_integration.py`

**Interfaces:**
- Consumes: `resolve_response_language`
- Produces: optional query form field `ui_locale`
- Produces: optional resume body field `ui_locale`
- Produces: SSE payload field `response_language`
- Produces: draft graph input/state field `response_language`

- [ ] **Step 1: Write failing boundary tests**

Verify:

```text
new English request with no state -> en
new Chinese request with English UI -> zh-CN
short "ok" with persisted zh-CN -> zh-CN
short "好的" with persisted en -> en
intent_routed payload includes response_language
draft explanation uses the resolved language rather than detecting again
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
cd llm_backend
./.venv/bin/pytest \
  tests/test_travel_sse_envelope.py \
  tests/test_conversation_runtime_integration.py \
  tests/test_draft_pipeline_integration.py -q
```

Expected: new language metadata and state assertions fail.

- [ ] **Step 3: Thread the resolved language through the request**

At query/resume entry:

```python
decision = resolve_response_language(
    query,
    current_language=runtime_snapshot.response_language,
    ui_locale=ui_locale,
)
runtime_snapshot.response_language = decision.language
```

Persist before returning from fast paths. Pass `response_language` through
intent events and into the draft graph. Keep `_detect_response_language` as a
compatibility wrapper over the new policy until all callers are migrated.

- [ ] **Step 4: Run tests and verify GREEN**

Run the Task 3 command and require all tests to pass.

### Task 4: Localize Core Backend Response Paths

**Files:**
- Modify: `llm_backend/app/services/travel_clarification_service.py`
- Modify: `llm_backend/app/domain/travel/clarification_rules.py`
- Modify: `llm_backend/app/api/travel.py`
- Modify: `llm_backend/app/lg_agent/travel_draft_graph.py`
- Create: `llm_backend/tests/test_travel_language_paths.py`
- Modify: `llm_backend/tests/test_travel_m2_012_013.py`
- Modify: `llm_backend/tests/test_draft_pipeline_integration.py`

**Interfaces:**
- Consumes: `localized_text`
- Produces: `build_clarification_payload(..., response_language)`
- Produces: language-aware QA, edit, reset, draft fallback, and degradation text

- [ ] **Step 1: Write failing localized-path tests**

Cover both languages for:

```text
clarification with missing destination/duration/budget
QA with and without an itinerary
unconfirmed edit and missing target
edit replan failure preserving the old revision
reset acknowledgement
draft failure and candidate-insufficient safe degradation
```

Assert semantic language, not exact punctuation. English responses must not
contain Chinese sentence copy; Chinese responses must contain Han characters.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
cd llm_backend
./.venv/bin/pytest \
  tests/test_travel_language_paths.py \
  tests/test_travel_m2_012_013.py \
  tests/test_draft_pipeline_integration.py -q
```

Expected: English-path assertions fail on current Chinese hardcoded copy.

- [ ] **Step 3: Replace core user-visible hardcoded copy**

Pass one resolved `response_language` into clarification, QA, edit, reset,
draft fallback, and safe-degradation helpers. Keep logs and internal validation
diagnostics unchanged unless they are directly shown to the user.

For LLM-guided clarification, add the requested response language to the system
prompt and keep deterministic localized fallback copy.

- [ ] **Step 4: Run tests and verify GREEN**

Run the Task 4 command and require all tests to pass.

### Task 5: Bilingual Multi-Turn Acceptance Report

**Files:**
- Create: `llm_backend/evaluation/bilingual_conversation_cases.json`
- Create: `llm_backend/scripts/bilingual_conversation_eval.py`
- Create: `llm_backend/tests/test_bilingual_conversation_eval.py`
- Modify: `docs/travelmind_core_integration_gate.md`

**Interfaces:**
- Consumes: production `resolve_response_language`, conversation snapshot, and localized copy
- Produces: `evaluate_cases(cases) -> dict`
- Produces: `is_passing(report) -> bool`
- Produces: JSON/Markdown artifacts under `reports/bilingual-conversation-eval/`

- [ ] **Step 1: Add 20 checked-in multi-turn cases and failing evaluator tests**

Use 10 Chinese and 10 English journeys covering:

```text
create
clarify
QA
edit
reset
candidate-insufficient fallback
short acknowledgements
explicit language override
revision language preservation
UI-locale fallback
```

Hard metrics:

```text
case_count                         = 20
Chinese cases                      >= 10
English cases                      >= 10
language drift                     = 0
wrong-language final responses     = 0
state persistence failures         = 0
missing language metadata          = 0
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
cd llm_backend
./.venv/bin/pytest tests/test_bilingual_conversation_eval.py -q
```

Expected: collection fails because the evaluator does not exist.

- [ ] **Step 3: Implement the deterministic evaluator**

Replay raw turns through the production language policy and conversation state.
Exercise localized copy for the expected response path and emit per-turn traces
containing query, previous language, selected language, decision source, event
metadata, and failure reason.

This phase writes a standalone report. It does not claim the final
`bilingual_experience_eval` gate until the frontend locale switch and browser
checks are complete.

- [ ] **Step 4: Run evaluator and focused tests**

Run:

```bash
cd llm_backend
./.venv/bin/python -m scripts.bilingual_conversation_eval \
  --output-dir reports/bilingual-conversation-eval/latest
./.venv/bin/pytest tests/test_bilingual_conversation_eval.py -q
```

Expected: `20/20` cases pass and all hard metrics are zero.

### Task 6: Regression Verification And Delivery

**Files:**
- Modify: `docs/superpowers/specs/2026-07-28-bilingual-experience-contract-design.md`
- Modify: `docs/简历-项目描述-旅行规划系统.md`

**Interfaces:**
- Consumes: all prior tasks
- Produces: verified backend bilingual-conversation milestone

- [ ] **Step 1: Update status without overstating frontend completion**

Record that Bilingual Conversation Core v1 is complete while the English-first
Vue switch remains the next closed loop.

- [ ] **Step 2: Run focused and full backend verification**

Run:

```bash
cd llm_backend
./.venv/bin/pytest \
  tests/test_language_policy.py \
  tests/test_conversation_runtime.py \
  tests/test_conversation_runtime_integration.py \
  tests/test_travel_sse_envelope.py \
  tests/test_travel_language_paths.py \
  tests/test_travel_m2_012_013.py \
  tests/test_draft_pipeline_integration.py \
  tests/test_bilingual_conversation_eval.py -q
./.venv/bin/pytest tests/ -q
```

- [ ] **Step 3: Run existing project milestone**

Run:

```bash
cd llm_backend
./.venv/bin/python -m scripts.milestone_runner \
  --run-id bilingual-conversation-core-v1
```

Expected: existing `17/17` milestone remains green. The standalone bilingual
report must also show `20/20`.

- [ ] **Step 4: Inspect and commit**

Run:

```bash
git diff --check
git status --short
```

Commit only the files owned by this plan with:

```bash
git commit -m "feat: add bilingual conversation language core"
```
