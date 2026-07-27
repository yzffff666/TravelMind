# Destination Generalization v1

## Goal

TravelMind must not turn weak destination data into a plausible but cross-city itinerary. The v1 contract is:

```text
destination -> resolved geographic profile -> local, coordinate-backed candidates
            -> candidate ranking/planning -> LLM expression
```

When the system cannot obtain at least three verified local candidates, it returns an explicit degraded response instead of letting the LLM fill the gap from general travel knowledge.

## Why This Is Not A Bigger BBox Table

Static bbox entries are a fast path for common destinations. Adding every city by hand would improve a demo list but would not generalize to long-tail cities or overseas destinations.

The selected approach separates two concerns:

| Layer | Choice | Trade-off |
| --- | --- | --- |
| Common-city safety | Static bbox | Fast and deterministic, but coverage is finite. |
| Long-tail destination resolution | Amap / Geoapify dynamic geocoding | Generalizes beyond the table, but depends on provider availability and latency. |
| Publish gate | At least 3 locally grounded candidates with valid coordinates | Prevents cross-city hallucinations, but can return a degraded response more often. |
| Evidence and media | Coverage metrics, not the location gate | Makes quality gaps visible without treating an image as proof of location. |
| Provider fallback | No Mock candidate counts as real live readiness | Honest about live coverage; development fixtures still remain useful. |

This is a candidate-decision safety design, not a claim that a language model can validate geography by itself.

## Acceptance Matrix

`llm_backend/evaluation/destination_readiness_cases.json` defines 12 deterministic cases:

- Static/common: Shenzhen, Hong Kong, Macau, Tokyo, Kyoto, San Francisco.
- Dynamic/long-tail: Jingdezhen, Dunhuang, Kashgar, Tromso, Hobart, Oaxaca.
- Cross-city decoys include Tokyo, Kyoto, Paris, and Shanghai POIs.
- Kashgar and Oaxaca intentionally have only two local candidates; safe degradation is the expected result.

Run it from the backend directory:

```bash
./.venv/bin/python -m scripts.destination_readiness_eval \
  --output-dir reports/destination-readiness-eval/latest
```

The gate passes only when all of these hold:

1. The correct static or dynamic profile resolves.
2. Cross-city decoys are excluded from publishable candidates.
3. Coordinate-less legacy candidates never count toward publishable candidates.
4. Ready cases have at least three local candidates.
5. Candidate-shortage cases return `insufficient_candidates`.
6. Ready fixture cases meet the evidence and image coverage signal thresholds.

The initial matrix result is `12/12` passed: 10 ready cases and 2 deliberate safe-degradation cases.

## Live Provider Boundary

The offline matrix proves the routing and safety contract, not that every external Provider currently has worldwide POI coverage. Use the live probe separately because it can consume quota:

```bash
./.venv/bin/python -m scripts.live_destination_grounding_probe \
  --allow-live \
  --output reports/live-destination-grounding-probe.json
```

The probe does not call an LLM or use Mock fallback. It records each Provider's configured key, cache, and live-call state separately, plus profile source, candidate source counts, coordinate-backed candidate count, evidence/media counts, and quality flags. `ready` means the city is safe to plan; `health_status=degraded` still exposes quota/provider/media weakness; `healthy` means neither is present in that run. A global readiness claim requires a real run with a global geocoder/provider enabled; a successful offline fixture run is not enough.

## Resulting Product Behavior

For a city with enough verified candidates, the planner receives grounded POIs and the LLM is used to organize and explain the itinerary. For a city without enough verified candidates, the user receives a clear data-availability message and no final itinerary is persisted. This favors a visible limitation over a confident but incorrect Kyoto-style cross-city plan.
