"""FastAPI application entrypoint.

All wiring happens in the lifespan handler; importing this module must not have
side effects beyond router registration (CLAUDE.md §1.10).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

import structlog
from fastapi import FastAPI, Request, Response
from pydantic import BaseModel

from app.platform.db import Database
from app.platform.logging import configure_logging
from app.platform.otel import setup_telemetry, shutdown_telemetry
from app.platform.redis import RedisClient
from app.platform.settings import Settings, get_settings

logger = structlog.get_logger(__name__)


class HealthResponse(BaseModel):
    """Liveness payload."""

    status: Literal["ok"]
    service: str
    version: str


class ReadyResponse(BaseModel):
    """Readiness payload, including the state of each checked dependency."""

    status: Literal["ok", "degraded"]
    checks: dict[str, str]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start and stop process-wide resources.

    The DB engine and Redis pool are created lazily — neither connects here, so
    the app boots even while Postgres or Redis is still coming up. Actual
    reachability is reported by ``/readyz``.
    """
    settings = get_settings()
    configure_logging(settings)
    setup_telemetry(settings)

    app.state.db = Database.create(settings)
    app.state.redis = RedisClient.create(settings)
    logger.info("app.startup", version=settings.version)

    yield

    logger.info("app.shutdown")
    await app.state.db.dispose()
    await app.state.redis.aclose()
    shutdown_telemetry()


def register_routes(app: FastAPI, settings: Settings) -> None:
    """Attach the operational endpoints.

    Module routers (`app/api/*`) are included here as each module lands, starting
    with Catalog in F1.1.
    """

    @app.get("/healthz", response_model=HealthResponse, tags=["ops"])
    async def healthz() -> HealthResponse:
        """Liveness probe. Must stay cheap — no I/O (architecture §17.4)."""
        return HealthResponse(
            status="ok",
            service=settings.service_name,
            version=settings.version,
        )

    @app.get(
        "/readyz",
        response_model=ReadyResponse,
        tags=["ops"],
        responses={503: {"model": ReadyResponse, "description": "A dependency is unreachable"}},
    )
    async def readyz(request: Request, response: Response) -> ReadyResponse:
        """Readiness probe: reports whether Postgres and Redis are reachable.

        Each dependency is probed independently; a single failure flips the
        overall status to ``degraded`` and the response to ``503`` so the
        orchestrator stops routing traffic, while the body still reports which
        checks passed. Kept off the liveness path so a transient dependency blip
        does not get the container killed (architecture §17.4).
        """
        db: Database = request.app.state.db
        redis: RedisClient = request.app.state.redis

        checks: dict[str, str] = {}
        for name, probe in (("postgres", db.ping), ("redis", redis.ping)):
            try:
                await probe()
                checks[name] = "ok"
            except Exception as exc:  # probe reports failure, never raises
                checks[name] = "error"
                logger.warning("readyz.check_failed", check=name, error=str(exc))

        healthy = all(v == "ok" for v in checks.values())
        if not healthy:
            response.status_code = 503
        return ReadyResponse(status="ok" if healthy else "degraded", checks=checks)


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    settings = get_settings()
    app = FastAPI(
        title="Endless — Jewelry Ecommerce Platform",
        version=settings.version,
        lifespan=lifespan,
    )
    register_routes(app, settings)
    return app


app = create_app()
