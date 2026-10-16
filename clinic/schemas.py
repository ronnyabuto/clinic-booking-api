from datetime import UTC, date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, field_validator

from clinic.policies import normalize_reason


def require_timestamp_string(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    raise ValueError("Use an ISO 8601 timestamp with a timezone offset")


SlotStart = Annotated[AwareDatetime, BeforeValidator(require_timestamp_string)]


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BookAppointment(RequestModel):
    doctor_id: UUID
    patient_id: UUID
    slot_start: SlotStart


class RescheduleAppointment(RequestModel):
    slot_start: SlotStart


class CancelAppointment(RequestModel):
    reason: str

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value: str) -> str:
        return normalize_reason(value)


class AppointmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    doctor_id: UUID
    patient_id: UUID
    slot_start: datetime
    status: Literal["BOOKED", "CANCELLED"]
    cancel_reason: str | None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @field_validator("slot_start", "cancelled_at", "created_at", "updated_at")
    @classmethod
    def utc_timestamps(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC) if value is not None else None


class AvailabilityResponse(BaseModel):
    doctor_id: UUID
    date: date
    timezone: str = "Africa/Nairobi"
    slots: list[datetime]


class ValidationDetail(BaseModel):
    location: list[str | int]
    message: str
    type: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ValidationDetail] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
