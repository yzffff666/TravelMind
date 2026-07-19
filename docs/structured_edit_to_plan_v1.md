# Structured Edit-to-Plan v1

## Problem

Hybrid Structured QP v1 can understand a difficult edit request, but the old execution path parsed raw text again with `parse_edit_ops`. That could lose `target_day`, `target_slot`, and edit constraints, then treat wording like "改成室内" as itinerary content.

The required path is:

```text
safe Structured QP
-> bounded Edit Command
-> REPLAN_DAY PatchOp
-> Provider recall + ranking + constraint planner
-> verified slot replacement or no new revision
```

## Decision

`StructuredEditCommand` is a narrow bridge, not a second workflow engine. It accepts only `qp_source=llm`, `intent=edit`, `safety_level=safe`, an explicit mutation request, an in-range day, and at least one bounded constraint: `indoor`, `relaxed`, `food`, or `culture`.

The model can therefore decide *which day / slot / constraint* needs replanning, but cannot insert a POI title, free-form activity, budget, or arbitrary payload. It only emits the existing `REPLAN_DAY` PatchOp.

```text
Structured QP: understanding
PatchOp: bounded execution request
DayReplanService: candidate-grounded planning
ItineraryV1: publishable itinerary
```

This keeps the existing PatchOp / DayReplan control plane as the single execution path.

## Local Replanning

For `把第二天下午改成室内`:

1. `PatchEngine` records a replan request without mutating the original day.
2. `DayReplanService` recalls candidates, applies destination grounding and ranking, then invokes `ConstraintAwareItineraryPlanner`.
3. POIs on other days and same-day non-target slots are excluded.
4. Only the target afternoon slot is replaced; the other slots and day theme stay unchanged.
5. Candidate insufficiency or a replan exception returns `final_text` saying the original itinerary was kept. It emits no `edit_diff` / `final_itinerary` and persists no revision.

Full-day edits retain full-day planner behavior.

## Technology Trade-offs

### Why not have DeepSeek write the new POI directly?

It would be linguistically flexible but breaks evidence ownership: a plausible POI may lack provider evidence, geographic grounding, or budget and constraint validation. TravelMind's primary risk is incorrect persisted itinerary state, so the model emits a bounded decision and candidate services own POI selection.

### Why not use rules only?

Rules remain the low-latency fast path for clear edits. They become brittle for contextual or multilingual requests that require jointly understanding day, slot, and preference. Selective Structured QP handles hard cases, while `off` / `shadow` / `selective` modes make rollout reversible.

### Why no trained intent model yet?

Current data is adequate for safety regression but too small and synthetic to train a reliable classifier. The command schema and outcome logs create a clean supervision boundary; after enough reviewed edit/QA badcases, a small router can become:

```text
rule fast path -> small intent/risk model -> DeepSeek fallback -> clarification
```

### Why can a target slot use one candidate?

A slot-local edit has one decision position, so three candidates would reject valid edits without improving correctness. Full-day replans still require enough distinct candidates for every selected slot. The planner rejects generic, duplicate, cross-city, and constraint-mismatched candidates in both cases.

## Acceptance

```bash
cd llm_backend
./.venv/bin/python scripts/structured_edit_replan_eval.py
```

The v1 fixture set has 15 cases: 8 accepted bounded edits and 7 QA / blocked / fallback / invalid-day / no-constraint rejections. Required result:

```text
15/15 passed
unsafe_revision_failures=0
```

Automated coverage also verifies field propagation, target-slot-only replacement with evidence, no template mutation before candidate validation, no-commit fallback for candidate insufficiency/provider failures, and explicit manual POI replacement compatibility.

## Rollout

This is offline-complete. `STRUCTURED_QP_MODE=off` remains the global default. A controlled `selective` rollout should record command accept/reject rate, day/slot correctness, candidate replan success rate, no-commit fallback rate, and replan/E2E P95 before expanding traffic.
