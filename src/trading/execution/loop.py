import asyncio
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.config import personal, settings
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


def _acquire_execution_lock() -> bool:
    lock_dir = Path(os.environ.get("FINN_LOCK_DIR", tempfile.gettempdir()))
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / "finn_execution.lock"
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False


def _release_execution_lock() -> None:
    lock_dir = Path(os.environ.get("FINN_LOCK_DIR", tempfile.gettempdir()))
    lock_path = lock_dir / "finn_execution.lock"
    lock_path.unlink(missing_ok=True)


_EXECUTION_LOCK_HELD = False

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
    except Exception as exc:
        logger.error("Failed to save daily counters: %s", exc)
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
        await asyncio.to_thread(_load_daily_counters)
    if _last_reset_day is None or _last_reset_day != today:
        await asyncio.to_thread(reset_daily_counters)

    if _trades_today >= _max_trades_per_day:
        return False, f"Max trades per day reached ({_max_trades_per_day})"

    return True, "ok"


async def market_hours_check() -> bool:
    now = datetime.now(timezone.utc)
    hour = now.hour
    minute = now.minute
    time_decimal = hour + minute / 60

    if 6.83 <= time_decimal <= 15.83:
        return True
    if 16.0 <= time_decimal <= 20.833:
        return True

    logger.debug("Outside market hours (UTC %.2f)", time_decimal)
    return False


async def _check_var(db: AsyncSession | None = None) -> tuple[bool, str]:
    if db is not None:
        return await _check_var_async(db)

    def _work() -> tuple[bool, str]:
        sync_db = get_session()
        try:
            from src.db.models import Portfolio, Price

            positions = sync_db.query(Portfolio).all()
            all_returns = []
            for p in positions:
                if not p.instrument_id:
                    continue
                prices = sync_db.query(Price.close).filter_by(instrument_id=p.instrument_id).order_by(Price.date.desc()).limit(60).all()
                vals = [r[0] for r in prices if r[0] is not None]
                if len(vals) < 20:
                    continue
                rets = [(vals[i + 1] - vals[i]) / vals[i] for i in range(len(vals) - 1)]
                all_returns.extend(rets)
            if len(all_returns) < 20:
                return True, "ok"
            import numpy as np

            var_95 = float(abs(np.percentile(all_returns, 5)))
            return check_var_limit(var_95)
        finally:
            sync_db.close()

    return await asyncio.to_thread(_work)


async def _check_var_async(db: AsyncSession) -> tuple[bool, str]:
    from sqlalchemy import select

    from src.db.models import Portfolio, Price

    result = await db.execute(select(Portfolio))
    positions = result.scalars().all()
    all_returns: list[float] = []
    for p in positions:
        if not p.instrument_id:
            continue
        result = await db.execute(select(Price.close).where(Price.instrument_id == p.instrument_id).order_by(Price.date.desc()).limit(60))
        vals = [r[0] for r in result.all() if r[0] is not None]
        if len(vals) < 20:
            continue
        rets = [(vals[i] - vals[i + 1]) / vals[i + 1] for i in range(len(vals) - 1)]
        all_returns.extend(rets)
    if len(all_returns) < 20:
        return True, "ok"
    import numpy as np

    var_95 = float(abs(np.percentile(all_returns, 5)))
    return check_var_limit(var_95)


async def _check_liquidity(ticker: str) -> tuple[bool, str]:

    def _work() -> tuple[bool, str]:
        db = get_session()
        try:
            from src.db.models import Instrument, Price

            inst = db.query(Instrument).filter_by(ticker=ticker).first()
            if not inst or not inst.id:
                return True, "ok"
            prices = db.query(Price.close, Price.volume).filter_by(instrument_id=inst.id).order_by(Price.date.desc()).limit(20).all()
            volumes = [p.volume for p in prices if p.volume is not None and p.close is not None]
            if len(volumes) < 5:
                return True, "ok"
            avg_vol = sum(volumes) / len(volumes)
            last_price = prices[0].close if prices and prices[0] else 0
            order_value = last_price * 10 if last_price else 0
            return check_liquidity(avg_vol, order_value)
        finally:
            db.close()

    return await asyncio.to_thread(_work)


async def _check_news(ticker: str) -> tuple[bool, str]:

    def _work() -> tuple[bool, str]:
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

    return await asyncio.to_thread(_work)


async def _process_signals() -> None:
    if not await market_hours_check():
        logger.info("Market closed, skipping signal processing")
        return

    can, reason = await can_trade()
    if not can:
        logger.warning("Cannot trade: %s", reason)
        return

    from sqlalchemy import select
    from sqlalchemy.orm import joinedload

    from src.db.connection import AsyncSessionLocal
    from src.db.models import Instrument, News, NewsInstrument
    from src.db.models import Portfolio as PortModel
    from src.db.models import Price as PriceModel
    from src.db.models import Signal as SignalModel

    signals: list[SignalModel] = []
    liquidity_cache: dict[str, tuple[bool, str]] = {}
    news_cache: dict[str, tuple[bool, str]] = {}
    total_value = 100000
    last_price_rows: dict[int, float] = {}

    async with AsyncSessionLocal() as db:
        today = datetime.now(timezone.utc).date()
        result = await db.execute(
            select(SignalModel).options(joinedload(SignalModel.instrument)).where(SignalModel.date >= today).order_by(SignalModel.confidence.desc())
        )
        signals = result.scalars().all()
        if not signals:
            return

        result = await db.execute(select(PortModel))
        port_rows = result.scalars().all()

        if port_rows:
            inst_ids = [p.instrument_id for p in port_rows if p.instrument_id]
            latest_prices: dict[int, float] = {}
            if inst_ids:
                result = await db.execute(
                    select(PriceModel.instrument_id, PriceModel.close).where(PriceModel.instrument_id.in_(inst_ids)).order_by(PriceModel.date.desc())
                )
                seen_prices: set[int] = set()
                for row in result.all():
                    if row.instrument_id not in seen_prices and row.close is not None:
                        latest_prices[row.instrument_id] = float(row.close)
                        seen_prices.add(row.instrument_id)

            total_value = sum((p.quantity or 0) * (latest_prices.get(p.instrument_id) or p.avg_price or 0) for p in port_rows) or 100000

        signal_inst_ids = [s.instrument_id for s in signals if s.instrument]
        if signal_inst_ids:
            result = await db.execute(
                select(PriceModel.instrument_id, PriceModel.close)
                .where(PriceModel.instrument_id.in_(signal_inst_ids))
                .order_by(PriceModel.date.desc())
            )
            seen_prices = set()
            for row in result.all():
                if row.instrument_id not in seen_prices and row.close is not None:
                    last_price_rows[row.instrument_id] = float(row.close)
                    seen_prices.add(row.instrument_id)

        # Pre-fetch liquidity and news data for all signal instruments
        tickers_with_inst = {s.instrument.ticker: s.instrument_id for s in signals if s.instrument and s.instrument_id}

        ticker_inst_map: dict[str, int] = {
            inst.ticker: inst.id
            for inst in (await db.execute(select(Instrument).where(Instrument.ticker.in_(list(tickers_with_inst.keys()))))).scalars().all()
            if inst.id
        }

        for ticker in tickers_with_inst:
            inst_id = ticker_inst_map.get(ticker)
            if not inst_id:
                liquidity_cache[ticker] = (True, "ok")
                news_cache[ticker] = (True, "ok")
                continue

            # Liquidity
            result = await db.execute(
                select(PriceModel.close, PriceModel.volume).where(PriceModel.instrument_id == inst_id).order_by(PriceModel.date.desc()).limit(20)
            )
            price_rows = result.all()
            volumes = [r.volume for r in price_rows if r.volume is not None and r.close is not None]
            if len(volumes) >= 5:
                avg_vol = sum(volumes) / len(volumes)
                last_price = price_rows[0].close if price_rows and price_rows[0] else 0
                order_value = last_price * 10 if last_price else 0
                liquidity_cache[ticker] = check_liquidity(avg_vol, order_value)
            else:
                liquidity_cache[ticker] = (True, "ok")

            # News sentiment
            result = await db.execute(
                select(News.sentiment_weighted, News.sentiment_score)
                .join(NewsInstrument)
                .where(NewsInstrument.instrument_id == inst_id)
                .order_by(News.published_at.desc())
                .limit(10)
            )
            scores = [n.sentiment_weighted or n.sentiment_score or 0 for n in result.all()]
            news_cache[ticker] = check_news_sentiment(scores)

        var_ok, var_msg = await _check_var(db=db)
        if not var_ok:
            logger.warning("VaR limit exceeded: %s", var_msg)
            return

    for s in signals:
        if not s.instrument:
            continue
        ticker = s.instrument.ticker

        lq_ok, lq_msg = liquidity_cache.get(ticker, (True, "ok"))
        if not lq_ok:
            logger.warning("Liquidity check failed for %s: %s", ticker, lq_msg)
            continue

        ns_ok, ns_msg = news_cache.get(ticker, (True, "ok"))
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
            await asyncio.to_thread(_save_daily_counters)


async def _check_stop_losses() -> None:
    from sqlalchemy import select

    from src.db.connection import AsyncSessionLocal
    from src.db.models import Instrument, Price

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(OrderModel).where(OrderModel.status.in_(["filled", "partial"])))
        open_orders = result.scalars().all()
        if not open_orders:
            return

        tickers = list({o.ticker for o in open_orders if o.ticker})
        instruments_map: dict[str, Instrument] = {}
        if tickers:
            result = await db.execute(select(Instrument).where(Instrument.ticker.in_(tickers)))
            for i in result.scalars().all():
                if i.id:
                    instruments_map[str(i.ticker)] = i

        inst_ids = [i.id for i in instruments_map.values() if i.id]
        latest_prices: dict[int, float] = {}
        if inst_ids:
            result = await db.execute(select(Price).where(Price.instrument_id.in_(inst_ids)).order_by(Price.instrument_id, Price.date.desc()))
            all_prices = result.scalars().all()
            seen: set[int] = set()
            for p in all_prices:
                if p.instrument_id not in seen and p.close is not None:
                    latest_prices[p.instrument_id] = float(p.close)
                    seen.add(p.instrument_id)

        triggers: list[tuple[str, float]] = []
        for order in open_orders:
            inst = instruments_map.get(str(order.ticker))
            if not inst or not inst.id:
                continue
            price_close = latest_prices.get(inst.id)
            if price_close is None:
                continue
            triggers.append((str(order.ticker), price_close))

    for ticker, price_close in triggers:
        await position_tracker.execute_triggers(ticker, price_close)


async def _check_daily_pnl() -> None:
    from sqlalchemy import select

    from src.db.connection import AsyncSessionLocal
    from src.db.models import Portfolio as PortModel
    from src.db.models import Price as PriceModel

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(PortModel))
        total = result.scalars().all()
        current_value = 0.0
        if total:
            inst_ids = [p.instrument_id for p in total if p.instrument_id]
            latest_prices: dict[int, float] = {}
            if inst_ids:
                result = await db.execute(
                    select(PriceModel.instrument_id, PriceModel.close).where(PriceModel.instrument_id.in_(inst_ids)).order_by(PriceModel.date.desc())
                )
                rows = result.all()
                seen: set[int] = set()
                for row in rows:
                    pid = row.instrument_id
                    close_val = row.close
                    if pid is not None and pid not in seen and close_val is not None:
                        latest_prices[pid] = float(close_val)
                        seen.add(pid)

            for p in total:
                if not p.instrument_id:
                    continue
                price = latest_prices.get(p.instrument_id, float(p.avg_price or 0))
                current_value += float(p.quantity or 0) * price

    pnl, pnl_pct = get_day_pnl()
    await async_update_day_value(current_value)
    await async_update_drawdown(current_value)
    await async_check_daily_loss(pnl_pct)


async def _rebalance_portfolio() -> None:

    def _work() -> list[tuple[str, float, float]]:
        db = get_session()
        try:
            from src.notifications.service import NotificationService

            ns = NotificationService()
            alerts = ns.check_rebalance(db)
            result: list[tuple[str, float, float]] = []
            for alert in alerts:
                if abs(alert.deviation_pct) < 0.02:
                    continue
                result.append((alert.ticker, alert.deviation_pct, alert.target_pct))
            return result
        except Exception:
            logger.exception("Unhandled exception")
            return []
        finally:
            db.close()

    rebalances = await asyncio.to_thread(_work)
    for ticker, deviation_pct, target_pct in rebalances:
        direction = "BUY" if deviation_pct < 0 else "SELL"
        qty = max(1, int(abs(deviation_pct) * 100))
        await execute_order(
            ticker=ticker,
            direction=direction,
            quantity=qty,
            reason=f"rebalance: {target_pct:.0%} target, drift {deviation_pct:+.1%}",
        )


async def run_execution_loop(interval: int = 300) -> None:
    global _running, _EXECUTION_LOCK_HELD
    if not _acquire_execution_lock():
        logger.error("Another execution loop instance is already running (lock file exists)")
        return
    _EXECUTION_LOCK_HELD = True
    if _running:
        logger.warning("Execution loop already running")
        return
    _running = True

    logger.info("Execution loop started (interval=%ds)", interval)

    try:
        from src.core.shutdown import register_shutdown_hook, setup_signal_handlers

        setup_signal_handlers()
        register_shutdown_hook(stop)
    except Exception as exc:
        logger.warning("Failed to setup signal handlers/shutdown hook: %s", exc)

    try:
        from src.db.connection import init_db

        init_db()
    except Exception as exc:
        logger.warning("init_db failed: %s", exc)

    try:
        from src.trading.risk.guards import wire_circuit_breakers_to_kill_switch

        wire_circuit_breakers_to_kill_switch()
        logger.info("Circuit breakers wired to kill switch")
    except Exception as exc:
        logger.warning("Failed to wire circuit breakers to kill switch: %s", exc)

    await asyncio.to_thread(_load_daily_counters)
    _load_risk_params()
    await async_start_day(personal.get("day_start_balance", 1_000_000))

    rebalance_interval = 3600 * 6
    last_rebalance = 0.0

    shutdown_event = asyncio.Event()

    async def _check_shutdown() -> None:
        global _running
        while _running:
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if shutdown_event.is_set():
                logger.info("shutdown.execution_signal_received")
                _running = False
                break

    asyncio.create_task(_check_shutdown())
    while _running:
        try:
            if await market_hours_check():
                await _check_daily_pnl()

                if not settings.enable_trading:
                    if _trades_today > 0 and _last_reset_day != datetime.now(timezone.utc).strftime("%Y-%m-%d"):
                        await asyncio.to_thread(reset_daily_counters)
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
    global _EXECUTION_LOCK_HELD
    if _EXECUTION_LOCK_HELD:
        _release_execution_lock()
        _EXECUTION_LOCK_HELD = False
    global _running
    _running = False
    logger.info("Execution loop stopping")
