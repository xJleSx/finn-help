from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

from src.core.ddd.base import AggregateRoot, Entity, Repository, ValueObject
from src.core.event_bus import DomainEvent


class Ticker(ValueObject):
    def __init__(self, symbol: str, exchange: str = "MOEX") -> None:
        self.symbol = symbol.upper()
        self.exchange = exchange

    def __str__(self) -> str:
        return f"{self.symbol}"

    def __repr__(self) -> str:
        return f"Ticker({self.symbol}, {self.exchange})"


class Price(ValueObject):
    def __init__(self, amount: Decimal, currency: str = "RUB") -> None:
        self.amount = amount
        self.currency = currency

    def __repr__(self) -> str:
        return f"Price({self.amount} {self.currency})"


@dataclass
class Sector(ValueObject):
    name: str
    code: str


class Instrument(AggregateRoot[str]):
    def __init__(
        self,
        ticker: Ticker,
        name: str,
        instrument_type: str,
        sector: Optional[Sector] = None,
        lot_size: int = 1,
        face_value: Optional[Decimal] = None,
    ) -> None:
        super().__init__(id=ticker.symbol)
        self.ticker = ticker
        self.name = name
        self.instrument_type = instrument_type
        self.sector = sector
        self.lot_size = lot_size
        self.face_value = face_value


class Portfolio(AggregateRoot[str]):
    def __init__(self, user_id: str, name: str = "main") -> None:
        super().__init__(id=f"{user_id}:{name}")
        self.user_id = user_id
        self.name = name
        self._positions: dict[str, Position] = {}

    @property
    def positions(self) -> dict[str, Position]:
        return dict(self._positions)

    def add_position(self, position: Position) -> None:
        self._positions[position.instrument_id] = position
        self.add_domain_event(TradeEvent(
            event_type="position.opened",
            data={"instrument_id": position.instrument_id, "quantity": position.quantity},
        ))

    def remove_position(self, instrument_id: str) -> None:
        self._positions.pop(instrument_id, None)
        self.add_domain_event(TradeEvent(
            event_type="position.closed",
            data={"instrument_id": instrument_id},
        ))


@dataclass
class Position(Entity[str]):
    instrument_id: str
    quantity: int
    avg_price: Decimal
    current_price: Optional[Decimal] = None


class TradeEvent(DomainEvent):
    pass


class InstrumentRepository(Repository[Instrument]):
    def add(self, aggregate: Instrument) -> None:
        from src.db.connection import get_session
        from src.db.models import Instrument as InstrumentModel
        db = get_session()
        try:
            model = db.query(InstrumentModel).filter(InstrumentModel.ticker == aggregate.id).first()
            if model:
                model.name = aggregate.name
                model.type = aggregate.instrument_type
                model.lot_size = aggregate.lot_size
            else:
                model = InstrumentModel(
                    ticker=aggregate.id,
                    name=aggregate.name,
                    type=aggregate.instrument_type,
                    lot_size=aggregate.lot_size,
                )
                db.add(model)
            db.commit()
        finally:
            db.close()

    def get(self, id: str) -> Optional[Instrument]:
        from src.db.connection import get_session
        from src.db.models import Instrument as InstrumentModel
        db = get_session()
        try:
            model = db.query(InstrumentModel).filter(InstrumentModel.ticker == id).first()
            if not model:
                return None
            return Instrument(
                ticker=Ticker(model.ticker),
                name=model.name or "",
                instrument_type=model.type or "stock",
                lot_size=model.lot_size or 1,
            )
        finally:
            db.close()

    def remove(self, aggregate: Instrument) -> None:
        from src.db.connection import get_session
        from src.db.models import Instrument as InstrumentModel
        db = get_session()
        try:
            model = db.query(InstrumentModel).filter(InstrumentModel.ticker == aggregate.id).first()
            if model:
                db.delete(model)
                db.commit()
        finally:
            db.close()

    def list(self, **filters: Any) -> list[Instrument]:
        from src.db.connection import get_session
        from src.db.models import Instrument as InstrumentModel
        db = get_session()
        try:
            query = db.query(InstrumentModel)
            for key, value in filters.items():
                if hasattr(InstrumentModel, key):
                    query = query.filter(getattr(InstrumentModel, key) == value)
            return [
                Instrument(
                    ticker=Ticker(m.ticker),
                    name=m.name or "",
                    instrument_type=m.type or "stock",
                    lot_size=m.lot_size or 1,
                )
                for m in query.all()
            ]
        finally:
            db.close()
