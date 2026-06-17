import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from src.analysis.correlation_analysis import correlation_table
from src.analysis.whatif import whatif_scenario
from src.brokers.market_data import update_all_favorites
from src.config import personal, settings
from src.db.connection import get_session
from src.db.models import Order as OrderModel
from src.db.models import UserSetting
from src.execution.engine import OrderRecord, execute_order, get_log, set_mode
from src.execution.stoploss import position_tracker
from src.risk.guards import (
    activate_kill_switch,
    check_daily_loss,
    check_var_limit,
    deactivate_kill_switch,
    get_day_pnl,
    is_kill_switch_active,
    start_day,
    update_day_value,
    update_drawdown,
    _load_risk_params,
)

logger = logging.getLogger(__name__)

_running = False
_max_trades_per_day = 5
_trades_today = 0
_last_reset_day: Optional[str] = None

_KEY_TRADES = "loop_trades_today"
_KEY_RESET_DAY = "loop_reset_day"


def _load_daily_counters():
    global _trades_today, _last_reset_day
    db = get_session()
    try:
        row = db.query(UserSetting).filter(UserSetting.key == _KEY_TRADES).first()
        if row:
            _trades_today = int(row.value)
        row2 = db.query(UserSetting).filter(UserSetting.key == _KEY_RESET_DAY).first()
        if row2:
            _last_reset_day = row2.value
    finally:
        db.close()


def _save_daily_counters():
    db = get_session()
    try:
        existing = db.query(UserSetting).filter(UserSetting.key == _KEY_TRADES).first()
        if existing:
            existing.value = str(_trades_today)
        else:
            db.add(UserSetting(key=_KEY_TRADES, value=str(_trades_today)))
        existing2 = db.query(UserSetting).filter(UserSetting.key == _KEY_RESET_DAY).first()
        if existing2:
            existing2.value = str(_last_reset_day or "")
        else:
            db.add(UserSetting(key=_KEY_RESET_DAY, value=str(_last_reset_day or "")))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def set_max_trades_per_day(n: int):
    global _max_trades_per_day
    _max_trades_per_day = n
    logger.info("Max trades per day set to %d", n)


def reset_daily_counters():
    global _trades_today, _last_reset_day
    _trades_today = 0
    _last_reset_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _save_daily_counters()
    logger.info("Daily trade counter reset")


def can_trade() -> tuple[bool, str]:
    if is_kill_switch_active():
        return False, "Kill switch active"

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _last_reset_day is None:
        _load_daily_counters()
    if _last_reset_day is None or _last_reset_day != today:
        reset_daily_counters()

    if _trades_today >= _max_trades_per_day:
        return False, f"Max trades per day reached ({_max_trades_per_day})"

    return True, "ok"


async def market_hours_check() -> bool:
    now = datetime.now(timezone.utc)
    # MOEX main session: 06:50-15:50 UTC (09:50-18:50 MSK)
    # Evening session: 16:00-18:00 UTC
    hour = now.hour
    minute = now.minute
    time_decimal = hour + minute / 60

    # main session
    if 6.83 <= time_decimal <= 15.83:
        return True
    # evening session
    if 16.0 <= time_decimal <= 18.0:
        return True

    logger.debug("Outside market hours (UTC %.2f)", time_decimal)
    return False


async def _check_var():
    db = get_session()
    try:
        from src.db.models import Portfolio, Price

        positions = db.query(Portfolio).all()
        all_returns = []
        for p in positions:
            prices = (
                db.query(Price.close)
                .filter_by(instrument_id=p.instrument_id)
                .order_by(Price.date.desc())
                .limit(60)
                .all()
            )
            vals = [r[0] for r in prices if r[0] is not None]
            if len(vals) < 20:
                continue
            rets = [(vals[i] - vals[i + 1]) / vals[i + 1] for i in range(len(vals) - 1)]
            all_returns.extend(rets)
        if len(all_returns) < 20:
            return True, "ok"
        import numpy as np
        var_95 = float(abs(np.percentile(all_returns, 5)))
        return check_var_limit(var_95)
    finally:
        db.close()


async def _process_signals():
    from src.db.models import Signal as SignalModel

    db = get_session()
    try:
        today = datetime.now(timezone.utc).date()
        signals = (
            db.query(SignalModel)
            .filter(SignalModel.date >= today)
            .order_by(SignalModel.confidence.desc())
            .all()
        )

        for s in signals:
            if not await market_hours_check():
                logger.info("Market closed, skipping signal processing")
                return

            can, reason = can_trade()
            if not can:
                logger.warning("Cannot trade: %s", reason)
                return

            var_ok, var_msg = await _check_var()
            if not var_ok:
                logger.warning("VaR limit exceeded: %s", var_msg)
                return

            if s.action in ("BUY", "CAUTIOUS_BUY"):
                result = await execute_order(
                    ticker=s.ticker,
                    direction="BUY",
                    quantity=10,
                    price=s.price if hasattr(s, "price") and s.price else None,
                    reason=f"Signal: {s.action} ({s.confidence:.0%})",
                )
            elif s.action == "SELL":
                result = await execute_order(
                    ticker=s.ticker,
                    direction="SELL",
                    quantity=10,
                    reason=f"Signal: {s.action} ({s.confidence:.0%})",
                )
            else:
                continue

            global _trades_today
            if result.status in ("filled", "simulated", "submitted"):
                _trades_today += 1
                _save_daily_counters()
    finally:
        db.close()


async def _check_stop_losses():
    db = get_session()
    try:
        from src.db.models import Instrument, Price

        open_orders = db.query(OrderModel).filter(OrderModel.status.in_(["filled", "partial"])).all()
        for order in open_orders:
            inst = db.query(Instrument).filter_by(ticker=order.ticker).first()
            if not inst:
                continue
            price = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date.desc()).first()
            if not price or not price.close:
                continue

            await position_tracker.execute_triggers(order.ticker, price.close)
    finally:
        db.close()


async def _check_daily_pnl():
    db = get_session()
    try:
        from src.db.models import Portfolio as PortModel, Price

        total = db.query(PortModel).all()
        current_value = 0.0
        for p in total:
            if not p.instrument_id:
                continue
            latest_price = (
                db.query(Price.close)
                .filter_by(instrument_id=p.instrument_id)
                .order_by(Price.date.desc())
                .first()
            )
            price = latest_price[0] if latest_price else (p.avg_price or 0)
            current_value += (p.quantity or 0) * price
        update_day_value(current_value)
        update_drawdown(current_value)
        pnl, pnl_pct = get_day_pnl()
        check_daily_loss(pnl_pct)
    finally:
        db.close()


async def run_execution_loop(interval: int = 300):
    global _running
    if _running:
        logger.warning("Execution loop already running")
        return
    _running = True

    logger.info("Execution loop started (interval=%ds)", interval)

    try:
        from src.db.connection import init_db
        init_db()
    except Exception:
        pass

    _load_daily_counters()
    _load_risk_params()
    start_day(1_000_000)

    while _running:
        try:
            if await market_hours_check():
                await _check_daily_pnl()

                if not is_kill_switch_active():
                    await _process_signals()
                    await _check_stop_losses()
        except Exception as e:
            logger.error("Execution loop error: %s", e, exc_info=True)

        await asyncio.sleep(interval)


def stop():
    global _running
    _running = False
    logger.info("Execution loop stopping")
