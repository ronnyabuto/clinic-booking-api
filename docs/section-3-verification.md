# Section 3 verification

## Current verification — 16 October 2026

The repository is now public at [ronnyabuto/clinic-booking-api](https://github.com/ronnyabuto/clinic-booking-api). Reviewers no longer need a collaborator invitation.

The startup follow-up, merged as `26f5ccc` in [PR #6](https://github.com/ronnyabuto/clinic-booking-api/pull/6), passed **189 tests with zero skips**, SQL constraint probes, Ruff lint/format and dependency consistency against an isolated PostgreSQL 17 database. Both [PR CI](https://github.com/ronnyabuto/clinic-booking-api/actions/runs/38891973844) and [main CI](https://github.com/ronnyabuto/clinic-booking-api/actions/runs/38892107294) passed. The earlier 179-test checkpoint below remains historical evidence.

Render deployment `dep-db8vsilbedkc73f9t1e0` for `79e22ab` built successfully but failed during startup with a port-scan timeout. Captured instance logs stopped at the startup command; they do not establish the original root cause. A manual redeployment of unchanged application code, `dep-db90arnf3r2c73flf85g` for `3fe4e82`, became live at 11:08:48 UTC. The failure did not recur in that attempt, so the evidence supports recovery without proving a deterministic application defect.

Startup now reports migration, seed and server stages, and database connection establishment defaults to 10 seconds per host/address instead of waiting indefinitely. Explicit `connect_timeout` URL options are preserved; SQL execution is not bounded by that connection timeout. This hardens a previously unbounded failure path rather than claiming to establish the original failure's cause.

After main CI passed, Render automatically deployed `26f5ccc` as `dep-db90d5p7lnhs73am8il0`, with trigger `new_commit` and status `live` at **11:13:40 UTC on 16 October 2026**. Its logs show migration preparation at 11:13:05, seeding at 11:13:23, server launch on port 10000 at 11:13:28, and application startup complete at 11:13:34.

The public HTTP lifecycle passed on the recovered service: availability, booking, occupied-slot conflict, rescheduling and old-slot release, blank-reason rejection, patient upcoming appointments, cancellation, repeated-cancellation conflict and rebooking. The retained synthetic appointment survived the subsequent automatic deployment of `26f5ccc`; a public read found it, cancellation returned 200, and availability showed the released slot. No active verification booking was left behind.

Scratch evidence: `/tmp/clinic-startup-fixed-deploys.json`, `/tmp/clinic-startup-fixed-stages.log` and `/tmp/clinic-render-smoke.json`. Render deployment history and the linked GitHub runs provide the remote evidence. Documentation-only follow-ups do not trigger another deployment because the runtime build filter is unchanged.

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
