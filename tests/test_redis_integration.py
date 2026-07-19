"""Integration tests for the async Redis wrapper.

Runs against a real Redis via testcontainers (CLAUDE.md §6). Deselected from the
unit suite by the ``integration`` marker.
"""

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio

from app.platform.redis import RedisClient
from app.platform.settings import Settings

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def redis_url() -> Iterator[str]:
    """Start a throwaway Redis and yield its DSN."""
    from testcontainers.redis import RedisContainer

    with RedisContainer("redis:7-alpine") as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(6379)
        yield f"redis://{host}:{port}/0"


@pytest_asyncio.fixture
async def redis_client(redis_url: str) -> AsyncIterator[RedisClient]:
    """A `RedisClient` bound to the test Redis."""
    client = RedisClient.create(Settings(redis_url=redis_url))
    yield client
    await client.aclose()


async def test_ping_succeeds_against_real_redis(redis_client: RedisClient) -> None:
    assert await redis_client.ping() is True


async def test_set_and_get_roundtrip(redis_client: RedisClient) -> None:
    await redis_client.client.set("probe:key", b"value")
    assert await redis_client.client.get("probe:key") == b"value"
