"""Deterministic four-scenario journey acceptance gate for TravelMind."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from app.domain.travel.conversation_runtime import (
    ConversationDecisionService,
    ConversationRuntimeSnapshot,
    apply_transition,
)
from app.domain.travel.query_processor import TravelQueryProcessor
from app.domain.travel.sse_envelope import build_event_envelope, build_event_line
from app.services.candidate_publishability import evaluate_candidate_publishability
from app.services.destination_grounding import DestinationProfile
from app.services.itinerary_planner import ConstraintAwareItineraryPlanner
from app.services.poi_ranking_policy import (
    POIRankingPolicy,
    apply_learned_ranking,
    select_runtime_ranking,
)
from app.services.providers.base import ProviderCandidate
from app.services.ranking_scorer import RankingScorer


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES_PATH = BACKEND_ROOT / "evaluation/demo_journey_cases.json"
DEFAULT_OUTPUT_DIR = Path("reports/demo-journey-eval/latest")
EXPECTED_CATEGORIES = {
    "domestic_long_tail",
    "overseas_unseen",
    "destination_switch_edits",
    "insufficient_candidates",
}
REQUIRED_ROLES = {
    "domestic_long_tail": {"create", "qa", "edit"},
    "overseas_unseen": {"create", "qa", "edit"},
    "destination_switch_edits": {"create", "qa", "switch", "edit"},
    "insufficient_candidates": {"degrade"},
}
SAFETY_METRICS = (
    "qa_revision_mutations",
    "wrong_edit_targets",
    "non_target_mutations",
    "stale_destination_candidates",
    "cross_city_published",
    "mock_published",
    "unsafe_final_itinerary_on_degrade",
    "missing_terminal_events",
    "revision_lineage_failures",
)
TERMINAL_EVENTS = {"final_itinerary", "final_text"}


def load_cases(path: Path = DEFAULT_CASES_PATH) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("demo journey cases must be a JSON list")
    return payload


def validate_case_contract(cases: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    if len(cases) != 4:
        errors.append(f"expected exactly 4 scenarios, got {len(cases)}")

    case_ids = [str(case.get("case_id") or "") for case in cases]
    if len(set(case_ids)) != len(case_ids) or any(not value for value in case_ids):
        errors.append("case_id values must be non-empty and unique")

    categories = {str(case.get("category") or "") for case in cases}
    if categories != EXPECTED_CATEGORIES:
        errors.append(
            f"category set mismatch: expected={sorted(EXPECTED_CATEGORIES)} "
            f"actual={sorted(categories)}"
        )

    for case in cases:
        case_id = str(case.get("case_id") or "unknown")
        category = str(case.get("category") or "")
        if not str(case.get("destination") or "").strip():
            errors.append(f"{case_id} destination must not be empty")
        center = case.get("center")
        if (
            not isinstance(center, list)
            or len(center) != 2
            or not all(isinstance(value, (int, float)) for value in center)
        ):
            errors.append(f"{case_id} center must be [lat, lng]")
        if int(case.get("days") or 0) < 1:
            errors.append(f"{case_id} days must be positive")

        turns = list(case.get("turns") or [])
        roles = [str(turn.get("role") or "") for turn in turns]
        missing_roles = REQUIRED_ROLES.get(category, set()) - set(roles)
        if missing_roles:
            errors.append(f"{case_id} missing turn roles: {sorted(missing_roles)}")
        if category == "destination_switch_edits" and roles.count("edit") < 2:
            errors.append(f"{case_id} must contain two consecutive edits")
        for index, turn in enumerate(turns, start=1):
            if not str(turn.get("query") or "").strip():
                errors.append(f"{case_id} turn {index} query must not be empty")

        candidate_ids: list[str] = []
        for group_name in ("candidates", "switch_candidates", "edit_candidates"):
            for index, candidate in enumerate(case.get(group_name) or [], start=1):
                candidate_id = str(candidate.get("candidate_id") or "")
                candidate_ids.append(candidate_id)
                role = str(candidate.get("role") or "")
                source = str(candidate.get("source") or "")
                if not candidate_id:
                    errors.append(f"{case_id} {group_name} row {index} missing candidate_id")
                if role not in {"local", "cross_city", "mock"}:
                    errors.append(
                        f"{case_id} {candidate_id or index} has invalid role {role!r}"
                    )
                if role == "local" and source.lower().startswith("mock"):
                    errors.append(
                        f"{case_id} {candidate_id or index} local candidate source must not be mock"
                    )
                if role != "mock" and (
                    not isinstance(candidate.get("lat"), (int, float))
                    or not isinstance(candidate.get("lng"), (int, float))
                ):
                    errors.append(
                        f"{case_id} {candidate_id or index} non-mock candidate needs coordinates"
                    )
        if len(set(candidate_ids)) != len(candidate_ids) or any(
            not value for value in candidate_ids
        ):
            errors.append(f"{case_id} candidate_id values must be non-empty and unique")
    return errors


def _empty_metrics() -> dict[str, int]:
    return {name: 0 for name in SAFETY_METRICS}


def _profile(
    destination: str,
    country: str,
    center: list[float],
) -> DestinationProfile:
    return DestinationProfile(
        requested_name=destination,
        canonical_name=destination,
        country=country,
        center_lat=float(center[0]),
        center_lng=float(center[1]),
        radius_km=45.0,
        confidence=0.95,
        source="demo_journey_fixture",
        is_dynamic=True,
    )


def _candidate(row: dict[str, Any]) -> ProviderCandidate:
    candidate_id = str(row["candidate_id"])
    title = str(row["title"])
    evidence = bool(row.get("evidence"))
    image = bool(row.get("image"))
    extra: dict[str, Any] = {
        "city": str(row.get("city") or ""),
        "lat": row.get("lat"),
        "lng": row.get("lng"),
        "rating": float(row.get("rating") or 0.0),
        "cost_estimate": float(row.get("cost") or 0.0),
        "provider_confidence": 0.9,
        "journey_role": str(row.get("role") or ""),
    }
    if evidence:
        extra.update(
            {
                "url": f"https://example.test/poi/{candidate_id}",
                "address": f"{row.get('city') or ''} {title}".strip(),
                "website": f"https://example.test/place/{candidate_id}",
                "tel": "000-0000",
            }
        )
    if image:
        extra["photos"] = [f"https://images.example.test/{candidate_id}.jpg"]
    return ProviderCandidate(
        candidate_id=candidate_id,
        source=str(row.get("source") or "fixture_map"),
        title=title,
        snippet=f"Verified fixture evidence for {title}" if evidence else "",
        score=min(max(float(row.get("rating") or 4.0) / 5.0, 0.0), 1.0),
        tags=[str(tag) for tag in row.get("tags") or []],
        extra=extra,
    )


def _candidate_pipeline(
    *,
    rows: list[dict[str, Any]],
    destination: str,
    country: str,
    center: list[float],
    days: int,
    budget: float,
    preferences: list[str],
    required_count: int,
    constraints: Iterable[str] = (),
    day_indexes: list[int] | None = None,
    slots_per_day: int | None = None,
    excluded_titles: Iterable[str] = (),
) -> tuple[Any, dict[str, Any]]:
    candidates = [_candidate(row) for row in rows]
    profile = _profile(destination, country, center)
    publishability = evaluate_candidate_publishability(
        candidates,
        profile,
        required_count=required_count,
        allow_mock=False,
    )
    legacy_ranked = RankingScorer().rank(
        publishability.accepted,
        preferences=preferences,
        budget=budget,
        days=days,
        top_k=max(24, len(publishability.accepted)),
    )
    policy_ranked = POIRankingPolicy().rank(
        publishability.accepted,
        destination=destination,
        destination_profile=profile,
        preferences=preferences,
        budget=budget,
        days=days,
        top_k=max(24, len(publishability.accepted)),
        include_rejected=True,
        allow_mock=False,
    )
    policy_ranked, learned_diagnostics = apply_learned_ranking(
        policy_ranked,
        mode="off",
        model_path=Path("unused-in-off-mode.json"),
    )
    ranked = select_runtime_ranking("candidate", legacy_ranked, policy_ranked)
    plan_result = None
    if publishability.ready:
        plan_result = ConstraintAwareItineraryPlanner().plan(
            ranked,
            destination=destination,
            days=days,
            total_budget=budget,
            preferences=preferences,
            constraints=constraints,
            excluded_titles=excluded_titles,
            day_indexes=day_indexes,
            slots_per_day=slots_per_day,
        )
    accepted_ids = {candidate.candidate_id for candidate in publishability.accepted}
    trace = {
        "destination_profile": profile.to_dict(),
        "candidate_count": len(candidates),
        "publishability_status": publishability.status,
        "publishable_candidate_ids": sorted(accepted_ids),
        "reject_reason_counts": publishability.reject_reason_counts,
        "policy_decisions": [
            {
                "candidate_id": item.candidate.candidate_id,
                "accepted": item.accepted,
                "rank_score": item.rank_score,
                "reject_reasons": list(item.reject_reasons),
            }
            for item in policy_ranked
        ],
        "learned_ranking": learned_diagnostics,
        "planner": plan_result.to_dict() if plan_result is not None else None,
    }
    return plan_result, trace


def _emit_event(
    events: list[dict[str, Any]],
    *,
    name: str,
    request_id: str,
    conversation_id: str,
    revision_id: str | None,
    payload: dict[str, Any],
) -> None:
    envelope = build_event_envelope(
        request_id=request_id,
        conversation_id=conversation_id,
        revision_id=revision_id,
        payload=payload,
    )
    wire = build_event_line(name, envelope)
    if not wire.startswith(f"event: {name}\ndata: "):
        raise AssertionError(f"invalid SSE wire envelope for {name}")
    events.append({"event": name, "revision_id": revision_id, "payload": payload})


def _slot_from_selection(selection: Any, *, slot: str | None = None) -> dict[str, Any]:
    payload = selection.to_dict()
    candidate = selection.scored.candidate
    return {
        "slot": slot or payload["slot"],
        "activity": f"游览 {payload['place']}",
        "place": payload["place"],
        "location": payload["location"],
        "image_url": payload["image_url"],
        "evidence_refs": [payload["evidence_ref"]],
        "candidate_id": candidate.candidate_id,
        "candidate_source": candidate.source,
        "candidate_role": candidate.extra.get("journey_role"),
        "estimated_cost": payload["estimated_cost"],
    }


def _build_itinerary(
    *,
    case_id: str,
    repetition: int,
    revision_number: int,
    base_revision_id: str | None,
    destination: str,
    days: int,
    budget: float,
    preferences: list[str],
    plan_result: Any,
) -> dict[str, Any]:
    if plan_result is None or not plan_result.feasible or plan_result.skeleton is None:
        raise ValueError("cannot build itinerary from infeasible plan")
    revision_id = f"{case_id}-run{repetition}-rev{revision_number}"
    return {
        "schema_version": "itinerary.v1",
        "itinerary_id": f"{case_id}-run{repetition}",
        "revision_id": revision_id,
        "base_revision_id": base_revision_id,
        "trip_profile": {
            "destination_city": destination,
            "constraints": {
                "budget_range": str(int(budget)),
                "preferences": list(preferences),
            },
        },
        "days": [
            {
                "day_index": day.day_index,
                "theme": day.theme,
                "slots": [
                    _slot_from_selection(selection)
                    for selection in day.selections
                ],
            }
            for day in plan_result.skeleton.days
        ],
        "budget_summary": {"total_estimate": budget},
        "validation": {"assumptions": []},
    }


def _all_slots(itinerary: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not itinerary:
        return []
    return [
        slot
        for day in itinerary.get("days") or []
        for slot in day.get("slots") or []
    ]


def _coverage(itinerary: dict[str, Any] | None) -> dict[str, float]:
    slots = _all_slots(itinerary)
    if not slots:
        return {"evidence": 0.0, "image": 0.0}
    return {
        "evidence": round(
            sum(bool(slot.get("evidence_refs")) for slot in slots) / len(slots),
            3,
        ),
        "image": round(
            sum(bool(slot.get("image_url")) for slot in slots) / len(slots),
            3,
        ),
    }


def _selected_safety_counts(
    itinerary: dict[str, Any] | None,
) -> tuple[int, int]:
    slots = _all_slots(itinerary)
    return (
        sum(slot.get("candidate_role") == "cross_city" for slot in slots),
        sum(
            slot.get("candidate_role") == "mock"
            or str(slot.get("candidate_source") or "").lower().startswith("mock")
            for slot in slots
        ),
    )


def _record_publication_safety(
    itinerary: dict[str, Any] | None,
    metrics: dict[str, int],
) -> None:
    cross_city, mock = _selected_safety_counts(itinerary)
    metrics["cross_city_published"] += cross_city
    metrics["mock_published"] += mock


def _find_day(itinerary: dict[str, Any], day_index: int) -> dict[str, Any] | None:
    return next(
        (
            day
            for day in itinerary.get("days") or []
            if day.get("day_index") == day_index
        ),
        None,
    )


def _non_target_changed(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    target_day: int,
    target_slot: str | None,
) -> bool:
    before_days = {
        int(day["day_index"]): day for day in before.get("days") or []
    }
    after_days = {
        int(day["day_index"]): day for day in after.get("days") or []
    }
    if set(before_days) != set(after_days):
        return True
    for day_index, before_day in before_days.items():
        after_day = after_days[day_index]
        if day_index != target_day:
            if before_day != after_day:
                return True
            continue
        if target_slot is None:
            continue
        before_slots = {
            str(slot.get("slot")): slot for slot in before_day.get("slots") or []
        }
        after_slots = {
            str(slot.get("slot")): slot for slot in after_day.get("slots") or []
        }
        if set(before_slots) != set(after_slots):
            return True
        for slot_name, before_slot in before_slots.items():
            if slot_name != target_slot and before_slot != after_slots[slot_name]:
                return True
    return False


def _run_case(
    case: dict[str, Any],
    *,
    repetition: int,
) -> dict[str, Any]:
    case_id = str(case["case_id"])
    conversation_id = f"demo-{case_id}-run{repetition}"
    processor = TravelQueryProcessor(structured_qp_mode="off")
    decision_service = ConversationDecisionService()
    snapshot = ConversationRuntimeSnapshot(conversation_id=conversation_id)
    metrics = _empty_metrics()
    errors: list[str] = []
    turn_traces: list[dict[str, Any]] = []
    revision_number = 0
    terminal_event: str | None = None
    old_destination_titles: set[str] = set()

    destination = str(case["destination"])
    country = str(case.get("country") or "")
    center = list(case["center"])
    days = int(case["days"])
    budget = float(case["budget"])
    preferences = [str(value) for value in case.get("preferences") or []]

    for turn_index, turn in enumerate(case.get("turns") or [], start=1):
        role = str(turn["role"])
        query = str(turn["query"])
        request_id = f"{conversation_id}-turn{turn_index}"
        before = snapshot.model_copy(deep=True)
        qp_output = processor.process(query)
        decision = decision_service.decide(query, qp_output, snapshot)
        transition = apply_transition(snapshot, decision)
        snapshot = transition.state_after
        events: list[dict[str, Any]] = []
        _emit_event(
            events,
            name="intent_routed",
            request_id=request_id,
            conversation_id=conversation_id,
            revision_id=before.current_revision_id,
            payload={
                "intent": decision.intent,
                "intent_detail": decision.intent_detail,
            },
        )
        pipeline_trace: dict[str, Any] | None = None

        expected_intent = {
            "create": "create",
            "qa": "qa",
            "edit": "edit",
            "switch": "change_destination",
            "degrade": "create",
        }[role]
        if decision.intent != expected_intent:
            errors.append(
                f"turn {turn_index} expected intent {expected_intent}, got {decision.intent}"
            )

        if role == "qa":
            if decision.target_day != turn.get("expected_target_day"):
                errors.append(
                    f"turn {turn_index} QA target day mismatch: {decision.target_day}"
                )
            if before.current_revision_id != snapshot.current_revision_id:
                metrics["qa_revision_mutations"] += 1
            _emit_event(
                events,
                name="final_text",
                request_id=request_id,
                conversation_id=conversation_id,
                revision_id=snapshot.current_revision_id,
                payload={"text": f"当前查询目标为第{decision.target_day}天。"},
            )

        elif role in {"create", "degrade"}:
            plan_result, pipeline_trace = _candidate_pipeline(
                rows=list(case.get("candidates") or []),
                destination=destination,
                country=country,
                center=center,
                days=days,
                budget=budget,
                preferences=preferences,
                required_count=days,
            )
            if plan_result is None or not plan_result.feasible:
                _emit_event(
                    events,
                    name="quality_warning",
                    request_id=request_id,
                    conversation_id=conversation_id,
                    revision_id=None,
                    payload={
                        "reason": (
                            pipeline_trace.get("publishability_status")
                            if pipeline_trace
                            else "insufficient_candidates"
                        )
                    },
                )
                _emit_event(
                    events,
                    name="final_text",
                    request_id=request_id,
                    conversation_id=conversation_id,
                    revision_id=None,
                    payload={
                        "text": "可验证候选不足，未发布可能不可靠的行程。",
                        "reason": "insufficient_candidates",
                    },
                )
                snapshot.current_itinerary = None
                snapshot.current_revision_id = None
                snapshot.active_destination = destination
                if role != "degrade":
                    errors.append(f"turn {turn_index} ready create did not produce a plan")
            else:
                revision_number += 1
                itinerary = _build_itinerary(
                    case_id=case_id,
                    repetition=repetition,
                    revision_number=revision_number,
                    base_revision_id=None,
                    destination=destination,
                    days=days,
                    budget=budget,
                    preferences=preferences,
                    plan_result=plan_result,
                )
                snapshot.active_destination = destination
                snapshot.trip_profile = deepcopy(itinerary["trip_profile"])
                snapshot.current_itinerary = itinerary
                snapshot.current_revision_id = itinerary["revision_id"]
                _record_publication_safety(itinerary, metrics)
                _emit_event(
                    events,
                    name="final_itinerary",
                    request_id=request_id,
                    conversation_id=conversation_id,
                    revision_id=itinerary["revision_id"],
                    payload={"itinerary": itinerary},
                )
                if role == "degrade":
                    metrics["unsafe_final_itinerary_on_degrade"] += 1

        elif role == "switch":
            expected_destination = str(turn.get("expected_destination") or "")
            if decision.destination != expected_destination:
                errors.append(
                    f"turn {turn_index} switch destination mismatch: {decision.destination}"
                )
            old_destination_titles = {
                str(slot.get("place") or "")
                for slot in _all_slots(before.current_itinerary)
            }
            if snapshot.current_itinerary is not None or snapshot.current_revision_id is not None:
                metrics["stale_destination_candidates"] += 1
            destination = expected_destination
            country = str(case.get("switch_country") or country)
            center = list(case.get("switch_center") or center)
            plan_result, pipeline_trace = _candidate_pipeline(
                rows=list(case.get("switch_candidates") or []),
                destination=destination,
                country=country,
                center=center,
                days=days,
                budget=budget,
                preferences=preferences,
                required_count=days,
            )
            if plan_result is None or not plan_result.feasible:
                errors.append(f"turn {turn_index} destination switch could not create new plan")
            else:
                revision_number += 1
                itinerary = _build_itinerary(
                    case_id=case_id,
                    repetition=repetition,
                    revision_number=revision_number,
                    base_revision_id=None,
                    destination=destination,
                    days=days,
                    budget=budget,
                    preferences=preferences,
                    plan_result=plan_result,
                )
                snapshot.active_destination = destination
                snapshot.trip_profile = deepcopy(itinerary["trip_profile"])
                snapshot.current_itinerary = itinerary
                snapshot.current_revision_id = itinerary["revision_id"]
                new_titles = {
                    str(slot.get("place") or "") for slot in _all_slots(itinerary)
                }
                metrics["stale_destination_candidates"] += len(
                    old_destination_titles.intersection(new_titles)
                )
                _record_publication_safety(itinerary, metrics)
                _emit_event(
                    events,
                    name="final_itinerary",
                    request_id=request_id,
                    conversation_id=conversation_id,
                    revision_id=itinerary["revision_id"],
                    payload={"itinerary": itinerary},
                )

        elif role == "edit":
            expected_day = int(turn.get("expected_target_day") or 0)
            expected_slot = turn.get("expected_target_slot")
            if (
                decision.target_day != expected_day
                or decision.target_slot != expected_slot
            ):
                metrics["wrong_edit_targets"] += 1
            current = deepcopy(snapshot.current_itinerary)
            if current is None:
                errors.append(f"turn {turn_index} edit has no itinerary")
            else:
                target_day = _find_day(current, expected_day)
                if target_day is None:
                    metrics["wrong_edit_targets"] += 1
                else:
                    target_slots = (
                        [str(expected_slot)]
                        if expected_slot
                        else [
                            str(slot.get("slot"))
                            for slot in target_day.get("slots") or []
                        ]
                    )
                    constraints = (
                        ("indoor",)
                        if "室内" in query or "indoor" in query.lower()
                        else ()
                    )
                    existing_titles = {
                        str(slot.get("place") or "")
                        for slot in _all_slots(current)
                    }
                    plan_result, pipeline_trace = _candidate_pipeline(
                        rows=list(case.get("edit_candidates") or []),
                        destination=destination,
                        country=country,
                        center=center,
                        days=1,
                        budget=budget / max(days, 1),
                        preferences=preferences,
                        required_count=len(target_slots),
                        constraints=constraints,
                        day_indexes=[expected_day],
                        slots_per_day=len(target_slots),
                        excluded_titles=existing_titles,
                    )
                    if (
                        plan_result is None
                        or not plan_result.feasible
                        or plan_result.skeleton is None
                        or len(plan_result.skeleton.selections) != len(target_slots)
                    ):
                        planner_trace = (pipeline_trace or {}).get("planner") or {}
                        planner_reason = (
                            str(
                                planner_trace.get("reason")
                                or "insufficient_candidates"
                            )
                        )
                        errors.append(f"edit_replan_failed:{planner_reason}")
                        _emit_event(
                            events,
                            name="final_text",
                            request_id=request_id,
                            conversation_id=conversation_id,
                            revision_id=before.current_revision_id,
                            payload={"text": "候选不足，已保留原行程。"},
                        )
                    else:
                        edited = deepcopy(current)
                        edited_day = _find_day(edited, expected_day)
                        assert edited_day is not None
                        replacements = [
                            _slot_from_selection(selection, slot=slot_name)
                            for selection, slot_name in zip(
                                plan_result.skeleton.selections,
                                target_slots,
                                strict=True,
                            )
                        ]
                        if expected_slot:
                            replacement = replacements[0]
                            edited_day["slots"] = [
                                replacement
                                if slot.get("slot") == expected_slot
                                else slot
                                for slot in edited_day.get("slots") or []
                            ]
                        else:
                            edited_day["slots"] = replacements
                            edited_day["theme"] = plan_result.skeleton.days[0].theme

                        if _non_target_changed(
                            current,
                            edited,
                            target_day=expected_day,
                            target_slot=expected_slot,
                        ):
                            metrics["non_target_mutations"] += 1
                        previous_revision = str(current.get("revision_id") or "")
                        revision_number += 1
                        new_revision = (
                            f"{case_id}-run{repetition}-rev{revision_number}"
                        )
                        edited["base_revision_id"] = previous_revision
                        edited["revision_id"] = new_revision
                        if (
                            edited["base_revision_id"] != previous_revision
                            or new_revision == previous_revision
                        ):
                            metrics["revision_lineage_failures"] += 1
                        snapshot.current_itinerary = edited
                        snapshot.current_revision_id = new_revision
                        _record_publication_safety(edited, metrics)
                        _emit_event(
                            events,
                            name="edit_diff",
                            request_id=request_id,
                            conversation_id=conversation_id,
                            revision_id=new_revision,
                            payload={
                                "old_revision_id": previous_revision,
                                "new_revision_id": new_revision,
                                "change_summary": {
                                    "changed_days": [expected_day],
                                    "target_slot": expected_slot,
                                },
                            },
                        )
                        _emit_event(
                            events,
                            name="final_itinerary",
                            request_id=request_id,
                            conversation_id=conversation_id,
                            revision_id=new_revision,
                            payload={"itinerary": edited},
                        )

        event_names = [event["event"] for event in events]
        terminal = next(
            (name for name in reversed(event_names) if name in TERMINAL_EVENTS),
            None,
        )
        if terminal is None:
            metrics["missing_terminal_events"] += 1
        else:
            terminal_event = terminal
        turn_traces.append(
            {
                "turn_index": turn_index,
                "role": role,
                "query": query,
                "qp_output": qp_output,
                "decision": decision.model_dump(mode="json"),
                "state_before": before.model_dump(mode="json"),
                "state_after": snapshot.model_dump(mode="json"),
                "pipeline": pipeline_trace,
                "event_names": event_names,
            }
        )

    if case["category"] == "insufficient_candidates":
        if any(
            "final_itinerary" in turn["event_names"] for turn in turn_traces
        ):
            metrics["unsafe_final_itinerary_on_degrade"] += 1
        if snapshot.current_revision_id is not None:
            metrics["unsafe_final_itinerary_on_degrade"] += 1

    for name, value in metrics.items():
        if value:
            errors.append(f"{name}={value}")
    return {
        "case_id": case_id,
        "category": case["category"],
        "repetition": repetition,
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "turn_count": len(turn_traces),
        "terminal_event": terminal_event,
        "final_destination": snapshot.active_destination,
        "final_revision_id": snapshot.current_revision_id,
        "coverage": _coverage(snapshot.current_itinerary),
        "metrics": metrics,
        "turns": turn_traces,
    }


def evaluate_cases(
    cases: list[dict[str, Any]],
    *,
    repetitions: int = 2,
) -> dict[str, Any]:
    contract_errors = validate_case_contract(cases)
    if repetitions < 1:
        contract_errors.append("repetitions must be positive")
    runs: list[dict[str, Any]] = []
    if not contract_errors:
        for repetition in range(1, repetitions + 1):
            for case in cases:
                try:
                    runs.append(_run_case(case, repetition=repetition))
                except Exception as exc:
                    metrics = _empty_metrics()
                    metrics["missing_terminal_events"] = 1
                    runs.append(
                        {
                            "case_id": case.get("case_id"),
                            "category": case.get("category"),
                            "repetition": repetition,
                            "status": "failed",
                            "errors": [f"{type(exc).__name__}: {exc}"],
                            "turn_count": 0,
                            "terminal_event": None,
                            "final_destination": None,
                            "final_revision_id": None,
                            "coverage": {"evidence": 0.0, "image": 0.0},
                            "metrics": metrics,
                            "turns": [],
                        }
                    )

    safety_metrics = _empty_metrics()
    for run in runs:
        for name in SAFETY_METRICS:
            safety_metrics[name] += int((run.get("metrics") or {}).get(name) or 0)
    passed = sum(run.get("status") == "passed" for run in runs)
    failures = [run for run in runs if run.get("status") != "passed"]
    report = {
        "schema_version": "demo_journey_eval_v1",
        "status": (
            "passed"
            if not contract_errors and not failures
            else "failed"
        ),
        "scenario_count": len(cases),
        "repetitions": repetitions,
        "journey_runs": len(runs),
        "passed_journey_runs": passed,
        "failed_journey_runs": len(runs) - passed,
        "turn_count": sum(int(run.get("turn_count") or 0) for run in runs),
        "contract_errors": contract_errors,
        "safety_metrics": safety_metrics,
        "failures": failures,
        "runs": runs,
    }
    return report


def is_passing(report: dict[str, Any]) -> bool:
    metrics = report.get("safety_metrics") or {}
    return (
        report.get("status") == "passed"
        and report.get("schema_version") == "demo_journey_eval_v1"
        and int(report.get("scenario_count") or 0) == 4
        and int(report.get("repetitions") or 0) == 2
        and int(report.get("journey_runs") or 0) == 8
        and int(report.get("passed_journey_runs") or 0) == 8
        and int(report.get("failed_journey_runs") or 0) == 0
        and int(report.get("turn_count") or 0) >= 24
        and not report.get("contract_errors")
        and all(int(metrics.get(name) or 0) == 0 for name in SAFETY_METRICS)
    )


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# TravelMind Four-Scenario Demo Journey Eval",
        "",
        f"- Status: `{report['status']}`",
        (
            f"- Journey runs: "
            f"{report['passed_journey_runs']}/{report['journey_runs']} passed"
        ),
        f"- Turns: {report['turn_count']}",
        "",
        "## Safety Metrics",
        "",
        "| Metric | Count |",
        "| --- | ---: |",
    ]
    for name, value in (report.get("safety_metrics") or {}).items():
        lines.append(f"| `{name}` | {value} |")
    lines.extend(
        [
            "",
            "## Journey Runs",
            "",
            "| Scenario | Repetition | Status | Turns | Final destination | Terminal |",
            "| --- | ---: | --- | ---: | --- | --- |",
        ]
    )
    for run in report.get("runs") or []:
        lines.append(
            f"| `{run['case_id']}` | {run['repetition']} | {run['status']} | "
            f"{run['turn_count']} | {run.get('final_destination') or '-'} | "
            f"{run.get('terminal_event') or '-'} |"
        )
    if report.get("contract_errors"):
        lines.extend(["", "## Contract Errors", ""])
        lines.extend(f"- {error}" for error in report["contract_errors"])
    if report.get("failures"):
        lines.extend(["", "## Failures", ""])
        for run in report["failures"]:
            lines.append(
                f"- `{run['case_id']}` run {run['repetition']}: "
                f"{'; '.join(run.get('errors') or [])}"
            )
    lines.append("")
    return "\n".join(lines)


def write_outputs(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "demo-journey-eval.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "demo-journey-eval.md").write_text(
        render_markdown(report),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    report = evaluate_cases(load_cases(args.cases), repetitions=args.repetitions)
    write_outputs(report, args.output_dir)
    print(
        "demo_journey_eval="
        f"{report['status']} "
        f"({report['passed_journey_runs']}/{report['journey_runs']} runs, "
        f"{report['turn_count']} turns)"
    )
    return 0 if is_passing(report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
