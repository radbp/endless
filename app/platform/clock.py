"""Time as an injected dependency.

CLAUDE.md §9 forbids calling ``datetime.now()`` inside ``domain`` or ``service``
code — it makes behaviour untestable. Instead, those layers take a ``Clock`` and
call ``clock.now()``. Production wires ``SystemClock``; tests wire ``FixedClock``
(or any callable) to pin time and make assertions deterministic.

All times are timezone-aware UTC. There is no naive-datetime path on purpose.
"""

from datetime import UTC, datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """A source of the current time.

    Injected wherever ``domain``/``service`` code needs "now". Keeping it an
    interface means tests never depend on wall-clock time.
    """

    def now(self) -> datetime:
        """Return the current instant as a timezone-aware UTC ``datetime``."""
        ...


class SystemClock:
    """The real clock, backed by the operating system.

    The one place a wall-clock read is allowed. Wired in ``app/main.py`` and the
    worker; never imported by ``domain`` code, which receives a ``Clock`` instead.
    """

    def now(self) -> datetime:
        """Return the current UTC time from the system clock."""
        return datetime.now(UTC)


class FixedClock:
    """A clock frozen at a fixed instant, for tests.

    ``advance`` moves it forward so a single test can exercise time-dependent
    behaviour (TTL expiry, reservation sweeps) without sleeping.
    """

    def __init__(self, now: datetime) -> None:
        """Freeze the clock at ``now`` (must be timezone-aware)."""
        if now.tzinfo is None:
            raise ValueError("FixedClock requires a timezone-aware datetime")
        self._now = now

    def now(self) -> datetime:
        """Return the frozen instant."""
        return self._now

    def advance(self, *, seconds: float) -> None:
        """Move the frozen instant forward by ``seconds``."""
        from datetime import timedelta

        self._now = self._now + timedelta(seconds=seconds)
