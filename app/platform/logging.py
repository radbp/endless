"""Structured logging setup.

One log line is one JSON object (CLAUDE.md §5.1). Every line carries `service`,
`environment`, and `event`; `trace_id` is added by the telemetry bootstrap once
OpenTelemetry is fully wired in F0.6.
"""

import logging
import sys

import structlog

from app.platform.settings import Settings


def configure_logging(settings: Settings) -> None:
    """Configure structlog and the stdlib root logger.

    Local runs get human-readable console output; every other environment emits
    JSON so Log Analytics can index it. Safe to call more than once.
    """
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=settings.log_level.upper(),
        force=True,
    )

    processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.is_local:
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[settings.log_level.upper()]
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    structlog.contextvars.bind_contextvars(
        service=settings.service_name,
        environment=settings.environment,
    )
