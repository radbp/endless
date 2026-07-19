"""Async database access: engine, session-per-request, transaction helper.

One async engine per process, created in the app lifespan (CLAUDE.md §1.10 — no
import-time side effects) and injected via ``app.state``. Two ways to get a
session:

* :meth:`Database.session` — a plain session for the request scope. Reads need
  nothing more; the caller commits writes explicitly.
* :meth:`Database.transaction` — a session wrapped in a single ``BEGIN … COMMIT``
  that rolls back on any exception. This is the "checkout is one transaction"
  primitive (CLAUDE.md §1.4): reserve stock **and** create the order inside one
  ``async with db.transaction()``.

This module also defines the shared declarative :class:`Base` and the column
mixins every module's tables reuse (CLAUDE.md §5.2): ``created_at`` / ``updated_at``
timestamps and an optimistic-locking ``version``. Models live in each module's
own package; only their shared scaffolding lives here.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from sqlalchemy import BigInteger, Integer, func
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TIMESTAMP

from app.platform.settings import Settings


class Base(DeclarativeBase):
    """Declarative base for every ORM model in the app.

    ``Base.metadata`` is the single target Alembic autogenerates against, so a
    module's tables appear in migrations only once its models import this base.
    """


class TimestampMixin:
    """``created_at`` / ``updated_at`` columns, database-defaulted (CLAUDE.md §5.2)."""

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class VersionMixin:
    """Optimistic-locking ``version`` column (CLAUDE.md §5.2).

    Combine with SQLAlchemy's ``__mapper_args__ = {"version_id_col": version}`` in
    a model to have writes fail on a stale version rather than clobber.
    """

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


# Re-exported so module models spell money columns consistently: minor units in a
# BIGINT, never FLOAT/NUMERIC (CLAUDE.md §5.2).
MoneyMinorUnits = BigInteger


class Database:
    """Owns the async engine and session factory for the process.

    Construct once at startup with :meth:`create`, dispose once at shutdown with
    :meth:`dispose`. Everything else borrows sessions from it.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        """Wrap an existing engine. Prefer :meth:`create` for normal use."""
        self._engine = engine
        self._sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=engine,
            expire_on_commit=False,
            autoflush=False,
        )

    @classmethod
    def create(cls, settings: Settings) -> "Database":
        """Build a :class:`Database` with a pooled async engine from ``settings``.

        ``pool_pre_ping`` guards against connections severed by a Postgres
        failover or an idle-timeout on the private endpoint.
        """
        engine = create_async_engine(
            settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_pre_ping=True,
        )
        return cls(engine)

    @property
    def engine(self) -> AsyncEngine:
        """The underlying async engine (for Alembic and diagnostics)."""
        return self._engine

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield a session for the request scope, closing it on exit.

        No implicit transaction: reads work as-is, and writers either commit
        explicitly or use :meth:`transaction`.
        """
        async with self._sessionmaker() as session:
            yield session

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        """Yield a session inside one ``BEGIN … COMMIT``.

        Commits when the block exits cleanly, rolls back on any exception. This
        is the single-transaction boundary the checkout and webhook paths rely on
        (CLAUDE.md §1.4).
        """
        async with self._sessionmaker() as session, session.begin():
            yield session

    async def ping(self) -> bool:
        """Return ``True`` if a trivial ``SELECT 1`` succeeds — for readiness."""
        from sqlalchemy import text

        async with self._sessionmaker() as session:
            await session.execute(text("SELECT 1"))
        return True

    async def dispose(self) -> None:
        """Close all pooled connections. Call once during app shutdown."""
        await self._engine.dispose()
