import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event

import pytest
from psycopg.errors import DeadlockDetected
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from clinic.errors import BookingError
from clinic.models import Appointment
from clinic.seed import DOCTOR_IDS, PATIENT_IDS
from clinic.service import BookingService

pytestmark = pytest.mark.integration
NOW = datetime(2030, 1, 7, 5, tzinfo=UTC)
FIRST = NOW + timedelta(hours=1)
SECOND = FIRST + timedelta(hours=1)
THIRD = SECOND + timedelta(hours=1)
DOCTOR = DOCTOR_IDS[0]
PATIENT = PATIENT_IDS[0]


def outcome(operation):
    try:
        return operation()
    except BookingError as error:
        return error


def test_concurrent_http_bookings_have_one_winner(client, service, sessions):
    barrier = Barrier(2, timeout=5)

    def clock():
        barrier.wait()
        return NOW

    service.clock = clock

    def book():
        return client.post(
            "/appointments",
            json={
                "doctor_id": str(DOCTOR),
                "patient_id": str(PATIENT),
                "slot_start": FIRST.isoformat(),
            },
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(book) for _ in range(2)]
        responses = [future.result(timeout=15) for future in futures]
    assert sorted(response.status_code for response in responses) == [201, 409]
    with sessions() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(Appointment).where(Appointment.status == "BOOKED")
            )
            == 1
        )


def test_insert_and_reschedule_contend_for_one_destination(service, sessions):
    original = service.book(DOCTOR, PATIENT, FIRST)
    barrier = Barrier(2, timeout=5)

    def clock():
        barrier.wait()
        return NOW

    service.clock = clock
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(outcome, lambda: service.book(DOCTOR, PATIENT, SECOND)),
            pool.submit(outcome, lambda: service.reschedule(original.id, SECOND)),
        ]
        results = [future.result(timeout=15) for future in futures]
    assert sum(isinstance(result, BookingError) for result in results) == 1
    assert (
        next(result for result in results if isinstance(result, BookingError)).code
        == "slot_unavailable"
    )
    with sessions() as session:
        active = list(session.scalars(select(Appointment).where(Appointment.status == "BOOKED")))
        assert sum(item.slot_start == SECOND for item in active) == 1
        saved = session.get(Appointment, original.id)
        assert saved.slot_start == (FIRST if isinstance(results[1], BookingError) else SECOND)


def test_reciprocal_reschedules_preserve_both_originals(service, sessions):
    first = service.book(DOCTOR, PATIENT, FIRST)
    second = service.book(DOCTOR, PATIENT, SECOND)
    barrier = Barrier(2, timeout=5)

    def move(appointment_id, destination):
        first_sample = True

        def clock():
            nonlocal first_sample
            if first_sample:
                first_sample = False
                barrier.wait()
            return NOW

        return outcome(
            lambda: BookingService(sessions, clock).reschedule(appointment_id, destination)
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(move, first.id, SECOND), pool.submit(move, second.id, FIRST)]
        results = [future.result(timeout=15) for future in futures]
    assert all(
        isinstance(result, BookingError) and result.code == "slot_unavailable" for result in results
    )
    with sessions() as session:
        assert session.get(Appointment, first.id).slot_start == FIRST
        assert session.get(Appointment, second.id).slot_start == SECOND


def test_concurrent_cancel_and_reschedule_never_revive_cancelled_record(service, sessions):
    original = service.book(DOCTOR, PATIENT, FIRST)
    barrier = Barrier(2, timeout=5)

    def run(operation):
        barrier.wait()
        return outcome(operation)

    with ThreadPoolExecutor(max_workers=2) as pool:
        cancel = pool.submit(run, lambda: service.cancel(original.id, "Changed"))
        move = pool.submit(run, lambda: service.reschedule(original.id, SECOND))
        assert cancel.result(timeout=15).status == "CANCELLED"
        moved = move.result(timeout=15)
        if isinstance(moved, BookingError):
            assert moved.code == "appointment_cancelled"
    with sessions() as session:
        saved = session.get(Appointment, original.id)
        assert saved.status == "CANCELLED"
        assert saved.cancel_reason == "Changed"
    assert service.book(DOCTOR, PATIENT, FIRST).status == "BOOKED"
    assert service.book(DOCTOR, PATIENT, SECOND).status == "BOOKED"


def test_lock_wait_samples_clock_after_lock_and_rejects_expired_destination(
    service, sessions, engine
):
    original = service.book(DOCTOR, PATIENT, FIRST)
    lock_query_started = Event()
    sampled = Event()
    current = [NOW]

    def clock():
        sampled.set()
        return current[0]

    def before_execute(connection, cursor, statement, parameters, context, executemany):
        if "FOR UPDATE" in statement:
            lock_query_started.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with sessions() as holder, holder.begin():
            holder.scalar(
                select(Appointment).where(Appointment.id == original.id).with_for_update()
            )
            event.listen(engine, "before_cursor_execute", before_execute)
            try:
                future = pool.submit(
                    outcome, lambda: BookingService(sessions, clock).reschedule(original.id, SECOND)
                )
                assert lock_query_started.wait(timeout=5)
                deadline = time.monotonic() + 5
                while True:
                    with engine.connect() as observer:
                        blocked = observer.scalar(
                            text(
                                "SELECT count(*) FROM pg_stat_activity "
                                "WHERE datname = current_database() "
                                "AND cardinality(pg_blocking_pids(pid)) > 0"
                            )
                        )
                    if blocked:
                        break
                    assert time.monotonic() < deadline, "Expected a real PostgreSQL row-lock wait"
                    time.sleep(0.01)
                assert not sampled.is_set()
                current[0] = SECOND - timedelta(hours=1) + timedelta(microseconds=1)
            finally:
                event.remove(engine, "before_cursor_execute", before_execute)
        result = future.result(timeout=15)
    assert isinstance(result, BookingError)
    assert result.code == "insufficient_notice"
    with sessions() as session:
        assert session.get(Appointment, original.id).slot_start == FIRST


def failing_sessions(engine, failures):
    attempts = []

    class FlakySession(Session):
        def flush(self, objects=None):
            dirty = bool(self.new or self.dirty)
            super().flush(objects)
            if dirty:
                attempts.append(self)
                if len(attempts) <= failures:
                    raise DBAPIError(None, None, DeadlockDetected("injected after flush"))

    return sessionmaker(engine, class_=FlakySession, expire_on_commit=False), attempts


def test_deadlock_retry_rolls_back_real_write_and_revalidates_time(
    service, sessions, engine, monkeypatch
):
    original = service.book(DOCTOR, PATIENT, FIRST)
    flaky, attempts = failing_sessions(engine, 1)
    samples = iter([NOW, SECOND - timedelta(hours=1) + timedelta(microseconds=1)])
    retrying = BookingService(flaky, clock=lambda: next(samples))
    monkeypatch.setattr("clinic.service.time.sleep", lambda _: None)
    with pytest.raises(BookingError) as raised:
        retrying.reschedule(original.id, SECOND)
    assert raised.value.code == "insufficient_notice"
    assert len(attempts) == 1
    with sessions() as session:
        assert session.get(Appointment, original.id).slot_start == FIRST


def test_deadlock_retries_complete_booking_and_only_one_row_commits(sessions, engine, monkeypatch):
    flaky, attempts = failing_sessions(engine, 2)
    samples = iter([NOW, NOW + timedelta(seconds=1), NOW + timedelta(seconds=2)])
    monkeypatch.setattr("clinic.service.time.sleep", lambda _: None)
    result = BookingService(flaky, clock=lambda: next(samples)).book(DOCTOR, PATIENT, THIRD)
    assert len(set(attempts)) == 3
    assert result.created_at == NOW + timedelta(seconds=2)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Appointment)) == 1


def test_deadlock_exhaustion_returns_503_over_http(client, engine, monkeypatch):
    flaky, attempts = failing_sessions(engine, 3)
    client.app.state.booking_service = BookingService(flaky, clock=lambda: NOW)
    monkeypatch.setattr("clinic.service.time.sleep", lambda _: None)
    response = client.post(
        "/appointments",
        json={
            "doctor_id": str(DOCTOR),
            "patient_id": str(PATIENT),
            "slot_start": THIRD.isoformat(),
        },
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "booking_temporarily_unavailable"
    assert response.headers["Retry-After"] == "1"
    assert len(set(attempts)) == 3
