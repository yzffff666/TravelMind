from __future__ import annotations


# Coarse destination bounds used only as a safety check to reject obvious cross-region POI matches.
# Values are intentionally wider than city administrative borders to allow nearby airports and day trips.
_DESTINATION_BOUNDS: dict[str, tuple[float, float, float, float]] = {
    "普吉": (7.3, 8.3, 97.9, 99.1),
    "普吉岛": (7.3, 8.3, 97.9, 99.1),
    "phuket": (7.3, 8.3, 97.9, 99.1),
    "曼谷": (13.4, 14.2, 100.1, 100.9),
    "bangkok": (13.4, 14.2, 100.1, 100.9),
    "东京": (35.3, 36.0, 139.3, 140.1),
    "tokyo": (35.3, 36.0, 139.3, 140.1),
    "大阪": (34.4, 35.0, 135.2, 135.8),
    "osaka": (34.4, 35.0, 135.2, 135.8),
    "京都": (34.7, 35.3, 135.4, 136.0),
    "kyoto": (34.7, 35.3, 135.4, 136.0),
    "首尔": (37.3, 37.8, 126.7, 127.2),
    "seoul": (37.3, 37.8, 126.7, 127.2),
    "新加坡": (1.1, 1.6, 103.5, 104.1),
    "singapore": (1.1, 1.6, 103.5, 104.1),
    "巴黎": (48.6, 49.1, 2.0, 2.7),
    "paris": (48.6, 49.1, 2.0, 2.7),
    "伦敦": (51.2, 51.8, -0.6, 0.3),
    "london": (51.2, 51.8, -0.6, 0.3),
    "罗马": (41.6, 42.1, 12.2, 12.8),
    "rome": (41.6, 42.1, 12.2, 12.8),
}


def destination_bounds(destination: str) -> tuple[float, float, float, float] | None:
    dest_lower = (destination or "").strip().lower()
    if not dest_lower:
        return None
    for key, bounds in _DESTINATION_BOUNDS.items():
        key_lower = key.lower()
        if key in destination or key_lower in dest_lower:
            return bounds
    return None


def is_coord_within_destination(destination: str, lat: float, lng: float) -> bool:
    bounds = destination_bounds(destination)
    if not bounds:
        return True
    min_lat, max_lat, min_lng, max_lng = bounds
    return min_lat <= lat <= max_lat and min_lng <= lng <= max_lng
