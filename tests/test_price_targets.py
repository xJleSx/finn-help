from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from src.analysis.ml.price_targets import (
    ENTRY_ATR_FACTOR,
    PROFILES,
    EntryZone,
    TakeProfit,
    TradePlan,
    build_trade_plan,
    compute_entry_zone,
    compute_risk_reward,
    compute_stop_loss,
    compute_support_resistance,
    compute_take_profits,
    to_dict,
)


def _make_df(n: int = 200) -> pd.DataFrame:
    dates = [date.today() - timedelta(days=i) for i in range(n, 0, -1)]
    close = np.sin(np.linspace(0, 6, n)) * 50 + 200 + np.random.default_rng(0).normal(0, 1, n)
    close = close + np.linspace(0, 10, n)
    df = pd.DataFrame(
        {
            "date": dates,
            "close": close,
            "open": close + np.random.default_rng(1).normal(0, 2, n),
            "high": close + abs(np.random.default_rng(2).normal(0, 3, n)),
            "low": close - abs(np.random.default_rng(3).normal(0, 3, n)),
            "volume": np.random.default_rng(4).poisson(5_000_000, n),
        }
    )
    df["rsi"] = 50 + np.random.default_rng(5).normal(0, 10, n)
    df["macd_hist"] = np.random.default_rng(6).normal(0, 1, n)
    df["sma_20"] = df["close"].rolling(20).mean()
    df["sma_50"] = df["close"].rolling(50).mean()
    df["atr"] = np.random.default_rng(7).uniform(1, 5, n)
    df["volume_sma_20"] = df["volume"].rolling(20).mean()
    return df


class TestEntryZone:
    def test_compute_basic(self):
        zone = compute_entry_zone(close=200.0, sma20=195.0, atr=10.0)
        assert isinstance(zone, EntryZone)
        expected_low = round(195.0 - ENTRY_ATR_FACTOR * 10.0, 2)
        expected_high = round(195.0 + ENTRY_ATR_FACTOR * 10.0, 2)
        assert zone.low == expected_low
        assert zone.high == expected_high
        assert zone.current == 200.0

    def test_falls_back_to_close_when_sma20_zero(self):
        zone = compute_entry_zone(close=150.0, sma20=0.0, atr=8.0)
        expected_low = round(150.0 - ENTRY_ATR_FACTOR * 8.0, 2)
        expected_high = round(150.0 + ENTRY_ATR_FACTOR * 8.0, 2)
        assert zone.low == expected_low
        assert zone.high == expected_high

    def test_entry_zone_low_less_than_high(self):
        zone = compute_entry_zone(close=300.0, sma20=290.0, atr=15.0)
        assert zone.low < zone.high


class TestSupportResistance:
    def test_returns_float_tuple(self):
        df = _make_df(100)
        sup, res = compute_support_resistance(df)
        assert sup is None or isinstance(sup, float)
        assert res is None or isinstance(res, float)
        if sup is not None and res is not None:
            assert sup <= res

    def test_short_df_returns_none(self):
        short = _make_df(5)
        result = compute_support_resistance(short)
        assert result == (None, None)

    def test_support_below_resistance(self):
        df = _make_df(200)
        sup, res = compute_support_resistance(df)
        if sup is not None and res is not None:
            assert sup < res


class TestStopLoss:
    def test_compute_stop_loss_conservative(self):
        sl = compute_stop_loss(entry=200.0, atr=10.0, side="buy", profile="conservative")
        expected = round(200.0 - PROFILES["conservative"]["stop_atr"] * 10.0, 2)
        assert sl == expected

    def test_compute_stop_loss_aggressive(self):
        sl = compute_stop_loss(entry=200.0, atr=10.0, side="buy", profile="aggressive")
        expected = round(200.0 - PROFILES["aggressive"]["stop_atr"] * 10.0, 2)
        assert sl == expected

    def test_stop_loss_below_entry_for_buy(self):
        for profile in ("conservative", "balanced", "aggressive"):
            sl = compute_stop_loss(entry=200.0, atr=10.0, side="buy", profile=profile)
            assert sl < 200.0

    def test_stop_loss_above_entry_for_sell(self):
        sl = compute_stop_loss(entry=200.0, atr=10.0, side="sell", profile="balanced")
        assert sl > 200.0


class TestTakeProfits:
    def test_compute_take_profits_conservative_returns_one_target(self):
        targets = compute_take_profits(entry=200.0, resistance=None, atr=10.0, profile="conservative")
        assert len(targets) == PROFILES["conservative"]["tp_count"]
        assert all(isinstance(t, TakeProfit) for t in targets)
        for t in targets:
            assert t.level > 200.0
            assert t.type.startswith("tp")

    def test_compute_take_profits_balanced_returns_two_targets(self):
        targets = compute_take_profits(entry=200.0, resistance=None, atr=10.0, profile="balanced")
        assert len(targets) == PROFILES["balanced"]["tp_count"]

    def test_compute_take_profits_aggressive_returns_three_targets(self):
        targets = compute_take_profits(entry=200.0, resistance=None, atr=10.0, profile="aggressive")
        assert len(targets) == PROFILES["aggressive"]["tp_count"]

    def test_targets_are_increasing(self):
        targets = compute_take_profits(entry=200.0, resistance=None, atr=10.0, profile="aggressive")
        levels = [t.level for t in targets]
        assert levels == sorted(levels)

    def test_risk_reward_increasing(self):
        targets = compute_take_profits(entry=200.0, resistance=None, atr=10.0, profile="balanced")
        rrs = [t.rr for t in targets]
        assert rrs == sorted(rrs)


class TestRiskReward:
    def test_compute_positive(self):
        entry = 200.0
        targets = [TakeProfit(level=220.0, type="tp1", return_pct=10.0, rr=2.0)]
        rr = compute_risk_reward(entry, targets, stop=190.0)
        assert rr > 0

    def test_compute_with_zero_risk(self):
        rr = compute_risk_reward(200.0, [TakeProfit(level=210.0, type="tp1", return_pct=5.0, rr=1.0)], stop=200.0)
        assert rr == 0.0


class TestBuildTradePlan:
    def test_returns_trade_plan(self):
        df = _make_df(200)
        plan = build_trade_plan(close=200.0, sma20=195.0, atr=10.0, df=df, profile="balanced")
        assert isinstance(plan, TradePlan)
        assert isinstance(plan.entry_zone, EntryZone)
        assert len(plan.targets) > 0
        assert plan.stop_loss < 200.0
        assert plan.risk_reward > 0

    def test_profiles_produce_different_plans(self):
        df = _make_df(200)
        conservative = build_trade_plan(200.0, 195.0, 10.0, df, profile="conservative")
        aggressive = build_trade_plan(200.0, 195.0, 10.0, df, profile="aggressive")
        assert len(conservative.targets) < len(aggressive.targets)
        assert conservative.stop_loss < aggressive.stop_loss

    def test_short_dataframe_returns_minimal_plan(self):
        df = _make_df(10)
        plan = build_trade_plan(200.0, 195.0, 10.0, df, profile="balanced")
        assert len(plan.targets) == PROFILES["balanced"]["tp_count"]
        for t in plan.targets:
            assert t.level > 0.0


class TestToDict:
    def test_returns_dict_with_expected_keys(self):
        df = _make_df(200)
        plan = build_trade_plan(200.0, 195.0, 10.0, df, profile="balanced")
        d = to_dict(plan)
        assert isinstance(d, dict)
        assert "entry_zone" in d
        assert "targets" in d
        assert "stop_loss" in d
        assert "trailing_after" in d
        assert "risk_reward" in d

    def test_entry_zone_has_low_high_current(self):
        df = _make_df(200)
        plan = build_trade_plan(200.0, 195.0, 10.0, df, profile="balanced")
        d = to_dict(plan)
        ez = d["entry_zone"]
        assert "low" in ez
        assert "high" in ez
        assert "current" in ez
        assert ez["low"] < ez["high"]

    def test_targets_have_all_fields(self):
        df = _make_df(200)
        plan = build_trade_plan(200.0, 195.0, 10.0, df, profile="aggressive")
        d = to_dict(plan)
        for t in d["targets"]:
            assert "level" in t
            assert "type" in t
            assert "return_pct" in t
            assert "rr" in t


class TestProfilesConfig:
    def test_all_profiles_have_required_keys(self):
        for name, config in PROFILES.items():
            assert "tp_count" in config
            assert "tp_levels" in config
            assert "stop_atr" in config
            assert "trailing_after" in config
            assert len(config["tp_levels"]) == config["tp_count"]

    def test_conservative_least_aggressive(self):
        assert PROFILES["conservative"]["stop_atr"] > PROFILES["aggressive"]["stop_atr"]
        assert len(PROFILES["conservative"]["tp_levels"]) < len(PROFILES["aggressive"]["tp_levels"])
