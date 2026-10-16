import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from clinic.models import Appointment
from clinic.policies import WHITE_SPACE
from clinic.schemas import AppointmentResponse
from clinic.seed import DOCTOR_IDS, PATIENT_IDS

pytestmark = pytest.mark.integration
DOCTOR = str(DOCTOR_IDS[0])
PATIENT = str(PATIENT_IDS[0])
START = "2030-01-07T09:00:00+03:00"
LATER = "2030-01-07T10:00:00+03:00"


def book(client, start=START, **changes):
    body = dict(doctor_id=DOCTOR, patient_id=PATIENT, slot_start=start)
    return client.post("/appointments", json=body | changes)


def availability(client, day="2030-01-07"):
    return client.get(f"/doctors/{DOCTOR}/availability", params={"date": day})


def test_booking_availability_cancellation_and_rebooking(client, sessions):
    before = availability(client).json()
    assert before["timezone"] == "Africa/Nairobi"
    assert len(before["slots"]) == 14
    assert before["slots"][0] == START
    response = book(client)
    assert response.status_code == 201
    appointment = response.json()
    assert appointment["status"] == "BOOKED"
    assert appointment["cancel_reason"] is None
    assert len(availability(client).json()["slots"]) == 13
    duplicate = book(client)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "slot_unavailable"
    cancelled = client.patch(
        f"/appointments/{appointment['id']}/cancel",
        json={"reason": WHITE_SPACE + "Plans changed" + WHITE_SPACE},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert cancelled.json()["cancel_reason"] == "Plans changed"
    assert cancelled.json()["cancelled_at"] is not None
    assert len(availability(client).json()["slots"]) == 14
    replacement = book(client)
    assert replacement.status_code == 201
    assert replacement.json()["id"] != appointment["id"]
    with sessions() as session:
        assert len(list(session.scalars(select(Appointment)))) == 2


def test_reschedule_releases_original_and_conflict_preserves_current(client):
    original = book(client).json()
    moved = client.patch(f"/appointments/{original['id']}/reschedule", json={"slot_start": LATER})
    assert moved.status_code == 200
    assert moved.json()["id"] == original["id"]
    assert datetime.fromisoformat(moved.json()["slot_start"]) == datetime.fromisoformat(LATER)
    assert START in availability(client).json()["slots"]
    assert LATER not in availability(client).json()["slots"]
    assert book(client).status_code == 201
    failed = client.patch(f"/appointments/{original['id']}/reschedule", json={"slot_start": START})
    assert failed.status_code == 409
    upcoming = client.get(f"/patients/{PATIENT}/appointments").json()
    saved = next(item for item in upcoming if item["id"] == original["id"])
    assert saved == moved.json()


@pytest.mark.parametrize(
    "destination,code",
    [
        ("2030-01-07T12:00:00+03:00", "outside_working_hours"),
        ("2030-01-07T09:15:00+03:00", "invalid_slot_grid"),
        ("2030-01-07T08:30:00+03:00", "insufficient_notice"),
        ("2029-01-01T09:00:00+03:00", "insufficient_notice"),
    ],
)
def test_invalid_booking_and_reschedule_destinations(client, destination, code):
    failed = book(client, destination)
    assert failed.status_code == 422
    assert failed.json()["error"]["code"] == code
    original = book(client).json()
    failed = client.patch(
        f"/appointments/{original['id']}/reschedule", json={"slot_start": destination}
    )
    assert failed.status_code == 422
    upcoming = client.get(f"/patients/{PATIENT}/appointments").json()
    assert upcoming == [original]


def test_cancelled_state_takes_precedence_over_destination_rules(client):
    appointment = book(client).json()
    path = f"/appointments/{appointment['id']}"
    assert client.patch(path + "/cancel", json={"reason": "Changed plans"}).status_code == 200
    again = client.patch(path + "/cancel", json={"reason": "Again"})
    assert again.status_code == 409
    move = client.patch(path + "/reschedule", json={"slot_start": "2029-01-01T09:00:00Z"})
    assert move.status_code == 409
    assert move.json()["error"]["code"] == "appointment_cancelled"


def test_same_slot_equivalent_offset_retains_timestamps_and_validates_notice(client, service):
    appointment = book(client).json()
    path = f"/appointments/{appointment['id']}/reschedule"
    unchanged = client.patch(path, json={"slot_start": "2030-01-07T06:00:00Z"})
    assert unchanged.status_code == 200
    assert unchanged.json() == appointment
    service.clock = lambda: datetime(2030, 1, 7, 5, 0, 0, 1, tzinfo=UTC)
    assert client.patch(path, json={"slot_start": START}).status_code == 422
    service.clock = lambda: datetime(2030, 1, 7, 7, tzinfo=UTC)
    assert client.patch(path, json={"slot_start": START}).status_code == 422
    assert client.patch(path, json={"slot_start": LATER}).status_code == 422
    assert client.patch(path, json={"slot_start": "2030-01-07T11:00:00+03:00"}).status_code == 200


def test_imminent_original_can_move_to_later_destination(client, service):
    appointment = book(client).json()
    service.clock = lambda: datetime(2030, 1, 7, 5, 45, tzinfo=UTC)
    moved = client.patch(
        f"/appointments/{appointment['id']}/reschedule", json={"slot_start": LATER}
    )
    assert moved.status_code == 200


def test_upcoming_is_active_sorted_patient_scoped_and_has_no_notice_filter(client, service):
    later = book(client, LATER).json()
    earlier = book(client).json()
    cancelled = book(client, "2030-01-07T11:00:00+03:00").json()
    client.patch(f"/appointments/{cancelled['id']}/cancel", json={"reason": "Changed"})
    assert (
        book(client, "2030-01-07T14:00:00+03:00", patient_id=str(PATIENT_IDS[1])).status_code == 201
    )
    service.clock = lambda: datetime(2030, 1, 7, 5, 45, tzinfo=UTC)
    upcoming = client.get(f"/patients/{PATIENT}/appointments").json()
    assert [item["id"] for item in upcoming] == [earlier["id"], later["id"]]
    service.clock = lambda: datetime(2030, 1, 7, 6, tzinfo=UTC) + timedelta(seconds=1)
    assert client.get(f"/patients/{PATIENT}/appointments").json() == [later]
    assert client.get(f"/patients/{PATIENT_IDS[2]}/appointments").json() == []


@pytest.mark.parametrize(
    "method,path,body",
    [
        (
            "post",
            "/appointments",
            {"doctor_id": str(uuid4()), "patient_id": PATIENT, "slot_start": START},
        ),
        (
            "post",
            "/appointments",
            {"doctor_id": DOCTOR, "patient_id": str(uuid4()), "slot_start": START},
        ),
        ("get", f"/doctors/{uuid4()}/availability?date=2030-01-07", None),
        ("get", f"/patients/{uuid4()}/appointments", None),
        ("patch", f"/appointments/{uuid4()}/cancel", {"reason": "Changed"}),
        ("patch", f"/appointments/{uuid4()}/reschedule", {"slot_start": START}),
    ],
)
def test_missing_resources_return_404(client, method, path, body):
    response = client.request(method, path, **({"json": body} if body is not None else {}))
    assert response.status_code == 404
    assert response.json()["error"]["code"].endswith("_not_found")


@pytest.mark.parametrize(
    "changes",
    [
        {"slot_start": "2030-01-07T09:00:00"},
        {"slot_start": 1893996000},
        {"doctor_id": "invalid"},
        {"patient_id": None},
        {"unexpected": 1},
    ],
)
def test_malformed_booking_input_returns_422(client, changes):
    response = (
        book(client, **changes)
        if "slot_start" not in changes
        else book(client, changes["slot_start"])
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


@pytest.mark.parametrize("reason", ["", WHITE_SPACE, None, 42])
def test_invalid_cancellation_reason_returns_422(client, reason):
    appointment = book(client).json()
    assert (
        client.patch(
            f"/appointments/{appointment['id']}/cancel", json={"reason": reason}
        ).status_code
        == 422
    )


@pytest.mark.parametrize("reason", ["Changed\x00plans", "Changed\ud800plans", "Changed\udfffplans"])
def test_unsupported_cancellation_text_preserves_booking(client, service, sessions, reason):
    appointment = book(client).json()
    appointment_id = UUID(appointment["id"])
    path = f"/appointments/{appointment_id}/cancel"
    response = client.patch(
        path,
        content=json.dumps({"reason": reason}),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_request"
    assert error["details"][0]["location"] == ["body", "reason"]
    assert "reason" in error["details"][0]["message"].lower()
    with pytest.raises(ValueError):
        service.cancel(appointment_id, reason)
    with sessions() as session:
        saved = session.get(Appointment, appointment_id)
        assert AppointmentResponse.model_validate(saved).model_dump(mode="json") == appointment
    valid_reason = "Plans changed — 次回 🩺"
    cancelled = client.patch(path, json={"reason": valid_reason})
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert cancelled.json()["cancel_reason"] == valid_reason
    with sessions() as session:
        saved = session.get(Appointment, appointment_id)
        assert saved.status == "CANCELLED"
        assert saved.cancel_reason == valid_reason
    assert START in availability(client).json()["slots"]


def test_empty_availability_and_invalid_date(client):
    assert availability(client, "2030-01-06").json()["slots"] == []
    assert availability(client, "2029-01-07").json()["slots"] == []
    assert availability(client, "not-a-date").status_code == 422
    assert client.get(f"/doctors/{DOCTOR}/availability").status_code == 422


def test_openapi_exposes_required_operations(client):
    schema = client.get("/openapi.json").json()
    assert schema["paths"]["/appointments"]["post"]["responses"]["201"]
    assert schema["paths"]["/appointments/{id}/cancel"]["patch"]
    assert schema["paths"]["/appointments/{id}/reschedule"]["patch"]
    assert schema["paths"]["/doctors/{id}/availability"]["get"]
    assert schema["paths"]["/patients/{id}/appointments"]["get"]
