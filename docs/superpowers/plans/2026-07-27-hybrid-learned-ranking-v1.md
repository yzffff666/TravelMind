# Hybrid Learned Ranking v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible 576-row ranking dataset, train a NumPy pairwise ranker, integrate safe runtime fallback after deterministic hard gates, and add a project-level learned-ranking acceptance gate.

**Architecture:** A deterministic rubric builder converts a compact destination/archetype catalog into destination-isolated query-candidate rows. A standalone pairwise linear model trains on normalized `CandidateFeature` vectors and serializes to JSON. Runtime policy applies the model only to hard-gate-passing candidates and falls back to the existing rule order on every load or inference failure.

**Tech Stack:** Python 3.10+, NumPy, Pydantic v2 settings, pytest, existing `CandidateFeature`/`POIRankingPolicy`, JSON/JSONL artifacts, existing milestone runner.

## Global Constraints

- The dataset has exactly 576 rows, 48 queries, and 12 destinations.
- Train, validation, and test destinations are disjoint.
- Labels are `0`, `1`, or `2` and use `curated_rubric_v1`; do not claim user behavior.
- Learned ranking only reorders candidates accepted by deterministic hard gates.
- `POI_LEARNED_RANKING_MODE` defaults to `off`.
- Missing, corrupt, or schema-incompatible models fall back to rule ranking.
- No new compiled ML dependency or live Provider/LLM call is required.
- Learned inference P95 must remain below 100 ms.
- The existing project integration milestone must remain green.

---

### Task 1: Model-Ready Ranking Dataset

**Files:**
- Create: `llm_backend/evaluation/learned_ranking_catalog_v1.json`
- Create: `llm_backend/scripts/build_learned_ranking_dataset.py`
- Create: `llm_backend/tests/test_build_learned_ranking_dataset.py`
- Generate: `llm_backend/evaluation/learned_ranking_dataset_v1.jsonl`
- Generate: `llm_backend/evaluation/learned_ranking_dataset_manifest_v1.json`

**Interfaces:**
- Consumes: compact catalog with `destinations`, `query_profiles`, and `candidate_archetypes`.
- Produces: `build_dataset(catalog: dict) -> tuple[list[dict], dict]`, JSONL rows, and a manifest.

- [ ] **Step 1: Write failing dataset contract tests**

Test that generated rows contain 576 samples, 48 query groups, 12 destinations,
disjoint split destinations, 12 candidates per query, labels `{0,1,2}`, and no
query without at least one label-2 and one label-0 candidate.

- [ ] **Step 2: Run the dataset tests and confirm RED**

Run:

```bash
cd llm_backend
./.venv/bin/pytest tests/test_build_learned_ranking_dataset.py -q
```

Expected: import/file failure because the builder does not exist.

- [ ] **Step 3: Implement the catalog and deterministic builder**

The builder must:

```python
rows, manifest = build_dataset(catalog)
write_dataset(rows, dataset_path)
write_manifest(manifest, manifest_path)
```

Each row stores identity fields, split, preferences, label source, hard-gate
status, all nine learned features, and the rule baseline score.

- [ ] **Step 4: Generate artifacts and verify GREEN**

Run:

```bash
./.venv/bin/python -m scripts.build_learned_ranking_dataset
./.venv/bin/pytest tests/test_build_learned_ranking_dataset.py -q
```

Expected: dataset reports `576 rows / 48 queries / 12 destinations`.

### Task 2: Pairwise Linear Model

**Files:**
- Create: `llm_backend/app/services/learned_poi_ranker.py`
- Create: `llm_backend/tests/test_learned_poi_ranker.py`

**Interfaces:**
- Produces: `FEATURE_NAMES`, `feature_vector`, `PairwiseLinearRanker.fit`,
  `predict_scores`, `save`, and `load`.
- Consumes: dataset rows from Task 1.

- [ ] **Step 1: Write failing algorithm and artifact tests**

Cover deterministic training, higher scores for preferred candidates, exact
round-trip serialization, feature schema mismatch, corrupt JSON, and finite
predictions for zero-variance features.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
./.venv/bin/pytest tests/test_learned_poi_ranker.py -q
```

- [ ] **Step 3: Implement pairwise logistic training**

Use train-only means/scales and pair differences for labels that differ within
the same query. Keep the best validation NDCG@5 weights and store them in a
versioned JSON schema.

- [ ] **Step 4: Run focused tests and confirm GREEN**

```bash
./.venv/bin/pytest tests/test_learned_poi_ranker.py -q
```

### Task 3: Training And Offline Evaluation

**Files:**
- Create: `llm_backend/scripts/train_poi_ranker.py`
- Create: `llm_backend/scripts/learned_ranking_eval.py`
- Create: `llm_backend/tests/test_learned_ranking_eval.py`
- Generate: `llm_backend/models/poi_pairwise_ranker_v1.json`

**Interfaces:**
- Produces: `train_from_rows`, `evaluate_rankers`, NDCG@5, Top-3 rate,
  inference P95, dataset leakage checks, and a model artifact.

- [ ] **Step 1: Write failing metric and acceptance tests**

Assert:

```text
learned_ndcg_at_5 >= rule_ndcg_at_5
learned_top3_rate >= rule_top3_rate + 0.05
unsafe_accepted_count == 0
inference_p95_ms < 100
train_test_destination_overlap == []
```

- [ ] **Step 2: Run tests and confirm RED**

```bash
./.venv/bin/pytest tests/test_learned_ranking_eval.py -q
```

- [ ] **Step 3: Implement training and evaluation commands**

Training reads only `train` and `validation` rows. Evaluation reads only test
rows for final metrics and writes a JSON/Markdown report.

- [ ] **Step 4: Train the artifact and confirm GREEN**

```bash
./.venv/bin/python -m scripts.train_poi_ranker
./.venv/bin/python -m scripts.learned_ranking_eval \
  --output-dir reports/learned-ranking-eval/local
./.venv/bin/pytest tests/test_learned_ranking_eval.py -q
```

### Task 4: Safe Runtime Integration

**Files:**
- Modify: `llm_backend/app/core/config.py`
- Modify: `.env.example`
- Modify: `llm_backend/app/services/poi_ranking_policy.py`
- Modify: `llm_backend/app/lg_agent/travel_draft_graph.py`
- Modify: `llm_backend/app/services/day_replan_service.py`
- Modify: `llm_backend/tests/test_poi_ranking_policy.py`
- Modify: `llm_backend/tests/test_day_replan_service.py`
- Modify: `llm_backend/tests/test_draft_pipeline_integration.py`

**Interfaces:**
- Produces: `apply_learned_ranking`, cached model loading, diagnostics, and
  `off|shadow|active` settings.
- Consumes: `RankedPOICandidate` after hard-gate scoring and the JSON artifact.

- [ ] **Step 1: Write failing runtime and fallback tests**

Cover:

- active mode reorders only accepted candidates;
- rejected candidates remain rejected;
- shadow mode preserves rule order;
- missing and corrupt models preserve rule order with fallback reason;
- create and local replan use the same helper.

- [ ] **Step 2: Run focused integration tests and confirm RED**

```bash
./.venv/bin/pytest \
  tests/test_poi_ranking_policy.py \
  tests/test_day_replan_service.py \
  tests/test_draft_pipeline_integration.py -q
```

- [ ] **Step 3: Implement the runtime helper and settings**

Default to `off`. Load the model lazily by resolved path and file modification
time. Return learned diagnostics without leaking model internals into the
planner contract.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run the same focused command and require zero failures.

### Task 5: Learned Ranking Project Gate

**Files:**
- Modify: `llm_backend/scripts/milestone_runner.py`
- Modify: `llm_backend/tests/test_milestone_runner.py`
- Modify: `docs/travelmind_core_integration_gate.md`
- Modify: `docs/superpowers/specs/2026-07-27-travelmind-v1-final-delivery-goal-design.md`
- Modify: `docs/简历-项目描述-旅行规划系统.md`

**Interfaces:**
- Produces: `learned_ranking_eval` milestone gate and current project
  documentation.

- [ ] **Step 1: Write failing milestone assertions**

Require the learned gate in the default gate list, require its focused tests in
the backend target set, and fail the gate when dataset/model metrics regress.

- [ ] **Step 2: Run milestone-runner tests and confirm RED**

```bash
./.venv/bin/pytest tests/test_milestone_runner.py -q
```

- [ ] **Step 3: Register the gate and update documentation**

Document the pairwise objective, rubric-data limitation, runtime fallback, and
actual evaluation metrics. Update the final goal from the historical 13-gate
wording to the current gate count.

- [ ] **Step 4: Run focused gate tests and confirm GREEN**

```bash
./.venv/bin/pytest \
  tests/test_build_learned_ranking_dataset.py \
  tests/test_learned_poi_ranker.py \
  tests/test_learned_ranking_eval.py \
  tests/test_poi_ranking_policy.py \
  tests/test_milestone_runner.py -q
```

### Task 6: Full Verification And Delivery

**Files:**
- Verify all modified and generated files.

**Interfaces:**
- Produces: final test evidence, milestone report, clean commit, and pushed main.

- [ ] **Step 1: Rebuild deterministic artifacts**

```bash
./.venv/bin/python -m scripts.build_learned_ranking_dataset
./.venv/bin/python -m scripts.train_poi_ranker
./.venv/bin/python -m scripts.learned_ranking_eval \
  --output-dir reports/learned-ranking-eval/release
```

- [ ] **Step 2: Run the full backend suite**

```bash
./.venv/bin/pytest tests/ -q
```

- [ ] **Step 3: Run the complete project milestone**

```bash
./.venv/bin/python -m scripts.milestone_runner \
  --run-id hybrid-learned-ranking-v1-release
```

- [ ] **Step 4: Inspect diff and credential safety**

Run `git diff --check`, inspect all changed paths, confirm generated reports are
ignored, and scan the staged diff for credential patterns.

- [ ] **Step 5: Commit and push**

```bash
git add \
  .env.example \
  docs/superpowers/specs/2026-07-27-travelmind-v1-final-delivery-goal-design.md \
  docs/travelmind_core_integration_gate.md \
  docs/简历-项目描述-旅行规划系统.md \
  llm_backend/app/core/config.py \
  llm_backend/app/lg_agent/travel_draft_graph.py \
  llm_backend/app/services/day_replan_service.py \
  llm_backend/app/services/learned_poi_ranker.py \
  llm_backend/app/services/poi_ranking_policy.py \
  llm_backend/evaluation/learned_ranking_catalog_v1.json \
  llm_backend/evaluation/learned_ranking_dataset_manifest_v1.json \
  llm_backend/evaluation/learned_ranking_dataset_v1.jsonl \
  llm_backend/models/poi_pairwise_ranker_v1.json \
  llm_backend/scripts/build_learned_ranking_dataset.py \
  llm_backend/scripts/learned_ranking_eval.py \
  llm_backend/scripts/milestone_runner.py \
  llm_backend/scripts/train_poi_ranker.py \
  llm_backend/tests/test_build_learned_ranking_dataset.py \
  llm_backend/tests/test_day_replan_service.py \
  llm_backend/tests/test_draft_pipeline_integration.py \
  llm_backend/tests/test_learned_poi_ranker.py \
  llm_backend/tests/test_learned_ranking_eval.py \
  llm_backend/tests/test_milestone_runner.py \
  llm_backend/tests/test_poi_ranking_policy.py
git commit -m "feat: add safe learned POI ranking"
git push origin main
```
