FROM python:3.14.4-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY requirements.lock pyproject.toml ./
RUN python -m pip install --no-cache-dir -r requirements.lock
COPY clinic/ clinic/
COPY migrations/ migrations/
COPY alembic.ini ./
COPY scripts/prepare-db.sh scripts/
RUN python -m pip install --no-cache-dir --no-deps .

CMD ["sh", "-c", "exec uvicorn clinic.main:app --host 0.0.0.0 --port \"${PORT:-8000}\""]
