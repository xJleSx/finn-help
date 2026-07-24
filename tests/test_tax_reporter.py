"""Tests for tax reporting (RUB)"""

from __future__ import annotations

from src.trading.tax.reporter import (
    compute_dividend_tax,
    compute_tax_lots,
    generate_3ndfl_section,
    generate_broker_report_csv,
    generate_tax_report,
)


def test_compute_tax_lots_simple():
    trades = [
        {"ticker": "SBER", "direction": "BUY", "quantity": 10, "price": 250, "commission": 1.0, "date": "2026-01-15T10:00:00"},
        {"ticker": "SBER", "direction": "SELL", "quantity": 10, "price": 300, "commission": 1.5, "date": "2026-03-15T10:00:00"},
    ]
    lots = compute_tax_lots(trades)
    assert len(lots) == 1
    assert lots[0].ticker == "SBER"
    assert lots[0].pnl == (300 - 250) * 10 - 1.5
    assert lots[0].tax_amount > 0
    assert lots[0].is_short_term is True


def test_compute_tax_lots_partial_fill():
    trades = [
        {"ticker": "SBER", "direction": "BUY", "quantity": 10, "price": 250, "commission": 1.0, "date": "2026-01-15T10:00:00"},
        {"ticker": "SBER", "direction": "SELL", "quantity": 5, "price": 300, "commission": 0.5, "date": "2026-03-15T10:00:00"},
    ]
    lots = compute_tax_lots(trades)
    assert len(lots) == 1
    assert lots[0].quantity == 5
    assert lots[0].pnl == (300 - 250) * 5 - 0.5


def test_compute_tax_lots_multiple_buys():
    trades = [
        {"ticker": "SBER", "direction": "BUY", "quantity": 10, "price": 240, "commission": 1.0, "date": "2026-01-10T10:00:00"},
        {"ticker": "SBER", "direction": "BUY", "quantity": 10, "price": 260, "commission": 1.0, "date": "2026-02-10T10:00:00"},
        {"ticker": "SBER", "direction": "SELL", "quantity": 15, "price": 300, "commission": 2.0, "date": "2026-03-15T10:00:00"},
    ]
    lots = compute_tax_lots(trades)
    assert len(lots) == 2
    assert lots[0].buy_price == 240
    assert lots[1].buy_price == 260
    total_pnl = sum(lot.pnl for lot in lots)
    expected = (300 - 240) * 10 + (300 - 260) * 5 - 2.0
    assert abs(total_pnl - expected) < 0.01


def test_compute_tax_lots_loss():
    trades = [
        {"ticker": "GAZP", "direction": "BUY", "quantity": 10, "price": 200, "commission": 1.0, "date": "2026-01-15T10:00:00"},
        {"ticker": "GAZP", "direction": "SELL", "quantity": 10, "price": 180, "commission": 1.0, "date": "2026-03-15T10:00:00"},
    ]
    lots = compute_tax_lots(trades)
    assert len(lots) == 1
    assert lots[0].pnl < 0
    assert lots[0].tax_amount == 0


def test_compute_dividend_tax():
    dividends = [
        {"ticker": "SBER", "date": "2026-05-01", "amount": 1000, "tax_rate": 0.13},
    ]
    result = compute_dividend_tax(dividends)
    assert len(result) == 1
    assert result[0]["gross_amount"] == 1000
    assert result[0]["tax_amount"] == 130
    assert result[0]["net_amount"] == 870


def test_generate_tax_report():
    trades = [
        {"ticker": "SBER", "direction": "BUY", "quantity": 10, "price": 250, "commission": 1.0, "date": "2026-01-15T10:00:00"},
        {"ticker": "SBER", "direction": "SELL", "quantity": 10, "price": 300, "commission": 1.0, "date": "2026-03-15T10:00:00"},
    ]
    dividends = [
        {"ticker": "SBER", "date": "2026-05-01", "amount": 500, "tax_rate": 0.13},
    ]
    report = generate_tax_report(year=2026, trades=trades, dividends=dividends)
    assert report.year == 2026
    assert report.total_realized_pnl > 0
    assert report.total_dividends == 500
    assert report.total_tax_due > 0
    assert len(report.lots) == 1
    assert len(report.dividends) == 1


def test_generate_broker_report_csv():
    trades = [
        {"ticker": "SBER", "direction": "BUY", "quantity": 10, "price": 250, "commission": 1.0, "date": "2026-01-15T10:00:00"},
        {"ticker": "SBER", "direction": "SELL", "quantity": 10, "price": 300, "commission": 1.0, "date": "2026-03-15T10:00:00"},
    ]
    report = generate_tax_report(year=2026, trades=trades)
    csv = generate_broker_report_csv(report)
    assert "Фин advice Broker Tax Report" in csv
    assert "SBER" in csv
    assert "Итого:" in csv


def test_generate_3ndfl_section():
    trades = [
        {"ticker": "SBER", "direction": "BUY", "quantity": 10, "price": 250, "commission": 1.0, "date": "2026-01-15T10:00:00"},
        {"ticker": "SBER", "direction": "SELL", "quantity": 10, "price": 300, "commission": 1.0, "date": "2026-03-15T10:00:00"},
    ]
    report = generate_tax_report(year=2026, trades=trades)
    ndfl = generate_3ndfl_section(report)
    assert ndfl["year"] == 2026
    assert ndfl["доходы_от_ценных_бумаг"] > 0
    assert ndfl["ставка_ндфл"] == 0.13


def test_tax_report_no_trades():
    report = generate_tax_report(year=2026)
    assert report.total_realized_pnl == 0.0
    assert report.lots == []
    assert report.total_tax_due == 0.0
