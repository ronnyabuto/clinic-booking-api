#!/bin/sh
set -eu

printf 'Applying database migrations...\n'
alembic upgrade head
printf 'Seeding synthetic clinic data...\n'
python -u -m clinic.seed
