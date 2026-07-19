"""Integration tests for the async database wrapper.

Runs against a real Postgres via testcontainers (CLAUDE.md §6 — never SQLite as a
substitute). Deselected from the unit suite by the ``integration`` marker.
"""

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.platform.db import Database
from app.platform.settings import Settings

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def postgres_url() -> Iterator[str]:
    """Start a throwaway Postgres and yield its async (asyncpg) DSN."""
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")


@pytest_asyncio.fixture
async def db(postgres_url: str) -> AsyncIterator[Database]:
    """A `Database` bound to the test Postgres, with a clean `probe` table."""
    database = Database.create(Settings(database_url=postgres_url))
    async with database.transaction() as session:
        await session.execute(text("CREATE TABLE IF NOT EXISTS probe (id text PRIMARY KEY)"))
        await session.execute(text("DELETE FROM probe"))
    yield database
    await database.dispose()


async def test_ping_succeeds_against_real_postgres(db: Database) -> None:
    assert await db.ping() is True


async def test_transaction_commits_on_clean_exit(db: Database) -> None:
    async with db.transaction() as session:
        await session.execute(text("INSERT INTO probe (id) VALUES ('committed')"))

    async with db.session() as session:
        count = await session.execute(text("SELECT count(*) FROM probe WHERE id = 'committed'"))
        assert count.scalar_one() == 1


async def test_transaction_rolls_back_on_exception(db: Database) -> None:
    with pytest.raises(RuntimeError, match="boom"):
        async with db.transaction() as session:
            await session.execute(text("INSERT INTO probe (id) VALUES ('rolled_back')"))
            raise RuntimeError("boom")

    async with db.session() as session:
        count = await session.execute(text("SELECT count(*) FROM probe WHERE id = 'rolled_back'"))
        assert count.scalar_one() == 0


async def test_session_does_not_autocommit(db: Database) -> None:
    """`session()` gives no implicit commit — an unflushed write must not persist."""
    async with db.session() as session:
        await session.execute(text("INSERT INTO probe (id) VALUES ('uncommitted')"))
        # Leaves the block without committing.

    async with db.session() as session:
        count = await session.execute(text("SELECT count(*) FROM probe WHERE id = 'uncommitted'"))
        assert count.scalar_one() == 0
