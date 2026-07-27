# Overseas Candidate Supply v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce safe, real POI candidate supply for unseen overseas destinations by correcting Geoapify retrieval semantics and locality grounding.

**Architecture:** Keep destination geocoding separate from POI recall. Generic recall uses bounded Geoapify Places category queries, explicit named-POI recall may add a name filter, and the existing deterministic destination gate validates normalized locality metadata and coordinates before ranking.

**Tech Stack:** Python 3.13, FastAPI service layer, httpx, pytest, Geoapify Geocoding and Places APIs.

## Global Constraints

- Do not add Tromso, Hobart, Valletta, or Oaxaca to production bbox, alias, or POI whitelist configuration.
- Mock candidates must never become publishable.
- The existing deterministic destination hard gate remains authoritative.
- Geoapify live calls must respect cache, daily budget, and cooldown controls.
- SerpAPI live calls remain disabled for this milestone.

---

### Task 1: Lock provider query semantics with tests

**Files:**
- Modify: `llm_backend/tests/test_geoapify_provider.py`
- Modify: `llm_backend/app/services/providers/geoapify_provider.py`

**Interfaces:**
- Produces: `_geoapify_place_categories(keywords: list[str]) -> tuple[str, ...]`
- Produces: `_is_explicit_place_query(keywords: list[str]) -> bool`

- [ ] Add a failing test proving generic travel keywords omit the Places `name` parameter and map to tourism, museum, and park categories.
- [ ] Run the focused test and confirm it fails because the current request contains `name`.
- [ ] Implement provider-neutral keyword classification and category mapping.
- [ ] Add a failing test proving a single explicit named POI retains `name`.
- [ ] Implement the explicit-name branch without changing generic requests.
- [ ] Run `pytest tests/test_geoapify_provider.py -v`.

### Task 2: Separate geocoding from general candidate recall

**Files:**
- Modify: `llm_backend/tests/test_geoapify_provider.py`
- Modify: `llm_backend/app/services/providers/factory.py`

**Interfaces:**
- `DestinationResolver` continues constructing `GeoapifySearchProvider` directly.
- `build_registry()` registers `GeoapifyMapProvider` but not
  `GeoapifySearchProvider` as general recall.

- [ ] Change the registry test first to require Geoapify only in map providers.
- [ ] Run the test and confirm it fails against the current registration.
- [ ] Remove Geoapify forward geocoding from general search registration.
- [ ] Derive `GeoapifyMapProvider.radius_meters` from
  `DESTINATION_GROUNDING_RADIUS_KM`.
- [ ] Add assertions for radius alignment and run the provider tests.

### Task 3: Preserve and validate locality hierarchy

**Files:**
- Modify: `llm_backend/tests/test_geoapify_provider.py`
- Modify: `llm_backend/tests/test_destination_grounding.py`
- Modify: `llm_backend/app/services/providers/geoapify_provider.py`
- Modify: `llm_backend/app/services/destination_grounding.py`

**Interfaces:**
- Produces: candidate `extra["locality_terms"]` as normalized source labels.
- Consumes: `DestinationProfile.match_terms()`.

- [ ] Add a failing provider test for preserved suburb, district, county,
  municipality, state, and country-code fields.
- [ ] Add failing grounding tests for diacritic-equivalent city names and a
  valid parent administrative locality.
- [ ] Extend candidate conversion with the full locality contract.
- [ ] Make destination profile selection use preserved administrative fields.
- [ ] Compare candidate locality fields as a set while retaining distance-first
  rejection and contradictory-city protection.
- [ ] Run provider and destination-grounding tests.

### Task 4: Add deterministic overseas supply replay

**Files:**
- Create: `llm_backend/evaluation/overseas_candidate_supply_cases.json`
- Create: `llm_backend/scripts/overseas_candidate_supply_eval.py`
- Create: `llm_backend/tests/test_overseas_candidate_supply_eval.py`
- Modify: `llm_backend/scripts/milestone_runner.py`
- Modify: `docs/travelmind_core_integration_gate.md`

**Interfaces:**
- Produces: `build_report(cases: list[dict]) -> dict`
- Report fields: `status`, `ready_destinations`, `resolved_profiles`,
  `cross_city_published`, `mock_published`, `results`.

- [ ] Write a failing test for the four-city expected outcome matrix.
- [ ] Add sanitized provider-shaped fixtures with three real local POIs for
  Tromso, Hobart, and Valletta and two for Oaxaca.
- [ ] Implement replay through destination grounding and candidate
  publishability.
- [ ] Assert ready `3/3`, Oaxaca safe degradation, cross-city `0`, and Mock
  publication `0`.
- [ ] Register the replay as a milestone gate and update gate documentation.
- [ ] Run replay and milestone-runner tests.

### Task 5: Live probe and full verification

**Files:**
- Update generated ignored reports under `llm_backend/reports/`.
- Modify docs only if observed behavior requires an explicit operational note.

**Interfaces:**
- Consumes: `scripts/live_destination_grounding_probe.py`
- Produces: targeted overseas live report with provider capability metadata.

- [ ] Run focused provider, grounding, replay, and graph integration tests.
- [ ] Run the four-city targeted live probe with Geoapify budget controls and
  SerpAPI live disabled.
- [ ] If live results fail, classify provider availability separately from
  deterministic logic and add only a general regression case.
- [ ] Run the full backend suite.
- [ ] Run the 14-gate milestone.
- [ ] Run `git diff --check` and scan tracked changes for secrets.
- [ ] Commit and push the closed loop.
