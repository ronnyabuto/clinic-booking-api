import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url

from clinic.database import make_engine, make_session_factory
from clinic.main import create_app
from clinic.seed import seed_demo
from clinic.service import BookingService

NOW = datetime(2030, 1, 7, 5, tzinfo=UTC)  # Monday, 08:00 Nairobi.


@pytest.fixture(scope="session")
def engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a dedicated disposable PostgreSQL database")
    parsed = make_url(url)
    if not parsed.database or not parsed.database.endswith("_test"):
        pytest.fail("TEST_DATABASE_URL database name must end in _test; tests truncate its tables")
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(config, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
    bounded_url = parsed.set(
        query=dict(parsed.query, options="-c statement_timeout=10000 -c lock_timeout=8000")
    )
    engine = make_engine(bounded_url.render_as_string(hide_password=False))
    yield engine
    engine.dispose()


@pytest.fixture
def sessions(engine):
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE appointments, doctor_schedules, patients, doctors"))
    factory = make_session_factory(engine)
    seed_demo(factory)
    return factory


@pytest.fixture
def service(sessions):
    return BookingService(sessions, clock=lambda: NOW)


@pytest.fixture
def client(service):
    from fastapi.testclient import TestClient

    with TestClient(create_app(service)) as client:
        yield client
