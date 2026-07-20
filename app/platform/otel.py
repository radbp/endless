"""OpenTelemetry bootstrap.

Exports traces, metrics, and logs to Azure Monitor / Application Insights **when a
connection string is configured**, and stays a no-op otherwise — so local and CI
runs need no secret and ship no telemetry (CLAUDE.md §1.3). Auto-instrumentation
of FastAPI, SQLAlchemy, redis, and httpx is layered on in F0.7; this ticket wires
the exporter and a graceful shutdown that flushes buffered spans.
"""

import structlog
from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider

from app.platform.settings import Settings

logger = structlog.get_logger(__name__)

_provider: TracerProvider | None = None
_azure_configured = False


def _resource(settings: Settings) -> Resource:
    """Describe this service for every emitted span/metric/log."""
    return Resource.create(
        {
            SERVICE_NAME: settings.service_name,
            SERVICE_VERSION: settings.version,
            "deployment.environment": settings.environment,
        }
    )


def setup_telemetry(settings: Settings) -> None:
    """Install telemetry for the process.

    With a connection string, hand off to ``configure_azure_monitor``, which sets
    the global tracer/meter/logger providers and their Azure Monitor exporters.
    Without one, install a bare :class:`TracerProvider` with no span processor, so
    instrumentation call sites still work but produce nothing.
    """
    global _provider, _azure_configured

    if _provider is not None or _azure_configured:
        return

    resource = _resource(settings)

    if settings.applicationinsights_connection_string:
        configure_azure_monitor(
            connection_string=settings.applicationinsights_connection_string,
            resource=resource,
        )
        _azure_configured = True
        logger.info("otel.configured", exporter="azure_monitor")
        return

    _provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(_provider)
    logger.info("otel.configured", exporter="none")


def shutdown_telemetry() -> None:
    """Flush and tear down telemetry during app shutdown.

    Shutting the tracer provider down flushes any batched spans before the
    process exits, so the last requests are not lost.
    """
    global _provider, _azure_configured

    if _azure_configured:
        provider = trace.get_tracer_provider()
        shutdown = getattr(provider, "shutdown", None)
        if callable(shutdown):
            shutdown()
        _azure_configured = False
        return

    if _provider is not None:
        _provider.shutdown()
        _provider = None
