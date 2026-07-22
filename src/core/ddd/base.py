from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Generic, Optional, TypeVar

from src.core.event_bus import DomainEvent, get_event_bus

TId = TypeVar("TId")
TAggregate = TypeVar("TAggregate")


class ValueObject(abc.ABC):
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self.__dict__ == other.__dict__

    def __hash__(self) -> int:
        return hash(tuple(sorted(self.__dict__.items())))


@dataclass
class Entity(Generic[TId]):
    id: TId

    def __hash__(self) -> int:
        return hash((type(self).__name__, self.id))
    _domain_events: list[DomainEvent] = field(default_factory=list, repr=False)

    def add_domain_event(self, event: DomainEvent) -> None:
        self._domain_events.append(event)

    def pop_events(self) -> list[DomainEvent]:
        events = list(self._domain_events)
        self._domain_events.clear()
        return events


class AggregateRoot(Entity[TId], abc.ABC):
    async def publish_events(self) -> None:
        bus = get_event_bus()
        for event in self.pop_events():
            await bus.publish_sync(event.event_type, event.data)


class Repository(Generic[TAggregate], abc.ABC):
    @abc.abstractmethod
    def add(self, aggregate: TAggregate) -> None: ...

    @abc.abstractmethod
    def get(self, id: Any) -> Optional[TAggregate]: ...

    @abc.abstractmethod
    def remove(self, aggregate: TAggregate) -> None: ...

    @abc.abstractmethod
    def list(self, **filters: Any) -> list[TAggregate]: ...


class UnitOfWork(abc.ABC):
    def __init__(self) -> None:
        if type(self) is UnitOfWork:
            raise TypeError("UnitOfWork must be subclassed; do not instantiate the base class directly")

    def __enter__(self) -> UnitOfWork:
        return self

    def __exit__(self, *args: Any) -> None:
        if args[0] is None:
            self.commit()
        else:
            self.rollback()

    @abc.abstractmethod
    def commit(self) -> None: ...

    @abc.abstractmethod
    def rollback(self) -> None: ...
