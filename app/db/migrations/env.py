"""Alembic migration environment (async).

Runs migrations against the async engine, using the application's own settings
for the database URL so there is a single source of truth (CLAUDE.md §1.3) and no
connection string in the repo. Target metadata is the shared ``Base.metadata``
aggregated in ``app/db/base.py``.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.base import Base
from app.platform.settings import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """The async database URL from application settings."""
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Emit SQL to the script output without a live connection (``--sql`` mode)."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    """Configure the context on a live connection and run the migrations."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Open an async connection and run migrations through ``run_sync``."""
    engine = create_async_engine(_database_url(), poolclass=None)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
