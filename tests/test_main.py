"""Smoke tests for the application skeleton.

These must pass with no environment variables set (CLAUDE.md §6). Using
`TestClient` as a context manager runs the lifespan handler, so this also
asserts that startup and shutdown wiring works.
"""

from fastapi.testclient import TestClient

from app.main import app


def test_healthz_reports_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "endless-api"


def test_readyz_reports_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_openapi_schema_is_generated() -> None:
    """FastAPI generates the spec the TS client is built from (CLAUDE.md §5.3)."""
    with TestClient(app) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/healthz" in response.json()["paths"]
