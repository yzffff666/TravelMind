# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Commands

### Backend

```bash
cd llm_backend

# Setup
python -m venv .venv && source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt

# Run (port 8000 — matches vite.config.ts proxy target, hot-reload enabled)
python run.py

# Tests — must use -X utf8 flag on Windows
pytest tests/ -v                                          # all tests
pytest tests/test_performance_regression.py -v           # performance regression (9 tests, all mock)
pytest tests/test_e2e_performance.py -v                  # E2E performance
pytest tests/test_ranking_scorer.py -v                   # single test file
```

### Frontend

```bash
cd frontend/DsAgentChat_web

npm install
npm run dev          # dev server with HMR
npm run build        # production build → dist/
npm run type-check   # vue-tsc --noEmit
npm run test         # vitest run (unit tests)
```

### Deployment note

`python run.py` mounts the frontend `dist/` at `/` in FastAPI. Build the frontend first for single-server deployment: the static dir expected is `llm_backend/static/dist`.

---

## Architecture

### Request Flow

```
User → Vue 3 UI (SSE client)
     → POST /api/travel/... (FastAPI)
     → TravelClarificationService (P0 gate: destination/days/budget)
     → TravelQueryProcessor (intent classify + constraint extraction)
     → LangGraph travel_draft_graph (4-node StateGraph)
          ├─ extract_node   → regex-based constraint extraction
          ├─ early_exit_node → returns final_text if P0 missing
          ├─ recall_node    → ProviderOrchestrator (Amap + SerpAPI + Mock, asyncio.gather)
          │                    → RankingScorer → ConstraintFilter → EvidenceBuilder
          ├─ llm_draft_node → DeepSeek astream → structured day/slot JSON
          └─ postprocess_node → ItineraryV1 validation, risk assessment, geo enrichment
     ← SSE stream of events back to client
```

### LangGraph State Graph (`app/lg_agent/travel_draft_graph.py`)

The **single source of truth** for agent state. No parallel control planes. All pipeline service instances are **lazy singletons** (initialized once per process via `_get_pipeline()`). The graph has a conditional edge from `extract_node`: if P0 constraints are missing → `early_exit_node`, else → `recall_node`.

### SSE Event Contract (`app/domain/travel/sse_envelope.py`)

The frontend/backend contract is SSE-first. Key events in order:
1. `intent_routed` — intent + conversation_id
2. `stage_start` / `stage_progress` — pipeline phase updates
3. `tool_result` — search/map results (candidate count, POIs)
4. `final_itinerary` — full ItineraryV1 JSON with evidence + change_summary
5. `final_text` — fallback when P0 fields are missing (clarification prompt)
6. `error` — `{error_code, message, recoverable}`

### ItineraryV1 Schema (`app/schemas/itinerary_v1.py`)

Structured contract with a **3-tier field policy**:
- **P0** — required; if missing → no `final_itinerary`, return `final_text` for clarification
- **P1** — strongly recommended; if missing → publish with degraded `validation.assumptions`
- **P2** — optional; missing fields keep default/empty values

Hard P0 constraints: `schema_version`, `itinerary_id`, `revision_id`, `trip_profile.destination_city`, `budget_summary.total_estimate`, plus at least one slot per day.

### Provider Layer (`app/services/providers/`)

`ProviderOrchestrator` manages parallel async calls to registered providers (Amap, SerpAPI, Mock). Key behaviors:
- Call budget limits per request
- In-memory TTL cache per provider
- Graceful degradation: failures append to `validation.assumptions` but don't break the pipeline
- Mock provider is always included as fallback (`include_mock_fallback=True`)

### Conversation & Revision Model (`app/services/conversation_service.py`)

MySQL-backed session state. Revision lineage: each edit creates a new revision with `base_revision_id` pointing to the parent. Self-referencing `revision_id == base_revision_id` is forbidden (enforced in schema). Full lineage validation is the database/service layer's responsibility.

### Intent Routing (`app/domain/travel/query_processor.py`)

Classifies user input into: `create | edit | qa | reset | chat`. The `edit` intent feeds into `patch_engine.py` (`apply_patch` / `parse_edit_ops`) for slot-level modifications (replace / delete / insert) without touching non-target days.

---

## Key Files

| File | Role |
|------|------|
| `llm_backend/app/lg_agent/travel_draft_graph.py` | 4-node graph definition, pipeline singletons, LLM prompt assembly |
| `llm_backend/app/api/travel.py` | All travel endpoints + SSE streaming logic (~40KB) |
| `llm_backend/app/schemas/itinerary_v1.py` | ItineraryV1 Pydantic schema + P0/P1/P2 field policy |
| `llm_backend/app/domain/travel/patch_engine.py` | Edit Day N patch parsing and application |
| `llm_backend/app/domain/travel/sse_envelope.py` | SSE event builder helpers |
| `llm_backend/app/services/providers/orchestrator.py` | Async provider dispatch, budgeting, TTL cache |
| `llm_backend/app/services/ranking_scorer.py` | Multi-dimensional POI scoring |
| `llm_backend/main.py` | FastAPI app, middleware, router registration, static file mount |
| `frontend/DsAgentChat_web/src/views/TravelPlanner.vue` | Main UI: dual-panel (chat left, itinerary right) |
| `frontend/DsAgentChat_web/src/services/api.ts` | SSE client + event handler wiring |

---

## Environment

Copy `.env.example` → `llm_backend/.env`. Minimum required:

```env
DEEPSEEK_API_KEY=your_api_key_here
DEEPSEEK_MODEL=deepseek-chat
OLLAMA_BASE_URL=http://localhost:11434
DATABASE_URL=mysql+aiomysql://user:pass@localhost:3306/travelmind
REDIS_URL=redis://localhost:6379/0
```

Service selection (affects which LLM client is used throughout):
```env
CHAT_SERVICE=deepseek   # or: ollama
AGENT_SERVICE=deepseek
```

Optional integrations (default OFF, fail-safe):
```env
ENABLE_GRAPHRAG_EXT=false
ENABLE_DEEPAGENTS=false
ENABLE_DEEPSEARCH=false
```

---

## Performance Targets

These are enforced by `tests/test_performance_regression.py` (all mocked, no real API calls):

| Node | Target |
|------|--------|
| `extract_node` | < 50ms |
| `recall_node` | < 5s |
| `llm_draft_node` | < 30s |
| `postprocess_node` | < 200ms |
| Full graph (prod) | < 40s |
| P0-missing early exit | < 2ms |
