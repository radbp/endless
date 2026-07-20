"""Transactional outbox: the reliable bridge to the two external edges.

A module writes business state **and** an outbox row in the same transaction
(architecture §7.3). The Arq worker later drains the row, performing the external
action — a Stripe call or an email send — with at-least-once delivery. Nothing
external happens inside the request; nothing durable is lost if the process dies
between the commit and the send.

This module supplies the shared machinery, not any specific table:

* :class:`OutboxMessage` — a declarative mixin. Each module defines its own
  prefixed table (``catalog_outbox``, ``order_outbox``; §5.2) by subclassing it,
  so no module reads another's outbox.
* :class:`OutboxRegistry` — modules register ``(table, dispatcher)`` pairs into
  the shared :data:`outbox_registry`; the worker drains everything registered.
* :func:`drain` — claims due rows with ``FOR UPDATE SKIP LOCKED`` (so multiple
  workers never grab the same row), dispatches them, marks them sent, or on
  failure reschedules with exponential backoff and jitter — dead-lettering after
  ``outbox_max_attempts`` (§8.3).

Delivery is at-least-once, so dispatchers must be idempotent.
"""

import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import Index, Integer, Text, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, declared_attr, mapped_column
from sqlalchemy.types import TIMESTAMP

from app.platform.clock import Clock
from app.platform.db import Database, TimestampMixin
from app.platform.settings import Settings

logger = structlog.get_logger(__name__)


class OutboxStatus:
    """The lifecycle states of an outbox message (stored as plain text)."""

    PENDING = "pending"
    """Awaiting delivery, or waiting for its next retry after a failure."""

    SENT = "sent"
    """Delivered successfully; retained for audit until pruned."""

    DEAD = "dead"
    """Exhausted its attempts; flagged for human inspection (§8.3)."""


class OutboxMessage(TimestampMixin):
    """Declarative mixin for a module's outbox table.

    Subclass alongside the shared ``Base`` and set ``__tablename__`` to the
    module-prefixed name::

        class CatalogOutbox(Base, OutboxMessage):
            __tablename__ = "catalog_outbox"

    The ``id`` is a caller-supplied prefixed ULID (§5.2); everything else has a
    safe default so a module writes a row with just an id, topic, and payload.
    """

    if TYPE_CHECKING:
        # Set by each concrete subclass; declared here so the __table_args__
        # directive below type-checks. No runtime effect (SQLAlchemy reads the
        # real value off the mapped class).
        __tablename__: str

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    """Prefixed ULID, supplied by the writing module."""

    topic: Mapped[str] = mapped_column(Text, nullable=False)
    """Message kind (e.g. ``email.order_paid``); the dispatcher routes on it."""

    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    """The message body — everything the dispatcher needs to act."""

    status: Mapped[str] = mapped_column(
        Text, nullable=False, default=OutboxStatus.PENDING, server_default=OutboxStatus.PENDING
    )
    """One of :class:`OutboxStatus`."""

    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    """How many delivery attempts have been made."""

    next_attempt_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    """Earliest time this row is eligible for (re)delivery."""

    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    """The most recent failure message, truncated; ``None`` until one occurs."""

    processed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    """When the row reached a terminal state (``sent``/``dead``)."""

    @declared_attr.directive
    def __table_args__(cls) -> tuple[Any, ...]:
        # Index the exact predicate the drain claim filters on (§5.2).
        return (Index(f"ix_{cls.__tablename__}_due", "status", "next_attempt_at"),)


OutboxDispatcher = Callable[[Any], Awaitable[None]]
"""Performs the external action for one outbox row. Raises to signal failure."""


@dataclass(frozen=True)
class Registration:
    """A table paired with the dispatcher that delivers its rows."""

    table: type[Any]
    dispatcher: OutboxDispatcher


class OutboxRegistry:
    """The set of outbox tables the worker drains.

    Modules register their table and dispatcher during app wiring (registry
    registration is the one import-time-ish side effect CLAUDE.md §1.10 allows).
    The worker iterates every registration each drain pass.
    """

    def __init__(self) -> None:
        """Create an empty registry."""
        self._registrations: list[Registration] = []

    def register(self, table: type[Any], dispatcher: OutboxDispatcher) -> None:
        """Register ``table`` to be drained by ``dispatcher``."""
        self._registrations.append(Registration(table=table, dispatcher=dispatcher))

    @property
    def registrations(self) -> tuple[Registration, ...]:
        """The registered ``(table, dispatcher)`` pairs, in registration order."""
        return tuple(self._registrations)

    def clear(self) -> None:
        """Drop all registrations (used by tests)."""
        self._registrations.clear()


outbox_registry = OutboxRegistry()
"""Process-wide registry that modules register into and the worker drains."""


def compute_backoff(
    attempt: int,
    *,
    base_seconds: float,
    cap_seconds: float,
    rng: Callable[[], float] = random.random,
) -> float:
    """Return the retry delay in seconds for a failed ``attempt`` (1-based).

    Exponential (``base * 2**(attempt-1)``) capped at ``cap_seconds``, then full
    jitter: uniformly scaled into ``[0, ceiling)`` so retries from many workers
    spread out instead of thundering. ``rng`` returns a float in ``[0, 1)`` and is
    injectable for deterministic tests.
    """
    ceiling = min(cap_seconds, base_seconds * 2.0 ** (attempt - 1))
    return ceiling * rng()


@dataclass
class DrainResult:
    """Tally of one drain pass, for logging and tests."""

    sent: int = 0
    retried: int = 0
    dead_lettered: int = 0

    @property
    def total(self) -> int:
        """Rows touched this pass."""
        return self.sent + self.retried + self.dead_lettered


async def _claim_one(session: Any, table: type[Any], now: datetime) -> Any:
    """Claim the oldest due pending row of ``table``, skipping locked rows."""
    stmt = (
        select(table)
        .where(table.status == OutboxStatus.PENDING, table.next_attempt_at <= now)
        .order_by(table.next_attempt_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


def _record_failure(row: Any, exc: Exception, now: datetime, settings: Settings, rng: Any) -> str:
    """Update ``row`` for a failed delivery; return the resulting status."""
    row.attempts += 1
    row.last_error = str(exc)[:1000]
    if row.attempts >= settings.outbox_max_attempts:
        row.status = OutboxStatus.DEAD
        row.processed_at = now
    else:
        delay = compute_backoff(
            row.attempts,
            base_seconds=settings.outbox_backoff_base_seconds,
            cap_seconds=settings.outbox_backoff_cap_seconds,
            rng=rng,
        )
        row.next_attempt_at = now + timedelta(seconds=delay)
    return str(row.status)


async def drain(
    db: Database,
    registry: OutboxRegistry,
    clock: Clock,
    settings: Settings,
    *,
    rng: Callable[[], float] = random.random,
) -> DrainResult:
    """Deliver every due message across all registered outbox tables.

    Each row is handled in its own transaction: claim (locking the row), dispatch,
    then mark sent — or, on a raised dispatcher error, reschedule with backoff or
    dead-letter. The dispatcher runs inside the transaction so the lock is held
    until the outcome is durably recorded, and the exception is caught so the
    status update commits rather than rolling back. Processes at most
    ``outbox_batch_size`` rows per table per pass.
    """
    result = DrainResult()
    for registration in registry.registrations:
        processed = 0
        while processed < settings.outbox_batch_size:
            async with db.transaction() as session:
                row = await _claim_one(session, registration.table, clock.now())
                if row is None:
                    break
                processed += 1
                try:
                    await registration.dispatcher(row)
                except Exception as exc:
                    status = _record_failure(row, exc, clock.now(), settings, rng)
                    if status == OutboxStatus.DEAD:
                        result.dead_lettered += 1
                        logger.error(
                            "outbox.dead_lettered",
                            table=registration.table.__tablename__,
                            outbox_id=row.id,
                            topic=row.topic,
                            attempts=row.attempts,
                        )
                    else:
                        result.retried += 1
                else:
                    row.status = OutboxStatus.SENT
                    row.processed_at = clock.now()
                    result.sent += 1
    if result.total:
        logger.info(
            "outbox.drained",
            sent=result.sent,
            retried=result.retried,
            dead_lettered=result.dead_lettered,
        )
    return result
