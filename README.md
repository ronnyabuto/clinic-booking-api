# Clinic Booking API

FastAPI and PostgreSQL API for a clinic with five doctors. Patients can view available 30-minute slots, book, cancel with a reason, and reschedule.

- **Live API:** [clinic-booking-api-hsqq.onrender.com](https://clinic-booking-api-hsqq.onrender.com)
- **Interactive docs:** [Swagger UI](https://clinic-booking-api-hsqq.onrender.com/docs)
- **Health:** [/health](https://clinic-booking-api-hsqq.onrender.com/health)
- **Repository:** [ronnyabuto/clinic-booking-api](https://github.com/ronnyabuto/clinic-booking-api)

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
- Cancellation retains the record and releases the slot after commit. A nonblank reason and cancellation timestamp are required. Repeated cancellation is a conflict; no cancellation deadline is imposed.
- Schedules are fixed weekly, same-day windows. Seeding rejects overlapping or invalid windows; adjacent windows are valid. Seeding is a single-writer operation; runtime editing, holidays and overnight shifts are outside scope.
- Patients reference existing seeded records. The brief does not prohibit bookings with different doctors at the same time, so no additional restriction is imposed.
- Demo patients are synthetic. Patient IDs are references, not credentials. Authentication and ownership checks are required before real patient use.

### Consistency and failure handling

A partial unique index, `uq_doctor_active_slot`, on `(doctor_id, slot_start)` where status is `BOOKED` gives one owner per doctor-slot under concurrency. Cancelled records can share the slot. This relies on fixed duration and shared-grid validation; uniqueness alone does not prevent arbitrary interval overlap. A second partial index supports upcoming appointments by patient.

Booking validates resources and scheduling rules, inserts, then commits. Availability is a snapshot, not a reservation; the unique index arbitrates competing writes. Only SQLSTATE `23505` on the named doctor-slot index maps to `409 slot_unavailable`.

Cancellation and rescheduling lock the appointment with `SELECT ... FOR UPDATE` under `READ COMMITTED`, then check state. Rescheduling samples UTC time after acquiring the lock, validates the destination and updates in one transaction. An occupied destination rolls back the move and preserves the original slot. Success is returned only after commit.

Deadlocked transactions are retried in fresh sessions up to twice, with bounded jitter. Exhausted retries return `503 booking_temporarily_unavailable`. Other database failures are not automatically replayed.

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

## Section 2 — API Implementation

### Run locally

Requires Python 3.12+ and PostgreSQL 17 (or Docker Compose for the database). Run these commands from the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps -e .
cp .env.example .env
docker compose up -d --wait db
alembic upgrade head
python -m clinic.seed
uvicorn clinic.main:app --host 127.0.0.1 --port 8000
```

Open [Swagger UI](http://127.0.0.1:8000/docs), [ReDoc](http://127.0.0.1:8000/redoc), or [OpenAPI JSON](http://127.0.0.1:8000/openapi.json). Database migrations and seeding are explicit commands, rather than actions repeated by every application worker. For an existing PostgreSQL server, set `DATABASE_URL` in `.env` to a `postgresql+psycopg://` connection string and omit Compose. Environment variables override `.env`.

`requirements.lock` pins runtime dependencies, including transitive packages. `requirements-dev.lock` includes that file and adds the test and lint tools; use it for local development and CI. Render installs only `requirements.lock`. Update shared runtime pins in that file so both environments use the same versions. `pyproject.toml` declares compatible ranges. `docker compose stop` preserves local database data.

### Demo data

The seed command prints all IDs and can be repeated without duplicating its records. It creates synthetic data only:

| Resource | IDs | Schedule |
|---|---|---|
| Five doctors | `00000000-0000-0000-0000-000000000001` through `00000000-0000-0000-0000-000000000005` | Monday–Friday, 09:00–12:00 and 13:00–17:00 in Nairobi |
| Three patients | `10000000-0000-0000-0000-000000000001` through `10000000-0000-0000-0000-000000000003` | Existing references for booking requests |

Schedules are validated as a complete set before insertion. The seed process is a single-writer operation; stop application writers before changing seed data. No doctor, patient, or schedule administration endpoints are included. Appointment responses use UTC; availability uses Nairobi offsets and includes the clinic timezone name.

### Example requests

These examples use Monday, 7 January 2030; choose a future working date if that date is no longer at least an hour away. Set the appointment ID from the booking response before cancelling or rescheduling.

```bash
curl 'http://127.0.0.1:8000/doctors/00000000-0000-0000-0000-000000000001/availability?date=2030-01-07'

curl -X POST http://127.0.0.1:8000/appointments \
  -H 'Content-Type: application/json' \
  -d '{"doctor_id":"00000000-0000-0000-0000-000000000001","patient_id":"10000000-0000-0000-0000-000000000001","slot_start":"2030-01-07T09:00:00+03:00"}'

APPOINTMENT_ID='replace-with-booking-response-id'
curl -X PATCH "http://127.0.0.1:8000/appointments/$APPOINTMENT_ID/reschedule" \
  -H 'Content-Type: application/json' \
  -d '{"slot_start":"2030-01-07T10:00:00+03:00"}'

curl 'http://127.0.0.1:8000/patients/10000000-0000-0000-0000-000000000001/appointments'

curl -X PATCH "http://127.0.0.1:8000/appointments/$APPOINTMENT_ID/cancel" \
  -H 'Content-Type: application/json' \
  -d '{"reason":"Plans changed"}'
```

Availability returns `{"doctor_id":"...","date":"2030-01-07","timezone":"Africa/Nairobi","slots":["2030-01-07T09:00:00+03:00", "..."]}`. The patient endpoint returns an array of active future appointments, ordered by start time. Booking, cancellation, and rescheduling return the appointment record, including IDs, `slot_start`, status, cancellation metadata, and creation/update timestamps.

Domain errors use `{"error":{"code":"slot_unavailable","message":"The doctor's slot is already booked"}}`. Malformed input uses `422 invalid_request` with a `details` array containing field locations and messages. Extra request fields, naive timestamps, numeric timestamps, and blank cancellation reasons are rejected. Missing resources return `404`; occupied slots and cancelled-state transitions return `409`; scheduling failures return `422`; exhausted deadlock retries return `503` with `Retry-After: 1`. Unknown database failures remain server failures and are never mislabeled as occupied slots or automatically replayed.

### Tests and checks

Use a separate disposable database whose name ends in `_test`. Integration tests migrate that database, truncate all clinic tables before each test, and seed synthetic records. Do not run them against a shared database or concurrently against the same test database.

```bash
source .venv/bin/activate
docker compose exec db createdb -U clinic clinic_test
export TEST_DATABASE_URL='postgresql+psycopg://clinic:clinic@localhost:5432/clinic_test'
pytest -q
ruff check clinic migrations tests
ruff format --check clinic migrations tests
```

Run `createdb` once; omit it if the test database already exists. Export `TEST_DATABASE_URL` in the shell even if it appears in `.env`. Without it, integration tests skip explicitly. For checks that need no database, run `pytest -q -m 'not integration'`. Supplying an unreachable database produces an error, rather than a passing/skipped integration result.

The suite uses a deterministic clock for cutoff tests, independent PostgreSQL sessions for concurrency, barriers and bounded waits for contention, and controlled deadlock injection for rollback/retry tests. The additional [SQL probes](tests/database-probes.sql) run against a migrated database with `psql -v ON_ERROR_STOP=1 -f tests/database-probes.sql` and roll back their temporary records. They check constraints directly, rather than exercising the HTTP service.

## Section 3 — Deployment and CI/CD

The API is hosted on Render at [clinic-booking-api-hsqq.onrender.com](https://clinic-booking-api-hsqq.onrender.com). Use [/docs](https://clinic-booking-api-hsqq.onrender.com/docs) to explore the endpoints. `GET /health` checks database connectivity and returns `200 {"status":"ok"}`, or `503` if the database is unavailable.

### Hosting

[render.yaml](render.yaml) describes a Python web service and a private PostgreSQL 17 database in Frankfurt. The live resources are configured separately from Blueprint sync; the file provides a reproducible setup for a new environment. Python is pinned in [.python-version](.python-version), and production installs dependencies from `requirements.lock`.

[scripts/start.sh](scripts/start.sh) runs migrations and seeds synthetic records before starting Uvicorn. A preparation failure prevents startup. Seeding preserves existing appointments. This demo runs as one instance; multiple instances would require a coordinated migration and seed step.

The service uses Render's free plan, so it can sleep when idle and take time to respond to the first request. The demo database expires on **15 November 2026**; renew or replace it before then if reviewers still need access. Only synthetic patient data belongs in this unauthenticated demo.

### Pipeline and deployment branch

[.github/workflows/ci.yml](.github/workflows/ci.yml) runs on every pull request and every push to **`main`**. It provisions an isolated PostgreSQL 17 database, installs development dependencies, checks dependency consistency and Ruff lint/format, applies migrations, runs the unit, integration and concurrency tests, and checks SQL constraints directly. Test results are uploaded as a CI artifact.

Render watches **`main`** with `autoDeployTrigger: checksPass`. After a PR merges, GitHub Actions checks the resulting commit, and Render automatically deploys runtime changes once those checks pass. Failed checks block automatic deployment. The build filter in `render.yaml` excludes documentation, tests and development-only changes from deployment; CI still checks them.

## Section 4 — AI Reflection

### 1. What I used AI for

- **System design:** I used both Codex and Gemini Argon 4 to review the assumptions, challenge edge cases and help document the reasoning and trade-offs.
- **Implementation:** I used Codex to help implement the API, migrations, seed data and tests, and to review validation, concurrency and failure handling against the requirements.
- **Deployment and CI/CD:** I used AI to help configure GitHub Actions. I handled the Render deployment manually.

### 2. An AI suggestion that improved the work

I asked AI to review the Section 2 implementation and tests for accuracy and completeness. The resulting test improvements are recorded in [commit `8a91994`](https://github.com/ronnyabuto/clinic-booking-api/commit/8a919946848ac60fc627ad7b12c7d15be2e75c07).

They check that two doctors can independently book the same time, that each doctor's own hours control availability and booking, and that availability agrees with booking at the exact one-hour cutoff and just beyond it. The review also identified tests that imported the application's whitespace constant as their expected input; explicit test values now make those expectations independent of the implementation.

### 3. AI output that was incomplete, and how I caught it

The initial AI-assisted configuration used one dependency lockfile for production and development and did not limit deployment triggers to runtime changes. Reviewing the dependency files and Render build settings exposed both omissions: production would install test tools, and documentation or test edits could trigger unnecessary builds.

[Commit `79e22ab`](https://github.com/ronnyabuto/clinic-booking-api/commit/79e22abf4293ae6fd51c7567761247de8031b1df) separates runtime and development dependencies and adds a runtime-path build filter. CI still checks every PR and every push to `main`.

### 4. Two decisions I made without AI

- **Use a modular monolith.** Five doctors and one booking workflow did not justify independently deployed services. I chose separate modules within one application to keep responsibilities clear and deployment manageable. I trusted that judgment because the assessment's scale and transaction boundaries were explicit.
- **Make PostgreSQL enforce slot ownership and keep rescheduling atomic.** I chose a partial unique index for active doctor-slot bookings and a transaction for moving an appointment. Availability can become stale between reading and booking, so an application-level check cannot guarantee exclusive ownership. I trusted the database to arbitrate competing writes and preserve the original booking when a move fails. Fixed 30-minute slots on a shared grid make start-time uniqueness sufficient for this design.
