"""Smoke tests for the application skeleton.

These must pass with no environment variables set and no Docker (CLAUDE.md §6).
Using `TestClient` as a context manager runs the lifespan handler, so this also
asserts that startup and shutdown wiring works.

`/readyz` probes Postgres and Redis, which are not available in this hermetic
suite, so its dependencies are replaced with fakes after startup. The real
probes run under `make integration` against testcontainers.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app


class _FakeDep:
    """Stand-in for the DB / Redis wrappers: ``ping`` succeeds or raises."""

    def __init__(self, *, healthy: bool) -> None:
        self._healthy = healthy

    async def ping(self) -> bool:
        if not self._healthy:
            raise ConnectionError("unreachable")
        return True

    # Called by the lifespan on shutdown; no-ops for the fakes.
    async def dispose(self) -> None: ...
    async def aclose(self) -> None: ...


@pytest.fixture
def client_with_deps(request: pytest.FixtureRequest) -> Iterator[TestClient]:
    """A client whose DB and Redis are fakes with the requested health.

    Parametrized via ``indirect``: the param is ``(db_healthy, redis_healthy)``.
    """
    db_healthy, redis_healthy = request.param
    with TestClient(app) as client:
        app.state.db = _FakeDep(healthy=db_healthy)
        app.state.redis = _FakeDep(healthy=redis_healthy)
        yield client


def test_healthz_reports_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "endless-api"


@pytest.mark.parametrize("client_with_deps", [(True, True)], indirect=True)
def test_readyz_ok_when_dependencies_reachable(client_with_deps: TestClient) -> None:
    response = client_with_deps.get("/readyz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"postgres": "ok", "redis": "ok"}


@pytest.mark.parametrize("client_with_deps", [(True, False)], indirect=True)
def test_readyz_degraded_when_a_dependency_is_down(client_with_deps: TestClient) -> None:
    response = client_with_deps.get("/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"] == {"postgres": "ok", "redis": "error"}


def test_openapi_schema_is_generated() -> None:
    """FastAPI generates the spec the TS client is built from (CLAUDE.md §5.3)."""
    with TestClient(app) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/healthz" in response.json()["paths"]
