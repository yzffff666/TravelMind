import pytest
from pydantic import ValidationError

from app.schemas.itinerary_v1 import (
    ItineraryV1,
    FIELD_DEGRADE_STRATEGY,
    P0_FIELDS,
)


def _minimal_valid_payload():
    return {
        "schema_version": "itinerary.v1",
        "itinerary_id": "iti_001",
        "revision_id": "rev_001",
        "trip_profile": {
            "destination_city": "Shanghai",
            "constraints": {
                "budget_range": "5000-7000",
                "traveler_type": "couple",
                "preferences": ["culture", "food"],
            },
        },
        "days": [
            {
                "day_index": 1,
                "slots": [
                    {
                        "slot": "morning",
                        "activity": "City walk",
                    }
                ],
            }
        ],
        "budget_summary": {"total_estimate": 6000},
    }


def test_itinerary_v1_accepts_minimal_valid_payload():
    model = ItineraryV1(**_minimal_valid_payload())
    assert model.schema_version == "itinerary.v1"
    assert model.trip_profile.destination_city == "Shanghai"


def test_itinerary_v1_rejects_missing_p0_field():
    payload = _minimal_valid_payload()
    payload.pop("revision_id")

    with pytest.raises(ValidationError):
        ItineraryV1(**payload)


def test_itinerary_v1_allows_missing_p1_fields():
    payload = _minimal_valid_payload()
    # No risk/cost_breakdown/evidence provider fields present; P1 should not block.
    model = ItineraryV1(**payload)
    assert model.days[0].slots[0].risk is None
    assert model.evidence == []


def test_itinerary_v1_contract_metadata_present():
    rules = ItineraryV1.contract_rules()
    assert "trip_profile.destination_city" in rules["P0_FIELDS"]
    assert "P0_CONSTRAINTS" in rules
    assert "P1_FIELDS" in rules
    assert "P1_MISSING_ASSUMPTIONS" in rules
    assert "P2_FIELDS" in rules
    assert "REVISION_RULES" in rules
    assert "P0" in FIELD_DEGRADE_STRATEGY
    assert len(P0_FIELDS) > 0


def test_itinerary_v1_rejects_invalid_schema_version():
    payload = _minimal_valid_payload()
    payload["schema_version"] = "itinerary.v2"

    with pytest.raises(ValidationError):
        ItineraryV1(**payload)


def test_itinerary_v1_rejects_duplicate_day_index():
    payload = _minimal_valid_payload()
    payload["days"].append(
        {
            "day_index": 1,
            "slots": [{"slot": "afternoon", "activity": "Museum"}],
        }
    )

    with pytest.raises(ValidationError):
        ItineraryV1(**payload)


def test_itinerary_v1_rejects_invalid_risk_level():
    payload = _minimal_valid_payload()
    payload["days"][0]["slots"][0]["risk"] = {"level": "critical", "text": "Too crowded"}

    with pytest.raises(ValidationError):
        ItineraryV1(**payload)


def test_itinerary_v1_allows_initial_revision_with_null_base():
    payload = _minimal_valid_payload()
    payload["base_revision_id"] = None

    model = ItineraryV1(**payload)
    assert model.base_revision_id is None


def test_itinerary_v1_rejects_self_referenced_revision_link():
    payload = _minimal_valid_payload()
    payload["base_revision_id"] = payload["revision_id"]

    with pytest.raises(ValidationError):
        ItineraryV1(**payload)

