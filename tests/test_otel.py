"""Unit tests for the telemetry bootstrap (no live Azure)."""

from collections.abc import Iterator
from typing import Any

import pytest
from opentelemetry import trace

from app.platform import otel
from app.platform.settings import Settings


@pytest.fixture(autouse=True)
def reset_otel_state() -> Iterator[None]:
    """Reset the module globals so each test starts uninitialized."""
    otel._provider = None
    otel._azure_configured = False
    yield
    otel._provider = None
    otel._azure_configured = False


def test_without_connection_string_stays_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(otel, "configure_azure_monitor", lambda **kw: calls.append(kw))

    otel.setup_telemetry(Settings())

    assert calls == []  # Azure exporter never configured
    assert otel._provider is not None  # bare provider installed
    assert otel._azure_configured is False


def test_with_connection_string_configures_azure(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(otel, "configure_azure_monitor", lambda **kw: calls.append(kw))

    conn = "InstrumentationKey=00000000-0000-0000-0000-000000000000"
    otel.setup_telemetry(Settings(applicationinsights_connection_string=conn))

    assert len(calls) == 1
    assert calls[0]["connection_string"] == conn
    assert otel._azure_configured is True
    assert otel._provider is None  # Azure owns the providers


def test_setup_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(otel, "configure_azure_monitor", lambda **kw: calls.append(kw))

    conn = "InstrumentationKey=00000000-0000-0000-0000-000000000000"
    settings = Settings(applicationinsights_connection_string=conn)
    otel.setup_telemetry(settings)
    otel.setup_telemetry(settings)

    assert len(calls) == 1  # second call is a no-op


def test_shutdown_of_noop_provider_is_clean() -> None:
    otel.setup_telemetry(Settings())
    otel.shutdown_telemetry()
    assert otel._provider is None


def test_shutdown_flushes_azure_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    otel._azure_configured = True
    flushed: list[bool] = []

    class _Provider:
        def shutdown(self) -> None:
            flushed.append(True)

    monkeypatch.setattr(trace, "get_tracer_provider", lambda: _Provider())

    otel.shutdown_telemetry()

    assert flushed == [True]
    assert otel._azure_configured is False
