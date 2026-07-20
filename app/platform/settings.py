"""Application settings, loaded 12-factor style from the environment.

Every setting has a default that is safe for local development so the unit test
suite runs with no environment variables set (CLAUDE.md §6). Secrets never have
defaults beyond `None` and are supplied by Key Vault in deployed environments
(CLAUDE.md §1.3).
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "dev", "staging", "prod"]


class Settings(BaseSettings):
    """Runtime configuration for the API and the worker."""

    model_config = SettingsConfigDict(
        env_prefix="ENDLESS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Environment = "local"
    """Deployment environment. Drives logging format and telemetry wiring."""

    service_name: str = "endless-api"
    """Logical service name reported to telemetry and included in every log line."""

    version: str = "0.1.0"
    """Application version, stamped onto telemetry resources."""

    log_level: str = "INFO"
    """Root log level, e.g. DEBUG / INFO / WARNING."""

    database_url: str = "postgresql+asyncpg://endless:endless@localhost:5432/endless"
    """Async SQLAlchemy DSN. Defaults to the docker-compose Postgres; deployed
    environments inject the Key Vault value (CLAUDE.md §1.3)."""

    redis_url: str = "redis://localhost:6379/0"
    """Redis DSN for cache, idempotency keys, and the Arq queue. Defaults to the
    docker-compose Redis."""

    db_pool_size: int = 5
    """Baseline connections kept open per process by the async engine pool."""

    db_max_overflow: int = 10
    """Extra connections the pool may open transiently under load."""

    applicationinsights_connection_string: str | None = None
    """Azure Monitor / App Insights connection string. When unset (local), OTel
    stays a no-op and nothing is exported. Supplied by Key Vault in Azure."""

    outbox_max_attempts: int = 5
    """Delivery attempts before an outbox message is dead-lettered (architecture
    §8.3)."""

    outbox_batch_size: int = 100
    """Maximum outbox rows a single drain pass processes per registered table."""

    outbox_backoff_base_seconds: float = 5.0
    """Base delay for the outbox retry backoff; doubles each attempt, with jitter."""

    outbox_backoff_cap_seconds: float = 3600.0
    """Ceiling on the outbox retry backoff, before jitter."""

    @property
    def is_local(self) -> bool:
        """True when running against docker-compose rather than Azure."""
        return self.environment == "local"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton.

    Cached so that importing modules never re-parse the environment. Call
    `get_settings.cache_clear()` in tests that need to vary configuration.
    """
    return Settings()
