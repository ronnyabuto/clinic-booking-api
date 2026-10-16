# Section 2 verification

Verified on 16 October 2026 using Python 3.14.4 and PostgreSQL 17.9, with the versions pinned in `requirements.lock`.

| Check | Result |
|---|---|
| PyPI and Python-to-PostgreSQL connectivity | HTTPS package metadata/download and direct Psycopg/SQLAlchemy queries succeeded before tests |
| Full pytest suite | 174 passed: 89 non-integration and 85 PostgreSQL/HTTP integration cases |
| Online migrations | Alembic upgraded a new disposable database; model metadata comparison passed |
| SQL probes | `tests/database-probes.sql` passed and rolled back its records |
| Dependency consistency | `python -m pip check` passed |
| Lint, format and compilation | Ruff and `compileall` passed |
| Advisory scan | `pip-audit` found no known vulnerabilities in the 31 pinned dependencies |
| Configuration | Dotenv loading, environment precedence and empty database URL rejection passed |

## Coverage

- HTTP booking, working hours, slot-grid validation, one-hour notice and missing/malformed resources.
- Availability, cancellation/rebooking, retained cancellation history and repeated cancellation errors.
- Atomic rescheduling, occupied-destination rollback, unchanged destinations and cancelled-state precedence.
- Upcoming appointments scoped by patient, active/future filtering and date ordering.
- Concurrent HTTP bookings, insert/move contention, reciprocal moves and cancel/move serialization.
- An observed PostgreSQL row-lock wait crossing the notice cutoff, followed by fresh clock validation.
- Controlled deadlock injection covering rollback, fresh sessions/time, retry limits and HTTP 503; unknown outcomes are not replayed.
- Direct database constraints, repeatable/atomic seeding and retained schedule validation.

## Regression fixes

Cancellation reasons containing NUL or unpaired high/low Unicode surrogates originally reached the database and produced server errors. Three regression cases failed before the correction and passed afterward. The shared normalizer now rejects them with a validation error. HTTP requests return `422 invalid_request`, leave the persisted appointment unchanged, and permit subsequent cancellation with valid multilingual text and an emoji.

`pydantic-settings` was upgraded from 2.14.1 to 2.14.2, and the manifest minimum was raised accordingly. This addresses [GHSA-4xgf-cpjx-pc3j](https://github.com/pydantic/pydantic-settings/security/advisories/GHSA-4xgf-cpjx-pc3j); the affected nested-secrets feature was not used by this application. No transitive upgrades were needed.

## Reproduce

Follow the [README setup and test commands](../README.md#tests-and-checks). Integration tests require an explicitly exported `TEST_DATABASE_URL` pointing to a disposable database whose name ends in `_test`; they truncate clinic tables. Missing configuration skips integration tests, while an unreachable configured database fails setup.

Run `pip-audit -r requirements.lock --no-deps --disable-pip` using a separately installed `pip-audit` tool. The SQL probes can be run against a migrated disposable database with `psql -v ON_ERROR_STOP=1 -f tests/database-probes.sql`.

## Limits

Only Python 3.14.4 and PostgreSQL 17.9 were exercised; the complete declared Python 3.12+ range was not tested. The suite reports one upstream Starlette/AnyIO `BlockingPortal` deprecation warning. Reciprocal moves were tested, but an organic PostgreSQL deadlock was not established; controlled injection verifies recovery. Alembic metadata comparison does not exhaustively compare CHECK expressions, so direct SQL probes supplement it. No load, latency, production authorization or cloud deployment claim follows from these checks.
