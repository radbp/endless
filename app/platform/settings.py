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
