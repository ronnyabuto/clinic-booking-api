from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from clinic.config import Settings
from clinic.main import create_app
from clinic.service import BookingService


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
