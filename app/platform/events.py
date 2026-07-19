"""In-process event bus for cross-module facts.

Modules broadcast domain facts (``ProductCreatedV1``, ``OrderPaidV1``) and other
modules react — all inside the same process, no broker (architecture §8.2). This
is the synchronous publish/subscribe half of internal communication; direct
``service.py`` calls are the command half.

Design decisions:

* **Exact-type dispatch.** A handler subscribed to ``ProductCreatedV1`` receives
  exactly that type, never a subclass. Events are versioned by class name, so
  exact matching is what modules expect.
* **Fail loud, in the caller's transaction.** ``publish`` awaits each handler in
  registration order and does **not** swallow exceptions (CLAUDE.md §1.8). A
  publish happens inside the publisher's request transaction, so a failing
  subscriber rolls the whole thing back rather than leaving state diverged. A
  subscriber that must survive a crash (email) enqueues durable work via the
  outbox instead of relying on this bus (architecture §8.3).

Events themselves are plain Pydantic models defined in each module's
``events.py``; this bus is agnostic to their shape.
"""

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import structlog

logger = structlog.get_logger(__name__)

E = TypeVar("E")

Handler = Callable[[E], Awaitable[None]]
"""An async subscriber for events of type ``E``."""


class EventBus:
    """A synchronous, in-process typed publish/subscribe bus.

    One instance lives per process, created in the app lifespan and injected
    where needed. Not safe to share across processes — it is deliberately local
    (the worker has its own; durable cross-process handoff is the outbox).
    """

    def __init__(self) -> None:
        """Create an empty bus with no subscriptions."""
        # Type-erased at storage; ``subscribe`` enforces the (type, handler) pair.
        self._handlers: dict[type[Any], list[Callable[[Any], Awaitable[None]]]] = {}

    def subscribe(self, event_type: type[E], handler: Handler[E]) -> None:
        """Register ``handler`` to receive every event of exactly ``event_type``.

        Handlers fire in the order they were subscribed. Registering the same
        handler twice will invoke it twice — subscription is not deduplicated.
        """
        self._handlers.setdefault(event_type, []).append(handler)

    async def publish(self, event: object) -> None:
        """Deliver ``event`` to every handler subscribed to its exact type.

        Awaits handlers sequentially in registration order. If a handler raises,
        the exception propagates to the caller and remaining handlers do not run
        (CLAUDE.md §1.8 — no swallowing). Publishing an event with no subscribers
        is a no-op.
        """
        handlers = self._handlers.get(type(event), [])
        if not handlers:
            return
        for handler in handlers:
            await handler(event)

    def subscriber_count(self, event_type: type[Any]) -> int:
        """Return how many handlers are registered for ``event_type`` (for tests)."""
        return len(self._handlers.get(event_type, []))
