"""Tests for execution loop"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def reset_globals():
    import src.trading.execution.loop as loop

    loop._trades_today = 0
    loop._last_reset_day = None
    loop._max_trades_per_day = 5
    loop._running = False


class TestSetters:
    def test_set_max_trades_per_day(self):
        import src.trading.execution.loop as loop

        loop.set_max_trades_per_day(3)
        assert loop._max_trades_per_day == 3

    def test_stop(self):
        import src.trading.execution.loop as loop

        assert loop._running is False

        loop._running = True
        loop.stop()
        assert loop._running is False


class TestResetDailyCounters:
    def test_resets_globals_and_saves(self):
        import src.trading.execution.loop as loop

        with patch("src.trading.execution.loop._save_daily_counters") as mock_save:
            loop._trades_today = 3
            loop.reset_daily_counters()
            assert loop._trades_today == 0
            assert loop._last_reset_day is not None
            mock_save.assert_called_once()


class TestLoadSaveCounters:
    def test_load_counters_no_data(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.side_effect = [None, None]

        with patch("src.trading.execution.loop.get_session", return_value=mock_db):
            loop._load_daily_counters()
            assert loop._trades_today == 0
            assert loop._last_reset_day is None

    def test_load_counters_with_data(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        row_trades = MagicMock(value="3")
        row_day = MagicMock(value="2024-01-15")
        mock_db.query.return_value.filter.return_value.first.side_effect = [row_trades, row_day]

        with patch("src.trading.execution.loop.get_session", return_value=mock_db):
            loop._load_daily_counters()
            assert loop._trades_today == 3
            assert loop._last_reset_day == "2024-01-15"

    def test_save_counters_existing(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        existing_trades = MagicMock()
        existing_day = MagicMock()
        mock_db.query.return_value.filter.return_value.first.side_effect = [
            existing_trades,
            existing_day,
        ]

        with patch("src.trading.execution.loop.get_session", return_value=mock_db):
            loop._save_daily_counters()
            assert existing_trades.value == "0"
            assert existing_day.value == ""
            mock_db.commit.assert_called_once()
            mock_db.close.assert_called_once()

    def test_save_counters_new(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch("src.trading.execution.loop.get_session", return_value=mock_db):
            loop._save_daily_counters()
            assert mock_db.add.call_count == 2
            mock_db.commit.assert_called_once()
            mock_db.close.assert_called_once()

    def test_save_counters_exception(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.commit.side_effect = Exception("DB error")

        with patch("src.trading.execution.loop.get_session", return_value=mock_db):
            loop._save_daily_counters()
            mock_db.rollback.assert_called_once()
            mock_db.close.assert_called_once()


class TestMarketHoursCheck:
    @pytest.mark.asyncio
    async def test_main_session(self):
        import src.trading.execution.loop as loop

        dt = datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)
        with patch("src.trading.execution.loop.datetime") as mock_dt:
            mock_dt.now.return_value = dt
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw) if a else dt

            assert await loop.market_hours_check() is True

    @pytest.mark.asyncio
    async def test_outside_hours(self):
        import src.trading.execution.loop as loop

        dt = datetime(2024, 1, 15, 20, 0, tzinfo=timezone.utc)
        with patch("src.trading.execution.loop.datetime") as mock_dt:
            mock_dt.now.return_value = dt
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw) if a else dt

            assert await loop.market_hours_check() is False

    @pytest.mark.asyncio
    async def test_evening_session(self):
        import src.trading.execution.loop as loop

        dt = datetime(2024, 1, 15, 17, 0, tzinfo=timezone.utc)
        with patch("src.trading.execution.loop.datetime") as mock_dt:
            mock_dt.now.return_value = dt
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw) if a else dt

            assert await loop.market_hours_check() is True


class TestCanTrade:
    @pytest.mark.asyncio
    async def test_kill_switch_active(self):
        import src.trading.execution.loop as loop

        with patch(
            "src.trading.execution.loop.async_is_kill_switch_active",
            return_value=True,
        ):
            ok, reason = await loop.can_trade()
            assert ok is False
            assert "Kill switch" in reason

    @pytest.mark.asyncio
    async def test_max_trades_reached(self):
        import src.trading.execution.loop as loop

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        loop._max_trades_per_day = 2
        loop._trades_today = 2
        loop._last_reset_day = today

        with patch(
            "src.trading.execution.loop.async_is_kill_switch_active",
            return_value=False,
        ):
            ok, reason = await loop.can_trade()
            assert ok is False
            assert "Max trades" in reason

    @pytest.mark.asyncio
    async def test_can_trade_ok(self):
        import src.trading.execution.loop as loop

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        loop._max_trades_per_day = 5
        loop._trades_today = 1
        loop._last_reset_day = today

        with (
            patch(
                "src.trading.execution.loop.async_is_kill_switch_active",
                return_value=False,
            ),
            patch("src.trading.execution.loop._load_daily_counters"),
        ):
            ok, reason = await loop.can_trade()
            assert ok is True
            assert reason == "ok"

    @pytest.mark.asyncio
    async def test_resets_on_new_day(self):
        import src.trading.execution.loop as loop

        loop._last_reset_day = None

        with (
            patch(
                "src.trading.execution.loop.async_is_kill_switch_active",
                return_value=False,
            ),
            patch("src.trading.execution.loop._load_daily_counters"),
            patch("src.trading.execution.loop.reset_daily_counters") as mock_reset,
        ):
            ok, reason = await loop.can_trade()
            assert ok is True
            mock_reset.assert_called_once()


class TestCheckVar:
    @pytest.mark.asyncio
    async def test_no_positions_returns_ok(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        mock_db.query.return_value.all.return_value = []

        with patch("src.trading.execution.loop.get_session", return_value=mock_db):
            ok, reason = await loop._check_var()
            assert ok is True
            assert reason == "ok"

    @pytest.mark.asyncio
    async def test_few_returns_per_position_skips(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        pos = MagicMock(instrument_id=1)
        prices = [MagicMock(close=i) for i in range(5)]
        mock_db.query.return_value.all.return_value = [pos]
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.limit.return_value.all.return_value = (
            prices
        )

        with patch("src.trading.execution.loop.get_session", return_value=mock_db):
            ok, reason = await loop._check_var()
            assert ok is True
            assert reason == "ok"

    @pytest.mark.asyncio
    async def test_enough_returns_calls_check_var_limit(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        pos = MagicMock(instrument_id=1)
        prices = [MagicMock(close=i) for i in range(25)]
        mock_db.query.return_value.all.return_value = [pos]
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.limit.return_value.all.return_value = (
            prices
        )

        with (
            patch("src.trading.execution.loop.get_session", return_value=mock_db),
            patch("numpy.percentile", return_value=0.03),
            patch("src.trading.execution.loop.check_var_limit", return_value=(True, "VaR ok")) as mock_check,
        ):
            ok, reason = await loop._check_var()
            assert ok is True
            mock_check.assert_called_once()

    @pytest.mark.asyncio
    async def test_var_limit_exceeded(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        pos = MagicMock(instrument_id=1)
        prices = [MagicMock(close=i) for i in range(25)]
        mock_db.query.return_value.all.return_value = [pos]
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.limit.return_value.all.return_value = (
            prices
        )

        with (
            patch("src.trading.execution.loop.get_session", return_value=mock_db),
            patch("numpy.percentile", return_value=0.08),
            patch("src.trading.execution.loop.check_var_limit", return_value=(False, "VaR exceeded")) as mock_check,
        ):
            ok, reason = await loop._check_var()
            assert ok is False
            mock_check.assert_called_once()


class TestCheckLiquidity:
    @pytest.mark.asyncio
    async def test_instrument_not_found_returns_ok(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        with patch("src.trading.execution.loop.get_session", return_value=mock_db):
            ok, reason = await loop._check_liquidity("SBER")
            assert ok is True
            assert reason == "ok"

    @pytest.mark.asyncio
    async def test_few_volumes_returns_ok(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        inst = MagicMock(id=1)
        prices = [MagicMock(close=100.0, volume=1000) for _ in range(3)]
        mock_db.query.return_value.filter_by.return_value.first.return_value = inst
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.limit.return_value.all.return_value = (
            prices
        )

        with patch("src.trading.execution.loop.get_session", return_value=mock_db):
            ok, reason = await loop._check_liquidity("SBER")
            assert ok is True
            assert reason == "ok"

    @pytest.mark.asyncio
    async def test_sufficient_volumes_calls_check_liquidity(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        inst = MagicMock(id=1)
        prices = [MagicMock(close=100.0, volume=1000) for _ in range(10)]
        mock_db.query.return_value.filter_by.return_value.first.return_value = inst
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.limit.return_value.all.return_value = (
            prices
        )

        with (
            patch("src.trading.execution.loop.get_session", return_value=mock_db),
            patch(
                "src.trading.execution.loop.check_liquidity", return_value=(True, "✅ Ликвидность: 1x запас")
            ) as mock_check,
        ):
            ok, reason = await loop._check_liquidity("SBER")
            assert ok is True
            assert "Ликвидность" in reason
            mock_check.assert_called_once()


class TestCheckNews:
    @pytest.mark.asyncio
    async def test_instrument_not_found_returns_ok(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        with patch("src.trading.execution.loop.get_session", return_value=mock_db):
            ok, reason = await loop._check_news("SBER")
            assert ok is True
            assert reason == "ok"

    @pytest.mark.asyncio
    async def test_no_recent_news_returns_ok(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        inst = MagicMock(id=1)
        mock_db.query.return_value.filter_by.return_value.first.return_value = inst
        mock_db.query.return_value.join.return_value.filter.return_value\
            .order_by.return_value.limit.return_value.all.return_value = []

        with patch("src.trading.execution.loop.get_session", return_value=mock_db):
            ok, reason = await loop._check_news("SBER")
            assert ok is True

    @pytest.mark.asyncio
    async def test_positive_sentiment(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        inst = MagicMock(id=1)
        news = [
            MagicMock(sentiment_weighted=0.5, sentiment_score=0.4),
            MagicMock(sentiment_weighted=0.3, sentiment_score=0.2),
        ]
        mock_db.query.return_value.filter_by.return_value.first.return_value = inst
        mock_db.query.return_value.join.return_value.filter.return_value\
            .order_by.return_value.limit.return_value.all.return_value = news

        with patch("src.trading.execution.loop.get_session", return_value=mock_db):
            ok, reason = await loop._check_news("SBER")
            assert ok is True

    @pytest.mark.asyncio
    async def test_negative_sentiment_fails(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        inst = MagicMock(id=1)
        news = [
            MagicMock(sentiment_weighted=-0.6, sentiment_score=-0.5),
        ]
        mock_db.query.return_value.filter_by.return_value.first.return_value = inst
        mock_db.query.return_value.join.return_value.filter.return_value\
            .order_by.return_value.limit.return_value.all.return_value = news

        with patch("src.trading.execution.loop.get_session", return_value=mock_db):
            ok, reason = await loop._check_news("SBER")
            assert ok is False


class TestCheckStopLosses:
    @pytest.mark.asyncio
    async def test_no_open_orders(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []

        with patch("src.trading.execution.loop.get_session", return_value=mock_db):
            await loop._check_stop_losses()

    @pytest.mark.asyncio
    async def test_order_no_instrument_skips(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        order = MagicMock(ticker="SBER")
        mock_db.query.return_value.filter.return_value.all.return_value = [order]
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        with patch("src.trading.execution.loop.get_session", return_value=mock_db):
            await loop._check_stop_losses()

    @pytest.mark.asyncio
    async def test_order_no_price_skips(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        order = MagicMock(ticker="SBER")
        inst = MagicMock(id=1)
        mock_db.query.return_value.filter.return_value.all.return_value = [order]
        mock_db.query.return_value.filter_by.return_value.first.side_effect = [inst]
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = None

        with patch("src.trading.execution.loop.get_session", return_value=mock_db):
            await loop._check_stop_losses()

    @pytest.mark.asyncio
    async def test_executes_trigger(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        order = MagicMock(ticker="SBER")
        inst = MagicMock(id=1)
        price = MagicMock(close=250.0)
        mock_db.query.return_value.filter.return_value.all.return_value = [order]
        mock_db.query.return_value.filter_by.return_value.first.side_effect = [inst]
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = price

        tracker = MagicMock()
        tracker.execute_triggers = AsyncMock()

        with (
            patch("src.trading.execution.loop.get_session", return_value=mock_db),
            patch("src.trading.execution.loop.position_tracker", tracker),
        ):
            await loop._check_stop_losses()
            tracker.execute_triggers.assert_called_once_with("SBER", 250.0)


class TestCheckDailyPnl:
    @pytest.mark.asyncio
    async def test_no_positions(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        mock_db.query.return_value.all.return_value = []

        with (
            patch("src.trading.execution.loop.get_session", return_value=mock_db),
            patch("src.trading.execution.loop.async_update_day_value") as mock_update_val,
            patch("src.trading.execution.loop.async_update_drawdown") as mock_update_dd,
            patch("src.trading.execution.loop.get_day_pnl", return_value=(0.0, 0.0)),
            patch("src.trading.execution.loop.async_check_daily_loss") as mock_check_loss,
        ):
            await loop._check_daily_pnl()
            mock_update_val.assert_called_once_with(0.0)
            mock_update_dd.assert_called_once_with(0.0)
            mock_check_loss.assert_called_once_with(0.0)

    @pytest.mark.asyncio
    async def test_with_positions(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        pos1 = MagicMock(instrument_id=10, quantity=5, avg_price=200.0)
        pos2 = MagicMock(instrument_id=20, quantity=3, avg_price=100.0)
        mock_db.query.return_value.all.return_value = [pos1, pos2]

        price_row1 = (250.0,)
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = price_row1
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.first.side_effect = [price_row1, None]

        with (
            patch("src.trading.execution.loop.get_session", return_value=mock_db),
            patch("src.trading.execution.loop.async_update_day_value") as mock_update_val,
            patch("src.trading.execution.loop.async_update_drawdown") as mock_update_dd,
            patch("src.trading.execution.loop.get_day_pnl", return_value=(150.0, 0.05)),
            patch("src.trading.execution.loop.async_check_daily_loss") as mock_check_loss,
        ):
            await loop._check_daily_pnl()
            # pos1: 5 * 250 = 1250; pos2: no latest price, uses avg_price 100, 3 * 100 = 300; total 1550
            mock_update_val.assert_called_once_with(1550.0)
            mock_update_dd.assert_called_once_with(1550.0)
            mock_check_loss.assert_called_once_with(0.05)

    @pytest.mark.asyncio
    async def test_position_with_no_instrument_id_skips(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        pos = MagicMock(instrument_id=None, quantity=5, avg_price=200.0)
        mock_db.query.return_value.all.return_value = [pos]

        with (
            patch("src.trading.execution.loop.get_session", return_value=mock_db),
            patch("src.trading.execution.loop.async_update_day_value") as mock_update_val,
            patch("src.trading.execution.loop.async_update_drawdown") as mock_update_dd,
            patch("src.trading.execution.loop.get_day_pnl", return_value=(0.0, 0.0)),
            patch("src.trading.execution.loop.async_check_daily_loss") as mock_check_loss,
        ):
            await loop._check_daily_pnl()
            mock_update_val.assert_called_once_with(0.0)
            mock_update_dd.assert_called_once_with(0.0)
            mock_check_loss.assert_called_once_with(0.0)


class TestRebalancePortfolio:
    @pytest.mark.asyncio
    async def test_no_alerts(self):
        import src.trading.execution.loop as loop

        with (
            patch("src.notifications.service.NotificationService") as mock_ns_cls,
            patch("src.trading.execution.loop.execute_order") as mock_exec,
        ):
            mock_ns = MagicMock()
            mock_ns.check_rebalance.return_value = []
            mock_ns_cls.return_value = mock_ns

            await loop._rebalance_portfolio()
            mock_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_small_deviation_skipped(self):
        import src.trading.execution.loop as loop

        with (
            patch("src.notifications.service.NotificationService") as mock_ns_cls,
            patch("src.trading.execution.loop.execute_order") as mock_exec,
        ):
            mock_ns = MagicMock()
            alert = MagicMock(deviation_pct=0.01, ticker="SBER", target_pct=0.25)
            mock_ns.check_rebalance.return_value = [alert]
            mock_ns_cls.return_value = mock_ns

            await loop._rebalance_portfolio()
            mock_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_buy_alert(self):
        import src.trading.execution.loop as loop

        with (
            patch("src.notifications.service.NotificationService") as mock_ns_cls,
            patch("src.trading.execution.loop.execute_order", new_callable=AsyncMock) as mock_exec,
        ):
            mock_ns = MagicMock()
            alert = MagicMock(deviation_pct=-0.05, ticker="SBER", target_pct=0.25)
            mock_ns.check_rebalance.return_value = [alert]
            mock_ns_cls.return_value = mock_ns

            await loop._rebalance_portfolio()
            mock_exec.assert_called_once()
            args, kwargs = mock_exec.call_args
            assert kwargs["ticker"] == "SBER"
            assert kwargs["direction"] == "BUY"
            assert kwargs["quantity"] == 5

    @pytest.mark.asyncio
    async def test_sell_alert(self):
        import src.trading.execution.loop as loop

        with (
            patch("src.notifications.service.NotificationService") as mock_ns_cls,
            patch("src.trading.execution.loop.execute_order", new_callable=AsyncMock) as mock_exec,
        ):
            mock_ns = MagicMock()
            alert = MagicMock(deviation_pct=0.07, ticker="GAZP", target_pct=0.30)
            mock_ns.check_rebalance.return_value = [alert]
            mock_ns_cls.return_value = mock_ns

            await loop._rebalance_portfolio()
            mock_exec.assert_called_once()
            args, kwargs = mock_exec.call_args
            assert kwargs["ticker"] == "GAZP"
            assert kwargs["direction"] == "SELL"
            assert kwargs["quantity"] == 7

    @pytest.mark.asyncio
    async def test_exception_handled(self):
        import src.trading.execution.loop as loop

        with (
            patch("src.notifications.service.NotificationService") as mock_ns_cls,
            patch("src.trading.execution.loop.execute_order") as mock_exec,
        ):
            mock_ns = MagicMock()
            mock_ns.check_rebalance.side_effect = Exception("Rebalance error")
            mock_ns_cls.return_value = mock_ns

            await loop._rebalance_portfolio()
            mock_exec.assert_not_called()


class TestProcessSignals:
    @pytest.mark.asyncio
    async def test_no_signals(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        mock_db.query.return_value.options.return_value.filter.return_value.order_by.return_value.all.return_value = []

        with patch("src.trading.execution.loop.get_session", return_value=mock_db):
            await loop._process_signals()

    @pytest.mark.asyncio
    async def test_signal_no_instrument_skips(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        sig = MagicMock(instrument=None, action="BUY", confidence=0.8)
        mock_db.query.return_value.options.return_value.filter.return_value.order_by.return_value.all.return_value = [
            sig
        ]

        with patch("src.trading.execution.loop.get_session", return_value=mock_db):
            await loop._process_signals()

    @pytest.mark.asyncio
    async def test_market_closed_returns_early(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        inst = MagicMock(ticker="SBER")
        sig = MagicMock(instrument=inst, action="BUY", confidence=0.8)
        mock_db.query.return_value.options.return_value.filter.return_value.order_by.return_value.all.return_value = [
            sig
        ]

        with (
            patch("src.trading.execution.loop.get_session", return_value=mock_db),
            patch("src.trading.execution.loop.market_hours_check", return_value=False),
        ):
            await loop._process_signals()

    @pytest.mark.asyncio
    async def test_cannot_trade_returns_early(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        inst = MagicMock(ticker="SBER")
        sig = MagicMock(instrument=inst, action="BUY", confidence=0.8)
        mock_db.query.return_value.options.return_value.filter.return_value.order_by.return_value.all.return_value = [
            sig
        ]

        with (
            patch("src.trading.execution.loop.get_session", return_value=mock_db),
            patch("src.trading.execution.loop.market_hours_check", return_value=True),
            patch("src.trading.execution.loop.can_trade", return_value=(False, "Kill switch active")),
        ):
            await loop._process_signals()

    @pytest.mark.asyncio
    async def test_var_exceeded_returns_early(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        inst = MagicMock(ticker="SBER")
        sig = MagicMock(instrument=inst, action="BUY", confidence=0.8)
        mock_db.query.return_value.options.return_value.filter.return_value.order_by.return_value.all.return_value = [
            sig
        ]

        with (
            patch("src.trading.execution.loop.get_session", return_value=mock_db),
            patch("src.trading.execution.loop.market_hours_check", return_value=True),
            patch("src.trading.execution.loop.can_trade", return_value=(True, "ok")),
            patch("src.trading.execution.loop._check_var", return_value=(False, "VaR exceeded")),
        ):
            await loop._process_signals()

    @pytest.mark.asyncio
    async def test_liquidity_fail_skips_signal(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        inst = MagicMock(ticker="SBER")
        sig = MagicMock(instrument=inst, action="BUY", confidence=0.8)
        mock_db.query.return_value.options.return_value.filter.return_value.order_by.return_value.all.return_value = [
            sig
        ]

        with (
            patch("src.trading.execution.loop.get_session", return_value=mock_db),
            patch("src.trading.execution.loop.market_hours_check", return_value=True),
            patch("src.trading.execution.loop.can_trade", return_value=(True, "ok")),
            patch("src.trading.execution.loop._check_var", return_value=(True, "ok")),
            patch("src.trading.execution.loop._check_liquidity", return_value=(False, "Low liquidity")),
        ):
            await loop._process_signals()

    @pytest.mark.asyncio
    async def test_news_fail_skips_signal(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        inst = MagicMock(ticker="SBER")
        sig = MagicMock(instrument=inst, action="BUY", confidence=0.8)
        mock_db.query.return_value.options.return_value.filter.return_value.order_by.return_value.all.return_value = [
            sig
        ]

        with (
            patch("src.trading.execution.loop.get_session", return_value=mock_db),
            patch("src.trading.execution.loop.market_hours_check", return_value=True),
            patch("src.trading.execution.loop.can_trade", return_value=(True, "ok")),
            patch("src.trading.execution.loop._check_var", return_value=(True, "ok")),
            patch("src.trading.execution.loop._check_liquidity", return_value=(True, "ok")),
            patch("src.trading.execution.loop._check_news", return_value=(False, "Bad news")),
        ):
            await loop._process_signals()

    @pytest.mark.asyncio
    async def test_buy_action_executes(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        inst = MagicMock(ticker="SBER")
        sig = MagicMock(instrument=inst, action="BUY", confidence=0.8)
        mock_db.query.return_value.options.return_value.filter.return_value.order_by.return_value.all.return_value = [
            sig
        ]

        mock_result = MagicMock()
        mock_result.status = "filled"

        with (
            patch("src.trading.execution.loop.get_session", return_value=mock_db),
            patch("src.trading.execution.loop.market_hours_check", return_value=True),
            patch("src.trading.execution.loop.can_trade", return_value=(True, "ok")),
            patch("src.trading.execution.loop._check_var", return_value=(True, "ok")),
            patch("src.trading.execution.loop._check_liquidity", return_value=(True, "ok")),
            patch("src.trading.execution.loop._check_news", return_value=(True, "ok")),
            patch("src.trading.execution.loop.execute_order", new_callable=AsyncMock, return_value=mock_result),
            patch("src.trading.execution.loop._save_daily_counters") as mock_save,
        ):
            assert loop._trades_today == 0
            await loop._process_signals()
            assert loop._trades_today == 1
            mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_cautious_buy_executes_as_buy(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        inst = MagicMock(ticker="SBER")
        sig = MagicMock(instrument=inst, action="CAUTIOUS_BUY", confidence=0.6)
        mock_db.query.return_value.options.return_value.filter.return_value.order_by.return_value.all.return_value = [
            sig
        ]

        mock_result = MagicMock()
        mock_result.status = "filled"

        with (
            patch("src.trading.execution.loop.get_session", return_value=mock_db),
            patch("src.trading.execution.loop.market_hours_check", return_value=True),
            patch("src.trading.execution.loop.can_trade", return_value=(True, "ok")),
            patch("src.trading.execution.loop._check_var", return_value=(True, "ok")),
            patch("src.trading.execution.loop._check_liquidity", return_value=(True, "ok")),
            patch("src.trading.execution.loop._check_news", return_value=(True, "ok")),
            patch("src.trading.execution.loop.execute_order", new_callable=AsyncMock, return_value=mock_result),
            patch("src.trading.execution.loop._save_daily_counters"),
        ):
            assert loop._trades_today == 0
            await loop._process_signals()
            assert loop._trades_today == 1

    @pytest.mark.asyncio
    async def test_sell_action_executes(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        inst = MagicMock(ticker="GAZP")
        sig = MagicMock(instrument=inst, action="SELL", confidence=0.7)
        mock_db.query.return_value.options.return_value.filter.return_value.order_by.return_value.all.return_value = [
            sig
        ]

        mock_result = MagicMock()
        mock_result.status = "filled"

        with (
            patch("src.trading.execution.loop.get_session", return_value=mock_db),
            patch("src.trading.execution.loop.market_hours_check", return_value=True),
            patch("src.trading.execution.loop.can_trade", return_value=(True, "ok")),
            patch("src.trading.execution.loop._check_var", return_value=(True, "ok")),
            patch("src.trading.execution.loop._check_liquidity", return_value=(True, "ok")),
            patch("src.trading.execution.loop._check_news", return_value=(True, "ok")),
            patch("src.trading.execution.loop.execute_order", new_callable=AsyncMock, return_value=mock_result),
            patch("src.trading.execution.loop._save_daily_counters") as mock_save,
        ):
            assert loop._trades_today == 0
            await loop._process_signals()
            assert loop._trades_today == 1
            mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_action_skipped(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        inst = MagicMock(ticker="SBER")
        sig = MagicMock(instrument=inst, action="HOLD", confidence=0.5)
        mock_db.query.return_value.options.return_value.filter.return_value.order_by.return_value.all.return_value = [
            sig
        ]

        with (
            patch("src.trading.execution.loop.get_session", return_value=mock_db),
            patch("src.trading.execution.loop.market_hours_check", return_value=True),
            patch("src.trading.execution.loop.can_trade", return_value=(True, "ok")),
            patch("src.trading.execution.loop._check_var", return_value=(True, "ok")),
            patch("src.trading.execution.loop._check_liquidity", return_value=(True, "ok")),
            patch("src.trading.execution.loop._check_news", return_value=(True, "ok")),
            patch("src.trading.execution.loop.execute_order", new_callable=AsyncMock) as mock_exec,
        ):
            await loop._process_signals()
            mock_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_result_not_filled_does_not_increment(self):
        import src.trading.execution.loop as loop

        mock_db = MagicMock()
        inst = MagicMock(ticker="SBER")
        sig = MagicMock(instrument=inst, action="BUY", confidence=0.8)
        mock_db.query.return_value.options.return_value.filter.return_value.order_by.return_value.all.return_value = [
            sig
        ]

        mock_result = MagicMock()
        mock_result.status = "failed"

        loop._trades_today = 0

        with (
            patch("src.trading.execution.loop.get_session", return_value=mock_db),
            patch("src.trading.execution.loop.market_hours_check", return_value=True),
            patch("src.trading.execution.loop.can_trade", return_value=(True, "ok")),
            patch("src.trading.execution.loop._check_var", return_value=(True, "ok")),
            patch("src.trading.execution.loop._check_liquidity", return_value=(True, "ok")),
            patch("src.trading.execution.loop._check_news", return_value=(True, "ok")),
            patch("src.trading.execution.loop.execute_order", new_callable=AsyncMock, return_value=mock_result),
        ):
            await loop._process_signals()
            assert loop._trades_today == 0


class TestRunExecutionLoop:
    @pytest.mark.asyncio
    async def test_already_running_returns_early(self):
        import src.trading.execution.loop as loop

        loop._running = True

        with patch("src.trading.execution.loop._process_signals") as mock_process:
            await loop.run_execution_loop(interval=1)
            mock_process.assert_not_called()

    @pytest.mark.asyncio
    async def test_one_iteration_with_trading_enabled(self):
        import src.trading.execution.loop as loop

        async def fake_sleep(_):
            loop._running = False

        dt = datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)

        with (
            patch("src.trading.execution.loop.market_hours_check", return_value=True),
            patch("src.trading.execution.loop._check_daily_pnl") as mock_pnl,
            patch("src.trading.execution.loop.async_is_kill_switch_active"),
            patch("src.trading.execution.loop._process_signals") as mock_signals,
            patch("src.trading.execution.loop._check_stop_losses") as mock_sl,
            patch("src.trading.execution.loop._rebalance_portfolio") as mock_rebalance,
            patch("src.trading.execution.loop.asyncio.sleep", side_effect=fake_sleep),
            patch("src.trading.execution.loop.datetime") as mock_dt,
            patch("src.trading.execution.loop.settings") as mock_settings,
            patch("src.trading.execution.loop._load_daily_counters"),
            patch("src.trading.execution.loop._load_risk_params"),
            patch("src.trading.execution.loop.async_start_day"),
            patch("src.db.connection.init_db"),
        ):
            mock_settings.enable_trading = True
            mock_dt.now.return_value = dt
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw) if a else dt

            await loop.run_execution_loop(interval=1)

            mock_pnl.assert_called_once()
            mock_signals.assert_called_once()
            mock_sl.assert_called_once()
            mock_rebalance.assert_called_once()

    @pytest.mark.asyncio
    async def test_one_iteration_with_trading_disabled(self):
        import src.trading.execution.loop as loop

        async def fake_sleep(_):
            loop._running = False

        dt = datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)

        with (
            patch("src.trading.execution.loop.market_hours_check", return_value=True),
            patch("src.trading.execution.loop._check_daily_pnl") as mock_pnl,
            patch("src.trading.execution.loop.async_is_kill_switch_active") as mock_ks,
            patch("src.trading.execution.loop._process_signals") as mock_signals,
            patch("src.trading.execution.loop._check_stop_losses") as mock_sl,
            patch("src.trading.execution.loop.asyncio.sleep", side_effect=fake_sleep),
            patch("src.trading.execution.loop.datetime") as mock_dt,
            patch("src.trading.execution.loop.settings") as mock_settings,
            patch("src.trading.execution.loop._load_daily_counters"),
            patch("src.trading.execution.loop._load_risk_params"),
            patch("src.trading.execution.loop.async_start_day"),
            patch("src.db.connection.init_db"),
        ):
            mock_settings.enable_trading = False
            mock_dt.now.return_value = dt
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw) if a else dt

            await loop.run_execution_loop(interval=1)

            mock_pnl.assert_called_once()
            mock_ks.assert_not_called()
            mock_signals.assert_not_called()
            mock_sl.assert_not_called()

    @pytest.mark.asyncio
    async def test_outside_market_hours_skips_trading(self):
        import src.trading.execution.loop as loop

        async def fake_sleep(_):
            loop._running = False

        with (
            patch("src.trading.execution.loop.market_hours_check", return_value=False),
            patch("src.trading.execution.loop._check_daily_pnl") as mock_pnl,
            patch("src.trading.execution.loop._process_signals") as mock_signals,
            patch("src.trading.execution.loop.asyncio.sleep", side_effect=fake_sleep),
            patch("src.trading.execution.loop.settings"),
            patch("src.trading.execution.loop._load_daily_counters"),
            patch("src.trading.execution.loop._load_risk_params"),
            patch("src.trading.execution.loop.async_start_day"),
            patch("src.db.connection.init_db"),
        ):
            await loop.run_execution_loop(interval=1)

            mock_pnl.assert_not_called()
            mock_signals.assert_not_called()

    @pytest.mark.asyncio
    async def test_kill_switch_active_skips_trading(self):
        import src.trading.execution.loop as loop

        async def fake_sleep(_):
            loop._running = False

        dt = datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)

        with (
            patch("src.trading.execution.loop.market_hours_check", return_value=True),
            patch("src.trading.execution.loop._check_daily_pnl") as mock_pnl,
            patch("src.trading.execution.loop.async_is_kill_switch_active", return_value=True),
            patch("src.trading.execution.loop._process_signals") as mock_signals,
            patch("src.trading.execution.loop._check_stop_losses") as mock_sl,
            patch("src.trading.execution.loop.asyncio.sleep", side_effect=fake_sleep),
            patch("src.trading.execution.loop.datetime") as mock_dt,
            patch("src.trading.execution.loop.settings") as mock_settings,
            patch("src.trading.execution.loop._load_daily_counters"),
            patch("src.trading.execution.loop._load_risk_params"),
            patch("src.trading.execution.loop.async_start_day"),
            patch("src.db.connection.init_db"),
        ):
            mock_settings.enable_trading = True
            mock_dt.now.return_value = dt
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw) if a else dt

            await loop.run_execution_loop(interval=1)

            mock_pnl.assert_called_once()
            mock_signals.assert_not_called()
            mock_sl.assert_not_called()

    @pytest.mark.asyncio
    async def test_trading_disabled_resets_if_trades_open_on_new_day(self):
        import src.trading.execution.loop as loop

        loop._trades_today = 2

        async def fake_sleep(_):
            loop._running = False

        dt = datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)

        with (
            patch("src.trading.execution.loop.market_hours_check", return_value=True),
            patch("src.trading.execution.loop._check_daily_pnl") as mock_pnl,
            patch("src.trading.execution.loop.async_is_kill_switch_active"),
            patch("src.trading.execution.loop._process_signals"),
            patch("src.trading.execution.loop._check_stop_losses"),
            patch("src.trading.execution.loop.asyncio.sleep", side_effect=fake_sleep),
            patch("src.trading.execution.loop.datetime") as mock_dt,
            patch("src.trading.execution.loop.settings") as mock_settings,
            patch("src.trading.execution.loop._load_daily_counters"),
            patch("src.trading.execution.loop._load_risk_params"),
            patch("src.trading.execution.loop.async_start_day"),
            patch("src.db.connection.init_db"),
            patch("src.trading.execution.loop.reset_daily_counters") as mock_reset,
        ):
            mock_settings.enable_trading = False
            mock_dt.now.return_value = dt
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw) if a else dt

            await loop.run_execution_loop(interval=1)

            mock_pnl.assert_called_once()
            mock_reset.assert_called_once()

    @pytest.mark.asyncio
    async def test_market_hours_exception_handling(self):
        import src.trading.execution.loop as loop

        async def fake_sleep(_):
            loop._running = False

        with (
            patch("src.trading.execution.loop.market_hours_check", side_effect=Exception("Boom")),
            patch("src.trading.execution.loop.asyncio.sleep", side_effect=fake_sleep),
            patch("src.trading.execution.loop._load_daily_counters"),
            patch("src.trading.execution.loop._load_risk_params"),
            patch("src.trading.execution.loop.async_start_day"),
            patch("src.db.connection.init_db"),
        ):
            await loop.run_execution_loop(interval=1)
