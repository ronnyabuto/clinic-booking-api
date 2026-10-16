from datetime import time
from uuid import UUID, uuid5

from sqlalchemy import select

from clinic.config import Settings
from clinic.database import make_engine, make_session_factory
from clinic.models import Doctor, DoctorSchedule, Patient
from clinic.scheduling import validate_schedule_set

DOCTOR_IDS = [UUID(f"00000000-0000-0000-0000-{number:012d}") for number in range(1, 6)]
PATIENT_IDS = [UUID(f"10000000-0000-0000-0000-{number:012d}") for number in range(1, 4)]


def demo_schedules() -> list[DoctorSchedule]:
    windows = []
    for doctor_id in DOCTOR_IDS:
        for weekday in range(5):
            for start, end in ((time(9), time(12)), (time(13), time(17))):
                windows.append(
                    DoctorSchedule(
                        id=uuid5(doctor_id, f"{weekday}:{start}"),
                        doctor_id=doctor_id,
                        day_of_week=weekday,
                        start_time=start,
                        end_time=end,
                    )
                )
    return windows


def seed_demo(sessions, windows: list[DoctorSchedule] | None = None) -> None:
    proposed = demo_schedules() if windows is None else windows
    with sessions() as session, session.begin():
        existing = list(session.scalars(select(DoctorSchedule)))
        existing_by_id = {window.id: window for window in existing}
        additions = []
        for window in proposed:
            saved = existing_by_id.get(window.id)
            if saved is None:
                additions.append(window)
            elif (saved.doctor_id, saved.day_of_week, saved.start_time, saved.end_time) != (
                window.doctor_id,
                window.day_of_week,
                window.start_time,
                window.end_time,
            ):
                raise ValueError("Existing schedule differs from demo seed")
        validate_schedule_set(existing + additions)
        for number, doctor_id in enumerate(DOCTOR_IDS, 1):
            if session.get(Doctor, doctor_id) is None:
                session.add(Doctor(id=doctor_id, full_name=f"Demo Doctor {number}"))
        for number, patient_id in enumerate(PATIENT_IDS, 1):
            if session.get(Patient, patient_id) is None:
                session.add(Patient(id=patient_id, full_name=f"Demo Patient {number}"))
        session.flush()
        session.add_all(additions)


def main():
    engine = make_engine(Settings().database_url)
    try:
        seed_demo(make_session_factory(engine))
    finally:
        engine.dispose()
    print("Seeded five synthetic doctors (Mon–Fri 09–12, 13–17 Nairobi) and three patients.")
    print("Doctor IDs:", *DOCTOR_IDS, sep="\n")
    print("Patient IDs:", *PATIENT_IDS, sep="\n")


if __name__ == "__main__":
    main()
