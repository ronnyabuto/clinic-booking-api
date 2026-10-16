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

## Section 2 — API Implementation

### Run locally

Requires Python 3.12+ and PostgreSQL 17 (or Docker Compose for the database). The recorded checks used Python 3.14.4 and PostgreSQL 17.9. Run these commands from the project root:

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

Domain errors use `{"error":{"code":"slot_unavailable","message":"The doctor's slot is already booked"}}`. Malformed input uses `422 invalid_request` with a `details` array containing field locations and messages. Extra request fields, naive timestamps, numeric timestamps, and blank cancellation reasons are rejected. Cancellation reasons containing NUL or unpaired Unicode surrogates also return `422`; valid Unicode text is preserved. Missing resources return `404`; occupied slots and cancelled-state transitions return `409`; scheduling failures return `422`; exhausted deadlock retries return `503` with `Retry-After: 1`. Unknown database failures remain server failures and are never mislabeled as occupied slots or automatically replayed.

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

### Verification and remaining work

The current suite has **189 passing tests with zero skips** when run against PostgreSQL. The [verification record](docs/section-2-verification.md) identifies the checked revision and covers integration, concurrency, connection-timeout checks, invalid-text regressions and the dependency scan. Earlier checkpoint counts are retained as historical evidence.

Section 3 configuration and the Section 4 AI reflection are included below.

## Section 3 — Deployment and CI/CD

Repository: [ronnyabuto/clinic-booking-api](https://github.com/ronnyabuto/clinic-booking-api) (public; reviewers can read the source and CI history without an invitation).

**Public application URL:** [https://clinic-booking-api-hsqq.onrender.com](https://clinic-booking-api-hsqq.onrender.com). Open [Swagger UI](https://clinic-booking-api-hsqq.onrender.com/docs) to explore the API, or [health](https://clinic-booking-api-hsqq.onrender.com/health) to check readiness. The base path has no UI; use `/docs` in a browser. The public booking lifecycle was verified on 16 October 2026; see the [verification record](docs/section-3-verification.md).

### Render setup

The [Render Blueprint](render.yaml) defines a Python web service and a PostgreSQL 17 database in Frankfurt. Both use the free plan. Python is pinned in [.python-version](.python-version), shared by Render and CI. Database access is private to Render's network; the application normalizes Render's `postgresql://` connection string to the existing `postgresql+psycopg://` driver without changing credentials or connection options.

The live resources were provisioned through the authenticated Render API with these settings. They are not attached to a Blueprint sync; the YAML provides a reproducible setup for a new environment. The live database's internal connection string is stored in Render's `DATABASE_URL` environment variable. No database or Render credentials are stored in the repository or GitHub Actions.

1. Connect your GitHub account to Render and allow access to this repository so Render can observe CI results.
2. For a new environment, create a Blueprint from this repository, select `main`, and apply `render.yaml`. Review both free plans before provisioning. If the workspace already has its single free database, choose another workspace or explicitly select a paid plan. Do not provision a duplicate of the existing live service.
3. Confirm the service deploys from `main` with **After CI Checks Pass**, and that the health-check path is `/health`.
4. Wait for PostgreSQL to become available and the web deployment to become live. If the web service starts before the database's private hostname is ready, the migration fails safely; redeploy after database provisioning completes. Verify availability, booking, rescheduling, cancellation and rebooking using the synthetic IDs documented earlier.

The build installs the pinned dependencies and application. [scripts/start.sh](scripts/start.sh) runs migrations and the repeatable synthetic-data seed before starting Uvicorn on `0.0.0.0:$PORT`. Any migration or seed failure prevents startup. These commands run once per service process, outside the FastAPI lifecycle. Keep this demo at one instance with no concurrent seed or schedule writers. Existing synthetic IDs and appointments survive restarts; seeding does not reset appointments.

Startup logs identify migration, seed and HTTP-server stages. Database connections default to a 10-second timeout per host/address, including migration, seed and request connections. An explicit `connect_timeout` in `DATABASE_URL` overrides the default. This bounds connection establishment, not SQL execution or the entire startup sequence.

Free services do not support Render's separate pre-deploy command, so this demo performs preparation in the start command. For multiple instances or runtime schedule administration, move migration/seed preparation to a separately coordinated release step. Future migrations must remain compatible with the previous application version while Render transitions traffic.

`GET /health` returns `200 {"status":"ok"}` after a successful database query, or `503 {"status":"unavailable"}` on a database error. It does not reveal connection details. Successful migrations and seeding are required before the server starts; health itself checks connectivity, not schema version or seed completeness.

### Pipeline and deployment branch

[.github/workflows/ci.yml](.github/workflows/ci.yml) runs on **every pull request** and on **pushes to `main`**, including merged PRs. Each run starts an isolated PostgreSQL 17 service with a disposable `clinic_test` database, installs `requirements-dev.lock`, checks dependency consistency and Ruff lint/format, migrates a fresh database, runs the entire pytest suite including integration/concurrency tests, and runs the direct SQL constraint probes. Pip's cache key includes both lockfiles. Test results are uploaded as an artifact, including on failure when the report exists. CI uses no production database credentials.

New pushes to a PR cancel its superseded CI run. Main-branch runs are serialized without cancelling the running check. CI has no path filters, so documentation and test changes receive the same checks.

Render's `autoDeployTrigger: checksPass` links deployment to the CI result on **`main`**. After a PR merges, GitHub Actions tests the resulting commit; Render builds and deploys only after the checks pass. Failed checks prevent automatic deployment, and PR branches do not deploy to the live service. No deploy-hook or cloud API secret is required in GitHub Actions.

Render's build filter includes application code, migrations, startup scripts, `alembic.ini`, `pyproject.toml`, the runtime lockfile, `.python-version` and `render.yaml`. Documentation, tests, CI configuration and development-tool pins alone do not trigger an application deployment. The live service is managed through the Render API rather than Blueprint sync; keep its build filter aligned with `render.yaml` when changing these paths.

`main` has no enforced merge check. The repository is now public; branch protection can require PRs and the **Tests and database checks** status. Render's CI gate controls automatic deployment independently of merge protection.

### Operational limits

This is a public synthetic-data assessment demo. Free Render web services sleep after 15 idle minutes and can take about a minute to wake; free PostgreSQL databases expire after 30 days and have no backups. **The current database expires on 15 November 2026 at 08:50 UTC.** Confirm the database remains valid through the submission/review period, or explicitly upgrade before expiry. The service has no authentication or patient ownership checks and must not store real patient data. Application rollbacks do not reverse database migrations; preserve schema compatibility and arrange backups before using paid hosting for persistent data.

References: [Render Blueprint specification](https://render.com/docs/blueprint-spec), [CI-gated deployments and deploy commands](https://render.com/docs/deploys), [free-plan limits](https://render.com/docs/free).

## Section 4 — AI Reflection

### 1. What I used AI for

I used Codex throughout the assessment, with different responsibilities in each section:

- **System design:** I made the design decisions described in Section 1, then used AI to review the assumptions, challenge edge cases and help document the reasoning and trade-offs.
- **Implementation:** AI helped implement the API, migrations, seed data and tests. I also used it to review validation, concurrency and failure handling against the assessment requirements.
- **Deployment and CI/CD:** AI helped configure GitHub Actions and Render, troubleshoot deployment, verify the public booking lifecycle and document the setup.
- **Reflection:** AI helped inspect the commit history and draft this account. I supplied the distinction between my own design decisions and AI assistance.

### 2. An AI suggestion that improved the work

One useful contribution was strengthening the tests beyond successful requests and duplicate-booking checks. My Section 2 review prompt asked AI to check the implementation for “accuracy, completeness and senior level implementation.”

The subsequent test improvements are recorded in [commit `8a91994`](https://github.com/ronnyabuto/clinic-booking-api/commit/8a919946848ac60fc627ad7b12c7d15be2e75c07). They check that two doctors can independently book the same time, that each doctor's own hours control availability and booking, and that availability agrees with booking at the exact one-hour cutoff and just beyond it. The review also identified tests that imported the application's whitespace constant as their expected input; explicit test values now make those expectations independent of the implementation.

This improved confidence in the documented rules. The PR records 186 passing tests against PostgreSQL and targeted mutation checks for those boundaries; a passing test count alone would not establish that coverage.

### 3. AI output that was incomplete, and how I caught it

The initial AI-assisted deployment setup met the basic CI and automatic-deployment requirements, but it did not distinguish changes that needed an application deployment from documentation or test changes. It also used one dependency lockfile for production and development, so the production install included testing and lint tools.

Reviewing the Render build configuration and dependency files exposed those omissions. [Commit `79e22ab`](https://github.com/ronnyabuto/clinic-booking-api/commit/79e22abf4293ae6fd51c7567761247de8031b1df) adds a runtime-path build filter and separates development dependencies while retaining shared runtime pins. CI still checks every PR and every push to `main`; documentation and test changes alone no longer trigger an application deployment. The follow-up verification included a clean runtime-only install, migrations, seeding, startup and the HTTP booking lifecycle.

The original setup was functional, but operationally incomplete. I needed to review what it installed and when it deployed, rather than treating successful deployment as sufficient evidence.

### 4. Two decisions I made without AI

- **Use a modular monolith.** Five doctors and one booking workflow did not justify independently deployed services. I chose separate modules within one application to keep responsibilities clear and deployment manageable. I trusted that judgment because the assessment's scale and transaction boundaries were explicit.
- **Make PostgreSQL enforce slot ownership and keep rescheduling atomic.** I chose a partial unique index for active doctor-slot bookings and a transaction for moving an appointment. Availability can become stale between reading and booking, so an application-level check cannot guarantee exclusive ownership. I trusted the database to arbitrate competing writes and preserve the original booking when a move fails. Fixed 30-minute slots on a shared grid make start-time uniqueness sufficient for this design.
