# Four-Scenario Demo Journey Reliability Gate

## 1. Goal

Close the gap between TravelMind's individually passing subsystem gates and a
repeatable, user-visible journey-level acceptance result.

The new gate must prove that the existing conversation, candidate, ranking,
planning, revision, and SSE contracts compose correctly across four complete
travel journeys:

1. domestic long-tail destination;
2. unseen overseas destination;
3. destination switch followed by two consecutive local edits; and
4. insufficient candidates with safe degradation.

The deterministic gate runs every journey twice from a fresh state. Project
acceptance requires `8/8` journey runs to pass.

## 2. Why This Is The Next Milestone

Before this milestone, the 16-gate suite already verified:

- 48 multi-turn transcripts and 144 turns;
- destination grounding and cross-city rejection;
- production candidate ranking selection, with learned ranking kept in its
  rollout-safe default-off mode;
- constraint-aware planning;
- structured and explicit-POI local edits;
- SSE component contracts; and
- frontend tests, type checking, and production build.

Those gates mostly verify one subsystem or one request at a time. They do not
prove that a complete sequence keeps one coherent state while several
subsystems run in order.

This milestone therefore adds composition evidence rather than another model,
another city-specific rule, or a larger isolated test set.

## 3. Scope

### 3.1 Automated deterministic boundary

The automated journey runner uses production:

- `TravelQueryProcessor`;
- `ConversationDecisionService` and `apply_transition`;
- destination profiles and publishability checks;
- `RankingScorer`, `POIRankingPolicy`, and the learned-ranking rollout/fallback
  selector in default-off mode;
- `ConstraintAwareItineraryPlanner`;
- revision lineage rules; and
- SSE envelope builders.

It uses checked-in, sanitized candidate snapshots and an in-memory conversation
state. It does not call MySQL, DeepSeek, Amap, Geoapify, or SerpAPI.

### 3.2 Existing project-level boundary

The default milestone continues to run:

- backend integration tests;
- frontend chat component tests;
- frontend type checking; and
- frontend production build.

Together, the journey gate and the existing frontend gates cover the stable
backend decision/SSE contract consumed by the UI.

### 3.3 Live evidence boundary

Live Provider and browser runs remain explicit probes:

- one budget-controlled real Provider probe is sufficient;
- live failures are reported separately from deterministic CI;
- cached or sanitized responses may be retained as replay evidence; and
- no secret, raw API key, or unredacted provider URL may enter artifacts.

The deterministic gate must not claim to be browser automation, database
integration, or a live Provider benchmark.

## 4. Scenario Contract

### 4.1 Domestic long-tail

Destination: `景德镇`.

Flow:

```text
create 3-day itinerary
-> ask about day 2
-> replan day 2 as indoor/cultural
```

Required:

- the destination remains `景德镇`;
- all published POIs have local coordinates;
- QA does not change revision;
- the edit changes only day 2; and
- the edit creates a child revision.

### 4.2 Overseas unseen city

Destination: `Tromso`.

Flow:

```text
create 2-day itinerary
-> ask about the second day
-> replace the second afternoon with an indoor/cultural candidate
```

Required:

- no Tokyo, Kyoto, Paris, Shanghai, or Mock candidate is published;
- all selected POIs have coordinates and evidence;
- image/evidence coverage remains visible in the report;
- QA is read-only; and
- the local edit changes only the requested target.

### 4.3 Destination switch and consecutive edits

Flow:

```text
create Shenzhen itinerary
-> switch to Hong Kong
-> create Hong Kong itinerary
-> edit day 1
-> edit day 2 afternoon
```

Required:

- switching clears the Shenzhen itinerary and revision before Hong Kong create;
- the new itinerary contains no Shenzhen POI;
- edit 2 uses the revision created by edit 1;
- non-target days/slots remain unchanged; and
- final state remains Hong Kong.

### 4.4 Insufficient candidates

Destination: `Oaxaca`.

Flow:

```text
request 3-day itinerary
-> resolve destination
-> receive only two publishable local candidates
-> fail planning safely
```

Required:

- no `final_itinerary` event is emitted;
- a terminal `quality_warning` or `final_text` event is emitted;
- no Mock or cross-city candidate is published;
- no revision is created; and
- the failure trace identifies `insufficient_candidates`.

## 5. Data Contract

`evaluation/demo_journey_cases.json` contains exactly four scenarios. Each case
contains:

```json
{
  "case_id": "domestic_long_tail_jingdezhen",
  "category": "domestic_long_tail",
  "destination": "景德镇",
  "country": "中国",
  "center": [29.2687, 117.1784],
  "days": 3,
  "budget": 6000,
  "turns": [],
  "candidates": [],
  "edit_candidates": []
}
```

Candidate rows contain an ID, title, source, city, coordinates, tags, evidence,
image, rating, estimated cost, and role (`local`, `cross_city`, or `mock`).

The runner rejects missing IDs, duplicate IDs, unexpected categories, fewer or
more than four cases, and missing required turn roles.

## 6. Runner Architecture

`scripts/demo_journey_eval.py` owns only evaluation orchestration:

```text
fixture
-> raw natural-language turn
-> real QP
-> conversation decision and transition
-> candidate publishability
-> production rank selection (learned mode off)
-> constraint planner
-> itinerary/revision update
-> real SSE envelope construction
-> semantic assertions and trace
```

The runner exposes:

```python
load_cases(path: Path) -> list[dict[str, Any]]
validate_case_contract(cases: list[dict[str, Any]]) -> list[str]
evaluate_cases(cases: list[dict[str, Any]], *, repetitions: int = 2) -> dict[str, Any]
is_passing(report: dict[str, Any]) -> bool
write_outputs(report: dict[str, Any], output_dir: Path) -> None
```

Every turn records:

- raw query;
- QP output;
- conversation decision;
- state before and after;
- candidate accept/reject decisions;
- selected POIs;
- planner result;
- SSE event names;
- revision before and after; and
- assertion failures.

## 7. Safety Metrics

The report contains:

```text
journey_runs
passed_journey_runs
failed_journey_runs
turn_count
qa_revision_mutations
wrong_edit_targets
non_target_mutations
stale_destination_candidates
cross_city_published
mock_published
unsafe_final_itinerary_on_degrade
missing_terminal_events
revision_lineage_failures
```

## 8. Acceptance Criteria

```text
scenario definitions                         = 4
repetitions                                  = 2
journey runs                                 = 8
passed journey runs                          = 8
QA revision mutations                        = 0
wrong edit targets                           = 0
non-target mutations                         = 0
stale destination candidates                 = 0
cross-city candidates published              = 0
Mock candidates published                    = 0
unsafe final itinerary on degradation        = 0
missing terminal SSE events                  = 0
revision lineage failures                    = 0
```

The default project milestone fails if any criterion is violated.

## 9. Artifacts

Each run writes:

```text
reports/demo-journey-eval/<run>/
├── demo-journey-eval.json
└── demo-journey-eval.md
```

The JSON report is the machine-readable gate input. The Markdown report is the
project/demo evidence and includes per-scenario turn traces and failures.

## 10. Non-Goals

This milestone does not:

- introduce a new ranking model;
- add destination-specific production bbox, alias, or POI whitelists;
- refactor the full FastAPI route or persistence layer;
- perform browser automation in CI;
- consume live Provider quota on every test run;
- guarantee support for every city; or
- complete the final project report.

## 11. Stop Condition

Stop implementation when:

- the new deterministic gate passes `8/8`;
- the complete project milestone passes with the new gate included;
- the backend test suite remains green;
- the frontend test/type/build gates remain green; and
- documentation clearly separates deterministic, frontend, and live evidence.
