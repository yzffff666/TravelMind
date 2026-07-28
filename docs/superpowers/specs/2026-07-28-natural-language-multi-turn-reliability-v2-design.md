# Natural-Language Multi-Turn Reliability v2

## 1. Goal

Close the TravelMind v1 multi-turn stability gate with a deterministic,
natural-language-driven replay corpus.

The evaluator must send each user utterance through the real rule
`TravelQueryProcessor`, then through `ConversationDecisionService` and
`apply_transition`. Test fixtures may describe expected behavior and successful
revision commits, but they must not provide a precomputed QP intent or extracted
constraints.

This milestone validates conversation understanding and state safety. It does
not validate live Providers, learned ranking quality, LLM prose quality, or
frontend presentation.

## 2. Why This Is The Next Milestone

The existing 24-case corpus primarily validates state transitions after a QP
result has already been supplied by the fixture. That proves the transition
layer, but it can miss the user-visible failure where a natural-language query
is classified incorrectly before it reaches that layer.

TravelMind already has green subsystem gates for retrieval, ranking, planning,
replanning, and frontend buildability. Adding more features before the
conversation boundary is exercised end to end would increase complexity without
proving that ordinary multi-turn use is stable.

## 3. Scope

The v2 corpus contains exactly 48 transcripts and at least 144 turns:

```text
destination_switch              6
destination_mention_readonly     6
qa_readonly                      6
flexible_clarification           6
chat_goal_retention              6
consecutive_local_edit           6
reset_recovery                   6
malformed_ambiguous              6
```

Every transcript contains 3 to 6 user turns. Chinese and English cases are both
required. Cases must include direct requests, polite paraphrases, short
follow-ups, and ambiguous wording.

The corpus remains checked in as JSON so failures are reviewable and replayable.

## 4. Evaluation Pipeline

Normal turns use:

```text
raw query
  -> TravelQueryProcessor.process(query)
  -> ConversationDecisionService.decide(query, qp_output, state_before)
  -> apply_transition(state_before, decision)
  -> optional simulated successful revision commit
  -> expected decision/state comparison
```

Clarification turns use the production `TravelClarificationService` start and
continue APIs because clarification state is owned by that service.

The evaluator records, for every turn:

- raw query;
- normalized QP output;
- final conversation decision;
- state before and after;
- revision mutation;
- expectation mismatches; and
- failure category.

This makes a failed transcript useful for debugging instead of returning only a
pass/fail number.

## 5. Fixture Contract

A normal turn has this shape:

```json
{
  "query": "第三天下午去哪里？",
  "expected": {
    "intent": "qa",
    "mutation_scope": "none",
    "target_day": 3,
    "target_slot": "下午",
    "revision_after": "rev-1"
  }
}
```

A successful edit may declare the revision produced by the downstream planner:

```json
{
  "query": "把第二天下午改成室内活动",
  "commit_revision_id": "rev-2",
  "expected": {
    "intent": "edit",
    "mutation_scope": "single_slot",
    "revision_before": "rev-1",
    "revision_after": "rev-2"
  }
}
```

The `commit_revision_id` is not an intent hint. It simulates the successful
planner/persistence result after routing has already completed.

Existing `qp` fixture fields are forbidden in v2.

## 6. Safety Metrics

The report must expose:

```text
case_count
turn_count
passed_cases
failed_cases
failed_turns
overall_case_pass_rate
critical_case_pass_rate
qa_chat_unintended_mutations
false_destination_switches
explicit_destination_switch_failures
stale_itinerary_after_switch
consecutive_edit_target_failures
repeated_clarification_loops
```

Critical categories are:

- `destination_switch`;
- `destination_mention_readonly`;
- `qa_readonly`;
- `flexible_clarification`;
- `consecutive_local_edit`; and
- `reset_recovery`.

## 7. Acceptance Criteria

```text
transcripts                              = 48
turns                                    >= 144
turns per transcript                     = 3 to 6
overall case pass rate                   >= 95%
critical case pass rate                  = 100%
QA/chat unintended mutations             = 0
false destination switches               = 0
explicit destination switch failures     = 0
stale itinerary after switch             = 0
consecutive edit target failures         = 0
repeated clarification loops             = 0
```

The default project milestone must fail if any structural or behavioral
criterion is violated.

## 8. Debugging Rule

When a case fails:

1. identify whether the failure came from extraction, intent classification,
   conversation decision, clarification state, or transition state;
2. fix the general mechanism rather than adding a case-specific full-query
   equality check;
3. keep the failing transcript in the corpus;
4. add a focused unit test for the mechanism when the corpus alone would not
   localize the regression; and
5. rerun the focused evaluator and the full 16-gate milestone.

## 9. Non-Goals

This milestone does not:

- call DeepSeek in CI;
- call Amap, Geoapify, or SerpAPI;
- expand the learned-ranking rubric;
- test POI factual quality;
- redesign the frontend;
- produce the four final live demonstrations; or
- write the final graduation report.

Those remain separate delivery phases after the multi-turn gate is trustworthy.

