# Multi-Turn Conversation Stability v1 Design

## 1. Goal

Deliver one closed-loop milestone that makes TravelMind's multi-turn behavior
predictable, state-safe, and replayable.

The milestone is complete only when:

- 24 deterministic multi-turn transcripts pass;
- four API-level critical flows pass;
- QA and chat cannot mutate an itinerary;
- explicit destination changes are distinguished from ordinary city mentions;
- flexible clarification answers cannot create a repeated-question loop;
- consecutive edits are based on the latest revision;
- pending clarification survives service-object recreation through persisted
  dialogue state;
- every turn emits a replayable conversation-transition trace; and
- the existing 13/13 core integration milestone remains green.

## 2. Current Gaps

The current runtime has several independent mechanisms but no conversation-level
decision contract:

- `TravelQueryProcessor` emits only `create`, `edit`, `qa`, `reset`, and `chat`.
- Destination replacement is not represented as a distinct state transition.
- `TravelClarificationService` stores pending state only in process memory.
- `TravelConversationState` persists itinerary and chat history but not
  clarification or routing state.
- Route handlers infer mutation permissions from intent branches rather than from
  an explicit mutation scope.
- Existing QP and golden cases are primarily single-turn fixtures.

Adding more intent regexes inside `travel.py` would not solve these boundaries.
The new design adds a small domain layer between QP and route execution.

## 3. Architecture

```text
raw user turn
  -> TravelQueryProcessor
  -> ConversationDecisionService
       utterance intent
       active itinerary context
       explicit destination-switch signal
       target day/slot
       mutation permission
  -> ConversationTransitionPolicy
       validate transition
       derive preserved/cleared state
  -> route action
       read-only QA/chat
       local edit
       destination re-create
       reset
       clarification
  -> commit operation result
  -> persist dialogue state
  -> structured conversation_transition trace
```

QP remains responsible for utterance-level extraction. The conversation decision
layer is responsible for interpreting that result against current state.

## 4. Domain Contracts

Create `app/domain/travel/conversation_runtime.py`.

### 4.1 Conversation Decision

```python
ConversationIntent = Literal[
    "create",
    "clarify",
    "qa",
    "edit",
    "change_destination",
    "chat",
    "reset",
]

MutationScope = Literal[
    "none",
    "constraints_only",
    "single_slot",
    "single_day",
    "whole_trip",
    "reset_all",
]

class ConversationDecision(BaseModel):
    intent: ConversationIntent
    intent_detail: str
    confidence: float | None = None
    destination: str | None = None
    target_day: int | None = None
    target_slot: str | None = None
    mutation_scope: MutationScope
    preserve_fields: list[str] = Field(default_factory=list)
    clear_fields: list[str] = Field(default_factory=list)
    reason: str
```

### 4.2 Runtime Snapshot

```python
class ConversationRuntimeSnapshot(BaseModel):
    conversation_id: str
    active_destination: str | None = None
    trip_profile: dict[str, Any] = Field(default_factory=dict)
    current_itinerary: dict[str, Any] | None = None
    current_revision_id: str | None = None
    pending_clarification: dict[str, Any] | None = None
    asked_fields: list[str] = Field(default_factory=list)
    last_decision: dict[str, Any] | None = None
    last_user_query: str | None = None
```

### 4.3 Transition Result

```python
class ConversationTransitionResult(BaseModel):
    decision: ConversationDecision
    state_before: ConversationRuntimeSnapshot
    state_after: ConversationRuntimeSnapshot
    revision_changed: bool = False
    blocked: bool = False
    block_reason: str | None = None
```

`ConversationDecisionService.decide()` returns the decision. A pure
`apply_transition()` function validates and previews state changes. Route
execution may then commit an itinerary/revision result without bypassing the
previewed mutation scope.

## 5. Decision Rules

### 5.1 Read-Only Boundary

- QA and chat always use `mutation_scope="none"`.
- A day/slot question without an explicit mutation verb remains QA.
- A model cannot upgrade a read-only baseline query to edit without an explicit
  mutation signal.

### 5.2 Destination Change

An existing itinerary changes destination only when all are true:

- the turn contains an explicit replacement signal such as `改去`, `换成`,
  `还是去`, `instead go to`, or `change the destination to`;
- a destination is extracted;
- the destination differs from the active destination.

Examples:

```text
"还是改去杭州吧"         -> change_destination
"不去深圳了，换成厦门"   -> change_destination
"深圳到香港怎么走"       -> qa
"香港和澳门哪个更适合"   -> qa/chat, not change_destination
```

Destination changes preserve portable constraints:

- duration;
- budget;
- traveler type;
- preferences; and
- pace.

They clear:

- current itinerary;
- destination-bound candidate state;
- old revision reference in the active runtime state; and
- pending clarification for the previous destination.

The previous itinerary may remain in historical revision storage, but it cannot
remain the active itinerary.

### 5.3 Clarification

Destination, duration, and budget remain the P0 fields.

Flexible answers (`都可以`, `随便`, `你安排`, `均可`, `either is fine`) may fill
only non-destination missing fields:

- duration defaults to 3 days;
- budget defaults to `max(3000, duration * 2000)`.

A destination can never be invented from a flexible answer.

The pending snapshot stores:

- initial query;
- accumulated values;
- follow-up turns;
- asked fields; and
- defaults/assumptions applied.

The snapshot must be serializable and restorable.

### 5.4 Edit Boundary

- One explicit slot produces `single_slot`.
- A day-level constraint without a slot produces `single_day`.
- An edit cannot create a revision until patch/replan succeeds.
- A failed edit leaves the current itinerary and revision unchanged.
- The next edit must read the revision committed by the previous edit.

## 6. Persistence

Add one JSON column to `travel_conversation_states`:

```text
dialogue_state_json
```

It stores:

```json
{
  "pending_clarification": null,
  "asked_fields": [],
  "last_decision": null,
  "active_goal": "travel_planning",
  "pending_destination_change": null
}
```

`ConversationService` owns persistence. Domain services remain database-free.
The existing in-memory clarification map is retained only as a process-local
cache and can be reconstructed from the persisted snapshot.

## 7. Trace And Replay

Every decision logs `event_type="conversation_transition"` with:

```text
conversation_id
raw_query
intent
intent_detail
confidence
mutation_scope
destination_before
destination_after
revision_before
revision_after
revision_changed
pending_before
pending_after
reason
blocked
block_reason
```

The transcript evaluator uses the same decision and transition domain services as
runtime code. It writes JSON and Markdown reports with per-turn failures and
failure categories.

## 8. Evaluation Set

Create `evaluation/multi_turn_conversation_cases.json` with 24 transcripts:

- 4 explicit destination changes;
- 4 city mentions that must not change destination;
- 4 read-only QA conversations;
- 4 flexible clarification conversations;
- 4 casual-chat goal-retention conversations;
- 4 consecutive-edit/reset/recovery conversations.

Each transcript contains an initial state and ordered turns. Each turn declares
expected intent, mutation scope, destination, revision behavior, and pending
state.

Four focused API integration tests cover:

1. explicit destination switch clears stale active itinerary state;
2. route QA mentioning another city is read-only;
3. persisted clarification restores into a fresh service object;
4. two successful edits use successive revision IDs.

## 9. Acceptance Criteria

```text
multi-turn transcript pass                 24/24
critical API flows                         4/4
QA/chat unintended revision changes        0
false destination switches                 0
explicit destination switch success        100%
repeated clarification loops               0
stale active POIs after destination switch 0
consecutive edit latest-revision usage      100%
conversation transition traces             100%
core integration milestone                 13/13
frontend type-check/build                   pass
```

## 10. Non-Goals

This milestone does not include:

- Geoapify or Provider recall redesign;
- open-world eight-city readiness work;
- learned POI ranker training;
- a new frontend design;
- full revision rollback APIs;
- a new message-memory retrieval system; or
- broad refactoring of `travel.py`.

Targeted extraction from `travel.py` is allowed only where required to establish
the decision and transition boundary.

