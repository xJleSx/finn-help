import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from src.config import settings
from src.db.connection import get_session
from src.db.models import Order as OrderModel
from src.db.models import UserSetting
from src.trading.execution.engine import execute_order
from src.trading.execution.stoploss import position_tracker
from src.trading.risk.guards import (
    _load_risk_params,
    async_check_daily_loss,
    async_is_kill_switch_active,
    async_start_day,
    async_update_day_value,
    async_update_drawdown,
    check_liquidity,
    check_news_sentiment,
    check_var_limit,
    get_day_pnl,
)

logger = logging.getLogger(__name__)

_running = False
_max_trades_per_day = 5
_trades_today = 0
_last_reset_day: Optional[str] = None

_KEY_TRADES = "loop_trades_today"
_KEY_RESET_DAY = "loop_reset_day"


def _load_daily_counters() -> None:
    global _trades_today, _last_reset_day
    db = get_session()
    try:
        row = db.query(UserSetting).filter(UserSetting.key == _KEY_TRADES).first()
        if row:
            _trades_today = int(row.value)
        row2 = db.query(UserSetting).filter(UserSetting.key == _KEY_RESET_DAY).first()
        if row2:
            _last_reset_day = str(row2.value)
    finally:
        db.close()


def _save_daily_counters() -> None:
    db = get_session()
    try:
        existing = db.query(UserSetting).filter(UserSetting.key == _KEY_TRADES).first()
        if existing:
            existing.value = str(_trades_today)  # type: ignore[assignment]
        else:
            db.add(UserSetting(key=_KEY_TRADES, value=str(_trades_today)))
        existing2 = db.query(UserSetting).filter(UserSetting.key == _KEY_RESET_DAY).first()
        if existing2:
            existing2.value = str(_last_reset_day or "")  # type: ignore[assignment]
        else:
            db.add(UserSetting(key=_KEY_RESET_DAY, value=str(_last_reset_day or "")))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def set_max_trades_per_day(n: int) -> None:
    global _max_trades_per_day
    _max_trades_per_day = n
    logger.info("Max trades per day set to %d", n)


def reset_daily_counters() -> None:
    global _trades_today, _last_reset_day
    _trades_today = 0
    _last_reset_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _save_daily_counters()
    logger.info("Daily trade counter reset")


async def can_trade() -> tuple[bool, str]:
    if await async_is_kill_switch_active():
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


async def _check_var() -> tuple[bool, str]:
    db = get_session()
    try:
        from src.db.models import Portfolio, Price

        positions = db.query(Portfolio).all()
        all_returns = []
        for p in positions:
            if not p.instrument_id:
                continue
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


async def _check_liquidity(ticker: str) -> tuple[bool, str]:
    db = get_session()
    try:
        from src.db.models import Instrument, Price

        inst = db.query(Instrument).filter_by(ticker=ticker).first()
        if not inst or not inst.id:
            return True, "ok"
        prices = (
            db.query(Price.close, Price.volume)
            .filter_by(instrument_id=inst.id)
            .order_by(Price.date.desc())
            .limit(20)
            .all()
        )
        volumes = [p.volume for p in prices if p.volume is not None and p.close is not None]
        if len(volumes) < 5:
            return True, "ok"
        avg_vol = sum(volumes) / len(volumes)
        last_price = prices[0].close if prices and prices[0] else 0
        order_value = last_price * 10 if last_price else 0
        return check_liquidity(avg_vol, order_value)
    finally:
        db.close()


async def _check_news(ticker: str) -> tuple[bool, str]:
    db = get_session()
    try:
        from src.db.models import Instrument, News, NewsInstrument

        inst = db.query(Instrument).filter_by(ticker=ticker).first()
        if not inst:
            return True, "ok"
        recent_news = (
            db.query(News.sentiment_weighted, News.sentiment_score)
            .join(NewsInstrument)
            .filter(NewsInstrument.instrument_id == inst.id)
            .order_by(News.published_at.desc())
            .limit(10)
            .all()
        )
        scores = [n.sentiment_weighted or n.sentiment_score or 0 for n in recent_news]
        return check_news_sentiment(scores)
    finally:
        db.close()


async def _process_signals() -> None:
    from sqlalchemy.orm import joinedload

    from src.db.models import Signal as SignalModel

    db = get_session()
    try:
        today = datetime.now(timezone.utc).date()
        signals = (
            db.query(SignalModel)
            .options(joinedload(SignalModel.instrument))
            .filter(SignalModel.date >= today)
            .order_by(SignalModel.confidence.desc())
            .all()
        )

        if not signals:
            return

        if not await market_hours_check():
            logger.info("Market closed, skipping signal processing")
            return

        can, reason = await can_trade()
        if not can:
            logger.warning("Cannot trade: %s", reason)
            return

        var_ok, var_msg = await _check_var()
        if not var_ok:
            logger.warning("VaR limit exceeded: %s", var_msg)
            return

        db2 = get_session()
        try:
            from src.db.models import Portfolio as PortModel
            from src.db.models import Price as PriceModel

            port_rows = db2.query(PortModel).all()
            if port_rows:
                inst_ids = [p.instrument_id for p in port_rows if p.instrument_id]
                if inst_ids:
                    from sqlalchemy import func as sqlfunc

                    latest_prices_sub = (
                        db2.query(
                            PriceModel.instrument_id,
                            PriceModel.close,
                            sqlfunc.row_number()
                            .over(partition_by=PriceModel.instrument_id, order_by=PriceModel.date.desc())
                            .label("rn"),
                        )
                        .filter(PriceModel.instrument_id.in_(inst_ids))
                        .subquery()
                    )
                    latest_prices = {
                        pid: float(close)
                        for pid, close in db2.query(latest_prices_sub.c.instrument_id, latest_prices_sub.c.close)
                        .filter(latest_prices_sub.c.rn == 1)
                        .all()
                    }
                else:
                    latest_prices = {}

                total_value = (
                    sum(
                        (p.quantity or 0) * (latest_prices.get(p.instrument_id) or p.avg_price or 0)
                        for p in port_rows
                    )
                    or 100000
                )
            else:
                total_value = 100000

            signal_inst_ids = [s.instrument_id for s in signals if s.instrument]
            last_price_rows = {}
            if signal_inst_ids:
                latest_signal_prices_sub = (
                    db2.query(
                        PriceModel.instrument_id,
                        PriceModel.close,
                        sqlfunc.row_number()
                        .over(partition_by=PriceModel.instrument_id, order_by=PriceModel.date.desc())
                        .label("rn"),
                    )
                    .filter(PriceModel.instrument_id.in_(signal_inst_ids))
                    .subquery()
                )
                last_price_rows = {
                    pid: float(close)
                    for pid, close in db2.query(
                        latest_signal_prices_sub.c.instrument_id, latest_signal_prices_sub.c.close
                    )
                    .filter(latest_signal_prices_sub.c.rn == 1)
                    .all()
                }
        except Exception:
            total_value = 100000
            last_price_rows = {}
        finally:
            db2.close()

        for s in signals:
            if not s.instrument:
                continue
            ticker = s.instrument.ticker

            lq_ok, lq_msg = await _check_liquidity(ticker)
            if not lq_ok:
                logger.warning("Liquidity check failed for %s: %s", ticker, lq_msg)
                continue

            ns_ok, ns_msg = await _check_news(ticker)
            if not ns_ok:
                logger.warning("News sentiment check failed for %s: %s", ticker, ns_msg)
                continue

            max_pos_pct = s.fused_json.get("max_portfolio_pct", 10) if isinstance(s.fused_json, dict) else 10

            last_price = last_price_rows.get(s.instrument_id, 100)

            max_position_value = total_value * max_pos_pct / 100
            quantity = max(1, int(max_position_value / last_price))

            if s.action in ("BUY", "CAUTIOUS_BUY"):
                result = await execute_order(
                    ticker=ticker,
                    direction="BUY",
                    quantity=quantity,
                    reason=f"Signal: {s.action} ({s.confidence:.0%})",
                )
            elif s.action == "SELL":
                result = await execute_order(
                    ticker=ticker,
                    direction="SELL",
                    quantity=quantity,
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


async def _check_stop_losses() -> None:
    db = get_session()
    try:
        from src.db.models import Instrument, Price

        open_orders = db.query(OrderModel).filter(OrderModel.status.in_(["filled", "partial"])).all()
        if not open_orders:
            return

        tickers = list({o.ticker for o in open_orders if o.ticker})
        instruments_map = {}
        if tickers:
            for i in db.query(Instrument).filter(Instrument.ticker.in_(tickers)).all():
                if i.id:
                    instruments_map[i.ticker] = i

        inst_ids = [i.id for i in instruments_map.values() if i.id]
        latest_prices: dict[int, float] = {}
        if inst_ids:
            all_prices = (
                db.query(Price)
                .filter(Price.instrument_id.in_(inst_ids))
                .order_by(Price.instrument_id, Price.date.desc())
                .all()
            )
            seen: set[int] = set()
            for p in all_prices:
                if p.instrument_id not in seen and p.close is not None:
                    latest_prices[p.instrument_id] = float(p.close)
                    seen.add(p.instrument_id)

        for order in open_orders:
            inst = instruments_map.get(str(order.ticker))
            if not inst or not inst.id:
                continue
            price_close = latest_prices.get(inst.id)
            if price_close is None:
                continue
            await position_tracker.execute_triggers(str(order.ticker), price_close)
    finally:
        db.close()


async def _check_daily_pnl() -> None:
    db = get_session()
    try:
        from src.db.models import Portfolio as PortModel
        from src.db.models import Price

        total = db.query(PortModel).all()
        current_value = 0.0
        if total:
            inst_ids = [p.instrument_id for p in total if p.instrument_id]
            latest_prices: dict[int, float] = {}
            if inst_ids:
                all_prices = (
                    db.query(Price.instrument_id, Price.close)
                    .filter(Price.instrument_id.in_(inst_ids))
                    .order_by(Price.date.desc())
                    .all()
                )
                seen: set[int] = set()
                for row in all_prices:
                    pid = getattr(row, "instrument_id", row[0] if isinstance(row, (list, tuple)) else None)
                    close_val = getattr(row, "close", row[1] if isinstance(row, (list, tuple)) else None)
                    if pid is not None and pid not in seen and close_val is not None:
                        latest_prices[pid] = float(close_val)
                        seen.add(pid)

            for p in total:
                if not p.instrument_id:
                    continue
                price = latest_prices.get(p.instrument_id, float(p.avg_price or 0))
                current_value += float(p.quantity or 0) * price
        await async_update_day_value(current_value)
        await async_update_drawdown(current_value)
        pnl, pnl_pct = get_day_pnl()
        await async_check_daily_loss(pnl_pct)
    finally:
        db.close()


async def _rebalance_portfolio() -> None:
    db = get_session()
    try:
        from src.notifications.service import NotificationService

        ns = NotificationService()
        alerts = ns.check_rebalance(db)
        for alert in alerts:
            if abs(alert.deviation_pct) < 0.02:
                continue
            direction = "BUY" if alert.deviation_pct < 0 else "SELL"
            qty = max(1, int(abs(alert.deviation_pct) * 100))
            await execute_order(
                ticker=alert.ticker,
                direction=direction,
                quantity=qty,
                reason=f"rebalance: {alert.target_pct:.0%} target, drift {alert.deviation_pct:+.1%}",
            )
    except Exception as e:
        logger.warning("Rebalance error: %s", e)
    finally:
        db.close()


async def run_execution_loop(interval: int = 300) -> None:
    global _running
    if _running:
        logger.warning("Execution loop already running")
        return
    _running = True

    logger.info("Execution loop started (interval=%ds)", interval)

    try:
        from src.db.connection import init_db

        init_db()
    except Exception as e:
        logger.warning("Failed to initialize DB in execution loop: %s", e)

    _load_daily_counters()
    _load_risk_params()
    await async_start_day(1_000_000)

    rebalance_interval = 3600 * 6
    last_rebalance = 0.0

    while _running:
        try:
            if await market_hours_check():
                await _check_daily_pnl()

                if not settings.enable_trading:
                    if _trades_today > 0 and _last_reset_day != datetime.now(timezone.utc).strftime("%Y-%m-%d"):
                        reset_daily_counters()
                elif not await async_is_kill_switch_active():
                    await _process_signals()
                    await _check_stop_losses()

                    elapsed = datetime.now(timezone.utc).timestamp() - last_rebalance
                    if elapsed > rebalance_interval:
                        await _rebalance_portfolio()
                        last_rebalance = datetime.now(timezone.utc).timestamp()
        except Exception as e:
            logger.error("Execution loop error: %s", e, exc_info=True)

        await asyncio.sleep(interval)


def stop() -> None:
    global _running
    _running = False
    logger.info("Execution loop stopping")
