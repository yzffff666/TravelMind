# Overseas Candidate Supply v1 Design

## 1. Goal

Close the gap between offline unseen-destination fixtures and live overseas
candidate supply without adding city-specific production configuration.

The target holdout matrix is:

| Destination | Expected result |
| --- | --- |
| Tromso | ready |
| Hobart | ready |
| Valletta | ready |
| Oaxaca | explicit insufficient-candidates degradation |

`ready` means at least three real, publishable POIs with valid coordinates and
no cross-city or Mock candidates.

## 2. Evidence And Root Cause

The July 22 live probe resolved three of four destination profiles but produced
zero ready overseas destinations:

- Tromso: nine candidates, all rejected by locality or radius checks.
- Hobart: twenty candidates, only two accepted; accepted values were locality
  records rather than useful POIs.
- Valletta: destination profile unresolved.
- Oaxaca: safely degraded as expected.

The cached requests expose two provider-boundary problems:

1. `GeoapifySearchProvider` uses forward geocoding as general POI search.
   General travel text therefore returns cities, districts, and globally
   ambiguous names rather than a bounded POI set.
2. `GeoapifyMapProvider` sends concatenated generic keywords such as
   `文化景点 博物馆 历史街区 景点 公园` through the Places `name` parameter.
   `name` is intended for a concrete place name, so the request returns no
   Places results.

Additional data-contract problems amplify the failure:

- Places fetch radius is 120 km while publication grounding radius is 40 km.
- Candidate conversion preserves only `city` and discards useful locality
  fields such as `suburb`, `district`, `county`, `municipality`, and `state`.
- Destination profiles cannot retain administrative context because those
  fields are missing from the provider candidate.

## 3. Options

### Option A: Provider-semantic correction (selected)

Use geocoding only for destination or explicit-name resolution. Use Places
category plus spatial filters for generic travel recall. Preserve provider
locality metadata and apply the existing hard gate over normalized locality
terms and distance.

This fixes the general mechanism, keeps safety boundaries, and produces useful
candidate data for the later learned-ranker milestone.

### Option B: Loosen destination hard gates

Accept every candidate within a larger radius and ignore locality mismatch.
This can increase recall quickly but reintroduces the cross-city itinerary bug.
It is rejected.

### Option C: Add bbox, aliases, and POI lists for the four holdouts

This can make the fixed demo pass but violates the open-world requirement and
does not improve a fifth unseen city. It is rejected.

## 4. Design

### 4.1 Retrieval intent

Geoapify has two runtime roles:

- forward geocoding: resolve a destination or explicit named POI;
- Places: retrieve category POIs around a resolved city center.

The application provider registry will not expose forward geocoding as a
general search provider. `GeoapifySearchProvider` remains available to
`DestinationResolver`, while `GeoapifyMapProvider` supplies itinerary
candidates.

### 4.2 Generic and explicit Places queries

Generic map keywords are translated to provider categories. Generic retrieval
does not send `name`.

Examples:

```text
景点 / 文化 / 历史 -> tourism, entertainment.culture
博物馆 / museum   -> entertainment.museum
公园 / park       -> leisure.park
美食 / restaurant -> catering
海滩 / beach      -> beach
```

An explicit named POI query keeps `name`, but still uses a city-centered spatial
filter. This preserves local-edit behavior such as "第三天去迪士尼".

The category keys and request semantics follow the official Geoapify Places API:
https://apidocs.geoapify.com/docs/places/

### 4.3 Radius alignment

The map provider radius is derived from
`DESTINATION_GROUNDING_RADIUS_KM * 1000`. Recall and publication therefore use
the same geographic boundary. A future destination-profile-specific radius can
replace this process-level value without changing the provider contract.

### 4.4 Locality contract

Provider candidates retain:

```text
city
suburb
district
county
municipality
state
state_code
country
country_code
```

Destination profiles use the best matching locality as canonical name and
retain the nearest parent administrative area. Grounding compares the
normalized candidate locality set with profile match terms only after the
distance check.

Diacritics are normalized through the existing Unicode normalization, so
`Tromso` and `Tromsø` match without a city alias.

### 4.5 Safe degradation

The hard gate remains authoritative:

- invalid or missing coordinates are rejected;
- candidates outside the destination radius are rejected;
- explicit contradictory locality metadata is rejected;
- Mock candidates are never publishable;
- fewer than three publishable real candidates produces
  `insufficient_candidates`.

No LLM-generated POI is substituted when provider supply is insufficient.

## 5. Verification

### Offline unit and integration tests

- generic Places requests omit `name` and use mapped categories;
- explicit named-POI requests retain `name`;
- Geoapify geocoding is not registered as general search recall;
- provider candidates retain administrative locality fields;
- normalized locality matching accepts diacritics and valid parent areas;
- radius configuration is aligned;
- cross-city decoys remain rejected.

### Replay gate

Sanitized provider fixtures cover:

- three ready overseas destinations with at least three publishable POIs each;
- Oaxaca safe degradation;
- no Mock publication;
- no cross-city publication.

### Live acceptance

Run the targeted probe with bounded Geoapify live calls:

```text
Tromso   -> ready, at least 3 real POIs
Hobart   -> ready, at least 3 real POIs
Valletta -> ready, at least 3 real POIs
Oaxaca   -> insufficient_candidates
```

If the external provider is unavailable, the cached replay gate remains the
deterministic regression source and the live report records the environmental
failure separately.

### Regression

- Geoapify/provider and destination-grounding tests pass.
- Full backend suite passes.
- Existing 14-gate milestone remains green.

## 6. Out Of Scope

- city-specific aliases or bbox entries for the holdouts;
- image coverage improvements;
- SerpAPI live fallback expansion;
- learned ranking;
- frontend visual changes.

The next milestone after this one is candidate review data accumulation and a
small learned-ranker probe.
