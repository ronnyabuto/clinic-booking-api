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

The suite retains the upstream Starlette/AnyIO deprecation warning recorded in Section 2.

## GitHub and Render evidence

- [Implementation PR #1](https://github.com/ronnyabuto/clinic-booking-api/pull/1) passed [PR CI](https://github.com/ronnyabuto/clinic-booking-api/actions/runs/38876115081), including all 179 tests and the SQL probes, before merge.
- The resulting main commit, `d71ad2a629a481d42e8153b1b904116bdd2a6d09`, passed [main CI](https://github.com/ronnyabuto/clinic-booking-api/actions/runs/38876312188).
- Render's own Blueprint validator returned `valid: true`, planning the web service and database. The live resources were provisioned via the authenticated API using the same settings; they are not managed by Blueprint sync.
- The live service, `srv-db8uakvf3r2c73feuqpg`, reports branch `main`, trigger `checksPass`, Python runtime, free plan, Frankfurt region, one instance and health-check path `/health`.
- Automatic deployment `dep-db8uatnhvcus739cp68g` reports trigger `new_commit`, the main commit above, and status `live` at 08:53:07 UTC on 16 October 2026. No manual deploy hook was used for this deployment.
- An earlier initial deployment failed safely because the database was still provisioning and its private hostname did not resolve. The subsequent automatic deployment succeeded after database provisioning, without changing application code.
- Public [health](https://clinic-booking-api-hsqq.onrender.com/health), [OpenAPI](https://clinic-booking-api-hsqq.onrender.com/openapi.json) and [Swagger UI](https://clinic-booking-api-hsqq.onrender.com/docs) returned 200. The public lifecycle check verified availability, booking (201), duplicate conflict (409), rescheduling and old-slot release, blank-reason rejection (422), upcoming appointments, cancellation, repeated-cancellation conflict (409), and rebooking the released slot (201).
- Database `dpg-db8uajrbc2fs73c7i0ig-a` uses PostgreSQL 17, the free plan and an empty public IP allow list. Its expiry is 15 November 2026 at 08:50 UTC.

The cloud probe is retained locally as `/tmp/clinic-render-smoke.py`, with results in `/tmp/clinic-render-smoke.json`. It uses seeded synthetic records and retains a booking for verification across the URL documentation deployment; its `after-deploy` mode checks persistence and cancels the retained booking. Cloud probes never truncate tables. Render's deployment history and the linked GitHub runs provide durable evidence; `/tmp` files are local scratch artifacts.
