# Clinic Booking API

FastAPI and PostgreSQL API for a clinic with five doctors. Patients can view available 30-minute slots, book, cancel with a reason, and reschedule.

## Section 1 — System Design

### Architecture

A modular monolith keeps request validation, booking transactions, scheduling rules and persistence separate. FastAPI handles the REST contract; SQLAlchemy and Psycopg connect to PostgreSQL; Alembic owns schema changes. Synchronous routes and one session per operation keep the initial service straightforward. Migrations and seeding run explicitly, outside application startup.

| Component | Responsibility |
|---|---|
| `clinic/routes.py`, `schemas.py`, `main.py` | HTTP contract, request/response validation and application lifecycle |
| `clinic/service.py` | Transaction boundaries, lifecycle locks, conflict mapping and retries |
| `clinic/scheduling.py`, `policies.py` | Shared slot generation, destination validation and cancellation policy |
| `clinic/models.py`, `database.py`, `config.py` | Persistence models, sessions and settings |
| `clinic/seed.py`, `migrations/` | Validated demo data and versioned schema |

### Models

| Model | Fields and relationships |
|---|---|
| Doctor | UUID and full name; has schedule windows and appointments |
| Patient | UUID and full name; has appointments |
| DoctorSchedule | Doctor foreign key, weekday (`0..6`, Monday first), local start/end times; multiple windows per day permit breaks |
| Appointment | UUID, doctor/patient foreign keys, timezone-aware slot start, status, cancellation reason/time, creation/update times |

The appointment end is derived as start plus 30 minutes. Status is required and constrained to `BOOKED` or `CANCELLED`. Booked rows have no cancellation metadata; cancelled rows require a nonblank reason and cancellation timestamp. Foreign keys preserve resource references.

### Rules and assumptions

- The clinic uses `Africa/Nairobi`. Appointment input must include a timezone offset. Recurring schedules store local times; appointments store instants using PostgreSQL `TIMESTAMPTZ`.
- Slots start at local `:00` or `:30`, with zero seconds and microseconds, and must fit entirely inside one working window. A `09:00–17:00` window ends with `16:30–17:00`.
- New bookings and every reschedule destination require `slot_start >= now + 1 hour`; equality is allowed. Availability uses the same rules. Existing appointments remain valid as time passes.
- Rescheduling retains the appointment ID, doctor and patient. Validate even an unchanged destination; valid unchanged requests preserve timestamps. An imminent original appointment can move to a valid later slot. Cancelled appointments cannot move.
- Cancellation retains the record and releases the slot after commit. A reason must contain non-whitespace text, encode as UTF-8 and contain no NUL. API normalization and SQL checks share an explicit 25-character Unicode whitespace policy rather than locale-dependent trimming. Repeated cancellation is a conflict; no cancellation deadline is imposed.
- Schedules are fixed weekly, same-day windows. Seeding validates the complete resulting set, including retained rows, rejecting duplicate, overlapping, off-grid or fractional-second windows. Adjacent windows are valid. Seeding is a single-writer operation; runtime editing, holidays and overnight shifts are outside scope.
- Patients reference existing seeded records. The brief permits a patient to book different doctors at the same time; no additional restriction is imposed.
- Demo patients are synthetic. Patient IDs are references, not credentials. Authentication and ownership checks are required before real patient use.

### Consistency and failure handling

A partial unique index, `uq_doctor_active_slot`, on `(doctor_id, slot_start)` where status is `BOOKED` gives one owner per doctor-slot under concurrency. Cancelled records can share the slot. This relies on fixed duration and shared-grid validation; uniqueness alone does not prevent arbitrary interval overlap. A second partial index supports upcoming appointments by patient.

Booking validates resources and scheduling rules, inserts, then commits. Availability is a snapshot, not a reservation; the unique index arbitrates competing writes. Only SQLSTATE `23505` on the named doctor-slot index maps to `409 slot_unavailable`.

Cancellation and rescheduling lock the appointment with `SELECT ... FOR UPDATE` under `READ COMMITTED`, then check state. Rescheduling samples UTC time after acquiring the lock, validates the destination and updates in one transaction. An occupied destination rolls back the move and preserves the original slot. Success is returned only after commit.

For SQLSTATE `40P01`, retry the entire transaction in a fresh session at most twice after the initial attempt. Reload state and sample time again; wait outside the transaction with jitter bounded by 100 ms. Three deadlock failures return `503 booking_temporarily_unavailable`. Unknown connection failures and ambiguous commit outcomes are not automatically retried. No external side effects occur inside these transactions.

Database checks enforce schedule endpoint validity and cancellation metadata. Cross-row schedule non-overlap belongs to the validated seed path while schedules remain immutable; a runtime schedule-writing feature would need transaction-safe database enforcement. Time-dependent notice rules stay in the service rather than SQL CHECK constraints.

References: [PostgreSQL constraints](https://www.postgresql.org/docs/current/ddl-constraints.html), [partial indexes](https://www.postgresql.org/docs/current/indexes-partial.html), [locking](https://www.postgresql.org/docs/current/explicit-locking.html), [SQLAlchemy transactions](https://docs.sqlalchemy.org/en/20/orm/session_basics.html).

### Trade-offs and growth

| Choice | Trade-off |
|---|---|
| Compute availability on demand | Avoids materialized-slot maintenance; introduce caching or precomputed slots only if query measurements justify it |
| PostgreSQL constraints and short transactions | Enforces ownership across application replicas; connection pools must stay within database capacity |
| Fixed duration and start-time uniqueness | Simple slot ownership; variable durations would require interval-overlap enforcement, such as an exclusion constraint |
| Retain current state and cancelled records | Cancellation history survives; previous reschedule times and a full audit trail are not stored |
| One application and immutable schedules | Fits five doctors without service coordination; schedule administration and operational scaling remain separate extensions |
