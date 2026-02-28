# TravelMind

TravelMind is a conversational travel-planning agent focused on **editable, evidence-aware itineraries**.

## Vision

Build a travel assistant that is:
- **Conversational**: users can create, edit, ask, and reset in one session.
- **Structured**: output is a schema-based itinerary (`itinerary v1`) instead of plain text only.
- **Explainable**: recommendations can be traced with evidence and sources.
- **Practical**: supports budget/risk constraints and iterative planning.

## Product Scope (MVP)

- Multi-turn planning with session state
- Structured itinerary generation (`days` + `slots`)
- Clarification flow for missing hard constraints (destination/duration/budget)
- SSE streaming events for frontend real-time feedback
- Revision-oriented evolution toward diff/patch editing

Not included in MVP:
- Booking/payment fulfillment
- OTA-grade real-time guarantee

## Architecture Principles

- **Single control plane**: LangGraph is the only orchestrator and state truth.
- **Layered capability model**:
  - Control: clarification, routing, SSE, revision flow
  - Retrieval stack: QP -> Recall -> Ranking -> Rule Filter -> Evidence Builder
  - Optional enhancements: DeepResearch / DeepAgents behind feature flags
- **Provider abstraction first**: business logic should not be tightly coupled to vendor SDK fields.

## Current Progress (M2 snapshot)

Completed recently:
- Provider abstraction baseline (`SearchProvider/MapProvider/WeatherProvider/ReviewProvider`)
- QP baseline (`intent + constraints + recall_query`)
- Conversation-level itinerary state persistence
- Intent routing baseline (`create/edit/qa/reset`) with reset path

## Suggested Development Roadmap

- **M1**: first usable structured itinerary flow
- **M2**: conversational co-creation core loop
- **M3**: Edit Day N + revision/diff reliability
- **M4**: engineering quality (tests, export, observability)

## Local Validation Checklist

- Run schema and SSE tests
- Run intent-routing tests
- Verify create / clarification / reset behavior manually via API

## Notes

This repository tracks the project direction and documentation-first engineering decisions for TravelMind.
