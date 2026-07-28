# TravelMind v1 Final Delivery Goal

## 1. Status And Authority

This document defines the single final delivery goal for TravelMind v1.

Earlier milestone documents remain useful as implementation history and subsystem
contracts, but they do not independently define project completion. TravelMind v1
is complete only when the end-to-end acceptance criteria in this document pass.

## 2. Final Goal

Build TravelMind v1 as a stable, generalizable, explainable, and debuggable travel
planning agent.

The system must:

- preserve the user's active travel goal across multi-turn conversation;
- distinguish creation, itinerary QA, local edit, destination change, casual chat,
  clarification, and reset without unintended itinerary mutation;
- retrieve real POI candidates for previously unseen domestic and overseas
  destinations without adding destination-specific production code;
- apply deterministic safety gates before a lightweight learned ranker orders
  eligible candidates;
- construct a feasible itinerary through constraint-aware planning;
- support consecutive local replanning against the latest revision;
- fail safely when evidence or candidates are insufficient; and
- produce replayable decision traces that identify which layer caused a failure.

In one line:

```text
TravelMind v1 = reliable multi-turn state control
              + open-world POI retrieval
              + safe hybrid candidate ranking
              + constraint-aware planning
              + replayable local replanning
```

## 3. Problem Statement

A travel agent can appear functional while still being unreliable in ordinary
conversation. Common failures include:

- repeatedly asking the same clarification after the user answers with a flexible
  preference such as "都可以";
- treating an itinerary question as an edit and mutating stored state;
- writing an edit request directly into an itinerary slot instead of replanning;
- losing the active trip after unrelated conversation;
- interpreting any mention of another city as a destination switch;
- retaining POIs from the old destination after an explicit switch;
- producing plausible but ungrounded POIs when providers return weak results; and
- passing deterministic fixtures while failing on real unseen destinations.

The project therefore treats conversational stability as the first observable
quality boundary. Retrieval, ranking, planning, and model training only add value
after the agent can preserve and intentionally transition its goal state.

## 4. End-To-End Architecture

```text
user turn
  -> conversation decision
       intent
       confidence
       extracted constraints
       mutation scope
       state transition reason
  -> conversation state transition
       active goal
       destination
       trip constraints
       pending clarification
       current revision
  -> dynamic destination grounding
  -> destination-aware provider routing
  -> real POI candidate recall
  -> deterministic hard gate
  -> lightweight learned ranker
  -> constraint-aware planner
  -> LLM expression over a verified plan
  -> SSE response and revision persistence
  -> decision trace and replay artifact
```

### 4.1 Conversation Decision Layer

The routing result is a structured decision, not only an intent label:

```json
{
  "intent": "change_destination",
  "confidence": 0.93,
  "destination": "杭州",
  "mutation_scope": "whole_trip",
  "preserve_constraints": ["days", "budget", "preferences"],
  "clear_fields": ["itinerary", "poi_candidates"],
  "reason": "explicit destination replacement"
}
```

Required intents:

```text
create
clarify
qa
edit
change_destination
chat
reset
```

Required mutation scopes:

```text
none
constraints_only
single_slot
single_day
whole_trip
reset_all
```

Rules may handle high-confidence and safety-critical patterns. Ambiguous turns may
use Structured QP or another model-backed classifier. A deterministic state guard
must validate whether the predicted intent is allowed to mutate the itinerary.

### 4.2 Conversation State

The authoritative conversation state contains:

- active travel goal;
- destination profile;
- days, budget, pace, interests, and other portable constraints;
- pending clarification and fields already asked;
- current itinerary and revision lineage;
- latest routing decision;
- allowed mutation scope; and
- state transition reason.

QA and casual chat are read-only. An explicit destination change clears
destination-dependent POIs and itinerary state while preserving portable
constraints when appropriate. A local edit creates a new revision only after
replanning succeeds.

### 4.3 Open-World Candidate Supply

Support for a new destination must come from destination resolution, provider
metadata, and a provider-neutral POI category/query layer. It must not require a
new entry in a static bbox table, destination alias table, or POI whitelist.

Expected behavior:

- dynamically resolve canonical destination, country, administrative hierarchy,
  center, and search radius;
- route domestic and overseas requests to suitable providers;
- use geocoding for destination or named-POI resolution and a places/search API
  for category POI recall;
- normalize locality, district, suburb, city, and administrative-area metadata;
- align recall radius and publication radius; and
- return an explicit not-ready result when real candidates are insufficient.

Existing static bbox and reviewed alias entries may remain as compatibility
fast paths. They must not be required for unseen-destination correctness, and the
final holdout destinations must not receive new production entries.

### 4.4 Hybrid Candidate Ranking

Candidate selection has two layers.

Deterministic hard gates reject:

- unresolved or mismatched destinations;
- missing or invalid coordinates;
- disallowed Mock candidates;
- generic activities without a concrete POI;
- duplicates; and
- candidates that violate required publication constraints.

A lightweight learned ranker orders candidates that survive the hard gates. Its
features may include:

- semantic preference match;
- category match;
- evidence quality;
- provider confidence;
- destination distance;
- budget match;
- pace or indoor/outdoor compatibility; and
- reviewed name-resolution signals.

The first learned implementation should remain small and reproducible, such as a
LambdaMART/LightGBM ranker or another lightweight pairwise ranker. A model failure
must fall back to the deterministic rule score. The model must never bypass the
hard gates.

### 4.5 Constraint-Aware Planning And Replanning

Planning happens over verified ranked candidates before the LLM writes prose.
Required constraints include:

- no duplicate POI;
- destination consistency;
- daily slot capacity;
- budget;
- pace;
- indoor requirement;
- bounded travel distance; and
- preservation of non-target days during local replanning.

The following turns must remain behaviorally distinct:

```text
"第三天下午去哪里"         -> read-only QA
"把第三天下午改成室内"     -> single-slot local replan
"第三天去迪士尼"           -> explicit POI local replan
"还是改去杭州吧"           -> whole-trip destination change
"深圳到香港怎么走"         -> QA, not destination change
```

## 5. Debugging And Regression Loop

Every user turn must produce enough structured trace data to replay the decision:

```text
raw input
  -> extracted destination and constraints
  -> rule and model observations
  -> final intent and confidence
  -> mutation scope
  -> state before
  -> state after
  -> revision mutation
  -> provider route
  -> candidate decisions
  -> planner result
  -> response/fallback reason
```

The required debugging loop is:

```text
failed conversation
  -> replay decision trace
  -> classify failure layer
  -> fix the general mechanism
  -> promote the failure to a regression case
  -> rerun multi-turn and core integration gates
```

Failure categories must at least distinguish:

- intent classification;
- slot or constraint extraction;
- state transition;
- clarification loop;
- destination resolution;
- provider routing or recall;
- candidate grounding;
- ranking;
- planner feasibility;
- patch/revision persistence; and
- frontend/SSE presentation.

## 6. Final Acceptance Criteria

TravelMind v1 is complete only when every section below passes.

### 6.1 Multi-Turn Stability Gate

Maintain 40 to 50 complete conversation transcripts, each with 3 to 6 turns,
covering:

- normal creation and constraint completion;
- flexible answers such as "都可以";
- explicit destination changes;
- references to another city that must not switch the destination;
- read-only itinerary QA;
- consecutive local edits;
- casual chat followed by continued planning;
- reset and new-trip creation; and
- malformed or ambiguous input.

Pass criteria:

```text
critical conversation cases              = 100%
overall conversation pass rate           >= 95%
QA/chat unintended itinerary mutations   = 0
false destination switches               = 0
explicit destination switch success      = 100%
consecutive local-edit target accuracy   = 100%
repeated clarification loops             = 0
old-destination POIs after a switch       = 0
```

Critical cases are the transcripts that exercise read-only QA, explicit
destination change, false-switch prevention, consecutive local edits,
clarification-loop prevention, and removal of stale POIs after a destination
change. Every transcript in these categories must pass.

Implementation status (2026-07-28): complete. The checked-in v2 corpus contains
48 transcripts and 144 turns across eight balanced categories. Normal turns start
from raw natural-language queries and execute the production rule QP, conversation
decision service, and state transition; clarification turns execute the production
clarification service. The current acceptance result is 48/48 transcripts,
144/144 turns, 100% critical-category pass rate, with all six state-safety
counters at zero.

### 6.2 Open-World Destination Gate

Maintain an eight-destination holdout set with four domestic and four overseas
destinations. Holdout destinations must not receive production bbox, alias, or
POI whitelist entries.

Pass criteria:

```text
resolved holdout profiles                 >= 6/8
ready destinations                        >= 6/8
real publishable POIs per ready city      >= 3
published cross-city candidates           = 0
published Mock candidates                 = 0
unsafe LLM generation after not-ready     = 0
```

At least one budget-controlled real-provider run must be retained as evidence.
Sanitized real-provider snapshots may be used for repeatable testing and live-demo
fallback, but they are evaluation assets and cannot alter production policy.

### 6.3 Learned Ranking Gate

Build a small ranking dataset with:

```text
query-candidate samples                    500 to 800
travel requests                            >= 40
destinations                               >= 10
train/test destination overlap             = 0
```

Labels use a small relevance scale such as:

```text
0 = unsafe or irrelevant
1 = usable
2 = strongly relevant
```

Pass criteria:

```text
learned NDCG@5                             >= rule baseline
preference-sensitive Top-3 hit rate        >= rule baseline + 5 percentage points
unsafe candidates after hard gate          = 0
ranking inference P95                      < 100 ms
model-load/inference fallback tests        pass
```

This is an engineering acceptance comparison, not a claim of novel ranking
research.

Implementation evidence uses a transparent `curated_rubric_v1` benchmark with
576 rows, 48 requests, and 12 destinations split by destination into
8 train / 2 validation / 2 test. The NumPy pairwise linear ranker is disabled
by default, supports shadow/active rollout, and falls back to deterministic rule
ranking when its artifact is unavailable or incompatible. These offline
rubric results establish the engineering pipeline, not open-world city
generalization: destinations share a compact POI archetype template, feature
values are curated, and the results are not presented as online user-behavior
gains. The gate binds catalog, generated dataset, split provenance, and model
training fingerprint to prevent stale artifacts or train/test leakage.

### 6.4 Existing Regression And Demo Gate

- The current 17-gate core integration milestone remains green.
- Training, model loading, fallback, state transition, and replay have focused
  automated tests.
- Four end-to-end demonstrations run without manual database repair:
  - domestic long-tail destination;
  - overseas destination;
  - destination change followed by two consecutive local edits;
  - insufficient candidates with safe degradation and trace inspection.
- No API key or secret is present in Git history added by this work.
- README documents setup, training, evaluation, and demo commands.

Implementation status (2026-07-28): the deterministic four-scenario journey
gate is complete. Jingdezhen, Tromso, Shenzhen-to-Hong-Kong with consecutive
edits, and Oaxaca safe degradation run twice for `8/8` passing journey runs and
24 turns. The gate composes production QP, conversation transitions, candidate
publishability, ranking selection, constraint planning, revision lineage, and
SSE envelopes with all nine safety counters at zero. Live Provider/browser
evidence and the final README/report remain outstanding and are not implied by
this deterministic result.

## 7. Deliverables

The final project contains:

1. a runnable Vue/FastAPI/SSE application;
2. an explicit conversation decision and state-transition layer;
3. multi-turn transcript evaluation and replay tooling;
4. open-world destination resolution and provider routing;
5. a deterministic candidate safety gate;
6. a small ranking dataset and dataset manifest;
7. a reproducible lightweight ranker training pipeline and model artifact;
8. constraint-aware planning and revision-safe local replanning;
9. automated acceptance reports; and
10. a final project report covering architecture, difficult cases, implementation,
    limitations, and demonstration instructions.

## 8. Scope Boundaries

The final project does not require:

- fine-tuning a large language model;
- a two-tower recommender or large neural ranking model;
- CTR/CVR prediction or large-scale user behavior modeling;
- support for every city in the world;
- publication-quality algorithmic novelty;
- a broad GraphRAG or multi-agent expansion;
- a complete frontend redesign; or
- unrelated refactoring of every large backend module.

New functionality is accepted only when it advances the final end-to-end goal or
removes a blocker to its acceptance gates.

The implementation is scoped for approximately two to three focused weeks. If
scope pressure appears, reduce model complexity and presentation polish before
weakening conversation correctness, destination safety, or replayability.

## 9. Stop Condition

Once all final acceptance criteria pass, TravelMind v1 feature development stops.
The remaining work is limited to:

- final report writing;
- demonstration recording;
- architecture and result diagrams;
- installation verification; and
- presentation preparation.

Passing one subsystem milestone, adding a model, or fixing several visible cases
does not by itself complete the project.
