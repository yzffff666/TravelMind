# Explicit POI Edit Resolution v1

## Problem

The generic local-replan path correctly turns requests such as `把第二天下午改成室内` into a candidate-driven plan. It is unsafe for a different class of request:

```text
把第二天下午换成上海博物馆
```

`博物馆` used to be recognized as an `indoor` keyword, so the system could select any indoor candidate. Other named requests could fall through to `REPLACE_SLOT` and write the user's raw text into an itinerary with no evidence or location.

## Decision

TravelMind now distinguishes a **generic constraint** from a **literal POI request** before planning:

```text
generic constraint
  "改成室内博物馆"
  -> constraint replan (indoor)

explicit POI
  "换成上海博物馆"
  -> named-place replan (explicit_place="上海博物馆")
  -> provider recall + destination grounding + conservative title match
  -> replace only the requested slot, or do not create a revision
```

The `rule_explicit_poi` path has priority over a safe Structured QP result. This is not a return to raw rules as the final decision: the rule only preserves the literal user constraint. `DayReplanService` still owns provider recall, geographic grounding, ranking, planner payload construction, evidence, and the publish/no-publish decision.

## Runtime Contract

For a bounded request with a day and slot:

1. `PatchEngine` produces `REPLAN_DAY` with `explicit_place`, `target_day`, and `target_slot`; it does not mutate the slot.
2. `DayReplanService` searches `destination + explicit_place`.
3. Provider candidates first pass the existing destination profile / bbox gate.
4. Only candidates with valid coordinates and an exact or containment-level normalized title match remain.
5. The shared planner produces one evidence-bearing slot payload.
6. API emits `edit_diff` and `final_itinerary` only when the requested day was applied and then persists the new revision.

If the name cannot be verified, the candidate belongs to another city, the provider fails, or the user omitted the slot, the API emits `final_text` and leaves the prior revision unchanged.

## Technology Choices

### Why a deterministic name matcher now?

This is an execution safety boundary, not an open-ended relevance problem. The question is not whether a POI is semantically similar to a museum; it is whether it is the place the user explicitly named. Normalized equality and containment are explainable, cheap, and fail closed. `Shanghai Museum` must not resolve to `Shanghai Contemporary Art Museum` merely because both contain similar tokens.

### Why not use DeepSeek or embedding similarity for the match?

An LLM judge or embedding score can improve alias recall later, but it makes the current side-effect boundary slower and harder to audit. More importantly, semantic similarity tends to prefer related places, exactly the failure mode this path prevents. It would also add another online dependency to an edit flow that already calls providers.

### Why no city-specific alias table?

The existing backfill service contains a small Phuket alias set because it was built around historical geocoding badcases. Reusing that approach here would make user-command correctness depend on a finite hand-maintained city list. v1 intentionally supports generic normalized title variants only. Ambiguous aliases fail safely and should later be handled through provider canonical IDs or reviewed alias data, not a growing list of local strings.

### Why preserve generic rule replan?

`室内` and `轻松` are not POI names. They need candidate diversity, ranking, and constraint-aware planning. Combining generic preferences and literal names in one score would make a hard user constraint look like a soft ranking feature. The split gives each request an appropriate policy.

## Acceptance Gate

```bash
cd llm_backend
./.venv/bin/python -m scripts.explicit_poi_edit_eval
```

The v1 fixture contains 16 Chinese and English cases:

- named POIs including museums, landmarks, and a cross-city request;
- generic indoor and relaxed replans;
- no-slot clarification cases;
- QA and out-of-range day cases that must create no edit command.

Required result:

```text
16/16 passed
explicit_cases >= 7
unsafe_revision_failures=0
```

Service/API tests additionally cover title confusion, cross-city rejection, Structured QP precedence, target-slot-only mutation, and no persistence after verification failure.

## Next Data Step

This is deliberately not a trained matching model. Collect reviewed edit outcomes first: requested text, normalized explicit place, provider candidates, title-match score, destination-grounding outcome, final apply/no-commit result, and user correction. Once the project has diverse human-reviewed alias and confusion cases, the matcher can evolve into a learned alias/retrieval component without weakening the current no-commit guarantee.
