"""Chain-of-rules hard constraint filter for ranked candidates.

Design reference: ``docs/下层能力流水线技术方案.md`` §4.4

Rules execute sequentially (budget → pace → distance). Every rule
runs on every candidate (no short-circuit) so we collect ALL rejection
reasons per candidate.

When too few candidates survive, the filter relaxes thresholds and
appends an assumption explaining the relaxation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import radians, sin, cos, sqrt, atan2
from typing import Any

from app.services.ranking_scorer import ScoredCandidate


@dataclass(slots=True)
class FilterConfig:
    """Tunable thresholds for each filter rule."""

    budget_ratio_limit: float = 0.4
    pace_limits: dict[str, int] = field(default_factory=lambda: {
        "relaxed": 3,
        "moderate": 4,
        "intensive": 6,
    })
    default_pace: str = "moderate"
    distance_km_limit: float = 50.0
    min_survivors: int = 3
    relaxation_budget_ratio: float = 0.6
    relaxation_distance_km: float = 80.0


DEFAULT_FILTER_CONFIG = FilterConfig()


@dataclass(slots=True)
class FilteredCandidate:
    """Wrapper adding rejection info to a scored candidate."""

    scored: ScoredCandidate
    rejected: bool = False
    reject_reasons: list[str] = field(default_factory=list)


@dataclass
class FilterResult:
    """Output of the constraint filter step."""

    accepted: list[ScoredCandidate] = field(default_factory=list)
    rejected: list[FilteredCandidate] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    relaxed: bool = False


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two points in km."""
    r = 6371.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return r * 2 * atan2(sqrt(a), sqrt(1 - a))


class ConstraintFilter:
    """Applies chain-of-rules hard constraint filtering.

    Usage::

        flt = ConstraintFilter()
        result = flt.apply(
            scored_candidates=ranked,
            budget=6000, days=4, pace="moderate",
            city_center=(31.23, 121.47),
        )
    """

    def __init__(self, config: FilterConfig | None = None) -> None:
        self._cfg = config or DEFAULT_FILTER_CONFIG

    def apply(
        self,
        scored_candidates: list[ScoredCandidate],
        *,
        budget: float | None = None,
        days: int | None = None,
        pace: str | None = None,
        city_center: tuple[float, float] | None = None,
    ) -> FilterResult:
        if not scored_candidates:
            return FilterResult()

        daily_budget = None
        if budget is not None and days and days > 0:
            daily_budget = budget / days

        pace_key = (pace or self._cfg.default_pace).lower()
        if pace_key not in self._cfg.pace_limits:
            pace_key = self._cfg.default_pace
        pace_limit = self._cfg.pace_limits[pace_key]

        wrapped = [FilteredCandidate(scored=sc) for sc in scored_candidates]

        self._budget_filter(wrapped, daily_budget, self._cfg.budget_ratio_limit)
        self._pace_filter(wrapped, pace_limit)
        self._distance_filter(wrapped, city_center, self._cfg.distance_km_limit)

        accepted = [w.scored for w in wrapped if not w.rejected]
        rejected = [w for w in wrapped if w.rejected]
        assumptions: list[str] = []

        if len(accepted) < self._cfg.min_survivors and rejected:
            assumptions.append(
                f"过滤后仅剩 {len(accepted)} 个候选（低于最低要求 {self._cfg.min_survivors}），"
                "已放宽过滤阈值，部分结果可能不完全满足硬约束。"
            )
            wrapped = [FilteredCandidate(scored=sc) for sc in scored_candidates]
            self._budget_filter(wrapped, daily_budget, self._cfg.relaxation_budget_ratio)
            self._pace_filter(wrapped, pace_limit + 2)
            self._distance_filter(wrapped, city_center, self._cfg.relaxation_distance_km)

            accepted = [w.scored for w in wrapped if not w.rejected]
            rejected = [w for w in wrapped if w.rejected]

        result = FilterResult(
            accepted=accepted,
            rejected=rejected,
            assumptions=assumptions,
            relaxed=bool(assumptions),
        )
        return result

    def apply_from_qp(
        self,
        scored_candidates: list[ScoredCandidate],
        qp_output: dict[str, Any],
        *,
        city_center: tuple[float, float] | None = None,
    ) -> FilterResult:
        """Convenience: filter using structured QP output dict."""
        constraints = qp_output.get("constraints", {})
        return self.apply(
            scored_candidates,
            budget=constraints.get("budget"),
            days=constraints.get("days"),
            pace=constraints.get("pace"),
            city_center=city_center,
        )

    # ------------------------------------------------------------------
    # Individual filter rules
    # ------------------------------------------------------------------

    @staticmethod
    def _budget_filter(
        candidates: list[FilteredCandidate],
        daily_budget: float | None,
        ratio_limit: float,
    ) -> None:
        """Reject candidates whose cost exceeds ``ratio_limit`` of daily budget."""
        if daily_budget is None or daily_budget <= 0:
            return
        threshold = daily_budget * ratio_limit
        for w in candidates:
            cost = w.scored.candidate.extra.get("cost_estimate", 0.0)
            if cost and cost > threshold:
                w.rejected = True
                w.reject_reasons.append(
                    f"单项费用 {cost:.0f} 元超出日预算 {daily_budget:.0f} 元的 "
                    f"{ratio_limit:.0%}（阈值 {threshold:.0f} 元）"
                )

    @staticmethod
    def _pace_filter(
        candidates: list[FilteredCandidate],
        max_per_day: int,
    ) -> None:
        """If total non-rejected candidates exceed pace limit, reject lowest-scored extras."""
        alive = [w for w in candidates if not w.rejected]
        if len(alive) <= max_per_day:
            return
        alive.sort(key=lambda w: w.scored.total_score, reverse=True)
        for w in alive[max_per_day:]:
            w.rejected = True
            w.reject_reasons.append(
                f"节奏超载：候选数 {len(alive)} 超出节奏上限 {max_per_day}，"
                f"排名靠后被移除（得分 {w.scored.total_score:.3f}）"
            )

    @staticmethod
    def _distance_filter(
        candidates: list[FilteredCandidate],
        city_center: tuple[float, float] | None,
        km_limit: float,
    ) -> None:
        """Reject candidates too far from city center (if coordinates available)."""
        if city_center is None:
            return
        center_lat, center_lng = city_center
        for w in candidates:
            if w.rejected:
                continue
            lat = w.scored.candidate.extra.get("lat")
            lng = w.scored.candidate.extra.get("lng")
            if lat is None or lng is None:
                continue
            dist = _haversine_km(center_lat, center_lng, float(lat), float(lng))
            if dist > km_limit:
                w.rejected = True
                w.reject_reasons.append(
                    f"距离过远：距市中心 {dist:.1f} km，超出阈值 {km_limit:.0f} km"
                )
