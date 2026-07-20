from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger(__name__)

Handler = Callable[..., Coroutine[Any, Any, None]]


@dataclass
class DomainEvent:
    event_type: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = ""


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = {}
        self._wildcard_handlers: list[Handler] = []

    def subscribe(self, event_type: str, handler: Handler) -> None:
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
        logger.debug("Subscribed handler %s to %s", handler.__name__, event_type)

    def subscribe_all(self, handler: Handler) -> None:
        self._wildcard_handlers.append(handler)

    def unsubscribe(self, event_type: str, handler: Handler) -> None:
        if event_type in self._handlers:
            self._handlers[event_type] = [h for h in self._handlers[event_type] if h is not handler]

    async def publish(self, event: DomainEvent) -> None:
        logger.debug("Publishing event: %s", event.event_type)
        tasks = []
        for handler in self._handlers.get(event.event_type, []):
            tasks.append(handler(event))
        for handler in self._wildcard_handlers:
            tasks.append(handler(event))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def publish_sync(self, event_type: str, data: Optional[dict[str, Any]] = None) -> None:
        await self.publish(DomainEvent(event_type=event_type, data=data or {}))


_event_bus: EventBus = EventBus()


def get_event_bus() -> EventBus:
    return _event_bus
