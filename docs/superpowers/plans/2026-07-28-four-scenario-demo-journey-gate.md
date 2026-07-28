# Four-Scenario Demo Journey Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic four-scenario journey gate that runs twice and proves TravelMind's conversation, candidate, ranking, planning, revision, and SSE contracts compose safely.

**Architecture:** A checked-in four-case fixture drives one offline evaluator. The evaluator uses production domain services with sanitized candidates and in-memory state, emits real SSE envelopes, records complete decision traces, and exposes strict safety metrics to the existing milestone runner.

**Tech Stack:** Python 3.11, Pydantic, TravelMind domain services, pytest, JSON fixtures, Markdown/JSON reports.

## Global Constraints

- Exactly four scenario definitions and two repetitions are required.
- No live LLM, Provider, database, or browser dependency enters the deterministic gate.
- No new destination-specific production bbox, alias, or POI whitelist is allowed.
- Every behavior change follows red-green TDD.
- The final default milestone must fail on any journey safety regression.

---

### Task 1: Fixture Contract And Evaluation Skeleton

**Files:**
- Create: `llm_backend/evaluation/demo_journey_cases.json`
- Create: `llm_backend/scripts/demo_journey_eval.py`
- Create: `llm_backend/tests/test_demo_journey_eval.py`

**Interfaces:**
- Consumes: JSON cases with scenario, turn, destination, and candidate fields.
- Produces: `load_cases`, `validate_case_contract`, `evaluate_cases`, `is_passing`, `render_markdown`, and `write_outputs`.

- [ ] **Step 1: Write fixture contract tests**

Assert:

```python
cases = load_cases()
assert len(cases) == 4
assert {case["category"] for case in cases} == {
    "domestic_long_tail",
    "overseas_unseen",
    "destination_switch_edits",
    "insufficient_candidates",
}
assert validate_case_contract(cases) == []
```

- [ ] **Step 2: Run the contract test and verify RED**

Run:

```bash
./.venv/bin/pytest tests/test_demo_journey_eval.py -q
```

Expected: import or missing-file failure.

- [ ] **Step 3: Add the four sanitized scenarios**

Use:

- Jingdezhen local candidates plus cross-city decoys;
- Tromso local candidates plus Tokyo/Paris decoys;
- Shenzhen and Hong Kong local candidates for switch/edit lineage; and
- Oaxaca with exactly two publishable candidates plus rejected decoys.

- [ ] **Step 4: Implement strict structural validation**

Reject:

- case count other than four;
- missing or duplicate case IDs;
- category mismatch;
- duplicate candidate IDs;
- missing create/QA/edit/switch/degrade turn roles; and
- candidate rows without coordinates unless their role is `mock`.

- [ ] **Step 5: Run contract tests and verify GREEN**

Run:

```bash
./.venv/bin/pytest tests/test_demo_journey_eval.py::test_default_fixture_contract -q
```

Expected: pass.

---

### Task 2: Ready-Journey Candidate, Ranking, Planning, And SSE Flow

**Files:**
- Modify: `llm_backend/scripts/demo_journey_eval.py`
- Modify: `llm_backend/tests/test_demo_journey_eval.py`

**Interfaces:**
- Consumes: ready domestic/overseas candidate fixtures.
- Produces: complete create/QA/edit journey traces and final itineraries.

- [ ] **Step 1: Write failing ready-journey tests**

Assert:

```python
report = evaluate_cases(load_cases(), repetitions=1)
domestic = case_result(report, "domestic_long_tail_jingdezhen")
overseas = case_result(report, "overseas_unseen_tromso")
assert domestic["status"] == "passed"
assert overseas["status"] == "passed"
assert domestic["qa_revision_mutations"] == 0
assert overseas["cross_city_published"] == 0
assert overseas["mock_published"] == 0
```

- [ ] **Step 2: Run and verify RED**

Run:

```bash
./.venv/bin/pytest tests/test_demo_journey_eval.py::test_ready_journeys_compose_production_layers -q
```

Expected: evaluation is not implemented.

- [ ] **Step 3: Implement candidate conversion and safety filtering**

Convert fixture rows into `ProviderCandidate`, resolve a fixture-backed
`DestinationProfile`, call publishability filtering, and retain all candidate
decisions in the trace.

- [ ] **Step 4: Implement rule/learned ranking selection and planning**

Call `RankingScorer`, `POIRankingPolicy`, learned-ranking fallback selection,
and `ConstraintAwareItineraryPlanner`. Convert the resulting skeleton into one
plain itinerary payload with deterministic revision IDs.

- [ ] **Step 5: Implement raw-query routing and read-only QA**

Every normal turn must call `TravelQueryProcessor.process`, then
`ConversationDecisionService.decide`, then `apply_transition`. QA emits
`intent_routed` and `final_text` without changing the itinerary or revision.

- [ ] **Step 6: Implement local edit semantics**

Plan replacement candidates for the requested day or slot, change only that
target, create a child revision, and emit `edit_diff` plus `final_itinerary`.

- [ ] **Step 7: Run ready-journey tests and verify GREEN**

Run:

```bash
./.venv/bin/pytest tests/test_demo_journey_eval.py -q
```

Expected: domestic and overseas scenarios pass.

---

### Task 3: Destination Switch, Consecutive Edits, And Safe Degradation

**Files:**
- Modify: `llm_backend/scripts/demo_journey_eval.py`
- Modify: `llm_backend/tests/test_demo_journey_eval.py`

**Interfaces:**
- Consumes: switch/edit and insufficient-candidate scenarios.
- Produces: stale-state, lineage, and degradation safety metrics.

- [ ] **Step 1: Write failing switch and degradation tests**

Assert:

```python
report = evaluate_cases(load_cases(), repetitions=1)
switch = case_result(report, "destination_switch_shenzhen_hongkong")
degrade = case_result(report, "insufficient_candidates_oaxaca")
assert switch["revision_lineage_failures"] == 0
assert switch["stale_destination_candidates"] == 0
assert degrade["unsafe_final_itinerary_on_degrade"] == 0
assert degrade["terminal_event"] in {"quality_warning", "final_text"}
```

- [ ] **Step 2: Run and verify RED**

Run:

```bash
./.venv/bin/pytest tests/test_demo_journey_eval.py::test_switch_and_degradation_are_safe -q
```

Expected: missing metrics or failed scenarios.

- [ ] **Step 3: Implement destination switch cleanup**

Use the production decision transition to clear the old itinerary/revision,
then create the new destination itinerary. Count any old-city selected POI as a
stale candidate failure.

- [ ] **Step 4: Implement consecutive revision checks**

For every edit, require:

```text
new.base_revision_id == previous.revision_id
new.revision_id != previous.revision_id
```

Compare all non-target days/slots before and after.

- [ ] **Step 5: Implement safe degradation**

When publishability or planning is insufficient, emit `quality_warning` and
`final_text`, never emit `final_itinerary`, and keep revision unset.

- [ ] **Step 6: Run all evaluator tests and verify GREEN**

Run:

```bash
./.venv/bin/pytest tests/test_demo_journey_eval.py -q
```

Expected: all pass.

---

### Task 4: Two-Run Gate, Reports, And Milestone Integration

**Files:**
- Modify: `llm_backend/scripts/demo_journey_eval.py`
- Modify: `llm_backend/scripts/milestone_runner.py`
- Modify: `llm_backend/tests/test_demo_journey_eval.py`
- Modify: `llm_backend/tests/test_milestone_runner.py`
- Modify: `docs/travelmind_core_integration_gate.md`
- Modify: `docs/superpowers/specs/2026-07-27-travelmind-v1-final-delivery-goal-design.md`
- Modify: `docs/简历-项目描述-旅行规划系统.md`

**Interfaces:**
- Consumes: deterministic four-scenario report.
- Produces: strict `demo_journey_eval` project gate and compact delivery evidence.

- [ ] **Step 1: Write failing two-run acceptance tests**

Assert:

```python
report = evaluate_cases(load_cases(), repetitions=2)
assert report["journey_runs"] == 8
assert report["passed_journey_runs"] == 8
assert all(value == 0 for value in report["safety_metrics"].values())
assert is_passing(report)
```

- [ ] **Step 2: Implement report aggregation and Markdown output**

The CLI writes JSON/Markdown and returns nonzero unless all 8 runs and every
safety metric pass.

- [ ] **Step 3: Add the milestone runner gate**

Add `demo_journey_eval` before backend/frontend integration gates and expose:

```text
8/8 runs
turn count
wrong edit targets
stale candidates
unsafe degradation
lineage failures
```

- [ ] **Step 4: Update delivery documentation**

Document:

- deterministic boundary;
- two-run `8/8` result;
- separation from live/browser evidence; and
- remaining final-project tasks.

- [ ] **Step 5: Run focused milestone tests**

Run:

```bash
./.venv/bin/pytest \
  tests/test_demo_journey_eval.py \
  tests/test_milestone_runner.py \
  tests/test_multi_turn_conversation_eval.py \
  tests/test_conversation_runtime.py \
  tests/test_itinerary_planner.py -q
```

Expected: all pass.

---

### Task 5: Full Verification And Delivery

**Files:**
- Verify all files changed by Tasks 1-4.

**Interfaces:**
- Produces: committed and pushed journey-level delivery gate.

- [ ] **Step 1: Run static checks**

```bash
./.venv/bin/python -m compileall -q app scripts tests
git diff --check
```

- [ ] **Step 2: Run the full backend suite**

```bash
./.venv/bin/pytest tests/ -q
```

- [ ] **Step 3: Run the evaluator twice**

```bash
./.venv/bin/python -m scripts.demo_journey_eval \
  --repetitions 2 \
  --output-dir reports/demo-journey-eval/final
```

Required: `8/8` journey runs and all safety metrics zero.

- [ ] **Step 4: Run the complete milestone**

```bash
./.venv/bin/python -m scripts.milestone_runner \
  --run-id four-scenario-demo-journey-final
```

Required: every gate passes, including frontend tests, type checking, and build.

- [ ] **Step 5: Review for secrets and generated artifacts**

Confirm no API key, report cache, provider budget file, or generated build output
is staged.

- [ ] **Step 6: Commit and push**

```bash
git add docs llm_backend/app llm_backend/evaluation llm_backend/scripts llm_backend/tests
git commit -m "feat: add four-scenario demo journey gate"
git push origin main
```

