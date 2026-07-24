from __future__ import annotations

import pytest

from src.core.event_bus import DomainEvent, EventBus, get_event_bus


@pytest.fixture
def bus():
    return EventBus()


def test_domain_event_defaults():
    e = DomainEvent(event_type="test")
    assert e.event_type == "test"
    assert e.data == {}
    assert e.source == ""


def test_domain_event_with_data():
    e = DomainEvent(event_type="order_placed", data={"ticker": "SBER"}, source="engine")
    assert e.event_type == "order_placed"
    assert e.data["ticker"] == "SBER"
    assert e.source == "engine"


@pytest.mark.asyncio
async def test_subscribe_and_publish(bus):
    received = []

    async def handler(event: DomainEvent) -> None:
        received.append(event)

    bus.subscribe("test_event", handler)
    event = DomainEvent(event_type="test_event", data={"key": "val"})
    await bus.publish(event)
    assert len(received) == 1
    assert received[0].data["key"] == "val"


@pytest.mark.asyncio
async def test_subscribe_all(bus):
    received = []

    async def wildcard(event: DomainEvent) -> None:
        received.append(event.event_type)

    bus.subscribe_all(wildcard)
    await bus.publish(DomainEvent(event_type="a"))
    await bus.publish(DomainEvent(event_type="b"))
    assert received == ["a", "b"]


@pytest.mark.asyncio
async def test_unsubscribe(bus):
    received = []

    async def handler(event: DomainEvent) -> None:
        received.append(event)

    bus.subscribe("x", handler)
    bus.unsubscribe("x", handler)
    await bus.publish(DomainEvent(event_type="x"))
    assert len(received) == 0


@pytest.mark.asyncio
async def test_unsubscribe_unknown_type(bus):
    bus.unsubscribe("nonexistent", lambda e: None)
    assert True  # should not raise


@pytest.mark.asyncio
async def test_publish_sync(bus):
    received = []

    async def handler(event: DomainEvent) -> None:
        received.append(event)

    bus.subscribe("sync_test", handler)
    await bus.publish_async("sync_test", {"msg": "hello"})
    assert len(received) == 1
    assert received[0].event_type == "sync_test"
    assert received[0].data["msg"] == "hello"


@pytest.mark.asyncio
async def test_publish_no_handlers(bus):
    await bus.publish(DomainEvent(event_type="orphan"))
    assert True  # should not raise


@pytest.mark.asyncio
async def test_publish_sync_default_data(bus):
    received = []

    async def handler(event: DomainEvent) -> None:
        received.append(event)

    bus.subscribe("no_data", handler)
    await bus.publish_async("no_data")
    assert received[0].data == {}


def test_get_event_bus_singleton():
    b1 = get_event_bus()
    b2 = get_event_bus()
    assert b1 is b2
