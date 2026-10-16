from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from clinic.schemas import (
    AppointmentResponse,
    AvailabilityResponse,
    BookAppointment,
    CancelAppointment,
    ErrorResponse,
    RescheduleAppointment,
)
from clinic.service import BookingService

router = APIRouter(responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}})
write_errors = {409: {"model": ErrorResponse}, 503: {"model": ErrorResponse}}


def booking_service(request: Request) -> BookingService:
    return request.app.state.booking_service


Service = Annotated[BookingService, Depends(booking_service)]


@router.get("/health", include_in_schema=False)
def health(service: Service):
    try:
        with service.sessions() as session:
            session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return {"status": "ok"}


@router.post(
    "/appointments", response_model=AppointmentResponse, status_code=201, responses=write_errors
)
def book(body: BookAppointment, service: Service):
    return service.book(body.doctor_id, body.patient_id, body.slot_start)


@router.get("/doctors/{id}/availability", response_model=AvailabilityResponse)
def availability(id: UUID, date: Annotated[date, Query()], service: Service):
    return service.availability(id, date)


@router.patch(
    "/appointments/{id}/cancel", response_model=AppointmentResponse, responses=write_errors
)
def cancel(id: UUID, body: CancelAppointment, service: Service):
    return service.cancel(id, body.reason)


@router.patch(
    "/appointments/{id}/reschedule", response_model=AppointmentResponse, responses=write_errors
)
def reschedule(id: UUID, body: RescheduleAppointment, service: Service):
    return service.reschedule(id, body.slot_start)


@router.get("/patients/{id}/appointments", response_model=list[AppointmentResponse])
def upcoming(id: UUID, service: Service):
    return service.upcoming(id)
