import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request

from clinic.errors import BookingError
from clinic.main import create_app
from clinic.schemas import AppointmentResponse


def test_openapi_is_available_without_database_configuration(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    schema = create_app().openapi()
    assert schema["paths"]["/appointments"]["post"]["responses"]["201"]
    assert schema["paths"]["/appointments/{id}/cancel"]["patch"]
    assert schema["paths"]["/appointments/{id}/reschedule"]["patch"]
    assert schema["paths"]["/doctors/{id}/availability"]["get"]
    assert schema["paths"]["/patients/{id}/appointments"]["get"]
    assert schema["paths"]["/appointments"]["post"]["responses"]["422"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/ErrorResponse"}


@pytest.mark.parametrize(
    "status,code",
    [
        (404, "appointment_not_found"),
        (409, "slot_unavailable"),
        (422, "insufficient_notice"),
        (503, "booking_temporarily_unavailable"),
    ],
)
def test_domain_error_http_serialization(status, code):
    app = create_app()
    request = Request({"type": "http", "method": "POST", "path": "/appointments"})
    response = asyncio.run(
        app.exception_handlers[BookingError](request, BookingError(status, code, "Message"))
    )
    assert response.status_code == status
    assert json.loads(response.body) == {"error": {"code": code, "message": "Message"}}
    assert response.headers.get("retry-after") == ("1" if status == 503 else None)


def test_request_errors_serialize_without_echoing_raw_input_or_exception_objects():
    app = create_app()
    request = Request({"type": "http", "method": "POST", "path": "/appointments"})
    error = RequestValidationError(
        [
            {
                "loc": ("body", "reason"),
                "msg": "Value error, blank reason",
                "type": "value_error",
                "input": "sensitive input",
                "ctx": {"error": ValueError("blank reason")},
            }
        ]
    )
    response = asyncio.run(app.exception_handlers[RequestValidationError](request, error))
    assert response.status_code == 422
    body = json.loads(response.body)
    assert body["error"]["code"] == "invalid_request"
    assert body["error"]["details"][0]["location"] == ["body", "reason"]
    assert b"sensitive input" not in response.body


def test_appointment_output_normalizes_database_timezone_to_utc():
    stamp = datetime.fromisoformat("2030-01-07T09:00:00+03:00")
    appointment = AppointmentResponse(
        id=uuid4(),
        doctor_id=uuid4(),
        patient_id=uuid4(),
        slot_start=stamp,
        status="BOOKED",
        cancel_reason=None,
        cancelled_at=None,
        created_at=stamp,
        updated_at=stamp,
    )
    assert appointment.slot_start == datetime(2030, 1, 7, 6, tzinfo=UTC)
    assert appointment.slot_start.tzinfo == UTC
    assert appointment.model_dump(mode="json")["slot_start"] == "2030-01-07T06:00:00Z"
