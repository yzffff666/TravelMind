# Agentic Candidate Decision Runtime v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make candidate grounding and ranking a fail-closed runtime decision path shared by itinerary creation and local replanning.

**Architecture:** Add one provider-agnostic publishability policy between recall and ranking, then make both create and replan consume its result. Keep legacy and candidate ranking implementations behind an explicit mode so rollout is measurable and reversible, while the LLM only receives a verified plan skeleton.

**Tech Stack:** Python 3.13, FastAPI, LangGraph, Pydantic Settings, pytest, existing ProviderCandidate/RankingScorer/ConstraintAwareItineraryPlanner services.

## Global Constraints

- Do not add a trained model, LLM judge, vector database, or new external dependency.
- Candidate-stage failures must not fall through to free-form LLM POI generation.
- Static and dynamic destinations must require valid coordinates before publication.
- Local replan failure must preserve the itinerary and revision and emit no `edit_diff`.
- Mock candidates must not satisfy live publishability unless an explicit test-only setting allows them.
- Ranking rollout must support `legacy`, `shadow`, and `candidate` modes.
- Existing uncommitted destination-generalization and explicit-POI changes must be preserved.

---

### Task 1: Shared Candidate Publishability Policy

**Files:**
- Create: `llm_backend/app/services/candidate_publishability.py`
- Create: `llm_backend/tests/test_candidate_publishability.py`
- Modify: `llm_backend/app/core/config.py:56-63`
- Modify: `.env.example:43-53`

**Interfaces:**
- Consumes: `ProviderCandidate`, `DestinationProfile`, `validate_candidate_destination()`, `has_valid_coordinates()`.
- Produces: `PublishabilityResult` and `evaluate_candidate_publishability(candidates, profile, required_count, allow_mock)`.

- [x] **Step 1: Write failing policy tests**

Cover resolved local candidates, static coordinate-less candidates, dynamic cross-city candidates, invalid coordinates, mock candidates, and insufficient candidate counts. Assert exact reject reasons from the existing grounding contract, including `destination_unresolved`, `missing_geo`, `outside_destination_bounds` or `outside_destination_radius`, `candidate_city_mismatch`, and `mock_candidate`.

```python
result = evaluate_candidate_publishability(
    candidates,
    profile,
    required_count=3,
    allow_mock=False,
)
assert result.status == "ready"
assert len(result.accepted) == 3
assert result.reject_reason_counts == {"missing_geo": 1}
```

- [x] **Step 2: Run tests and verify RED**

Run: `cd llm_backend && ./.venv/bin/python -m pytest tests/test_candidate_publishability.py -q`

Expected: import failure because `candidate_publishability` does not exist.

- [x] **Step 3: Implement the policy and config**

```python
@dataclass(slots=True)
class PublishabilityResult:
    accepted: list[ProviderCandidate]
    status: str
    required_count: int
    reject_reason_counts: dict[str, int]

    @property
    def ready(self) -> bool:
        return self.status == "ready"


def evaluate_candidate_publishability(
    candidates: list[ProviderCandidate],
    profile: DestinationProfile,
    *,
    required_count: int,
    allow_mock: bool = False,
) -> PublishabilityResult:
    required = max(1, int(required_count))
    if not profile.resolved:
        return PublishabilityResult([], "destination_unresolved", required, {"destination_unresolved": 1})

    accepted: list[ProviderCandidate] = []
    rejected: Counter[str] = Counter()
    for candidate in candidates:
        grounding = validate_candidate_destination(candidate, profile)
        candidate.extra["destination_grounding"] = grounding.to_dict()
        if not grounding.accepted:
            rejected[grounding.reason] += 1
            continue
        if not has_valid_coordinates(candidate):
            rejected["missing_geo"] += 1
            continue
        if candidate.source.lower().startswith("mock") and not allow_mock:
            rejected["mock_candidate"] += 1
            continue
        accepted.append(candidate)

    status = "ready" if len(accepted) >= required else "insufficient_candidates"
    return PublishabilityResult(accepted, status, required, dict(rejected))
```

Add `ALLOW_MOCK_PUBLISH: bool = False` to settings and document it as a test-only override in `.env.example`.

- [x] **Step 4: Run policy tests and related grounding tests**

Run: `cd llm_backend && ./.venv/bin/python -m pytest tests/test_candidate_publishability.py tests/test_destination_grounding.py -q`

Expected: all pass.

- [ ] **Step 5: Commit the independently tested boundary**

```bash
git add .env.example llm_backend/app/core/config.py llm_backend/app/services/candidate_publishability.py llm_backend/tests/test_candidate_publishability.py
git commit -m "Add shared candidate publishability policy"
```

### Task 2: Fail-closed Create Pipeline

**Files:**
- Modify: `llm_backend/app/lg_agent/travel_draft_graph.py:815-1061,1329-1358`
- Modify: `llm_backend/tests/test_draft_pipeline_integration.py:941-974`
- Modify: `llm_backend/tests/test_destination_grounding_graph.py`

**Interfaces:**
- Consumes: `evaluate_candidate_publishability()` from Task 1.
- Produces: `grounding_status="pipeline_error"` and a safe `grounding_exit_node` path.

- [ ] **Step 1: Change failure tests to require fail-closed behavior**

```python
assert result["grounding_status"] == "pipeline_error"
assert result["final_itinerary"] is None
assert result["final_text"]
assert llm.calls == 0
```

Add separate coverage for `_get_pipeline` failure and `recall_from_qp` failure. Preserve the test proving LLM template fallback works after a valid planner skeleton exists.

- [ ] **Step 2: Run focused graph tests and verify RED**

Run: `cd llm_backend && ./.venv/bin/python -m pytest tests/test_draft_pipeline_integration.py::TestPipelineFailureGraceful tests/test_destination_grounding_graph.py -q`

Expected: old tests fail because pipeline exceptions still call the LLM.

- [ ] **Step 3: Integrate publishability and pipeline-error routing**

Replace the inline coordinate filter with the shared policy. In the `except` block return `pipeline_result=None`, `grounding_status="pipeline_error"`, a safe message, and timing fields. Extend `_should_continue_after_recall()`:

```python
if state.get("grounding_status") in {
    "unresolved",
    "insufficient_candidates",
    "planner_infeasible",
    "pipeline_error",
}:
    return "grounding_exit_node"
```

- [ ] **Step 4: Run graph and API persistence tests**

Run: `cd llm_backend && ./.venv/bin/python -m pytest tests/test_draft_pipeline_integration.py tests/test_destination_grounding_graph.py tests/test_travel_m2_012_013.py -q`

Expected: all pass; failure cases emit no final itinerary and therefore cannot persist state.

- [ ] **Step 5: Commit fail-closed behavior**

```bash
git add llm_backend/app/lg_agent/travel_draft_graph.py llm_backend/tests/test_draft_pipeline_integration.py llm_backend/tests/test_destination_grounding_graph.py llm_backend/tests/test_travel_m2_012_013.py
git commit -m "Fail closed when candidate planning is unavailable"
```

### Task 3: Apply the Shared Gate to Local Replanning

**Files:**
- Modify: `llm_backend/app/services/day_replan_service.py:11-176`
- Modify: `llm_backend/tests/test_day_replan_service.py`
- Modify: `llm_backend/tests/test_travel_m2_012_013.py`

**Interfaces:**
- Consumes: `evaluate_candidate_publishability()` from Task 1.
- Produces: identical coordinate, destination, mock, and required-count semantics for create and replan.

- [ ] **Step 1: Add failing static and dynamic replan tests**

Cover one-slot and full-day replan for static coordinate-less candidates, disallowed mock candidates, cross-city candidates, and insufficient candidate sets. Assert `applied_days == []`, original day equality, and no revision persistence at API level.

- [ ] **Step 2: Run replan tests and verify RED**

Run: `cd llm_backend && ./.venv/bin/python -m pytest tests/test_day_replan_service.py tests/test_travel_m2_012_013.py -q`

Expected: static coordinate-less generic replan currently reaches the planner and fails the new assertion.

- [ ] **Step 3: Replace dynamic-only candidate checks**

Call the shared policy with `required_count=len(target_slots)` for generic replans and `required_count=1` for explicit POI edits. Apply conservative name matching after publishability. Record `insufficient_candidates` consistently for static and dynamic profiles.

```python
publishability = evaluate_candidate_publishability(
    recall_result.candidates,
    profile,
    required_count=required_count,
    allow_mock=settings.ALLOW_MOCK_PUBLISH,
)
recall_result.candidates = publishability.accepted
if not publishability.ready:
    report.grounding_statuses[day_index] = publishability.status
    continue
```

- [ ] **Step 4: Run local-replan and patch tests**

Run: `cd llm_backend && ./.venv/bin/python -m pytest tests/test_day_replan_service.py tests/test_patch_engine.py tests/test_travel_m2_012_013.py tests/test_explicit_poi_edit_eval.py -q`

Expected: all pass.

- [ ] **Step 5: Commit unified replan safety**

```bash
git add llm_backend/app/services/day_replan_service.py llm_backend/tests/test_day_replan_service.py llm_backend/tests/test_travel_m2_012_013.py
git commit -m "Unify local replan publishability gates"
```

### Task 4: Destination-aware Ranking Runtime Modes

**Files:**
- Modify: `llm_backend/app/core/config.py:56-63`
- Modify: `.env.example:43-53`
- Modify: `llm_backend/app/services/poi_ranking_policy.py`
- Modify: `llm_backend/app/lg_agent/travel_draft_graph.py:948-1028`
- Modify: `llm_backend/app/services/day_replan_service.py:145-167`
- Modify: `llm_backend/tests/test_poi_ranking_policy.py`
- Modify: `llm_backend/tests/test_draft_pipeline_integration.py`
- Modify: `llm_backend/tests/test_day_replan_service.py`

**Interfaces:**
- Consumes: accepted candidates and `DestinationProfile` from the shared publishability stage.
- Produces: `POI_RANKING_MODE: Literal["legacy", "shadow", "candidate"]` and `policy_ranked_to_scored()` for planner compatibility.

- [ ] **Step 1: Write failing mode and dynamic-profile tests**

Assert missing-geo hard rejection, dynamic-radius rejection, candidate-mode planner order, shadow-mode legacy order, and invalid mode configuration rejection.

```python
ranked = POIRankingPolicy().rank(
    candidates,
    destination_profile=profile,
    include_rejected=True,
)
assert ranked[0].accepted is False
assert "missing_geo" in ranked[0].reject_reasons
```

- [ ] **Step 2: Run ranking tests and verify RED**

Run: `cd llm_backend && ./.venv/bin/python -m pytest tests/test_poi_ranking_policy.py tests/test_draft_pipeline_integration.py -q`

Expected: missing profile argument, missing hard reject, and absent mode behavior fail.

- [ ] **Step 3: Implement profile-aware features and planner adapter**

Add `destination_profile` to `CandidateFeature.from_candidate()` and `POIRankingPolicy.rank()`. Use `validate_candidate_destination()` for distance validity. Reject `missing_geo`, destination mismatch, generic activity, duplicate, and disallowed mock candidates. Convert accepted policy results into existing `ScoredCandidate` objects so the planner interface remains unchanged.

- [ ] **Step 4: Add runtime mode selection**

Compute legacy and policy results once. Use legacy in `legacy` and `shadow`; use accepted policy results in `candidate`. Keep the comparison report in `shadow` and `candidate`. Apply the same selector in `DayReplanService`.

```python
legacy_ranked = scorer.rank_from_qp(recall_result.candidates, qp_output, top_k=15)
policy_ranked = POIRankingPolicy().rank(
    recall_result.candidates,
    destination_profile=profile,
    preferences=constraints.get("preferences"),
    budget=constraints.get("budget"),
    days=constraints.get("days"),
    top_k=15,
    include_rejected=True,
)
ranked = (
    policy_ranked_to_scored(policy_ranked)
    if settings.POI_RANKING_MODE == "candidate"
    else legacy_ranked
)
```

- [ ] **Step 5: Run ranking, graph, planner, and replan tests**

Run: `cd llm_backend && ./.venv/bin/python -m pytest tests/test_poi_ranking_policy.py tests/test_ranking_scorer.py tests/test_itinerary_planner.py tests/test_draft_pipeline_integration.py tests/test_day_replan_service.py -q`

Expected: all pass in the default `shadow` mode and explicit candidate-mode tests.

- [ ] **Step 6: Commit reversible runtime ranking**

```bash
git add .env.example llm_backend/app/core/config.py llm_backend/app/services/poi_ranking_policy.py llm_backend/app/lg_agent/travel_draft_graph.py llm_backend/app/services/day_replan_service.py llm_backend/tests/test_poi_ranking_policy.py llm_backend/tests/test_draft_pipeline_integration.py llm_backend/tests/test_day_replan_service.py
git commit -m "Add reversible candidate ranking runtime"
```

### Task 5: Expand Ranking Evaluation and Guardrails

**Files:**
- Modify: `llm_backend/evaluation/ranking_eval_cases.json`
- Modify: `llm_backend/scripts/ranking_eval_report.py`
- Modify: `llm_backend/tests/test_ranking_eval_report.py`

**Interfaces:**
- Consumes: legacy and candidate ranking outputs from Task 4.
- Produces: at least 20 deterministic cases across at least 10 destinations plus quality and latency summaries.

- [ ] **Step 1: Add failing report-contract tests**

```python
assert report["case_count"] >= 20
assert report["summary"]["destination_count"] >= 10
assert report["summary"]["unsafe_accepted_count"] == 0
assert report["summary"]["policy_good_hit_rate"] >= report["summary"]["legacy_good_hit_rate"]
assert report["summary"]["ranking_latency_p95_ms"] < 50
```

- [ ] **Step 2: Run evaluation tests and verify RED**

Run: `cd llm_backend && ./.venv/bin/python -m pytest tests/test_ranking_eval_report.py -q`

Expected: existing two-case report lacks the required fields and thresholds.

- [ ] **Step 3: Expand the deterministic matrix**

Add cases for Shenzhen, Hong Kong, Macau, Tokyo, Kyoto, San Francisco, Jingdezhen, Dunhuang, Kashgar, Tromso, Hobart, Oaxaca, plus the existing Phuket and Shanghai cases. Across the matrix include cross-city decoys, invalid/missing coordinates, duplicate provider results, generic Chinese/English activities, weak evidence, budget conflict, preference match, provider confidence, reviewed alias, dynamic profiles, mock-only candidates, and candidate shortage.

- [ ] **Step 4: Add comparative and latency metrics**

Measure each policy call with `time.perf_counter()`. Report legacy/policy good-hit rates, unsafe accepted count, evidence coverage, duplicate/generic reject counts, destination count, and ranking P50/P95.

```python
started = time.perf_counter()
policy_ranked = policy.rank(
    candidates,
    destination_profile=profile,
    preferences=preferences,
    budget=budget,
    days=days,
    top_k=max(len(candidates), top_k),
    include_rejected=True,
)
latency_ms = (time.perf_counter() - started) * 1000

latencies = sorted(case.policy_latency_ms for case in results)
summary["ranking_latency_p50_ms"] = percentile(latencies, 0.50)
summary["ranking_latency_p95_ms"] = percentile(latencies, 0.95)
```

- [ ] **Step 5: Run evaluator and inspect generated report**

Run: `cd llm_backend && ./.venv/bin/python -m scripts.ranking_eval_report --output-dir reports/ranking-eval/candidate-runtime-v1`

Expected: status passed, at least 20 cases, at least 10 destinations, zero unsafe accepts, non-regressing Top-K, and P95 below 50 ms.

- [ ] **Step 6: Commit the expanded gate**

```bash
git add llm_backend/evaluation/ranking_eval_cases.json llm_backend/scripts/ranking_eval_report.py llm_backend/tests/test_ranking_eval_report.py
git commit -m "Expand candidate ranking evaluation gate"
```

### Task 6: Integration Gate, Documentation, and Final Verification

**Files:**
- Modify: `llm_backend/scripts/milestone_runner.py`
- Modify: `llm_backend/tests/test_milestone_runner.py`
- Modify: `docs/travelmind_core_integration_gate.md`
- Modify: `docs/travelmind_quality_loop_v1.md`
- Modify: `docs/performance-analysis-report.md`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: one repeatable local milestone and one budget-controlled live-provider verification command.

- [ ] **Step 1: Add failing milestone assertions**

Require the ranking gate summary to include case count, destination count, unsafe accepts, candidate-vs-legacy hit rates, and P95.

- [ ] **Step 2: Update runner and project documentation**

Document fail-closed semantics, shared create/replan policy, ranking modes, rollback configuration, expanded evaluation, and the distinction between offline safety and live provider readiness.

- [ ] **Step 3: Run focused backend verification**

Run: `cd llm_backend && ./.venv/bin/python -m pytest tests/test_candidate_publishability.py tests/test_destination_grounding_graph.py tests/test_day_replan_service.py tests/test_poi_ranking_policy.py tests/test_ranking_eval_report.py tests/test_milestone_runner.py -q`

Expected: all pass.

- [ ] **Step 4: Run the full backend suite**

Run: `cd llm_backend && ./.venv/bin/python -m pytest tests -q`

Expected: all tests pass with only the existing optional skips.

- [ ] **Step 5: Run the 13-gate project milestone**

Run: `cd llm_backend && ./.venv/bin/python -m scripts.milestone_runner --run-id candidate-decision-runtime-v1-final`

Expected: `status=passed`, all configured gates pass, frontend type-check and build pass.

- [ ] **Step 6: Run a budget-controlled real-provider probe**

Run domestic and overseas cases with Mock and LLM disabled through `scripts.live_destination_grounding_probe --allow-live`. The report must expose provider capabilities and classify every city as `healthy`, `degraded`, or `not_ready`; no unsafe itinerary is generated.

- [ ] **Step 7: Review diff and commit integration updates**

```bash
git diff --check
git add llm_backend/scripts/milestone_runner.py llm_backend/tests/test_milestone_runner.py docs/travelmind_core_integration_gate.md docs/travelmind_quality_loop_v1.md docs/performance-analysis-report.md
git commit -m "Complete agentic candidate decision runtime v1"
```
