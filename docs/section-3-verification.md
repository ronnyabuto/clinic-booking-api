# Section 3 verification

Local verification on 16 October 2026 used Python 3.14.4 and a dedicated PostgreSQL 17 container on port 15432. No shared or cloud database was used for destructive tests.

| Check | Result |
|---|---|
| Full pytest suite | 179 passed, including 86 PostgreSQL integration cases |
| SQL constraint probes | Passed; probe records rolled back |
| Ruff lint and format | Passed |
| Render Blueprint | Validated against Render's published JSON schema |
| GitHub workflow | Validated against SchemaStore's GitHub workflow schema |
| Shell entrypoint | Syntax check passed; actual migration/seed/server startup succeeded |
| HTTP lifecycle | Health, OpenAPI, availability, booking, slot removal, rescheduling, slot release, cancellation and rebooking passed through the running server |
| Hosted URL normalization | PostgreSQL URL schemes preserve encoded credentials and connection options |
| Health failure/recovery | Controlled database error returns 503 without details; a later successful query returns 200 |

The pytest report was written to `/tmp/clinic-section3-tests.xml`. CI retains its own JUnit report as a GitHub Actions artifact. Reproduce the database suite and SQL probes with the README commands, and the startup check with `DATABASE_URL` set and `sh scripts/start.sh` after activating the virtual environment.

The suite retains the upstream Starlette/AnyIO deprecation warning recorded in Section 2. Local startup and schema validation do not establish a live Render deployment or prove a cloud auto-deploy. Those checks remain pending provisioning and an observed merge/deployment cycle.
