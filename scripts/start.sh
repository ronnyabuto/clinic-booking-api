#!/bin/sh
set -eu

printf 'Applying database migrations...\n'
alembic upgrade head
printf 'Seeding synthetic clinic data...\n'
python -u -m clinic.seed
printf 'Starting HTTP server on port %s...\n' "${PORT:-8000}"
exec uvicorn clinic.main:app --host 0.0.0.0 --port "${PORT:-8000}"
