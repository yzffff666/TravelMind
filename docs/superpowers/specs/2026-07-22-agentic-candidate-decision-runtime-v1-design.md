# Agentic Candidate Decision Runtime v1 Design

## 1. Goal

Turn TravelMind's candidate-quality work from a shadow-only experiment into a safe runtime decision path.

The runtime contract is:

```text
destination resolution
  -> provider recall
  -> destination and coordinate publish gate
  -> candidate ranking policy
  -> constraint-aware planner
  -> LLM expression over a locked plan skeleton
  -> final publish and persistence
```

If any required stage cannot produce a verified decision, the request must fail closed with a clear degraded response. It must not fall through to free-form LLM POI generation.

## 2. Why This Work Is Needed

Three current gaps prevent the existing candidate-decision work from forming a complete product contract:

1. `recall_node` catches pipeline exceptions and continues to `llm_draft_node`. This can publish an ungrounded itinerary when a provider or ranking dependency fails.
2. Create and local replan do not apply the same coordinate-backed publish rule for every static and dynamic destination.
3. `POIRankingPolicy` produces a shadow report, while the planner still consumes the legacy `RankingScorer` output. The ranking evaluation also has only two deterministic cases.

## 3. Scope

### 3.1 Fail-closed pipeline behavior

- Add an explicit `pipeline_error` grounding status.
- Route `pipeline_error` to `grounding_exit_node`.
- Return a recoverable, user-facing degraded message.
- Do not call the LLM, emit `final_itinerary`, or persist a new conversation state after a required candidate-stage failure.
- Preserve template fallback only for an LLM failure after a valid plan skeleton exists.

### 3.2 Shared publishability policy

Introduce one small service-level policy used by create and local replan. It decides whether candidates are publishable based on:

- resolved destination profile;
- valid latitude and longitude;
- destination match;
- candidate source policy;
- minimum candidate count required by the requested operation.

Required counts are operation-specific:

- create: configured destination minimum, currently 3;
- one-slot replan: 1;
- full-day replan: number of target slots;
- explicit POI edit: 1 coordinate-backed candidate with a verified name match.

Mock candidates remain available for deterministic tests and local fixtures, but they must not count as live production readiness unless an explicit test-only setting enables them.

### 3.3 Ranking runtime modes

Add an explicit configuration mode:

```text
POI_RANKING_MODE=legacy | shadow | candidate
```

- `legacy`: existing `RankingScorer` controls planner input.
- `shadow`: legacy controls planner input; `POIRankingPolicy` writes comparison telemetry.
- `candidate`: accepted `POIRankingPolicy` results control planner input; legacy remains available for comparison and rollback.

Default rollout remains `shadow` until the expanded deterministic gate passes. The implementation must make switching modes a configuration change, not a code rollback.

### 3.4 Destination-aware ranking features

`POIRankingPolicy` must consume the resolved `DestinationProfile` or an equivalent grounding decision instead of relying only on the finite static bbox table.

Hard rejects:

- destination mismatch;
- missing or invalid coordinates;
- generic activity;
- duplicate POI;
- disallowed mock-only candidate in live mode.

Soft ranking dimensions remain explainable:

- resolvability;
- evidence coverage;
- preference match;
- provider confidence;
- distance feasibility;
- budget match;
- reviewed alias bonus.

## 4. Data Flow

### 4.1 Create itinerary

```text
QP constraints
  -> DestinationResolver
  -> RecallService
  -> shared publishability policy
  -> legacy and candidate ranking according to mode
  -> ConstraintAwareItineraryPlanner
  -> locked PlanSkeleton
  -> LLM text generation
  -> apply PlanSkeleton
  -> final validation
  -> SSE final_itinerary and persistence
```

### 4.2 Local replan

```text
REPLAN_DAY request
  -> DestinationResolver
  -> RecallService
  -> shared publishability policy
  -> selected ranking mode
  -> ConstraintAwareItineraryPlanner
  -> replace only target day or slot
  -> edit_diff and new revision only after success
```

### 4.3 Failure path

```text
profile unresolved
or provider/pipeline exception
or insufficient publishable candidates
or planner infeasible
  -> final_text / quality warning
  -> no free-form POI generation
  -> no final_itinerary
  -> no new revision or persistence
```

## 5. Error Handling

The system distinguishes operational degradation from programmer errors while keeping the same publication guarantee:

- Provider timeout or quota failure: aggregate provider assumptions; continue only if enough verified candidates remain.
- Complete recall/pipeline failure: `pipeline_error`, fail closed.
- Ranking policy exception in `candidate` mode: fail closed rather than silently using unverified candidates. Operators can switch the feature flag back to `legacy`.
- LLM failure after a feasible skeleton: template wording may be used, but POI identity remains locked to the skeleton.
- Persistence failure after a valid response: log as a persistence error; do not claim the revision was saved.

## 6. Evaluation Design

Expand ranking evaluation from 2 cases to at least 20 cases across at least 10 destinations.

Required categories:

- domestic common city;
- domestic long-tail city;
- overseas common city;
- overseas long-tail city;
- cross-city high-score decoy;
- missing coordinates;
- duplicate titles from different providers;
- generic activity;
- weak evidence;
- preference and budget trade-off;
- static and dynamic destination profiles;
- provider failure and candidate shortage.

The report compares legacy and candidate modes on:

- expected-good Top-K hit rate;
- unsafe accepted count;
- expected reject rate and reasons;
- evidence coverage;
- duplicate and generic-activity rate;
- ranking P50/P95;
- planner feasibility.

## 7. Acceptance Criteria

The goal is complete only when all conditions pass:

1. Injected pipeline and recall exceptions produce no LLM call, no `final_itinerary`, and no persistence.
2. Static and dynamic create flows reject coordinate-less, cross-city, and insufficient candidate sets.
3. Failed local replan leaves the original itinerary and revision unchanged and emits no `edit_diff`.
4. Mock-only candidates cannot satisfy live publishability.
5. Ranking evaluation has at least 20 cases and 10 destinations.
6. Candidate mode has zero unsafe accepts and does not reduce expected-good Top-K hit rate versus legacy.
7. Ranking-policy P95 is below 50 ms in deterministic evaluation.
8. Existing destination, planner, edit, SSE, frontend, and full backend gates remain green.
9. A budget-controlled real-provider probe covers domestic and overseas destinations without using Mock or an LLM, and reports `healthy`, `degraded`, or `not_ready` honestly.

## 8. Rollout

1. Land fail-closed behavior and the shared publishability policy while ranking remains `shadow`.
2. Expand deterministic evaluation and verify baseline reports.
3. Enable `candidate` mode in local and smoke environments.
4. Compare quality and latency reports on the same case set.
5. Keep production/default mode at `shadow` until the acceptance gate passes; then change the default in a separate, reversible commit.

## 9. Non-goals

This milestone does not include:

- a trained reranker, BERT intent model, two-tower model, or LLM judge;
- large-scale user behavior modeling;
- a new vector database;
- unrelated frontend redesign;
- complete revision rollback APIs;
- broad refactoring of `travel.py` or the entire LangGraph module.

Targeted extraction is allowed only when it creates the shared publishability boundary required by this design.

