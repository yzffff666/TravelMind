# TravelMind Bilingual Experience Contract

## Implementation Status

As of 2026-08-03, **Bilingual Experience v1 is complete**:

- one deterministic `en` / `zh-CN` response-language policy;
- response language persisted in the existing conversation dialogue state;
- query/resume, SSE, clarification, draft, QA, edit, reset, duplicate-request,
  and safe-degradation paths share the same language decision;
- short acknowledgements preserve the conversation language;
- explicit language switches override the current language; and
- the checked-in backend acceptance set passes `20/20` cases and `42` turns
  with zero language drift, wrong-language responses, persistence failures, or
  missing SSE language metadata.

The Vue interface is English-first, persists the EN/中文 selection, sends
`ui_locale` with every travel request, and formats UI-owned numbers through the
active locale. Active runtime routes use message catalogs and are protected by
the complete frontend test suite plus a 12-file visible-string inventory. Local
validation, progress, and map error states store semantic keys so already
rendered UI retranslates immediately when the locale changes; backend content
remains unchanged. The default milestone includes `bilingual_experience_eval`,
and this release candidate passed English/Chinese browser verification at
1280x720 and 390x844 without horizontal overflow.

## 1. Goal

Make TravelMind English-first for an overseas university demonstration while
preserving complete Chinese interaction for a Chinese-speaking supervisor.

The product must:

- open with an English interface by default;
- let the user switch the interface between English and Chinese;
- persist the selected interface language across refreshes;
- accept both Chinese and English travel requests;
- generate Chinese itinerary content for Chinese conversations and English
  itinerary content for English conversations; and
- keep one response language across clarification, QA, edit, reset, fallback,
  and error paths.

This is a P0 delivery requirement and must be completed before the final live
Provider and browser demonstration.

## 2. Why This Is A System Contract

The backend already detects Chinese characters for parts of draft generation,
and some QA/edit paths already accept English. That is only partial support.

The baseline before this milestone had:

- Chinese strings embedded in Vue views and components;
- Chinese-only date and number formatting;
- Chinese clarification, fallback, stage, and error messages;
- Provider query locale fixed to Chinese in some paths; and
- per-turn language detection that can switch a Chinese conversation to English
  after a short reply such as `ok`.

Therefore this work is not a one-time UI translation. It is an end-to-end
language consistency contract.

## 3. Two Independent Language States

### 3.1 UI locale

`ui_locale` controls product chrome:

- navigation;
- tabs;
- buttons;
- empty/loading/error states;
- form labels and placeholders;
- itinerary field labels;
- map controls;
- date, number, and currency formatting;
- accessibility labels and tooltips; and
- SSE phase labels rendered by the frontend.

Allowed values:

```text
en
zh-CN
```

The default is `en`. The frontend stores the explicit user selection in
`localStorage`.

### 3.2 Response language

`response_language` controls Agent-generated or backend-generated content:

- clarification questions;
- chat and itinerary QA answers;
- itinerary themes and activity descriptions;
- local-edit explanations and change summaries;
- quality warnings;
- safe-degradation messages;
- reset acknowledgements; and
- recoverable error and fallback text.

It is conversation state, not a global browser preference. It is persisted with
the conversation runtime state so a refresh or later turn does not reset it.

## 4. Response Language Resolution

Each user turn resolves language in this order:

1. an explicit user request such as "reply in English" or "请用中文";
2. a strong language signal in the current substantive query;
3. the existing conversation `response_language` for short or ambiguous replies;
4. the request `ui_locale` when a conversation has no language yet; and
5. English as the final default.

Examples:

```text
Chinese trip request -> 好的 -> 都可以        stays zh-CN
English trip request -> ok -> either is fine  stays en
Chinese conversation -> please answer in English  switches to en
English UI -> Chinese substantive query           responds in zh-CN
```

Language resolution must be deterministic and reusable. Prompt builders,
clarification services, QA handlers, patch/replan responses, and error paths
must consume the resolved value rather than detect language independently.

## 5. Architecture

### 5.1 Frontend

Use `vue-i18n` as the single UI translation layer.

Add:

- an `en` message catalog;
- a `zh-CN` message catalog;
- a locale store/composable backed by `localStorage`;
- a compact language switch in the main navigation and authentication screen;
  and
- locale-aware date, number, and currency formatting.

The frontend sends optional `ui_locale` metadata with every travel SSE request.
The field is a fallback hint, not an instruction to override a clearly Chinese
or English user query.

Visible product strings must come from the message catalog. Developer logs,
code comments, test descriptions, and archived unused views are outside the
runtime UI acceptance boundary.

### 5.2 Backend

Create one language policy module responsible for:

```text
detect strong query language
detect explicit language override
identify ambiguous short replies
resolve conversation response language
select localized backend message
```

Extend the conversation runtime snapshot with:

```json
{
  "response_language": "en"
}
```

Persist this field through the existing dialogue-state storage. Old
conversations without the field use `ui_locale`, then English.

The travel request accepts an optional `ui_locale` form field. The backend
includes `response_language` in `intent_routed` or equivalent early SSE metadata
so the frontend and trace report can inspect the decision.

### 5.3 Generation and Provider behavior

The resolved response language is passed to:

- draft prompt generation;
- clarification;
- local QA;
- local edit/replan;
- reset;
- fallback and degradation;
- structured validation summaries; and
- user-visible SSE payloads.

Provider locale should follow the resolved language when the provider supports
it. POI proper names may remain in the provider's canonical form; the system
does not invent translated place names.

## 6. Error Handling And Compatibility

- Missing or invalid `ui_locale` falls back to English.
- Missing persisted `response_language` is backward-compatible.
- Translation-key lookup failure falls back to the English catalog and is
  visible in development tests.
- Language detection failure preserves the current conversation language.
- Provider locale support is best-effort and must not block candidate recall.
- Switching the UI locale does not silently rewrite an existing itinerary.
- Switching response language affects future responses; existing revision
  content remains auditable in its original language.

## 7. Acceptance Gate

### 7.1 Frontend

```text
initial UI locale                              = en
English/Chinese switch                         works
selected UI locale after refresh               preserved
unlocalized static Chinese in English mode     = 0
unlocalized static English in Chinese mode     = 0, except proper nouns
frontend component tests                       pass
frontend type check                            pass
frontend production build                      pass
```

The raw-string checks apply to an explicit static runtime UI inventory. User
messages, Provider content, proper nouns, developer logs, code comments, and
archived views are not treated as untranslated UI.

### 7.2 Conversation

Maintain at least 20 bilingual multi-turn cases:

```text
Chinese journeys                               >= 10
English journeys                               >= 10
create / clarify / QA / edit / reset covered   yes
short acknowledgement language drift           = 0
wrong-language itinerary publication            = 0
wrong-language backend fallback                 = 0
language state lost after revision              = 0
```

Critical cases must pass at 100%. Overall bilingual journey pass rate must be
100% for the checked-in acceptance set.

### 7.3 Project gate

Add a `bilingual_experience_eval` gate to the default milestone. The existing
17 gates must remain green, so the default milestone becomes an 18-gate suite
and completion requires `18/18` passing.

## 8. Delivery Order

Implement as one medium-sized closed loop:

1. language policy and conversation-state contract;
2. localized backend messages and generation paths;
3. frontend i18n catalogs, switch, and formatting;
4. bilingual component and multi-turn fixtures;
5. browser verification in both locales; and
6. default milestone integration.

After this gate passes, continue with the budget-controlled live Provider and
browser demo probe, then final README and project report.

## 9. Non-Goals

This milestone does not require:

- machine translation of stored historical itineraries;
- support for languages other than English and Chinese;
- translating every POI proper name;
- locale-specific pricing or exchange-rate conversion;
- browser-language auto-detection that overrides the English-first default; or
- redesigning unrelated pages.
