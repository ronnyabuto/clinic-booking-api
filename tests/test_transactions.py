from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import DBAPIError

from clinic.errors import BookingError
from clinic.service import BookingService


class DatabaseFailure(Exception):
    def __init__(self, state, constraint=None):
        self.sqlstate = state
        self.diag = SimpleNamespace(constraint_name=constraint)


def failure(state, constraint=None):
    return DBAPIError(None, None, DatabaseFailure(state, constraint))


class Sessions:
    def __init__(self, commit_failures=()):
        self.opened = []
        self.committed = []
        self.rolled_back = []
        self.closed = []
        self.commit_failures = iter(commit_failures)

    @contextmanager
    def __call__(self):
        owner = self

        class Session:
            @contextmanager
            def begin(self):
                try:
                    yield
                    error = next(owner.commit_failures, None)
                    if error:
                        raise error
                    owner.committed.append(self)
                except Exception:
                    owner.rolled_back.append(self)
                    raise

        session = Session()
        self.opened.append(session)
        try:
            yield session
        finally:
            self.closed.append(session)


def test_deadlock_retries_whole_operation_in_fresh_sessions(monkeypatch):
    sessions = Sessions()
    service = BookingService(sessions)
    samples = []
    delays = []

    def operation(session):
        samples.append(session)
        if len(samples) < 3:
            raise failure("40P01")
        return "committed"

    def sleep(delay):
        assert len(sessions.closed) == len(samples)
        delays.append(delay)

    monkeypatch.setattr("clinic.service.time.sleep", sleep)
    assert service._write(operation) == "committed"
    assert len(set(samples)) == 3
    assert sessions.rolled_back == samples[:2]
    assert sessions.committed == samples[2:]
    assert len(delays) == 2 and all(0 <= delay <= 0.1 for delay in delays)


def test_three_deadlocks_return_503(monkeypatch):
    sessions = Sessions()
    monkeypatch.setattr("clinic.service.time.sleep", lambda _: None)

    def operation(session):
        raise failure("40P01")

    with pytest.raises(BookingError) as raised:
        BookingService(sessions)._write(operation)
    assert raised.value.status == 503
    assert raised.value.code == "booking_temporarily_unavailable"
    assert len(sessions.opened) == len(sessions.rolled_back) == 3


@pytest.mark.parametrize(
    "state,constraint,expected",
    [
        ("23505", "uq_doctor_active_slot", BookingError),
        ("23505", "patients_pkey", DBAPIError),
        ("23503", "appointments_patient_id_fkey", DBAPIError),
        ("08006", None, DBAPIError),
        (None, None, DBAPIError),
    ],
)
def test_only_named_slot_conflicts_translate_and_unknown_outcomes_never_retry(
    state, constraint, expected
):
    sessions = Sessions(commit_failures=[failure(state, constraint)])
    with pytest.raises(expected) as raised:
        BookingService(sessions)._write(lambda session: "not returned")
    assert len(sessions.opened) == len(sessions.rolled_back) == 1
    assert not sessions.committed
    if expected is BookingError:
        assert raised.value.status == 409
        assert raised.value.code == "slot_unavailable"


def test_deadlock_during_commit_reexecutes_operation(monkeypatch):
    sessions = Sessions(commit_failures=[failure("40P01"), None])
    monkeypatch.setattr("clinic.service.time.sleep", lambda _: None)
    calls = []

    def operation(session):
        calls.append(session)
        return len(calls)

    assert BookingService(sessions)._write(operation) == 2
    assert len(calls) == 2
    assert sessions.rolled_back == calls[:1]
    assert sessions.committed == calls[1:]


def test_domain_failure_after_deadlock_is_returned_without_further_retry(monkeypatch):
    sessions = Sessions()
    monkeypatch.setattr("clinic.service.time.sleep", lambda _: None)

    def operation(session):
        if len(sessions.opened) == 1:
            raise failure("40P01")
        raise BookingError(422, "insufficient_notice", "Clock has advanced")

    with pytest.raises(BookingError) as raised:
        BookingService(sessions)._write(operation)
    assert raised.value.code == "insufficient_notice"
    assert len(sessions.opened) == 2
