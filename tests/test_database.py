from datetime import UTC, datetime, time
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from clinic.models import Appointment, Doctor, DoctorSchedule
from clinic.policies import WHITE_SPACE
from clinic.seed import DOCTOR_IDS, PATIENT_IDS, demo_schedules, seed_demo

pytestmark = pytest.mark.integration
START = datetime(2030, 1, 7, 6, tzinfo=UTC)


@pytest.mark.parametrize(
    "fields",
    [
        {"status": None},
        {"status": "UNKNOWN"},
        {"status": "CANCELLED"},
        {"status": "CANCELLED", "cancel_reason": "Reason"},
        {"status": "CANCELLED", "cancel_reason": None, "cancelled_at": START},
        {"status": "CANCELLED", "cancel_reason": "", "cancelled_at": START},
        {"status": "CANCELLED", "cancel_reason": WHITE_SPACE, "cancelled_at": START},
        {"status": "BOOKED", "cancel_reason": "Reason"},
        {"status": "BOOKED", "cancelled_at": START},
    ]
    + [
        {"status": "CANCELLED", "cancel_reason": char, "cancelled_at": START}
        for char in WHITE_SPACE
    ],
)
def test_database_rejects_invalid_cancellation_state(sessions, fields):
    row = (
        dict(id=uuid4(), doctor_id=DOCTOR_IDS[0], patient_id=PATIENT_IDS[0], slot_start=START)
        | fields
    )
    with pytest.raises(IntegrityError), sessions() as session, session.begin():
        session.execute(Appointment.__table__.insert().values(**row))


@pytest.mark.parametrize(
    "fields",
    [
        {"day_of_week": None},
        {"doctor_id": None},
        {"day_of_week": 7},
        {"start_time": None},
        {"end_time": None},
        {"start_time": time(14)},
        {"start_time": time(9, 15)},
        {"end_time": time(12, 15)},
        {"start_time": time(9, 0, 0, 1)},
        {"end_time": time(12, 0, 0, 1)},
    ],
)
def test_database_rejects_invalid_schedule_endpoints(sessions, fields):
    row = (
        dict(
            id=uuid4(),
            doctor_id=DOCTOR_IDS[0],
            day_of_week=0,
            start_time=time(9),
            end_time=time(12),
        )
        | fields
    )
    with pytest.raises(IntegrityError), sessions() as session, session.begin():
        session.execute(DoctorSchedule.__table__.insert().values(**row))


def test_seed_is_repeatable_and_rejects_overlap_atomically(sessions):
    seed_demo(sessions)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Doctor)) == 5
        before = session.scalar(select(func.count()).select_from(DoctorSchedule))
        assert before == 50
    invalid = demo_schedules() + [
        DoctorSchedule(
            id=uuid4(),
            doctor_id=DOCTOR_IDS[0],
            day_of_week=0,
            start_time=time(10),
            end_time=time(11),
        )
    ]
    with pytest.raises(ValueError, match="overlap"):
        seed_demo(sessions, invalid)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(DoctorSchedule)) == before


def test_seed_validates_retained_windows_before_appending(sessions):
    with sessions() as session, session.begin():
        session.add(
            DoctorSchedule(
                doctor_id=DOCTOR_IDS[0], day_of_week=0, start_time=time(10), end_time=time(11)
            )
        )
    with pytest.raises(ValueError, match="overlap"):
        seed_demo(sessions)


def test_migrations_match_model_metadata(engine, sessions):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from clinic.models import Base

    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
