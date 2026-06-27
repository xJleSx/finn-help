"""Tests for risk guards"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.trading.risk.guards import (
    activate_kill_switch,
    check_concentration,
    check_daily_loss,
    check_leverage,
    check_liquidity,
    check_news_sentiment,
    check_position_size,
    check_var_limit,
    compute_position_shares,
    compute_volatility_target,
    deactivate_kill_switch,
    get_day_pnl,
    is_kill_switch_active,
    set_daily_loss_limit,
    set_max_drawdown_pct,
    set_max_leverage,
    set_max_position_pct,
    set_var_limit,
    start_day,
    update_day_value,
    update_drawdown,
)


@pytest.fixture(autouse=True)
def reset_guards():
    import src.trading.risk.guards as g

    g._kill_switch_active = False
    g._daily_loss_limit = None
    g._position_limit_pct = None
    g._max_drawdown_pct = 0.20
    g._peak_value = None
    g._day_start_value = None
    g._current_day_value = None
    yield


def test_kill_switch():
    assert is_kill_switch_active() is False
    activate_kill_switch("test")
    assert is_kill_switch_active() is True
    deactivate_kill_switch()
    assert is_kill_switch_active() is False


def test_daily_loss_limit():
    set_daily_loss_limit(0.05)
    assert check_daily_loss(-0.03) is False
    assert check_daily_loss(-0.06) is True
    assert is_kill_switch_active() is True


def test_check_position_size():
    set_max_position_pct(0.25)
    ok, msg = check_position_size(10000, 100000)
    assert ok is True
    assert "10.0%" in msg

    ok, msg = check_position_size(20000, 100000)
    assert ok is True
    assert "⚠️" in msg

    ok, msg = check_position_size(30000, 100000)
    assert ok is False

    ok, msg = check_position_size(40000, 100000)
    assert ok is False
    assert "40.0%" in msg


def test_check_position_size_no_limit():
    ok, _ = check_position_size(10000, 0)
    assert ok is True


def test_check_concentration():
    weights = {"SBER": 0.5, "GAZP": 0.25, "VTBR": 0.15, "LKOH": 0.10}
    warnings = check_concentration(weights)
    assert len(warnings) == 2
    assert any("SBER" in w for w in warnings)
    assert any("GAZP" in w for w in warnings)

    ok_weights = {"A": 0.15, "B": 0.15, "C": 0.10}
    assert check_concentration(ok_weights) == []


def test_compute_volatility_target():
    result = compute_volatility_target(target_vol=0.25, current_vol=0.5, max_leverage=1.0)
    assert result == 0.5

    result = compute_volatility_target(target_vol=0.25, current_vol=0.0, max_leverage=1.0)
    assert result == 1.0

    result = compute_volatility_target(target_vol=0.25, current_vol=0.1, max_leverage=2.0)
    assert result == 2.0


def test_compute_position_shares():
    shares = compute_position_shares(
        portfolio_value=100000,
        risk_per_trade=0.02,
        stop_loss_pct=0.05,
        current_price=100,
        max_shares=1000,
    )
    expected = int(100000 * 0.02 / (100 * 0.05))
    assert shares == min(max(expected, 1), 1000)

    shares = compute_position_shares(
        portfolio_value=100000,
        risk_per_trade=0.02,
        stop_loss_pct=0.05,
        current_price=100,
        max_shares=1000,
        current_vol=0.5,
    )
    assert shares < expected


def test_compute_position_shares_min():
    shares = compute_position_shares(
        portfolio_value=100,
        risk_per_trade=0.01,
        stop_loss_pct=0.5,
        current_price=1000,
        max_shares=100,
    )
    assert shares >= 1


def test_check_leverage():
    set_max_leverage(1.0)
    ok, _ = check_leverage(0.5)
    assert ok is True
    ok, _ = check_leverage(1.5)
    assert ok is False


def test_var_limit():
    set_var_limit(0.05)
    ok, _ = check_var_limit(0.03)
    assert ok is True
    ok, _ = check_var_limit(0.07)
    assert ok is False


def test_liquidity():
    ok, _ = check_liquidity(1_000_000, 100_000)
    assert ok is True

    ok, _ = check_liquidity(0, 100_000)
    assert ok is False

    ok, _ = check_liquidity(100_000, 200_000)
    assert ok is False

    ok, _ = check_liquidity(300_000, 200_000)
    assert ok is True


def test_news_sentiment():
    ok, _ = check_news_sentiment([])
    assert ok is True

    ok, _ = check_news_sentiment([0.1, 0.2, 0.3])
    assert ok is True

    ok, _ = check_news_sentiment([-0.4, -0.2, -0.35])
    assert ok is False

    ok, _ = check_news_sentiment([-0.6, 0.1, 0.2])
    assert ok is False


def test_drawdown():
    dd = update_drawdown(100000)
    assert dd == 0.0

    dd = update_drawdown(90000)
    assert dd == -0.10

    dd = update_drawdown(80000)
    assert dd == -0.20

    dd = update_drawdown(85000)
    assert round(dd, 4) == -0.15

    dd = update_drawdown(110000)
    assert dd == 0.0


def test_drawdown_triggers_kill_switch():
    set_max_drawdown_pct(0.10)
    update_drawdown(100000)
    update_drawdown(85000)
    assert is_kill_switch_active() is True


def test_drawdown_no_peak():
    from src.trading.risk.guards import current_drawdown

    dd = current_drawdown()
    assert dd == 0.0


def test_day_pnl():
    start_day(100000)
    pnl, pnl_pct = get_day_pnl()
    assert pnl == 0
    assert pnl_pct == 0

    update_day_value(105000)
    pnl, pnl_pct = get_day_pnl()
    assert pnl == 5000
    assert pnl_pct == 0.05

    update_day_value(90000)
    pnl, pnl_pct = get_day_pnl()
    assert pnl == -10000
    assert pnl_pct == -0.10


def test_get_day_pnl_no_start():
    from src.trading.risk.guards import get_day_pnl as get_pnl

    pnl, pnl_pct = get_pnl()
    assert pnl == 0.0
    assert pnl_pct == 0.0


def test_max_drawdown_pct_default():
    from src.trading.risk.guards import max_drawdown_pct as mdd

    assert mdd() == 0.20


def test_risk_per_trade():
    from src.trading.risk.guards import risk_per_trade as rpt

    result = rpt()
    assert 0 < result <= 0.10


def test_max_position_pct_default():
    from src.trading.risk.guards import max_position_pct as mpp

    with patch("src.trading.risk.guards.personal", {"risk_profile": "balanced"}):
        result = mpp()
        assert result == 0.25


def test_max_position_pct_conservative():
    from src.trading.risk.guards import max_position_pct as mpp

    with patch("src.trading.risk.guards.personal", {"risk_profile": "conservative"}):
        result = mpp()
        assert result == 0.15


def test_max_position_pct_aggressive():
    from src.trading.risk.guards import max_position_pct as mpp

    with patch("src.trading.risk.guards.personal", {"risk_profile": "aggressive"}):
        result = mpp()
        assert result == 0.35


def test_reset_peak():
    from src.trading.risk.guards import reset_peak, update_drawdown

    update_drawdown(100000)
    update_drawdown(90000)
    dd_before = update_drawdown(90000)
    assert dd_before < 0
    reset_peak(90000)
    dd_after = update_drawdown(90000)
    assert dd_after == 0.0


def test_set_min_volume():
    import src.trading.risk.guards as g

    g.set_min_volume(500000)
    assert g.MIN_DAILY_VOLUME == 500000


def test_check_daily_loss_no_limit():
    assert check_daily_loss(-1.0) is False


def test_news_sentiment_warning():
    ok, msg = check_news_sentiment([-0.2, -0.15, -0.1])
    assert ok is True
    assert "⚠️" in msg


def test_drawdown_negative_peak():
    dd = update_drawdown(-1000)
    assert dd == 0.0


class TestAsyncGuards:
    @pytest.mark.asyncio
    async def test_async_check_daily_loss(self):
        from src.trading.risk.guards import async_check_daily_loss

        set_daily_loss_limit(0.05)
        result = await async_check_daily_loss(-0.03)
        assert result is False

    @pytest.mark.asyncio
    async def test_async_update_drawdown(self):
        from src.trading.risk.guards import async_update_drawdown

        result = await async_update_drawdown(100000)
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_async_activate_deactivate_kill_switch(self):
        from src.trading.risk.guards import (
            async_activate_kill_switch,
            async_deactivate_kill_switch,
            async_is_kill_switch_active,
        )

        active = await async_is_kill_switch_active()
        assert active is False
        await async_activate_kill_switch("async test")
        active = await async_is_kill_switch_active()
        assert active is True
        await async_deactivate_kill_switch()
        active = await async_is_kill_switch_active()
        assert active is False

    @pytest.mark.asyncio
    async def test_async_update_day_value(self):
        from src.trading.risk.guards import async_update_day_value

        await async_update_day_value(50000)
        from src.trading.risk.guards import _current_day_value

        assert _current_day_value == 50000

    @pytest.mark.asyncio
    async def test_async_start_day(self):
        import src.trading.risk.guards as g

        await g.async_start_day(200000)
        assert g._day_start_value == 200000
