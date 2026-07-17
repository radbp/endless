"""OpenTelemetry bootstrap — stub.

F0.1 establishes the call sites and a tracer provider with no exporter, so the
app boots and traces are created but go nowhere. F0.6 replaces the no-op
exporter with the Azure Monitor / OTLP exporter and adds auto-instrumentation
for FastAPI, SQLAlchemy, redis, and httpx (architecture §11).
"""

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider

from app.platform.settings import Settings

_provider: TracerProvider | None = None


def setup_telemetry(settings: Settings) -> None:
    """Install a tracer provider for the process.

    No span processor is attached yet, so spans are created and dropped. This
    keeps instrumentation call sites honest without shipping data anywhere.
    """
    global _provider

    if _provider is not None:
        return

    resource = Resource.create(
        {
            SERVICE_NAME: settings.service_name,
            SERVICE_VERSION: settings.version,
            "deployment.environment": settings.environment,
        }
    )
    _provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(_provider)

    # TODO(F0.6): attach BatchSpanProcessor + Azure Monitor exporter, and call
    # the FastAPI/SQLAlchemy/redis/httpx auto-instrumentors here.


def shutdown_telemetry() -> None:
    """Flush and tear down the tracer provider during app shutdown."""
    global _provider

    if _provider is not None:
        _provider.shutdown()
        _provider = None
