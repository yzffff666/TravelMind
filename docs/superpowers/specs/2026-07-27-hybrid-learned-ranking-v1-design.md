# Hybrid Learned Ranking v1 Design

## 1. Goal

Complete the learned-ranking portion of the TravelMind v1 delivery goal without
weakening deterministic candidate safety.

The milestone delivers one reproducible loop:

```text
curated ranking rubric
  -> model-ready query/candidate dataset
  -> destination-isolated train/validation/test split
  -> pairwise linear ranker training
  -> rule baseline vs learned evaluation
  -> runtime model loading and deterministic fallback
  -> project milestone gate
```

The learned model only orders candidates that already passed
`POIRankingPolicy` hard gates. It cannot restore a rejected candidate.

## 2. Current Baseline

TravelMind already has:

- `CandidateFeature` as the provider-neutral feature contract;
- `POIRankingPolicy` with deterministic hard gates and a weighted rule score;
- ranking fixtures covering at least 20 destinations;
- candidate-decision log export, badcase reports, audit queues, and manifests;
- a 15-gate integration milestone; and
- open-world domestic and overseas candidate supply.

The existing observability artifacts contain only 33 weak-label candidate
decisions, concentrated in Phuket and Chengdu, with no reviewed graded test
set. They are useful badcases but not sufficient training data.

## 3. Options

### Option A: NumPy pairwise linear ranker (selected)

Train a small linear model with pairwise logistic loss over normalized
`CandidateFeature` values. Store feature order, means, scales, and weights in a
versioned JSON artifact.

Advantages:

- no new runtime dependency;
- deterministic CPU training;
- model artifact is small and human-auditable;
- pairwise objective directly models candidate ordering;
- inference is comfortably below the 100 ms budget; and
- failure can cleanly fall back to the current rule score.

Limitation: it learns feature weights and interactions only through the supplied
features; it is not a semantic encoder.

### Option B: LightGBM LambdaMART

This is a stronger production ranking baseline, but adds a compiled dependency
that is not currently installed. With only a small rubric dataset, the added
complexity would not yet provide a defensible benefit.

### Option C: embedding or LLM reranker

This adds latency, external model coupling, and less reproducible evaluation.
It is inappropriate before a stable graded ranking benchmark exists.

## 4. Dataset Contract

The dataset contains exactly 576 rows:

```text
12 destinations
* 4 preference-sensitive travel requests per destination
* 12 provider-shaped candidates per request
= 576 query-candidate rows
```

The destination split is fixed and disjoint:

```text
train:      8 destinations / 384 rows
validation: 2 destinations / 96 rows
test:       2 destinations / 96 rows
```

Each row contains:

```text
schema_version
query_id
destination
split
preferences
candidate_id
candidate_title
label
label_source
hard_gate_passed
features
rule_score
```

Labels are:

```text
0 = unsafe or irrelevant
1 = usable
2 = strongly relevant
```

The source catalog uses a reviewable compatibility rubric over POI archetypes
and preference profiles. It is deliberately described as
`curated_rubric_v1`, not as user behavior or production ground truth. Unsafe
rows are retained for gate verification but excluded from learned ordering.

The test destinations are never used to calculate feature normalization,
gradients, early stopping, or model selection.

## 5. Feature Vector

The offline rows and runtime `CandidateFeature` adapter share the same
versioned feature names and order:

```text
preference_match
evidence_score
provider_confidence
resolvable_score
distance_feasibility
budget_match
alias_hit
rating_score
review_count_score
```

At runtime, `rating_score` normalizes a five-point rating to `[0, 1]`, while
`review_count_score` applies `log1p` and a fixed cap before normalization.
The v1 offline values are curated feature values rather than raw Provider
payloads, so this milestone establishes schema parity, not production feature
distribution parity.

Feature order is part of the model schema. A missing, extra, or reordered
feature causes model loading to fail closed and triggers rule fallback.

## 6. Training

For every query group, training creates pairs whose labels differ. Given a
higher-relevance row `x+` and lower-relevance row `x-`, the model minimizes:

```text
log(1 + exp(-w * (x+ - x-))) + lambda * ||w||^2
```

Training uses full-batch gradient descent with:

- deterministic initialization;
- train-split means and standard deviations;
- validation NDCG@5 for model selection;
- bounded epochs; and
- a versioned JSON artifact.

The artifact records dataset fingerprint, feature order, normalization,
weights, training configuration, and validation metrics.

## 7. Evaluation

The report compares the existing rule score with the learned score on a
destination-ID-isolated curated-rubric test set. Split destination IDs are
disjoint, and model metadata must match the current train-split fingerprint and
training destination set. Score ties preserve input order and never use labels
as an implicit tie-breaker.

Required metrics:

```text
dataset rows                              = 576
travel requests                          = 48
destinations                             = 12
train/test destination overlap           = 0
learned NDCG@5                            >= rule NDCG@5
learned preference-sensitive Top-3 rate  >= rule + 0.05
unsafe accepted candidates               = 0
learned inference P95                     < 100 ms
```

Preference-sensitive Top-3 rate is the fraction of available label-2 placements
captured in the top three, averaged by query. This is stricter than checking
whether any relevant candidate appears.

All destinations deliberately share a compact set of POI archetypes. Therefore,
this benchmark verifies the training/evaluation/deployment mechanism and the
ability to recover the curated preference policy; it does not establish
open-world destination generalization or online user benefit. Those claims
require logged runtime candidates and human or user feedback.

## 8. Runtime Integration

Runtime configuration:

```text
POI_LEARNED_RANKING_MODE=off|shadow|active
POI_LEARNED_RANKING_MODEL_PATH=models/poi_pairwise_ranker_v1.json
```

Behavior:

- `off`: use the existing rule ranking;
- `shadow`: compute learned scores for diagnostics, preserve rule order;
- `active`: order hard-gate-passing candidates by learned score;
- missing/corrupt/incompatible model: record fallback reason and use rule order.

The existing `POI_RANKING_MODE` continues to control whether the candidate
policy itself is shadowed or active. Learned ranking never bypasses
`POIRankingPolicy._hard_gate`.

## 9. Testing And Acceptance

The milestone adds:

- dataset contract and split tests;
- pairwise training determinism tests;
- model serialization and schema mismatch tests;
- rule fallback tests for missing and corrupt artifacts;
- a hard-gate preservation test;
- metric implementation tests;
- a learned-ranking evaluation gate; and
- focused runtime integration tests for create and local replan.

Completion requires:

```text
learned ranking gate passes
full backend test suite passes
core integration milestone passes
frontend tests, type-check, and build pass
git diff contains no credential
```

## 10. Scope Boundaries

This milestone does not:

- claim real user-behavior training data;
- fine-tune an LLM or embedding model;
- add a two-tower architecture;
- remove deterministic safety rules;
- make learned ranking active by default;
- perform online A/B testing; or
- expand unrelated frontend functionality.

After this milestone, the remaining TravelMind v1 work is multi-turn corpus
expansion, final end-to-end demonstrations, documentation, and the project
report.
