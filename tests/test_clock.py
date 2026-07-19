"""Unit tests for the injectable clock (CLAUDE.md §9)."""

from datetime import UTC, datetime

import pytest

from app.platform.clock import Clock, FixedClock, SystemClock


def test_system_clock_returns_timezone_aware_utc() -> None:
    now = SystemClock().now()
    assert now.tzinfo is not None
    assert now.utcoffset() == UTC.utcoffset(None)


def test_system_clock_satisfies_the_protocol() -> None:
    assert isinstance(SystemClock(), Clock)


def test_fixed_clock_freezes_time() -> None:
    instant = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
    clock = FixedClock(instant)
    assert clock.now() == instant
    assert clock.now() == instant  # stable across calls


def test_fixed_clock_advances() -> None:
    clock = FixedClock(datetime(2026, 7, 17, 12, 0, tzinfo=UTC))
    clock.advance(seconds=90)
    assert clock.now() == datetime(2026, 7, 17, 12, 1, 30, tzinfo=UTC)


def test_fixed_clock_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FixedClock(datetime(2026, 7, 17, 12, 0))  # naive on purpose — the test's point
