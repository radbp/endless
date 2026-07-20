"""Unit tests for the outbox machinery (pure parts — no DB)."""

from datetime import UTC, datetime
from types import SimpleNamespace

from app.platform.outbox import (
    DrainResult,
    OutboxRegistry,
    OutboxStatus,
    _record_failure,
    compute_backoff,
)
from app.platform.settings import Settings


def test_backoff_is_exponential() -> None:
    def at(attempt: int) -> float:
        return compute_backoff(attempt, base_seconds=5.0, cap_seconds=3600.0, rng=lambda: 1.0)

    assert at(1) == 5.0
    assert at(2) == 10.0
    assert at(3) == 20.0


def test_backoff_is_capped() -> None:
    assert compute_backoff(20, base_seconds=5.0, cap_seconds=100.0, rng=lambda: 1.0) == 100.0


def test_backoff_applies_full_jitter() -> None:
    # rng scales the ceiling into [0, ceiling).
    assert compute_backoff(1, base_seconds=8.0, cap_seconds=3600.0, rng=lambda: 0.0) == 0.0
    assert compute_backoff(1, base_seconds=8.0, cap_seconds=3600.0, rng=lambda: 0.5) == 4.0


def test_registry_registers_and_clears() -> None:
    registry = OutboxRegistry()

    async def dispatch(_: object) -> None: ...

    # Assign len() to locals: comparing len(expr) directly makes mypy narrow the
    # property to a fixed-length tuple, which poisons later assertions.
    assert len(registry.registrations) == 0

    registry.register(str, dispatch)
    registry.register(int, dispatch)
    after_register = len(registry.registrations)
    assert after_register == 2
    # The stored table is exercised end-to-end in test_outbox_integration.

    registry.clear()
    after_clear = len(registry.registrations)
    assert after_clear == 0


def test_drain_result_total() -> None:
    assert DrainResult(sent=2, retried=1, dead_lettered=3).total == 6


def _row() -> SimpleNamespace:
    return SimpleNamespace(
        id="obx_1",
        attempts=0,
        last_error=None,
        status=OutboxStatus.PENDING,
        next_attempt_at=None,
        processed_at=None,
    )


def test_record_failure_reschedules_below_max() -> None:
    now = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
    row = _row()
    settings = Settings(outbox_max_attempts=5, outbox_backoff_base_seconds=5.0)

    status = _record_failure(row, RuntimeError("smtp down"), now, settings, lambda: 1.0)

    assert status == OutboxStatus.PENDING
    assert row.attempts == 1
    assert row.last_error == "smtp down"
    assert row.next_attempt_at == datetime(2026, 7, 20, 12, 0, 5, tzinfo=UTC)
    assert row.processed_at is None


def test_record_failure_dead_letters_at_max() -> None:
    now = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
    row = _row()
    row.attempts = 4
    settings = Settings(outbox_max_attempts=5)

    status = _record_failure(row, RuntimeError("still down"), now, settings, lambda: 1.0)

    assert status == OutboxStatus.DEAD
    assert row.attempts == 5
    assert row.processed_at == now


def test_record_failure_truncates_long_errors() -> None:
    now = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
    row = _row()
    status = _record_failure(row, RuntimeError("x" * 5000), now, Settings(), lambda: 1.0)
    assert status == OutboxStatus.PENDING
    assert len(row.last_error) == 1000
