"""Unit tests for the Arq worker wiring (no DB, no Redis)."""

from typing import Any

from arq.connections import RedisSettings

from app.platform.db import Database
from app.worker.main import WorkerSettings, drain_outbox, shutdown, startup


async def test_startup_and_shutdown_wire_and_dispose_ctx() -> None:
    ctx: dict[str, Any] = {}

    await startup(ctx)
    assert isinstance(ctx["db"], Database)
    assert "clock" in ctx
    assert "settings" in ctx

    await shutdown(ctx)  # disposes the (lazy) engine cleanly


def test_worker_settings_registers_the_outbox_drain() -> None:
    assert drain_outbox in WorkerSettings.functions
    assert WorkerSettings.cron_jobs  # at least the drain cron
    assert isinstance(WorkerSettings.redis_settings, RedisSettings)
