"""Arq worker entrypoint — the same codebase, a separate process.

Run with ``arq app.worker.main.WorkerSettings``. Its first job (F0.6) is draining
the transactional outbox; the reservation-expiry sweep (F3.4) and abandoned-cart
checks (F4.10) register here as they land.

Wiring lives in :func:`startup` / :func:`shutdown`, which open and dispose the
worker's own database connection (Arq owns the Redis connection via
``redis_settings``). Jobs read their dependencies off the Arq ``ctx``.
"""

from typing import Any, ClassVar

import structlog
from arq import cron
from arq.connections import RedisSettings

from app.platform.clock import SystemClock
from app.platform.db import Database
from app.platform.logging import configure_logging
from app.platform.outbox import drain, outbox_registry
from app.platform.settings import get_settings

logger = structlog.get_logger(__name__)

OUTBOX_DRAIN_LOCK = 4_820_001
"""Advisory-lock key that makes the outbox drain a singleton across replicas."""


async def startup(ctx: dict[str, Any]) -> None:
    """Open the worker's database connection and shared dependencies."""
    settings = get_settings()
    configure_logging(settings)
    ctx["settings"] = settings
    ctx["db"] = Database.create(settings)
    ctx["clock"] = SystemClock()
    logger.info("worker.startup")


async def shutdown(ctx: dict[str, Any]) -> None:
    """Dispose the worker's database connection."""
    db: Database | None = ctx.get("db")
    if db is not None:
        await db.dispose()
    logger.info("worker.shutdown")


async def drain_outbox(ctx: dict[str, Any]) -> int:
    """Drain every registered outbox table, guarded so only one worker runs it.

    Returns the number of rows delivered this pass. Skips silently when another
    replica holds the advisory lock.
    """
    db: Database = ctx["db"]
    async with db.advisory_lock(OUTBOX_DRAIN_LOCK) as acquired:
        if not acquired:
            return 0
        result = await drain(db, outbox_registry, ctx["clock"], ctx["settings"])
    return result.sent


class WorkerSettings:
    """Arq worker configuration (referenced as ``app.worker.main.WorkerSettings``)."""

    functions: ClassVar[list[Any]] = [drain_outbox]
    cron_jobs: ClassVar[list[Any]] = [
        cron(drain_outbox, second={0, 10, 20, 30, 40, 50}, run_at_startup=True)
    ]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    on_startup = startup
    on_shutdown = shutdown
