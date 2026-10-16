from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol
from uuid import UUID

from clinic.errors import BookingError
from clinic.policies import CLINIC_TIMEZONE, MIN_NOTICE, SLOT_DURATION


class ScheduleWindow(Protocol):
    doctor_id: UUID
    day_of_week: int
    start_time: time
    end_time: time


def on_grid(value: time) -> bool:
    return (
        value.tzinfo is None and value.minute in (0, 30) and not (value.second or value.microsecond)
    )


def validate_schedule_set(windows: list[ScheduleWindow]) -> None:
    grouped = defaultdict(list)
    for window in windows:
        if (
            window.doctor_id is None
            or window.day_of_week is None
            or not 0 <= window.day_of_week <= 6
            or window.start_time is None
            or window.end_time is None
            or not on_grid(window.start_time)
            or not on_grid(window.end_time)
            or window.start_time >= window.end_time
        ):
            raise ValueError(
                "Invalid schedule: require weekday 0..6 and ordered on-grid local times"
            )
        grouped[window.doctor_id, window.day_of_week].append(window)
    for group in grouped.values():
        ordered = sorted(group, key=lambda window: window.start_time)
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if current.start_time < previous.end_time:
                raise ValueError("Schedule windows must not overlap or repeat")


def scheduled_slots(day: date, windows: list[ScheduleWindow]) -> set[datetime]:
    slots = set()
    for window in windows:
        if window.day_of_week != day.weekday():
            continue
        start = datetime.combine(day, window.start_time, CLINIC_TIMEZONE)
        end = datetime.combine(day, window.end_time, CLINIC_TIMEZONE)
        while start + SLOT_DURATION <= end:
            slots.add(start.astimezone(UTC))
            start += SLOT_DURATION
    return slots


def validate_destination(start: datetime, windows: list[ScheduleWindow], now: datetime) -> datetime:
    if start.tzinfo is None or start.utcoffset() is None:
        raise BookingError(422, "timezone_required", "slot_start must include a timezone offset")
    try:
        local = start.astimezone(CLINIC_TIMEZONE)
        start = start.astimezone(UTC)
    except OverflowError as error:
        raise BookingError(
            422, "invalid_slot_start", "Timestamp is outside supported dates"
        ) from error
    if not on_grid(local.time()):
        raise BookingError(422, "invalid_slot_grid", "Slots start at :00 or :30 with zero seconds")
    if start < now + MIN_NOTICE:
        raise BookingError(422, "insufficient_notice", "Slot must start at least one hour from now")
    if start not in scheduled_slots(local.date(), windows):
        raise BookingError(
            422, "outside_working_hours", "Slot must fit within a doctor's working window"
        )
    return start


def day_bounds(day: date) -> tuple[datetime, datetime]:
    try:
        return (
            datetime.combine(day, time.min, CLINIC_TIMEZONE).astimezone(UTC),
            datetime.combine(day + timedelta(days=1), time.min, CLINIC_TIMEZONE).astimezone(UTC),
        )
    except OverflowError as error:
        raise BookingError(
            422, "invalid_date", "Date is outside supported date boundaries"
        ) from error
