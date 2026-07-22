from __future__ import annotations

import csv
import io
import logging
from datetime import datetime
from typing import Any, Optional

from src.db.connection import get_session
from src.db.models import Dividend, Instrument, TradeLog
from src.trading.types import TaxLot, TaxReport

logger = logging.getLogger(__name__)

DIVIDEND_TAX_RATE: float = 0.13
CAPITAL_GAINS_TAX_RATE: float = 0.13
LONG_TERM_HOLDING_DAYS: int = 365 * 3
LONG_TERM_TAX_RATE: float = 0.0
TAX_FREE_THRESHOLD: float = 0.0
BROKER_COMMISSION_PCT: float = 0.0004


def compute_tax_lots(trades: list[dict[str, Any]]) -> list[TaxLot]:
    long_queue: list[dict[str, Any]] = []
    short_queue: list[dict[str, Any]] = []
    lots: list[TaxLot] = []
    for t in sorted(trades, key=lambda x: x.get("date", "")):
        ticker = t.get("ticker", "")
        direction = t.get("direction", "")
        qty = int(t.get("quantity", 0))
        price = float(t.get("price", 0))
        date_str = str(t.get("date", ""))
        commission = float(t.get("commission", 0))
        if direction == "BUY":
            long_queue.append(
                {
                    "ticker": ticker,
                    "quantity": qty,
                    "price": price,
                    "date": date_str,
                    "commission": commission,
                }
            )
        elif direction == "SHORT":
            short_queue.append(
                {
                    "ticker": ticker,
                    "quantity": qty,
                    "price": price,
                    "date": date_str,
                    "commission": commission,
                }
            )
        elif direction == "SELL":
            remaining = qty
            trade_commission = commission
            total_lot_qty_for_trade = qty
            while remaining > 0 and long_queue:
                lot = long_queue[0]
                used = min(remaining, lot["quantity"])
                buy_price = lot["price"]
                buy_date = lot["date"]
                lot["quantity"] -= used
                if lot["quantity"] <= 0:
                    long_queue.pop(0)
                lot_commission = trade_commission * (used / total_lot_qty_for_trade)
                pnl = (price - buy_price) * used - lot_commission
                holding_days = 0
                if buy_date and date_str:
                    try:
                        bd = datetime.fromisoformat(buy_date)
                        sd = datetime.fromisoformat(date_str)
                        holding_days = (sd - bd).days
                    except (ValueError, TypeError):
                        pass
                is_short_term = holding_days < LONG_TERM_HOLDING_DAYS
                tax_rate = LONG_TERM_TAX_RATE if not is_short_term else CAPITAL_GAINS_TAX_RATE
                tax_amount = max(0.0, pnl * tax_rate) if pnl > 0 else 0.0
                lot_rec = TaxLot(
                    id=f"{ticker}_{date_str}_{len(lots)}",
                    ticker=ticker,
                    quantity=used,
                    buy_price=buy_price,
                    buy_date=buy_date,
                    sell_price=price,
                    sell_date=date_str,
                    pnl=round(pnl, 2),
                    tax_rate=tax_rate,
                    tax_amount=round(tax_amount, 2),
                    holding_days=holding_days,
                    is_short_term=is_short_term,
                )
                lots.append(lot_rec)
                remaining -= used
        elif direction == "COVER":
            remaining = qty
            trade_commission = commission
            total_lot_qty_for_trade = qty
            while remaining > 0 and short_queue:
                lot = short_queue[0]
                used = min(remaining, lot["quantity"])
                short_price = lot["price"]
                short_date = lot["date"]
                lot["quantity"] -= used
                if lot["quantity"] <= 0:
                    short_queue.pop(0)
                lot_commission = trade_commission * (used / total_lot_qty_for_trade)
                pnl = (short_price - price) * used - lot_commission
                holding_days = 0
                if short_date and date_str:
                    try:
                        bd = datetime.fromisoformat(short_date)
                        sd = datetime.fromisoformat(date_str)
                        holding_days = (sd - bd).days
                    except (ValueError, TypeError):
                        pass
                is_short_term = holding_days < LONG_TERM_HOLDING_DAYS
                tax_rate = LONG_TERM_TAX_RATE if not is_short_term else CAPITAL_GAINS_TAX_RATE
                tax_amount = max(0.0, pnl * tax_rate) if pnl > 0 else 0.0
                lot_rec = TaxLot(
                    id=f"{ticker}_{date_str}_{len(lots)}",
                    ticker=ticker,
                    quantity=used,
                    buy_price=short_price,
                    buy_date=short_date,
                    sell_price=price,
                    sell_date=date_str,
                    pnl=round(pnl, 2),
                    tax_rate=tax_rate,
                    tax_amount=round(tax_amount, 2),
                    holding_days=holding_days,
                    is_short_term=is_short_term,
                )
                lots.append(lot_rec)
                remaining -= used
    return lots


def compute_dividend_tax(dividends: list[dict[str, Any]], tax_rate: float = DIVIDEND_TAX_RATE) -> list[dict[str, Any]]:
    result = []
    for d in dividends:
        gross = float(d.get("amount", 0))
        rate = float(d.get("tax_rate", tax_rate)) or tax_rate
        tax = gross * rate
        result.append(
            {
                "ticker": d.get("ticker", ""),
                "date": str(d.get("date", "")),
                "gross_amount": round(gross, 2),
                "tax_rate": rate,
                "tax_amount": round(tax, 2),
                "net_amount": round(gross - tax, 2),
            }
        )
    return result


def _apply_loss_harvesting(lots: list[TaxLot]) -> list[TaxLot]:
    """Offset winning lots with losing lots across the portfolio."""
    wins = sorted([l for l in lots if l.pnl > 0], key=lambda x: x.pnl, reverse=True)
    losses = sorted([l for l in lots if l.pnl <= 0], key=lambda x: x.pnl)
    if not wins or not losses:
        return lots
    total_loss = abs(sum(l.pnl for l in losses))
    for win in wins:
        if total_loss <= 0:
            break
        offset = min(win.pnl, total_loss)
        win.tax_amount = round(max(0.0, (win.pnl - offset) * win.tax_rate), 2)
        total_loss -= offset
    return lots


def generate_tax_report(
    year: int | None = None,
    trades: Optional[list[dict[str, Any]]] = None,
    dividends: Optional[list[dict[str, Any]]] = None,
    include_broker_report: bool = True,
) -> TaxReport:
    if year is None:
        year = datetime.now().year
    report = TaxReport(year=year)
    if trades:
        lots = compute_tax_lots(trades)
        lots = _apply_loss_harvesting(lots)
        report.lots = lots
        report.total_realized_pnl = round(sum(lot.pnl for lot in lots), 2)
        report.total_tax_due = round(sum(lot.tax_amount for lot in lots), 2)
    if dividends:
        div_results = compute_dividend_tax(dividends)
        report.dividends = div_results
        report.total_dividends = round(sum(d["gross_amount"] for d in div_results), 2)
        report.total_tax_due += round(sum(d["tax_amount"] for d in div_results), 2)
    if trades:
        report.broker_commission_total = round(sum(float(t.get("commission", 0)) for t in trades), 2)
    return report


def load_trades_from_db(
    year: int | None = None,
    ticker: Optional[str] = None,
) -> list[dict[str, Any]]:
    if year is None:
        year = datetime.now().year
    db = get_session()
    try:
        query = db.query(TradeLog)
        if year:
            from sqlalchemy import extract

            query = query.filter(extract("year", TradeLog.created_at) == year)
        if ticker:
            query = query.filter(TradeLog.ticker == ticker)
        trades = query.order_by(TradeLog.created_at).all()
        return [
            {
                "id": t.id,
                "ticker": t.ticker,
                "direction": t.direction,
                "quantity": t.quantity,
                "price": t.price,
                "commission": t.commission or 0,
                "pnl": t.pnl or 0,
                "date": t.created_at.isoformat(),
            }
            for t in trades
        ]
    finally:
        db.close()


def load_dividends_from_db(
    year: int | None = None,
    ticker: Optional[str] = None,
) -> list[dict[str, Any]]:
    if year is None:
        year = datetime.now().year
    db = get_session()
    try:
        query = db.query(Dividend).join(Instrument)
        if year:
            from sqlalchemy import extract

            query = query.filter(extract("year", Dividend.date) == year)
        if ticker:
            query = query.filter(Instrument.ticker == ticker)
        dividends = query.order_by(Dividend.date).all()
        return [
            {
                "ticker": d.instrument.ticker if d.instrument else "",
                "date": d.date.isoformat(),
                "amount": d.amount,
                "tax_rate": d.tax_rate or DIVIDEND_TAX_RATE,
            }
            for d in dividends
        ]
    finally:
        db.close()


def generate_broker_report_csv(report: TaxReport) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Фин advice Broker Tax Report", str(report.year)])
    writer.writerow([])
    writer.writerow(["Сделки (Tax Lots):"])
    writer.writerow(
        ["ID", "Тикер", "Кол-во", "Цена покупки", "Дата покупки", "Цена продажи", "Дата продажи", "P&L", "Ставка налога", "Налог", "Дней", "Тип"]
    )
    for lot in report.lots:
        writer.writerow(
            [
                lot.id,
                lot.ticker,
                lot.quantity,
                lot.buy_price,
                lot.buy_date,
                lot.sell_price,
                lot.sell_date,
                lot.pnl,
                lot.tax_rate,
                lot.tax_amount,
                lot.holding_days,
                "short" if lot.is_short_term else "long",
            ]
        )
    writer.writerow([])
    writer.writerow(["Дивиденды:"])
    writer.writerow(["Тикер", "Дата", "Сумма (гросс)", "Ставка налога", "Налог", "Сумма (нетто)"])
    for d in report.dividends:
        writer.writerow([d["ticker"], d["date"], d["gross_amount"], d["tax_rate"], d["tax_amount"], d["net_amount"]])
    writer.writerow([])
    writer.writerow(["Итого:"])
    writer.writerow(["Реализованный P&L", f"{report.total_realized_pnl:.2f} RUB"])
    writer.writerow(["Дивиденды (гросс)", f"{report.total_dividends:.2f} RUB"])
    writer.writerow(["Налог к уплате", f"{report.total_tax_due:.2f} RUB"])
    writer.writerow(["Комиссии брокера", f"{report.broker_commission_total:.2f} RUB"])
    return output.getvalue()


def generate_3ndfl_section(report: TaxReport) -> dict[str, Any]:
    taxable_income = report.total_realized_pnl + report.total_dividends
    return {
        "year": report.year,
        "доходы_от_ценных_бумаг": round(report.total_realized_pnl, 2),
        "доходы_от_дивидендов": round(report.total_dividends, 2),
        "налоговая_база": round(taxable_income, 2),
        "налог_к_уплате": round(report.total_tax_due, 2),
        "ставка_ндфл": CAPITAL_GAINS_TAX_RATE,
        "льготный_период_лет": LONG_TERM_HOLDING_DAYS // 365,
        "освобождено_от_налога": round(sum(lot.pnl for lot in report.lots if not lot.is_short_term), 2),
    }
