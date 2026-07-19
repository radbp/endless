"""Async Redis access: one connection pool per process.

Redis backs the cart store, idempotency keys, rate-limit counters, and the Arq
job queue (architecture §6). Like the database, the client is created in the app
lifespan and injected via ``app.state`` — never imported at module load
(CLAUDE.md §1.10).

Clients are created with ``decode_responses=False``: callers that store text
encode/decode explicitly, and binary payloads (Arq job blobs) pass through
untouched.
"""

from redis.asyncio import Redis
from redis.asyncio.connection import ConnectionPool

from app.platform.settings import Settings


class RedisClient:
    """Owns the Redis connection pool for the process.

    Construct once with :meth:`create`, close once with :meth:`aclose`. Hand the
    wrapped :attr:`client` to anything that needs Redis.
    """

    def __init__(self, client: Redis) -> None:
        """Wrap an existing async ``Redis``. Prefer :meth:`create`."""
        self._client = client

    @classmethod
    def create(cls, settings: Settings) -> "RedisClient":
        """Build a :class:`RedisClient` with a pool from ``settings.redis_url``."""
        pool = ConnectionPool.from_url(settings.redis_url, decode_responses=False)
        return cls(Redis(connection_pool=pool))

    @property
    def client(self) -> Redis:
        """The underlying async Redis client."""
        return self._client

    async def ping(self) -> bool:
        """Return ``True`` if the server answers ``PING`` — for readiness."""
        result = await self._client.ping()
        return bool(result)

    async def aclose(self) -> None:
        """Close the client and its connection pool. Call once at shutdown."""
        await self._client.aclose()
