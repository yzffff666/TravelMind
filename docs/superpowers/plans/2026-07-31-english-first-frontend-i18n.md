# English-First Frontend i18n Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver an English-first Vue interface with a persistent English/Chinese switch, locale-aware formatting, `ui_locale` request metadata, and browser-verifiable bilingual journeys.

**Architecture:** Use `vue-i18n` in composition mode as the single source of UI copy. Keep UI locale separate from backend `response_language`: the frontend persists `ui_locale` in `localStorage` and sends it with every travel request, while backend SSE metadata continues to describe the Agent response language. Localize only active runtime routes and their imported components; archived unused views remain outside the acceptance boundary.

**Tech Stack:** Vue 3, TypeScript, Pinia, vue-i18n, Vitest, Vue Test Utils, Vite, FastAPI SSE

## Global Constraints

- Default UI locale is `en`; allowed values are exactly `en` and `zh-CN`.
- The selected UI locale persists under `travelmind.ui_locale` and updates `document.documentElement.lang`.
- A substantive Chinese query can still produce Chinese Agent output while the UI remains English.
- Every travel request includes `ui_locale`; it is a fallback hint, not a response-language override.
- Visible strings in `/`, `/login`, `/register`, and their active child components come from message catalogs.
- POI names and backend-generated itinerary content are not translated by the frontend.
- Existing API, router, SSE, itinerary, map, and revision behavior must remain unchanged.
- No redesign or unrelated refactor is included.

---

### Task 1: vue-i18n Foundation And Persisted Locale

**Files:**
- Modify: `frontend/DsAgentChat_web/package.json`
- Modify: `frontend/DsAgentChat_web/package-lock.json`
- Create: `frontend/DsAgentChat_web/src/i18n/messages/en.ts`
- Create: `frontend/DsAgentChat_web/src/i18n/messages/zh-CN.ts`
- Create: `frontend/DsAgentChat_web/src/i18n/index.ts`
- Create: `frontend/DsAgentChat_web/src/i18n/index.test.ts`
- Modify: `frontend/DsAgentChat_web/src/main.ts`

**Interfaces:**
- Produces: `AppLocale = 'en' | 'zh-CN'`
- Produces: `LOCALE_STORAGE_KEY = 'travelmind.ui_locale'`
- Produces: `resolveInitialLocale(storage?: Storage) -> AppLocale`
- Produces: `setAppLocale(locale: AppLocale) -> void`
- Produces: configured `i18n` instance in composition mode

- [x] **Step 1: Install the standard translation dependency**

Run:

```bash
cd frontend/DsAgentChat_web
npm install vue-i18n
```

- [x] **Step 2: Write failing locale-policy tests**

Cover:

```ts
expect(resolveInitialLocale(emptyStorage)).toBe('en')
expect(resolveInitialLocale(storageWith('zh-CN'))).toBe('zh-CN')
expect(resolveInitialLocale(storageWith('fr'))).toBe('en')
setAppLocale('zh-CN')
expect(localStorage.getItem(LOCALE_STORAGE_KEY)).toBe('zh-CN')
expect(document.documentElement.lang).toBe('zh-CN')
```

- [x] **Step 3: Run the test and verify RED**

Run:

```bash
npm run test -- src/i18n/index.test.ts
```

Expected: import failure because `src/i18n/index.ts` does not exist.

- [x] **Step 4: Implement the locale boundary**

Configure:

```ts
createI18n({
  legacy: false,
  locale: resolveInitialLocale(),
  fallbackLocale: 'en',
  messages: { en, 'zh-CN': zhCN },
})
```

`setAppLocale` updates the reactive global locale, `localStorage`, and the HTML `lang` attribute. Register `i18n` in `main.ts` before mounting.

- [x] **Step 5: Run the focused test and verify GREEN**

Run `npm run test -- src/i18n/index.test.ts` and require all tests to pass.

### Task 2: Locale Switch And API Contract

**Files:**
- Create: `frontend/DsAgentChat_web/src/components/ui/LocaleSwitch.vue`
- Create: `frontend/DsAgentChat_web/src/components/ui/LocaleSwitch.test.ts`
- Modify: `frontend/DsAgentChat_web/src/components/ui/index.ts`
- Modify: `frontend/DsAgentChat_web/src/services/api.ts`
- Create: `frontend/DsAgentChat_web/src/services/api.test.ts`

**Interfaces:**
- Consumes: `AppLocale`, `setAppLocale`, `useI18n`
- Produces: two-option segmented control (`EN`, `中文`)
- Extends: `TravelStreamOptions.uiLocale: AppLocale`
- Produces: multipart form field `ui_locale`

- [x] **Step 1: Write failing switch and request tests**

Verify that clicking `中文` changes the active locale and persists it. Stub `fetch`, call `travelQueryStream`, inspect `FormData`, and assert:

```ts
expect(formData.get('ui_locale')).toBe('en')
```

- [x] **Step 2: Run focused tests and verify RED**

Run:

```bash
npm run test -- src/components/ui/LocaleSwitch.test.ts src/services/api.test.ts
```

Expected: component/option contract missing.

- [x] **Step 3: Implement the segmented control and API field**

The switch exposes `aria-label` from the catalog, stable button dimensions, `aria-pressed`, visible focus, and no layout shift. `travelQueryStream` always appends `ui_locale` from its required option.

- [x] **Step 4: Run focused tests and verify GREEN**

Require both files to pass.

### Task 3: Localize The Travel Workspace

**Files:**
- Modify: `frontend/DsAgentChat_web/src/views/TravelPlanner.vue`
- Modify: `frontend/DsAgentChat_web/src/components/chat/InputBar.vue`
- Modify: `frontend/DsAgentChat_web/src/components/chat/PhaseIndicator.vue`
- Modify: `frontend/DsAgentChat_web/src/components/chat/DiffCard.vue`
- Modify: `frontend/DsAgentChat_web/src/components/itinerary/EmptyState.vue`
- Modify: `frontend/DsAgentChat_web/src/components/itinerary/ErrorState.vue`
- Modify: `frontend/DsAgentChat_web/src/components/itinerary/TripOverview.vue`
- Modify: `frontend/DsAgentChat_web/src/components/itinerary/BudgetCard.vue`
- Modify: `frontend/DsAgentChat_web/src/components/itinerary/ItineraryTimeline.vue`
- Modify: `frontend/DsAgentChat_web/src/components/itinerary/MapPanel.vue`
- Modify: existing tests beside those components
- Create: `frontend/DsAgentChat_web/src/views/TravelPlanner.i18n.test.ts`

**Interfaces:**
- Consumes: `useI18n()` and `LocaleSwitch`
- Passes: `uiLocale: locale.value as AppLocale` into `travelQueryStream`
- Uses: `n(value, 'integer')` and catalog currency/day labels for locale-aware display

- [x] **Step 1: Convert component tests into bilingual contract tests**

Mount with an i18n test plugin and assert representative English defaults and Chinese switch output for phase, diff, input, empty, error, budget, timeline, and overview components. Add a workspace test that verifies the English welcome title, English navigation, and locale switch.

- [x] **Step 2: Run workspace/component tests and verify RED**

Run `npm run test` and confirm new English assertions fail against hardcoded Chinese copy.

- [x] **Step 3: Move active workspace copy into the catalogs**

Catalog groups must cover:

```text
common, localeSwitch, auth, planner, phase, input, diff,
emptyState, errorState, overview, budget, timeline, map
```

Use English suggestion queries in English UI and Chinese queries in Chinese UI so demonstrations naturally produce matching Agent output. Keep backend text and POI names unchanged.

- [x] **Step 4: Localize runtime status and fallback copy**

Replace hardcoded workspace status, intent labels, candidate progress, local errors, reset fallback, and request failure text with `t(...)`. Remove only the known optional-clause suffix in both supported languages.

- [x] **Step 5: Localize itinerary and map chrome**

Translate day labels, transport/evidence badges, budget categories, map status/hints/errors, engine labels, coordinate counts, accessibility labels, and tooltips. Preserve canonical map provider and POI names.

- [x] **Step 6: Run component tests and verify GREEN**

Run `npm run test` and require the complete frontend suite to pass.

### Task 4: Localize Authentication Routes

**Files:**
- Modify: `frontend/DsAgentChat_web/src/views/Login.vue`
- Create: `frontend/DsAgentChat_web/src/views/Login.i18n.test.ts`

**Interfaces:**
- Consumes: `useI18n()` and `LocaleSwitch`
- Produces: English default login/register form and Chinese switched form

- [x] **Step 1: Write failing login/register locale tests**

Assert English default title, labels, validation copy, submit action, and language switch; then switch to Chinese and assert Chinese title/labels. Mock auth/store/router boundaries only where submission is exercised.

- [x] **Step 2: Run the focused test and verify RED**

Run `npm run test -- src/views/Login.i18n.test.ts`.

- [x] **Step 3: Replace authentication copy and validators with translation keys**

Localize login/register headings, field labels, validation errors, agreement, links, alternative login, success dialog, and service-error fallback. Keep backend-provided detail text unchanged when returned.

- [x] **Step 4: Run the focused test and verify GREEN**

Require the authentication tests to pass.

### Task 5: Visible-String Inventory And Full Bilingual Gate

**Files:**
- Create: `frontend/DsAgentChat_web/scripts/check-visible-i18n.mjs`
- Modify: `frontend/DsAgentChat_web/package.json`
- Modify: `llm_backend/scripts/milestone_runner.py`
- Modify: `llm_backend/tests/test_milestone_runner.py`
- Modify: `docs/travelmind_core_integration_gate.md`
- Modify: `docs/superpowers/specs/2026-07-28-bilingual-experience-contract-design.md`
- Modify: `docs/简历-项目描述-旅行规划系统.md`

**Interfaces:**
- Produces: `npm run i18n-check`
- Produces: `bilingual_experience_eval` milestone gate
- Upgrades: default milestone from `17/17` to `18/18`

- [x] **Step 1: Write failing inventory and milestone tests**

The inventory scans only active routes and imported runtime components. It rejects literal visible Chinese sentence copy while allowing comments, translation catalogs, provider names, slot-key lookup tables, and backend content. The milestone test expects a new frontend gate named `bilingual_experience_eval`.

- [x] **Step 2: Run tests and verify RED**

Run:

```bash
cd frontend/DsAgentChat_web && npm run i18n-check
cd ../../../llm_backend && .venv/bin/pytest tests/test_milestone_runner.py -q
```

- [x] **Step 3: Implement the inventory and milestone command**

The new gate runs frontend i18n tests plus `npm run i18n-check`. Keep the existing standalone backend bilingual evaluator and all 17 previous gates.

- [x] **Step 4: Run all automated verification**

Run:

```bash
cd frontend/DsAgentChat_web
npm run test
npm run i18n-check
npm run type-check
npm run build

cd ../../llm_backend
.venv/bin/pytest tests/ -q
.venv/bin/python -m scripts.bilingual_conversation_eval \
  --output-dir reports/bilingual-conversation-eval/frontend-final
.venv/bin/python -m scripts.milestone_runner \
  --run-id english-first-frontend-final
```

Expected: frontend tests/check/type/build pass, backend tests pass, bilingual backend remains `20/20`, and milestone reports `18/18`.

- [x] **Step 5: Run browser acceptance in both locales**

Start the backend and frontend. Verify desktop and mobile:

```text
English default -> create -> QA -> local edit -> reset
switch to Chinese -> refresh persistence -> create -> QA -> local edit -> reset
```

Capture screenshots and confirm no overlapping text, empty map canvas, clipped controls, or untranslated active UI copy.

- [x] **Step 6: Update status and deliver**

Record the automated and browser evidence without claiming provider content translation. Run `git diff --check`, scan staged files for secrets, commit with `feat: add English-first bilingual frontend`, push `main`, and verify a clean synchronized repository.
