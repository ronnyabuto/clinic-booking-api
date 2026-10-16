import random
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from clinic.errors import BookingError
from clinic.models import Appointment, Doctor, DoctorSchedule, Patient
from clinic.policies import CLINIC_TIMEZONE, MIN_NOTICE, normalize_reason
from clinic.scheduling import day_bounds, scheduled_slots, validate_destination
from clinic.schemas import AppointmentResponse, AvailabilityResponse


def utc_now() -> datetime:
    return datetime.now(UTC)


class BookingService:
    def __init__(self, sessions: sessionmaker, clock: Callable[[], datetime] = utc_now):
        self.sessions = sessions
        self.clock = clock

    def _write(self, operation):
        for attempt in range(3):
            try:
                with self.sessions() as session, session.begin():
                    result = operation(session)
                return result
            except DBAPIError as error:
                state = getattr(error.orig, "sqlstate", None)
                constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
                if state == "23505" and constraint == "uq_doctor_active_slot":
                    raise BookingError(
                        409, "slot_unavailable", "The doctor's slot is already booked"
                    ) from error
                if state != "40P01":
                    raise
                if attempt == 2:
                    raise BookingError(
                        503, "booking_temporarily_unavailable", "Booking is busy; please try again"
                    ) from error
                time.sleep(random.uniform(0, 0.1))

    @staticmethod
    def _require(session: Session, model, resource_id: UUID):
        resource = session.get(model, resource_id)
        if resource is None:
            name = model.__tablename__.removesuffix("s")
            raise BookingError(404, f"{name}_not_found", f"{name.capitalize()} was not found")
        return resource

    @staticmethod
    def _windows(session: Session, doctor_id: UUID) -> list[DoctorSchedule]:
        return list(
            session.scalars(select(DoctorSchedule).where(DoctorSchedule.doctor_id == doctor_id))
        )

    @staticmethod
    def _lock_active(session: Session, appointment_id: UUID) -> Appointment:
        appointment = session.scalar(
            select(Appointment).where(Appointment.id == appointment_id).with_for_update()
        )
        if appointment is None:
            raise BookingError(404, "appointment_not_found", "Appointment was not found")
        if appointment.status == "CANCELLED":
            raise BookingError(409, "appointment_cancelled", "Appointment is already cancelled")
        return appointment

    def book(self, doctor_id: UUID, patient_id: UUID, slot_start: datetime) -> AppointmentResponse:
        def operation(session):
            self._require(session, Doctor, doctor_id)
            self._require(session, Patient, patient_id)
            windows = self._windows(session, doctor_id)
            now = self.clock()
            start = validate_destination(slot_start, windows, now)
            appointment = Appointment(
                doctor_id=doctor_id,
                patient_id=patient_id,
                slot_start=start,
                created_at=now,
                updated_at=now,
            )
            session.add(appointment)
            session.flush()
            return AppointmentResponse.model_validate(appointment)

        return self._write(operation)

    def cancel(self, appointment_id: UUID, reason: str) -> AppointmentResponse:
        reason = normalize_reason(reason)

        def operation(session):
            appointment = self._lock_active(session, appointment_id)
            now = self.clock()
            appointment.status = "CANCELLED"
            appointment.cancel_reason = reason
            appointment.cancelled_at = now
            appointment.updated_at = now
            session.flush()
            return AppointmentResponse.model_validate(appointment)

        return self._write(operation)

    def reschedule(self, appointment_id: UUID, slot_start: datetime) -> AppointmentResponse:
        def operation(session):
            appointment = self._lock_active(session, appointment_id)
            windows = self._windows(session, appointment.doctor_id)
            now = self.clock()
            start = validate_destination(slot_start, windows, now)
            if start != appointment.slot_start:
                appointment.slot_start = start
                appointment.updated_at = now
                session.flush()
            return AppointmentResponse.model_validate(appointment)

        return self._write(operation)

    def availability(self, doctor_id: UUID, day: date) -> AvailabilityResponse:
        with self.sessions() as session:
            self._require(session, Doctor, doctor_id)
            windows = self._windows(session, doctor_id)
            lower, upper = day_bounds(day)
            taken = set(
                session.scalars(
                    select(Appointment.slot_start).where(
                        Appointment.doctor_id == doctor_id,
                        Appointment.status == "BOOKED",
                        Appointment.slot_start >= lower,
                        Appointment.slot_start < upper,
                    )
                )
            )
            cutoff = self.clock() + MIN_NOTICE
            slots = sorted(
                start for start in scheduled_slots(day, windows) - taken if start >= cutoff
            )
            return AvailabilityResponse(
                doctor_id=doctor_id,
                date=day,
                slots=[start.astimezone(CLINIC_TIMEZONE) for start in slots],
            )

    def upcoming(self, patient_id: UUID) -> list[AppointmentResponse]:
        with self.sessions() as session:
            self._require(session, Patient, patient_id)
            appointments = session.scalars(
                select(Appointment)
                .where(
                    Appointment.patient_id == patient_id,
                    Appointment.status == "BOOKED",
                    Appointment.slot_start > self.clock(),
                )
                .order_by(Appointment.slot_start, Appointment.id)
            )
            return [AppointmentResponse.model_validate(item) for item in appointments]
