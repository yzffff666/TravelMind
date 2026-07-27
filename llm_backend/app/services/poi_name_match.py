"""Small, provider-agnostic POI name matcher for explicit user requests.

This intentionally does not contain city-specific aliases.  Explicit POI edits
need a conservative verification boundary: a provider candidate may be used
only when its title is an exact or near-exact rendering of the place the user
named.  Destination grounding remains a separate responsibility.
"""
from __future__ import annotations

import re
import unicodedata


def normalize_poi_name(value: object) -> str:
    """Normalize punctuation, case, and parenthetical provider suffixes."""
    text = unicodedata.normalize("NFKC", str(value or "")).lower().strip()
    text = re.sub(r"[（(].*?[)）]", "", text)
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


def poi_name_match_score(requested_name: str, candidate_title: str) -> float:
    """Return a conservative [0, 1] title-match score for a named POI."""
    requested = normalize_poi_name(requested_name)
    candidate = normalize_poi_name(candidate_title)
    if not requested or not candidate:
        return 0.0
    if requested == candidate:
        return 1.0
    if requested in candidate or candidate in requested:
        return 0.92

    return 0.0


def is_verified_poi_name_match(requested_name: str, candidate_title: str) -> bool:
    """Accept only exact or containment-level matches; fuzzy similarity is unsafe here."""
    return poi_name_match_score(requested_name, candidate_title) >= 0.90
