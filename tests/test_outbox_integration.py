"""Integration tests for the outbox drain and advisory lock (real Postgres)."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.orm import DeclarativeBase

from app.platform.clock import FixedClock
from app.platform.db import Database
from app.platform.outbox import (
    OutboxDispatcher,
    OutboxMessage,
    OutboxRegistry,
    OutboxStatus,
    drain,
    outbox_registry,
)
from app.platform.settings import Settings
from app.worker.main import drain_outbox

pytestmark = pytest.mark.integration

PAST = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)
NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


class _ProbeBase(DeclarativeBase):
    """Isolated metadata so the probe table never pollutes the app's Base."""


class ProbeOutbox(_ProbeBase, OutboxMessage):
    __tablename__ = "probe_outbox"


@pytest.fixture(scope="module")
def postgres_url() -> Iterator[str]:
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")


@pytest_asyncio.fixture
async def db(postgres_url: str) -> AsyncIterator[Database]:
    database = Database.create(Settings(database_url=postgres_url))
    async with database.engine.begin() as conn:
        await conn.run_sync(_ProbeBase.metadata.create_all)
        await conn.execute(text("DELETE FROM probe_outbox"))
    yield database
    await database.dispose()


async def _seed(db: Database, count: int) -> None:
    """Insert `count` due pending messages."""
    async with db.transaction() as session:
        for i in range(count):
            session.add(
                ProbeOutbox(
                    id=f"obx_{i}", topic="probe.test", payload={"i": i}, next_attempt_at=PAST
                )
            )


async def _statuses(db: Database) -> list[tuple[str, int, str]]:
    async with db.session() as session:
        rows = (await session.execute(select(ProbeOutbox))).scalars().all()
        return [(r.id, r.attempts, r.status) for r in rows]


def _registry_for(dispatcher: OutboxDispatcher) -> OutboxRegistry:
    registry = OutboxRegistry()
    registry.register(ProbeOutbox, dispatcher)
    return registry


async def test_drain_delivers_and_marks_sent(db: Database) -> None:
    await _seed(db, 3)
    seen: list[str] = []

    async def ok(row: ProbeOutbox) -> None:
        seen.append(row.id)

    result = await drain(db, _registry_for(ok), FixedClock(NOW), Settings())

    assert result.sent == 3
    assert sorted(seen) == ["obx_0", "obx_1", "obx_2"]
    assert all(status == OutboxStatus.SENT for _, _, status in await _statuses(db))


async def test_drain_reschedules_failures_with_backoff(db: Database) -> None:
    await _seed(db, 2)

    async def boom(_: ProbeOutbox) -> None:
        raise RuntimeError("smtp down")

    settings = Settings(outbox_max_attempts=5, outbox_backoff_base_seconds=5.0)
    result = await drain(db, _registry_for(boom), FixedClock(NOW), settings, rng=lambda: 1.0)

    assert result.retried == 2
    assert result.sent == 0
    async with db.session() as session:
        row = (await session.execute(select(ProbeOutbox).limit(1))).scalar_one()
        assert row.status == OutboxStatus.PENDING
        assert row.attempts == 1
        assert row.last_error == "smtp down"
        assert row.next_attempt_at == datetime(2026, 7, 20, 12, 0, 5, tzinfo=UTC)


async def test_drain_dead_letters_after_max_attempts(db: Database) -> None:
    await _seed(db, 1)

    async def boom(_: ProbeOutbox) -> None:
        raise RuntimeError("permanent")

    result = await drain(db, _registry_for(boom), FixedClock(NOW), Settings(outbox_max_attempts=1))

    assert result.dead_lettered == 1
    rows = await _statuses(db)
    assert len(rows) == 1
    _, attempts, status = rows[0]
    assert status == OutboxStatus.DEAD
    assert attempts == 1


async def test_concurrent_drains_never_double_deliver(db: Database) -> None:
    await _seed(db, 10)
    seen: list[str] = []

    async def ok(row: ProbeOutbox) -> None:
        await asyncio.sleep(0)  # yield, so the two drains actually interleave
        seen.append(row.id)

    registry = _registry_for(ok)
    clock = FixedClock(NOW)
    results = await asyncio.gather(
        drain(db, registry, clock, Settings()),
        drain(db, registry, clock, Settings()),
    )

    assert sum(r.sent for r in results) == 10
    assert sorted(seen) == [f"obx_{i}" for i in range(10)]  # each row exactly once


async def test_advisory_lock_is_mutually_exclusive(db: Database) -> None:
    async with db.advisory_lock(999_001) as first:
        assert first is True
        async with db.advisory_lock(999_001) as second:
            assert second is False
    # Released on exit — reacquirable.
    async with db.advisory_lock(999_001) as third:
        assert third is True


async def test_worker_drain_outbox_runs_the_registry(db: Database) -> None:
    await _seed(db, 2)
    seen: list[str] = []

    async def ok(row: ProbeOutbox) -> None:
        seen.append(row.id)

    outbox_registry.clear()
    outbox_registry.register(ProbeOutbox, ok)
    try:
        ctx = {"db": db, "clock": FixedClock(NOW), "settings": Settings()}
        sent = await drain_outbox(ctx)
    finally:
        outbox_registry.clear()

    assert sent == 2
    assert sorted(seen) == ["obx_0", "obx_1"]
