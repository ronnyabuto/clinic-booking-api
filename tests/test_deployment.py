import socket
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from clinic.config import Settings
from clinic.database import make_engine
from clinic.main import create_app
from clinic.service import BookingService


@pytest.mark.parametrize("query,expected", [("", 10), ("?connect_timeout=3&sslmode=require", 3)])
def test_database_connections_have_a_timeout_and_preserve_explicit_options(query, expected):
    engine = make_engine(f"postgresql+psycopg://clinic:clinic@localhost/clinic{query}")
    try:
        _, parameters = engine.dialect.create_connect_args(engine.url)
        assert int(parameters["connect_timeout"]) == expected
        if query:
            assert parameters["sslmode"] == "require"
    finally:
        engine.dispose()


def test_unresponsive_database_connection_times_out():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from clinic.database import make_engine; "
                "import sys; make_engine(sys.argv[1]).connect()",
                f"postgresql+psycopg://clinic:clinic@127.0.0.1:{port}/clinic_test",
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=15,
        )
    assert result.returncode != 0
    assert "timeout expired" in result.stderr


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+psycopg"])
def test_hosted_database_url_preserves_credentials_and_connection_options(scheme):
    suffix = "user:p%40ss@db.internal:5432/clinic?sslmode=require"
    settings = Settings(_env_file=None, database_url=f"{scheme}://{suffix}")
    assert settings.database_url == f"postgresql+psycopg://{suffix}"


def test_health_returns_503_on_query_failure_then_200_on_success():
    sessions = MagicMock()
    execute = sessions.return_value.__enter__.return_value.execute
    execute.side_effect = [
        OperationalError("SELECT 1", {}, Exception("secret connection details")),
        None,
    ]
    with TestClient(create_app(BookingService(sessions))) as client:
        response = client.get("/health")
        assert response.status_code == 503
        assert response.json() == {"status": "unavailable"}
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


@pytest.mark.integration
def test_health_uses_the_live_database(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
