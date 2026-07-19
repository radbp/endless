"""Unit tests for the in-process event bus (architecture §8.2)."""

from dataclasses import dataclass

import pytest

from app.platform.events import EventBus


@dataclass
class ProductCreatedV1:
    product_id: str


@dataclass
class ProductArchivedV1:
    product_id: str


async def test_publish_invokes_subscribed_handler() -> None:
    bus = EventBus()
    seen: list[str] = []

    async def handler(event: ProductCreatedV1) -> None:
        seen.append(event.product_id)

    bus.subscribe(ProductCreatedV1, handler)
    await bus.publish(ProductCreatedV1(product_id="prd_1"))

    assert seen == ["prd_1"]


async def test_dispatch_is_by_exact_type() -> None:
    bus = EventBus()
    seen: list[str] = []

    async def handler(event: ProductCreatedV1) -> None:
        seen.append(event.product_id)

    bus.subscribe(ProductCreatedV1, handler)
    # A different event type must not reach this handler.
    await bus.publish(ProductArchivedV1(product_id="prd_1"))

    assert seen == []


async def test_handlers_fire_in_registration_order() -> None:
    bus = EventBus()
    order: list[int] = []

    async def first(_: ProductCreatedV1) -> None:
        order.append(1)

    async def second(_: ProductCreatedV1) -> None:
        order.append(2)

    bus.subscribe(ProductCreatedV1, first)
    bus.subscribe(ProductCreatedV1, second)
    await bus.publish(ProductCreatedV1(product_id="prd_1"))

    assert order == [1, 2]


async def test_publish_with_no_subscribers_is_a_noop() -> None:
    bus = EventBus()
    await bus.publish(ProductCreatedV1(product_id="prd_1"))  # must not raise


async def test_handler_exception_propagates_and_halts_remaining() -> None:
    bus = EventBus()
    reached_second = False

    async def boom(_: ProductCreatedV1) -> None:
        raise RuntimeError("projection failed")

    async def second(_: ProductCreatedV1) -> None:
        nonlocal reached_second
        reached_second = True

    bus.subscribe(ProductCreatedV1, boom)
    bus.subscribe(ProductCreatedV1, second)

    with pytest.raises(RuntimeError, match="projection failed"):
        await bus.publish(ProductCreatedV1(product_id="prd_1"))
    assert reached_second is False


def test_subscriber_count() -> None:
    bus = EventBus()

    async def handler(_: ProductCreatedV1) -> None: ...

    assert bus.subscriber_count(ProductCreatedV1) == 0
    bus.subscribe(ProductCreatedV1, handler)
    bus.subscribe(ProductCreatedV1, handler)
    assert bus.subscriber_count(ProductCreatedV1) == 2
