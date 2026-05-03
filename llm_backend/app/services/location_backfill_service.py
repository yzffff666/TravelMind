from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from hashlib import md5
from typing import Any

from app.core.logger import get_logger
from app.schemas.itinerary_v1 import EvidenceItem, ItineraryV1, Location
from app.services.geo_bounds import is_coord_within_destination
from app.services.providers.base import MapProvider
from app.services.providers.factory import build_registry

logger = logging.getLogger(__name__)
structured_logger = get_logger(service="location_backfill")

_CACHE_TTL_SECONDS = 3600
_cache: dict[str, tuple[float, dict | None]] = {}

_PLACE_ALIASES = {
    "普吉国际机场": ["Phuket International Airport"],
    "幻多奇主题乐园": ["Phuket FantaSea"],
    "皮皮岛": ["Phi Phi Islands"],
    "皇帝岛": ["Racha Island"],
    "芭东海滩": ["Patong Beach"],
    "卡塔海滩": ["Kata Beach"],
    "卡伦海滩": ["Karon Beach"],
    "普吉老镇": ["Old Phuket Town", "Phuket Old Town"],
}

_DEST_ALIASES = {
    "普吉岛": "Phuket",
    "东京": "Tokyo",
    "大阪": "Osaka",
    "京都": "Kyoto",
    "首尔": "Seoul",
    "新加坡": "Singapore",
    "罗马": "Rome",
    "巴黎": "Paris",
    "伦敦": "London",
}

_TRIM_SUFFIXES = (
    "附近餐厅",
    "内餐厅",
    "观景餐厅",
    "餐厅",
    "购物中心",
    "一日游行程",
    "码头集合点",
)


@dataclass
class BackfillReport:
    attempted: int = 0
    filled: int = 0
    unresolved: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)


@dataclass
class _CacheLookup:
    found: bool
    payload: dict | None = None


@dataclass
class _BackfillDiagnostics:
    fallback_reason: str = ""
    variants_tried: list[str] = field(default_factory=list)
    provider_status_counts: dict[str, int] = field(default_factory=dict)
    best_candidate_title: str | None = None
    best_match_score: float = 0.0
    candidate_count: int = 0
    rejected_bbox_count: int = 0
    rejected_score_count: int = 0
    rejected_missing_coord_count: int = 0
    cache_hit_count: int = 0
    cache_negative_hit_count: int = 0
    variant_limit_reached: bool = False

    def merge(self, other: "_BackfillDiagnostics") -> None:
        self.variants_tried.extend(other.variants_tried)
        for status, count in other.provider_status_counts.items():
            self.provider_status_counts[status] = self.provider_status_counts.get(status, 0) + count
        self.candidate_count += other.candidate_count
        self.rejected_bbox_count += other.rejected_bbox_count
        self.rejected_score_count += other.rejected_score_count
        self.rejected_missing_coord_count += other.rejected_missing_coord_count
        self.cache_hit_count += other.cache_hit_count
        self.cache_negative_hit_count += other.cache_negative_hit_count
        self.variant_limit_reached = self.variant_limit_reached or other.variant_limit_reached
        if other.best_match_score > self.best_match_score:
            self.best_match_score = other.best_match_score
            self.best_candidate_title = other.best_candidate_title

    def mark_status(self, status: str) -> None:
        self.provider_status_counts[status] = self.provider_status_counts.get(status, 0) + 1

    def as_log_extra(self) -> dict[str, Any]:
        return {
            "variants_tried": self.variants_tried,
            "provider_status_counts": self.provider_status_counts,
            "best_candidate_title": self.best_candidate_title,
            "best_match_score": round(self.best_match_score, 4),
            "candidate_count": self.candidate_count,
            "rejected_bbox_count": self.rejected_bbox_count,
            "rejected_score_count": self.rejected_score_count,
            "rejected_missing_coord_count": self.rejected_missing_coord_count,
            "cache_hit_count": self.cache_hit_count,
            "cache_negative_hit_count": self.cache_negative_hit_count,
            "variant_limit_reached": self.variant_limit_reached,
        }


@dataclass
class _ResolveResult:
    resolved: dict | None = None
    diagnostics: _BackfillDiagnostics = field(default_factory=_BackfillDiagnostics)


@dataclass
class _QueryResult:
    resolved: dict | None = None
    diagnostics: _BackfillDiagnostics = field(default_factory=_BackfillDiagnostics)


class LocationBackfillService:
    """Best-effort post-generation geocoding for slots still missing location."""

    def __init__(
        self,
        *,
        max_slots_per_request: int = 12,
        max_variants_per_place: int = 3,
        provider_timeout_seconds: float = 2.5,
        total_budget_seconds: float = 8.0,
        min_match_score: float = 0.72,
        max_concurrent_backfills: int = 4,
    ) -> None:
        registry = build_registry(include_mock_fallback=False)
        self._providers: list[MapProvider] = list(registry.map_providers)
        self._max_slots_per_request = max_slots_per_request
        self._max_variants_per_place = max_variants_per_place
        self._provider_timeout_seconds = provider_timeout_seconds
        self._total_budget_seconds = total_budget_seconds
        self._min_match_score = min_match_score
        self._max_concurrent_backfills = max(1, max_concurrent_backfills)

    async def backfill_itinerary(self, itinerary: ItineraryV1) -> BackfillReport:
        if not self._providers:
            report = BackfillReport()
            report.assumptions.append("未配置真实地图数据源，缺失坐标无法回填。")
            self._log_backfill_summary(itinerary, report, elapsed_ms=0.0)
            return report

        pending_slots = self._collect_pending_slots(itinerary)
        return await self._backfill_slots(itinerary, pending_slots)

    async def backfill_changed_days(
        self,
        itinerary: ItineraryV1,
        changed_days: list[int],
    ) -> BackfillReport:
        if not self._providers:
            report = BackfillReport()
            report.assumptions.append("未配置真实地图数据源，缺失坐标无法回填。")
            self._log_backfill_summary(itinerary, report, elapsed_ms=0.0)
            return report

        changed = set(changed_days or [])
        if not changed:
            return BackfillReport()

        pending_slots = [
            slot
            for day in itinerary.days
            if day.day_index in changed
            for slot in day.slots
            if slot.location is None and (slot.place or slot.activity)
        ][: self._max_slots_per_request]
        return await self._backfill_slots(itinerary, pending_slots)

    async def _backfill_slots(self, itinerary: ItineraryV1, pending_slots: list) -> BackfillReport:
        report = BackfillReport()
        started = time.perf_counter()

        destination_raw = itinerary.trip_profile.destination_city or ""
        destination = _DEST_ALIASES.get(destination_raw, destination_raw)

        jobs: list[tuple[object, str, int | None]] = []
        for slot in pending_slots:
            if time.perf_counter() - started >= self._total_budget_seconds:
                report.assumptions.append("坐标回填已达到本次请求时延预算，剩余地点保留为空。")
                break

            place = (slot.place or slot.activity or "").strip()
            if not place:
                continue
            report.attempted += 1
            jobs.append((slot, place, self._find_day_index(itinerary, slot)))

        semaphore = asyncio.Semaphore(self._max_concurrent_backfills)

        async def resolve_job(place: str) -> _ResolveResult:
            async with semaphore:
                remaining = self._remaining_budget(started)
                if remaining <= 0:
                    return _ResolveResult(
                        diagnostics=_BackfillDiagnostics(fallback_reason="total_budget_exhausted")
                    )
                try:
                    return await asyncio.wait_for(
                        self._resolve_place(place, destination, started),
                        timeout=remaining,
                    )
                except asyncio.TimeoutError:
                    return _ResolveResult(
                        diagnostics=_BackfillDiagnostics(fallback_reason="total_budget_exhausted")
                    )

        results = await asyncio.gather(*(resolve_job(place) for _, place, _ in jobs))

        for (slot, place, day_index), result in zip(jobs, results):
            resolved = result.resolved
            diagnostics = result.diagnostics
            if not resolved:
                report.unresolved.append(place)
                self._log_location_backfill(
                    itinerary=itinerary,
                    slot=slot,
                    place=place,
                    destination=destination,
                    day_index=day_index,
                    resolved=None,
                    elapsed_ms=self._elapsed_ms(started),
                    fallback_reason=diagnostics.fallback_reason or "provider_empty",
                    diagnostics=diagnostics,
                )
                continue

            slot.location = Location(lat=resolved["lat"], lng=resolved["lng"])
            if resolved.get("image_url") and not slot.image_url:
                slot.image_url = str(resolved["image_url"])
            self._attach_evidence(itinerary, slot, place, resolved)
            report.filled += 1
            self._log_location_backfill(
                itinerary=itinerary,
                slot=slot,
                place=place,
                destination=destination,
                day_index=day_index,
                resolved=resolved,
                elapsed_ms=self._elapsed_ms(started),
                diagnostics=diagnostics,
            )

        if report.filled:
            report.assumptions.append(
                f"已对 {report.filled} 个缺失地点执行坐标回填，地图展示稳定性已提升。"
            )
        if report.unresolved:
            sample = "、".join(report.unresolved[:3])
            report.assumptions.append(
                f"仍有 {len(report.unresolved)} 个地点未匹配到可靠坐标，例如：{sample}。"
            )
        self._log_backfill_summary(itinerary, report, elapsed_ms=self._elapsed_ms(started))
        return report

    def _remaining_budget(self, started: float) -> float:
        return max(0.0, self._total_budget_seconds - (time.perf_counter() - started))

    def _collect_pending_slots(self, itinerary: ItineraryV1) -> list:
        """
        Select missing-location slots with day coverage priority.

        Stage 1: pick one pending slot per day.
        Stage 2: fill the remaining quota with other pending slots in order.
        """
        day_heads: list = []
        all_pending: list = []
        for day in itinerary.days:
            day_pending = [
                slot
                for slot in day.slots
                if slot.location is None and (slot.place or slot.activity)
            ]
            if day_pending:
                day_heads.append(day_pending[0])
                all_pending.extend(day_pending)

        selected: list = []
        seen_ids: set[int] = set()
        for slot in day_heads + all_pending:
            sid = id(slot)
            if sid in seen_ids:
                continue
            selected.append(slot)
            seen_ids.add(sid)
            if len(selected) >= self._max_slots_per_request:
                break
        return selected

    async def _resolve_place(self, place: str, destination: str, started: float) -> _ResolveResult:
        all_variants = self._build_variants(place, destination)
        variants = all_variants[: self._max_variants_per_place]
        diagnostics = _BackfillDiagnostics(
            variant_limit_reached=len(all_variants) > len(variants)
        )
        for variant in variants:
            if time.perf_counter() - started >= self._total_budget_seconds:
                diagnostics.fallback_reason = "total_budget_exhausted"
                return _ResolveResult(diagnostics=diagnostics)

            cache_key = f"{destination.lower()}|{variant.lower()}"
            cached = self._get_cache(cache_key)
            diagnostics.variants_tried.append(variant)
            if cached.found:
                if cached.payload:
                    diagnostics.cache_hit_count += 1
                    return _ResolveResult(resolved=cached.payload, diagnostics=diagnostics)
                diagnostics.cache_negative_hit_count += 1
                continue

            query_result = await self._query_best_candidate(place, destination, variant)
            diagnostics.merge(query_result.diagnostics)
            self._set_cache(cache_key, query_result.resolved)
            if query_result.resolved:
                return _ResolveResult(resolved=query_result.resolved, diagnostics=diagnostics)
        diagnostics.fallback_reason = self._choose_fallback_reason(diagnostics)
        return _ResolveResult(diagnostics=diagnostics)

    async def _query_best_candidate(self, place: str, destination: str, variant: str) -> _QueryResult:
        best: dict | None = None
        best_score = 0.0
        diagnostics = _BackfillDiagnostics()
        for provider in self._providers:
            try:
                response = await asyncio.wait_for(
                    provider.nearby_poi(
                        city=destination,
                        keywords=[variant],
                        top_k=5,
                        context=None,
                    ),
                    timeout=self._provider_timeout_seconds,
                )
            except asyncio.TimeoutError:
                diagnostics.mark_status("timeout")
                logger.warning("Location backfill provider %s timed out for %s", provider.name, variant)
                continue
            except Exception as exc:  # noqa: BLE001
                diagnostics.mark_status("error")
                logger.warning("Location backfill provider %s failed for %s: %s", provider.name, variant, exc)
                continue

            if not response.candidates:
                diagnostics.mark_status("empty")
                continue

            diagnostics.mark_status("success")
            for candidate in response.candidates:
                diagnostics.candidate_count += 1
                lat = self._to_float(candidate.extra.get("lat"))
                lng = self._to_float(candidate.extra.get("lng"))
                if lat is None or lng is None:
                    diagnostics.rejected_missing_coord_count += 1
                    continue
                score = max(
                    self._match_score(place, candidate.title or "", candidate.extra.get("address", "")),
                    self._match_score(variant, candidate.title or "", candidate.extra.get("address", "")),
                )
                if score > diagnostics.best_match_score:
                    diagnostics.best_match_score = score
                    diagnostics.best_candidate_title = candidate.title
                if not is_coord_within_destination(destination, lat, lng):
                    diagnostics.rejected_bbox_count += 1
                    logger.info(
                        "Location backfill rejected out-of-bounds candidate %s for %s: %s,%s",
                        candidate.title,
                        destination,
                        lat,
                        lng,
                    )
                    continue

                if score < self._min_match_score or score <= best_score:
                    diagnostics.rejected_score_count += 1
                    continue

                photos = candidate.extra.get("photos") or []
                best = {
                    "lat": lat,
                    "lng": lng,
                    "image_url": candidate.extra.get("thumbnail") or (photos[0] if photos else None),
                    "provider": candidate.source,
                    "title": candidate.title,
                    "snippet": candidate.snippet,
                    "address": candidate.extra.get("address"),
                    "rating": candidate.extra.get("rating"),
                    "cost_estimate": candidate.extra.get("cost_estimate"),
                    "url": candidate.extra.get("url"),
                    "candidate_id": candidate.candidate_id,
                    "match_score": score,
                }
                best_score = score
        return _QueryResult(resolved=best, diagnostics=diagnostics)

    @staticmethod
    def _choose_fallback_reason(diagnostics: _BackfillDiagnostics) -> str:
        statuses = diagnostics.provider_status_counts
        if diagnostics.cache_negative_hit_count and not statuses:
            return "cache_negative_hit"
        if diagnostics.rejected_bbox_count:
            return "bbox_rejected"
        if diagnostics.rejected_score_count:
            return "score_rejected"
        if statuses.get("timeout") and not diagnostics.candidate_count:
            return "provider_timeout"
        if statuses.get("error") and not diagnostics.candidate_count:
            return "provider_error"
        if diagnostics.variant_limit_reached:
            return "variant_limit_exhausted"
        if statuses.get("empty") or not statuses:
            return "provider_empty"
        return "provider_empty"

    @staticmethod
    def _find_day_index(itinerary: ItineraryV1, target_slot) -> int | None:
        for day in itinerary.days:
            if any(slot is target_slot for slot in day.slots):
                return day.day_index
        return None

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 2)

    def _log_location_backfill(
        self,
        *,
        itinerary: ItineraryV1,
        slot,
        place: str,
        destination: str,
        day_index: int | None,
        resolved: dict | None,
        elapsed_ms: float,
        fallback_reason: str = "",
        diagnostics: _BackfillDiagnostics | None = None,
    ) -> None:
        lat = resolved.get("lat") if resolved else None
        lng = resolved.get("lng") if resolved else None
        bbox_valid = (
            is_coord_within_destination(destination, lat, lng)
            if lat is not None and lng is not None
            else False
        )
        match_score = float(resolved.get("match_score") or 0.0) if resolved else 0.0
        log_extra = {
            "event_type": "location_backfill",
            "itinerary_id": itinerary.itinerary_id,
            "revision_id": itinerary.revision_id,
            "day_index": day_index,
            "slot_label": getattr(slot, "slot", None),
            "activity": getattr(slot, "activity", None),
            "place": place,
            "destination": destination,
            "candidate_title": resolved.get("title") if resolved else None,
            "lat": lat,
            "lng": lng,
            "source": "provider" if resolved else "unresolved",
            "confidence": self._confidence_label(match_score) if resolved else "low",
            "elapsed_ms": elapsed_ms,
            "fallback_reason": fallback_reason,
            "bbox_valid": bbox_valid,
        }
        if diagnostics:
            log_extra.update(diagnostics.as_log_extra())
        structured_logger.info(
            "location_backfill",
            extra=log_extra,
        )

    @staticmethod
    def _confidence_label(match_score: float) -> str:
        if match_score >= 0.9:
            return "high"
        if match_score >= 0.8:
            return "medium"
        return "low"

    @staticmethod
    def _log_backfill_summary(
        itinerary: ItineraryV1,
        report: BackfillReport,
        *,
        elapsed_ms: float,
    ) -> None:
        total_slots = sum(len(day.slots) for day in itinerary.days)
        slots_with_location = sum(
            1
            for day in itinerary.days
            for slot in day.slots
            if slot.location is not None
        )
        structured_logger.info(
            "itinerary_quality_summary",
            extra={
                "event_type": "itinerary_quality_summary",
                "itinerary_id": itinerary.itinerary_id,
                "revision_id": itinerary.revision_id,
                "destination": itinerary.trip_profile.destination_city,
                "days_count": len(itinerary.days),
                "total_slots": total_slots,
                "slots_with_location": slots_with_location,
                "fallback_slots": 0,
                "bbox_invalid_slots": 0,
                "coverage_score": itinerary.validation.coverage_score,
                "backfill_elapsed_ms": elapsed_ms,
                "backfill_attempted": report.attempted,
                "backfill_filled": report.filled,
                "backfill_unresolved": len(report.unresolved),
                "degraded": bool(report.unresolved),
            },
        )

    @staticmethod
    def _attach_evidence(
        itinerary: ItineraryV1,
        slot,
        place: str,
        resolved: dict,
    ) -> None:
        provider = str(resolved.get("provider") or "map_backfill")
        title = str(resolved.get("title") or place).strip()
        candidate_id = str(
            resolved.get("candidate_id")
            or md5(f"{provider}:{title}".encode()).hexdigest()[:12]
        )
        evidence_id = f"ev-{candidate_id}"

        if evidence_id not in {item.evidence_id for item in itinerary.evidence}:
            snippet_parts = [
                str(resolved.get("snippet") or "").strip(),
                str(resolved.get("address") or "").strip(),
            ]
            snippet = " | ".join(part for part in snippet_parts if part) or None
            itinerary.evidence.append(EvidenceItem(
                evidence_id=evidence_id,
                provider=provider,
                source_type="map",
                title=title or None,
                url=resolved.get("url") or None,
                snippet=snippet,
                fetched_at=datetime.now(timezone.utc).isoformat(),
                attribution="数据来源：地图 POI 回填",
                confidence=0.7,
                rating=float(resolved["rating"]) if resolved.get("rating") not in (None, "", 0) else None,
                cost_estimate=float(resolved["cost_estimate"]) if resolved.get("cost_estimate") not in (None, "") else None,
            ))
        if evidence_id not in slot.evidence_refs:
            slot.evidence_refs.append(evidence_id)

    def _build_variants(self, place: str, destination: str) -> list[str]:
        raw = (place or "").strip()
        variants: list[str] = []

        def add(v: str) -> None:
            v = re.sub(r"\s+", " ", v).strip(" ,，")
            if v and v not in variants:
                variants.append(v)

        add(raw)

        stripped = re.sub(r"[（(].*?[)）]", "", raw).strip()
        add(stripped)

        temporal_prefix_stripped = re.sub(r"^(?:19|20)\d{2}\s*", "", stripped).strip()
        add(temporal_prefix_stripped)

        simplified = temporal_prefix_stripped
        for suffix in _TRIM_SUFFIXES:
            if simplified.endswith(suffix):
                simplified = simplified[: -len(suffix)].strip()
        add(simplified)

        for alias in _PLACE_ALIASES.get(simplified, []):
            add(alias)

        if destination:
            add(f"{simplified} {destination}")
            add(f"{raw} {destination}")
        return variants

    @staticmethod
    def _match_score(place: str, title: str, address: str) -> float:
        p = LocationBackfillService._normalize(place)
        t = LocationBackfillService._normalize(title)
        a = LocationBackfillService._normalize(address)

        if not p or not t:
            return 0.0
        if p == t:
            return 1.0
        if p in t or t in p:
            return 0.92
        if a and (p in a or t in a):
            return 0.8
        return SequenceMatcher(None, p, t).ratio()

    @staticmethod
    def _normalize(value: str) -> str:
        value = value.lower().strip()
        value = re.sub(r"[（(].*?[)）]", "", value)
        value = re.sub(r"^(?:19|20)\d{2}\s*", "", value)
        value = re.sub(r"附近餐厅|内餐厅|观景餐厅|购物中心|一日游行程", "", value)
        value = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value)
        return value

    @staticmethod
    def _to_float(value: object) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _get_cache(key: str) -> _CacheLookup:
        cached = _cache.get(key)
        if not cached:
            return _CacheLookup(found=False)
        ts, payload = cached
        if time.time() - ts >= _CACHE_TTL_SECONDS:
            del _cache[key]
            return _CacheLookup(found=False)
        return _CacheLookup(found=True, payload=payload)

    @staticmethod
    def _set_cache(key: str, payload: dict | None) -> None:
        _cache[key] = (time.time(), payload)
