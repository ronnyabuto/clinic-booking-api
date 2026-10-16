from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from clinic.errors import BookingError
from clinic.models import DoctorSchedule
from clinic.policies import WHITE_SPACE, normalize_reason
from clinic.scheduling import (
    day_bounds,
    scheduled_slots,
    validate_destination,
    validate_schedule_set,
)
from clinic.schemas import BookAppointment, CancelAppointment
from clinic.seed import DOCTOR_IDS, PATIENT_IDS, demo_schedules

DAY = date(2030, 1, 7)
NOW = datetime(2030, 1, 7, 5, tzinfo=UTC)
DOCTOR = DOCTOR_IDS[0]
WINDOWS = [window for window in demo_schedules() if window.doctor_id == DOCTOR]


def window(start=time(9), end=time(12), weekday=0):
    return DoctorSchedule(
        id=uuid4(), doctor_id=DOCTOR, day_of_week=weekday, start_time=start, end_time=end
    )


@pytest.mark.parametrize("hour,minute", [(9, 0), (11, 30), (13, 0), (16, 30)])
def test_valid_slot_boundaries(hour, minute):
    start = datetime.fromisoformat(f"2030-01-07T{hour:02}:{minute:02}:00+03:00")
    assert validate_destination(start, WINDOWS, NOW) == start.astimezone(UTC)
    assert start in scheduled_slots(DAY, WINDOWS)


@pytest.mark.parametrize(
    "stamp,code",
    [
        ("2030-01-07T08:30:00+03:00", "insufficient_notice"),
        ("2030-01-07T07:00:00+03:00", "insufficient_notice"),
        ("2030-01-07T09:15:00+03:00", "invalid_slot_grid"),
        ("2030-01-07T09:00:01+03:00", "invalid_slot_grid"),
        ("2030-01-07T09:00:00.000001+03:00", "invalid_slot_grid"),
        ("2030-01-07T12:00:00+03:00", "outside_working_hours"),
        ("2030-01-07T12:30:00+03:00", "outside_working_hours"),
        ("2030-01-07T17:00:00+03:00", "outside_working_hours"),
        ("2030-01-12T09:00:00+03:00", "outside_working_hours"),
        ("2030-01-07T09:00:00", "timezone_required"),
    ],
)
def test_invalid_destinations(stamp, code):
    with pytest.raises(BookingError) as raised:
        validate_destination(datetime.fromisoformat(stamp), WINDOWS, NOW)
    assert raised.value.status == 422
    assert raised.value.code == code


def test_notice_equality_and_one_microsecond_late():
    start = datetime(2030, 1, 7, 6, tzinfo=UTC)
    assert validate_destination(start, WINDOWS, NOW) == start
    with pytest.raises(BookingError, match="at least one hour"):
        validate_destination(start, WINDOWS, NOW + timedelta(microseconds=1))


def test_timezone_conversion_uses_local_weekday_and_grid():
    start = datetime.fromisoformat("2030-01-06T22:00:00-08:00")
    assert validate_destination(start, WINDOWS, NOW).hour == 6


def test_availability_is_sorted_unique_and_respects_break():
    slots = sorted(scheduled_slots(DAY, WINDOWS))
    assert len(slots) == 14
    assert len(set(slots)) == 14
    assert slots[0] == datetime(2030, 1, 7, 6, tzinfo=UTC)
    assert slots[-1] == datetime(2030, 1, 7, 13, 30, tzinfo=UTC)
    assert not scheduled_slots(date(2030, 1, 6), WINDOWS)
    assert scheduled_slots(DAY, WINDOWS + WINDOWS) == set(slots)


def test_local_date_bounds_are_half_open_utc():
    lower, upper = day_bounds(DAY)
    assert lower == datetime(2030, 1, 6, 21, tzinfo=UTC)
    assert upper == datetime(2030, 1, 7, 21, tzinfo=UTC)


@pytest.mark.parametrize("day", [date.min, date.max])
def test_unrepresentable_date_boundaries_return_validation_errors(day):
    with pytest.raises(BookingError) as raised:
        day_bounds(day)
    assert raised.value.code == "invalid_date"


def test_unrepresentable_timezone_conversion_returns_validation_error():
    with pytest.raises(BookingError) as raised:
        validate_destination(datetime.fromisoformat("9999-12-31T23:30:00-12:00"), WINDOWS, NOW)
    assert raised.value.code == "invalid_slot_start"


@pytest.mark.parametrize(
    "start,end,weekday",
    [
        (time(12), time(9), 0),
        (time(9), time(9), 0),
        (time(9, 15), time(12), 0),
        (time(9), time(12, 15), 0),
        (time(9, 0, 0, 1), time(12), 0),
        (time(9), time(12, 0, 0, 1), 0),
        (None, time(12), 0),
        (time(9), None, 0),
        (time(9), time(12), -1),
        (time(9), time(12), 7),
        (time(9), time(12), None),
        (time(9, tzinfo=UTC), time(12, tzinfo=UTC), 0),
    ],
)
def test_invalid_schedule_windows(start, end, weekday):
    with pytest.raises(ValueError):
        validate_schedule_set([window(start, end, weekday)])


@pytest.mark.parametrize(
    "other",
    [
        (time(9), time(12)),
        (time(10), time(11)),
        (time(11, 30), time(13)),
        (time(8), time(10)),
    ],
)
def test_duplicate_contained_and_overlapping_windows_rejected(other):
    with pytest.raises(ValueError, match="overlap"):
        validate_schedule_set([window(), window(*other)])


def test_adjacent_windows_and_complete_demo_set_accepted():
    validate_schedule_set(demo_schedules())
    adjacent = [window(), window(time(12), time(13))]
    validate_schedule_set(adjacent)
    assert len(scheduled_slots(DAY, adjacent)) == 8


@pytest.mark.parametrize("reason", ["", WHITE_SPACE, *WHITE_SPACE])
def test_explicit_whitespace_rejected(reason):
    with pytest.raises(ValueError):
        normalize_reason(reason)
    with pytest.raises(ValidationError):
        CancelAppointment(reason=reason)


def test_reason_normalization_is_pinned():
    assert len(WHITE_SPACE) == 25
    assert normalize_reason(WHITE_SPACE + "Changed plans" + WHITE_SPACE) == "Changed plans"
    assert normalize_reason("\u001c") == "\u001c"


@pytest.mark.parametrize(
    "stamp", ["2030-01-07T09:00:00", "1893996000", "2030-01-07", 1893996000, None, True]
)
def test_api_requires_offset_aware_timestamp(stamp):
    with pytest.raises(ValidationError):
        BookAppointment(doctor_id=DOCTOR, patient_id=PATIENT_IDS[0], slot_start=stamp)


def test_api_rejects_extra_input_and_accepts_explicit_offset():
    body = dict(doctor_id=DOCTOR, patient_id=PATIENT_IDS[0], slot_start="2030-01-07T06:00:00Z")
    assert BookAppointment(**body).slot_start.tzinfo is not None
    with pytest.raises(ValidationError):
        BookAppointment(**body, status="CANCELLED")
