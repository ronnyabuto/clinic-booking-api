#!/bin/sh
set -eu

alembic upgrade head
python -m clinic.seed
exec uvicorn clinic.main:app --host 0.0.0.0 --port "${PORT:-8000}"
