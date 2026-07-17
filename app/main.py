"""FastAPI application entrypoint.

All wiring happens in the lifespan handler; importing this module must not have
side effects beyond router registration (CLAUDE.md §1.10).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

import structlog
from fastapi import FastAPI
from pydantic import BaseModel

from app.platform.logging import configure_logging
from app.platform.otel import setup_telemetry, shutdown_telemetry
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
    """Start and stop process-wide resources."""
    settings = get_settings()
    configure_logging(settings)
    setup_telemetry(settings)
    logger.info("app.startup", version=settings.version)

    # TODO(F0.6): open the DB engine and Redis pool here, close them on shutdown.
    yield

    logger.info("app.shutdown")
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

    @app.get("/readyz", response_model=ReadyResponse, tags=["ops"])
    async def readyz() -> ReadyResponse:
        """Readiness probe.

        Reports `ok` with no dependency checks until the DB and Redis pools are
        wired in F0.6, at which point each is probed and reported here.
        """
        # TODO(F0.6): probe Postgres and Redis; return "degraded" on failure.
        checks: dict[str, str] = {}
        return ReadyResponse(status="ok", checks=checks)


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
