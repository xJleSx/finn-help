"""Tests for Phase 10 trading types"""

from __future__ import annotations

from src.trading.types import (
    Direction,
    Fill,
    LeverageInfo,
    MarginRequirements,
    OrderStatus,
    OrderType,
    TaxLot,
    TaxReport,
    TimeInForce,
)


def test_order_type_values():
    assert OrderType.MARKET.value == "market"
    assert OrderType.LIMIT.value == "limit"
    assert OrderType.IOC.value == "ioc"
    assert OrderType.FOK.value == "fok"


def test_time_in_force_values():
    assert TimeInForce.DAY.value == "day"
    assert TimeInForce.IOC.value == "ioc"
    assert TimeInForce.FOK.value == "fok"
    assert TimeInForce.GTC.value == "gtc"


def test_direction_values():
    assert Direction.BUY.value == "BUY"
    assert Direction.SELL.value == "SELL"
    assert Direction.SHORT.value == "SHORT"
    assert Direction.COVER.value == "COVER"


def test_order_status_values():
    assert OrderStatus.PENDING.value == "pending"
    assert OrderStatus.PARTIAL.value == "partial"
    assert OrderStatus.FILLED.value == "filled"
    assert OrderStatus.EXPIRED.value == "expired"


def test_fill_dataclass():
    f = Fill(quantity=10, price=250.5, commission=1.5)
    assert f.quantity == 10
    assert f.price == 250.5
    assert f.commission == 1.5
    assert f.filled_at is not None


def test_margin_requirements_defaults():
    mr = MarginRequirements()
    assert mr.initial_margin == 0.0
    assert mr.leverage == 1.0
    assert mr.margin_status == "safe"


def test_tax_lot_dataclass():
    lot = TaxLot(
        id="test_1",
        ticker="SBER",
        quantity=10,
        buy_price=250,
        sell_price=280,
        pnl=300,
        tax_rate=0.13,
        tax_amount=39,
        holding_days=100,
        is_short_term=True,
    )
    assert lot.pnl == 300
    assert lot.tax_amount == 39
    assert lot.is_short_term is True


def test_tax_report_defaults():
    r = TaxReport(year=2026)
    assert r.year == 2026
    assert r.total_realized_pnl == 0.0
    assert r.lots == []
    assert r.dividends == []


def test_leverage_info_defaults():
    info = LeverageInfo()
    assert info.leverage_ratio == 1.0
    assert info.margin_status == "safe"
    assert info.free_margin == 0.0
