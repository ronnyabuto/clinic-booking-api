from datetime import datetime, time
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from clinic.policies import WHITE_SPACE


class Base(DeclarativeBase):
    pass


class Doctor(Base):
    __tablename__ = "doctors"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    full_name: Mapped[str] = mapped_column(String(200))


class Patient(Base):
    __tablename__ = "patients"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    full_name: Mapped[str] = mapped_column(String(200))


class DoctorSchedule(Base):
    __tablename__ = "doctor_schedules"
    __table_args__ = (
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_schedule_weekday"),
        CheckConstraint("start_time < end_time", name="ck_schedule_order"),
        CheckConstraint(
            "EXTRACT(MINUTE FROM start_time) IN (0, 30) AND "
            "EXTRACT(SECOND FROM start_time) = 0 AND "
            "EXTRACT(MINUTE FROM end_time) IN (0, 30) AND "
            "EXTRACT(SECOND FROM end_time) = 0",
            name="ck_schedule_grid",
        ),
        Index("ix_schedule_doctor_weekday", "doctor_id", "day_of_week"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    doctor_id: Mapped[UUID] = mapped_column(ForeignKey("doctors.id"))
    day_of_week: Mapped[int]
    start_time: Mapped[time]
    end_time: Mapped[time]


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint("status IN ('BOOKED', 'CANCELLED')", name="ck_appointment_status"),
        CheckConstraint(
            "(status = 'BOOKED' AND cancel_reason IS NULL AND cancelled_at IS NULL) OR "
            "(status = 'CANCELLED' AND cancel_reason IS NOT NULL AND "
            f"btrim(cancel_reason, '{WHITE_SPACE}') <> '' AND cancelled_at IS NOT NULL)",
            name="ck_appointment_cancellation_state",
        ),
        Index(
            "uq_doctor_active_slot",
            "doctor_id",
            "slot_start",
            unique=True,
            postgresql_where=text("status = 'BOOKED'"),
        ),
        Index(
            "ix_patient_active_slot",
            "patient_id",
            "slot_start",
            postgresql_where=text("status = 'BOOKED'"),
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    doctor_id: Mapped[UUID] = mapped_column(ForeignKey("doctors.id"))
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id"))
    slot_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="BOOKED", server_default="BOOKED")
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
