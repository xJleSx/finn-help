#!/usr/bin/env python3
"""ML Model Backtest Report — reproducible OOS evaluation.

For each model (XGBoost, LightGBM, CatBoost, Ensemble):
  - Walk-forward: train on expanding window -> predict next day
  - Track: OOS return, Sharpe, max DD, win rate, accuracy, benchmark comparison

Usage:
    uv run python tools/ml_backtest_report.py
    uv run python tools/ml_backtest_report.py --ticker SBER --days 504
    uv run python tools/ml_backtest_report.py --all
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
logging.basicConfig(level=logging.WARNING, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

from src.analysis.metrics import (
    compute_max_drawdown,
    compute_profit_factor,
    compute_sharpe,
    compute_win_rate,
)
from src.analysis.technical import TechnicalAnalyzer
from src.config import settings
from src.db.connection import get_session
from src.db.models.instrument import Instrument, Price

SEED = 42
TICKERS_LIQUID = ["SBER", "GAZP", "LKOH", "VTBR", "MOEX"]
TRAIN_PCT = 0.65
RETRAIN_EVERY = 5

# Override strict thresholds for backtest so we get enough labeled data
# The models use 5d/3% by default, which is too strict for MOEX stocks
OVERRIDE_THRESHOLD = 0.02  # 2% forward return threshold (was 3%)
OVERRIDE_LOOKAHEAD = 5


@dataclass
class ModelBacktest:
    model_name: str
    ticker: str
    total_return: float = 0.0
    benchmark_return: float = 0.0
    alpha: float = 0.0
    sharpe: float = 0.0
    benchmark_sharpe: float = 0.0
    max_drawdown: float = 0.0
    benchmark_max_dd: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    signal_accuracy: float = 0.0
    signal_precision: float = 0.0
    signal_recall: float = 0.0
    signal_f1: float = 0.0
    buy_signals: int = 0
    sell_signals: int = 0
    hold_signals: int = 0
    total_signals: int = 0
    avg_confidence: float = 0.0
    avg_forward_return: float = 0.0
    n_train: int = 0
    n_test: int = 0
    train_time_s: float = 0.0
    daily_pnl: list[float] = field(default_factory=list)
    benchmark_daily: list[float] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    valid: bool = False

    @property
    def summary(self) -> dict[str, Any]:
        return {
            "model": self.model_name,
            "ticker": self.ticker,
            "valid": self.valid,
            "oos_return_pct": round(self.total_return * 100, 2),
            "benchmark_return_pct": round(self.benchmark_return * 100, 2),
            "alpha_pct": round(self.alpha * 100, 2),
            "sharpe": round(self.sharpe, 2),
            "max_drawdown_pct": round(self.max_drawdown * 100, 2),
            "win_rate_pct": round(self.win_rate * 100, 2),
            "profit_factor": round(self.profit_factor, 2),
            "signal_accuracy_pct": round(self.signal_accuracy * 100, 2),
            "signal_f1": round(self.signal_f1, 3),
            "buy_signals": self.buy_signals,
            "sell_signals": self.sell_signals,
            "hold_signals": self.hold_signals,
            "n_train": self.n_train,
            "n_test": self.n_test,
            "avg_confidence": round(self.avg_confidence, 3),
            "train_time_s": round(self.train_time_s, 2),
        }


# ── data helpers ─────────────────────────────────────────────────────────────


def fetch_prices(ticker: str, max_days: int = 504) -> pd.DataFrame:
    db = get_session()
    try:
        inst = db.query(Instrument).filter(Instrument.ticker == ticker).first()
        if not inst:
            raise ValueError(f"Ticker {ticker!r} not found")
        rows = (
            db.query(Price)
            .filter(Price.instrument_id == inst.id)
            .order_by(Price.date.asc())
            .all()
        )
        if not rows:
            raise ValueError(f"No prices for {ticker}")
        records = [
            {
                "date": r.date,
                "open": r.open or 0.0,
                "high": r.high or 0.0,
                "low": r.low or 0.0,
                "close": r.close or 0.0,
                "volume": r.volume or 0,
            }
            for r in rows
        ]
        df = pd.DataFrame(records).tail(max_days + 200)
        df = df.dropna(subset=["close"])
        return df.reset_index(drop=True)
    finally:
        db.close()


def compute_benchmark(tickers: list[str], max_days: int = 504) -> pd.Series:
    db = get_session()
    try:
        all_rets: dict[str, pd.Series] = {}
        for t in tickers:
            inst = db.query(Instrument).filter(Instrument.ticker == t).first()
            if not inst:
                continue
            rows = (
                db.query(Price)
                .filter(Price.instrument_id == inst.id)
                .order_by(Price.date.asc())
                .all()
            )
            closes = [r.close for r in rows if r.close]
            dates = [r.date for r in rows if r.close]
            if len(closes) < 2:
                continue
            s = pd.Series(closes, index=pd.DatetimeIndex(dates))
            ret = s.pct_change().dropna()
            all_rets[t] = ret
        if not all_rets:
            return pd.Series(dtype=float)
        bm = pd.concat(all_rets, axis=1).mean(axis=1).tail(max_days)
        return bm.dropna()
    finally:
        db.close()


@contextlib.contextmanager
def _override_ml_settings(
    threshold: float = 0.02,
    lookahead: int = 5,
    min_train_rows: int = 20,
    min_predict_rows: int = 30,
):
    """Temporarily change ML settings for backtesting."""
    old = {
        "threshold": settings.ml_threshold,
        "lookahead": settings.ml_lookahead,
        "min_train_rows": settings.ml_min_train_rows,
        "min_predict_rows": settings.ml_min_predict_rows,
        "hpo_enabled": settings.ml_hpo_enabled,
        "action_threshold": settings.ml_action_threshold,
    }
    settings.ml_threshold = threshold
    settings.ml_lookahead = lookahead
    settings.ml_min_train_rows = min_train_rows
    settings.ml_min_predict_rows = min_predict_rows
    settings.ml_hpo_enabled = False
    settings.ml_action_threshold = 0.55
    try:
        yield
    finally:
        settings.ml_threshold = old["threshold"]
        settings.ml_lookahead = old["lookahead"]
        settings.ml_min_train_rows = old["min_train_rows"]
        settings.ml_min_predict_rows = old["min_predict_rows"]
        settings.ml_hpo_enabled = old["hpo_enabled"]
        settings.ml_action_threshold = old["action_threshold"]


# ── walk-forward backtest ────────────────────────────────────────────────────


def backtest_model(
    model_name: str,
    model_factory: Any,
    df_full: pd.DataFrame,
    train_split: int,
    retrain_every: int = RETRAIN_EVERY,
    ticker: str = "",
) -> ModelBacktest:
    """Walk-forward backtest: retrain every N days, predict next-day direction."""
    result = ModelBacktest(model_name=model_name, ticker=ticker)
    n_total = len(df_full)
    if n_total < 80:
        return result

    daily_pnl: list[float] = []
    dates_oos: list[str] = []
    actions: list[str] = []
    confidences: list[float] = []
    forward_rets: list[float] = []

    model = model_factory(ticker=ticker)
    model_trained = False
    t_train_total = 0.0

    for i in range(train_split, n_total - 1):
        df_window = df_full.iloc[: i + 1].reset_index(drop=True)
        tech = TechnicalAnalyzer()
        df_window = tech.compute_all(df_window)

        if len(df_window) < 60:
            continue

        needs_retrain = (i - train_split) % retrain_every == 0

        try:
            if needs_retrain or not model_trained:
                model = model_factory(ticker=ticker)
                t0 = time.perf_counter()
                ok = all(model.train_all(df_window).values()) if model_name == "Ensemble" else model.train(df_window)
                t_train_total += time.perf_counter() - t0
                model_trained = ok
                if not ok:
                    continue
            pred = model.predict(df_window)
        except Exception as e:
            logger.debug("%s err idx=%d: %s", model_name, i, e)
            continue

        action = pred.get("action", "HOLD")
        confidence = pred.get("confidence", 0.0)
        actions.append(action)
        confidences.append(confidence)

        fwd_ret = df_full.iloc[i + 1]["close"] / df_full.iloc[i]["close"] - 1
        forward_rets.append(fwd_ret)

        if action == "BUY":
            pnl = fwd_ret
        elif action == "SELL":
            pnl = -fwd_ret
        else:
            pnl = 0.0

        daily_pnl.append(pnl)
        dates_oos.append(str(df_full.iloc[i]["date"]))

    result.n_train = train_split
    result.n_test = len(daily_pnl)
    result.train_time_s = t_train_total

    if len(daily_pnl) < 5:
        return result

    result.daily_pnl = daily_pnl
    result.dates = dates_oos

    # Benchmark: buy & hold starting from same split
    bench_rets: list[float] = []
    for i in range(train_split, min(n_total - 1, train_split + len(daily_pnl))):
        br = df_full.iloc[i + 1]["close"] / df_full.iloc[i]["close"] - 1
        bench_rets.append(br)
    if bench_rets:
        bench_rets = bench_rets[: len(daily_pnl)]
        result.benchmark_daily = bench_rets
        result.benchmark_return = float(np.prod(1 + np.array(bench_rets)) - 1)
        result.benchmark_sharpe = compute_sharpe(np.array(bench_rets))
        bench_eq = np.cumprod(1 + np.array(bench_rets))
        result.benchmark_max_dd = compute_max_drawdown(bench_eq.tolist())

    # Financial metrics
    pnl_arr = np.array(daily_pnl)
    result.total_return = float(np.prod(1 + pnl_arr) - 1)
    result.alpha = result.total_return - result.benchmark_return
    result.win_rate = compute_win_rate(pnl_arr)
    result.profit_factor = compute_profit_factor(pnl_arr)
    result.sharpe = compute_sharpe(pnl_arr)
    eq_curve = np.cumprod(1 + pnl_arr)
    result.max_drawdown = compute_max_drawdown(eq_curve.tolist())
    result.avg_forward_return = float(np.mean(forward_rets)) if forward_rets else 0.0
    result.avg_confidence = float(np.mean(confidences)) if confidences else 0.0

    # Classification: is BUY correct? is SELL correct?
    result.buy_signals = actions.count("BUY")
    result.sell_signals = actions.count("SELL")
    result.hold_signals = actions.count("HOLD")
    result.total_signals = len(actions)

    if len(actions) == len(forward_rets):
        correct = 0
        tp = fp = fn = 0
        for a, fr in zip(actions, forward_rets):
            if a == "BUY" and fr > 0 or a == "SELL" and fr < 0:
                correct += 1
                tp += 1
            elif a in ("BUY", "SELL") and fr <= 0:
                fp += 1
                fn += 1
        non_hold = sum(1 for a in actions if a != "HOLD")
        result.signal_accuracy = correct / non_hold if non_hold > 0 else 0.0
        result.signal_precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        result.signal_recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        result.signal_f1 = (
            2 * result.signal_precision * result.signal_recall
            / (result.signal_precision + result.signal_recall)
            if (result.signal_precision + result.signal_recall) > 0
            else 0.0
        )

    result.valid = True
    return result


# ── report ───────────────────────────────────────────────────────────────────


def print_report(results: list[ModelBacktest], ticker: str) -> None:
    sep = "=" * 95
    sep2 = "-" * 95
    print(f"\n{sep}")
    print(f"  ML Backtest Report -- {ticker}")
    print(f"{sep}")
    print("  Strategy: long BUY, short SELL, flat HOLD")
    print(f"  Benchmark: buy & hold {ticker}")
    print(f"  Threshold: {OVERRIDE_THRESHOLD*100:.0f}% / {OVERRIDE_LOOKAHEAD}d lookahead")
    print(f"{sep2}\n")

    models = ["XGBoost", "LightGBM", "CatBoost", "Ensemble"]
    lookup = {r.model_name: r for r in results if r.valid}

    print(f"  {'Metric':<28} {'XGBoost':<12} {'LightGBM':<12} {'CatBoost':<12} {'Ensemble':<12} {'Benchmark':<12}")
    print(sep2)

    rows = [
        ("OOS Return (%)", "total_return", 100, "{:+.2f}%%"),
        ("Sharpe Ratio", "sharpe", 1, "{:+.3f}"),
        ("Max Drawdown (%)", "max_drawdown", 100, "{:.2f}%%"),
        ("Win Rate (%)", "win_rate", 100, "{:.1f}%%"),
        ("Profit Factor", "profit_factor", 1, "{:.3f}"),
        ("Alpha (%)", "alpha", 100, "{:+.2f}%%"),
        ("Signal Accuracy (%)", "signal_accuracy", 100, "{:.1f}%%"),
        ("Signal F1", "signal_f1", 1, "{:.3f}"),
    ]

    for label, attr, mul, _ in rows:
        parts = [f"  {label:<28}"]
        for m in models:
            r = lookup.get(m)
            if r is None:
                parts.append(f"{'--':>10}")
            else:
                val = getattr(r, attr, 0.0) * mul
                if attr in ("total_return", "alpha"):
                    parts.append(f"{val:>+8.2f}%")
                elif attr in ("max_drawdown", "win_rate", "signal_accuracy"):
                    parts.append(f"{val:>8.1f}%")
                else:
                    parts.append(f"{val:>10.3f}")
        # Benchmark
        r0 = next(iter(lookup.values()), None)
        if r0 is not None:
            if attr == "total_return":
                parts.append(f"{r0.benchmark_return * 100:>+8.2f}%")
            elif attr == "sharpe":
                parts.append(f"{r0.benchmark_sharpe:>10.3f}")
            elif attr == "max_drawdown":
                parts.append(f"{r0.benchmark_max_dd * 100:>8.1f}%")
            else:
                parts.append(f"{'--':>10}")
        else:
            parts.append(f"{'--':>10}")
        print("  ".join(parts))

    print(sep2)

    # Signal distribution
    parts_dist = [f"  {'BUY / SELL / HOLD':<28}"]
    for m in models:
        r = lookup.get(m)
        if r is None:
            parts_dist.append(f"{'--':>10}")
        else:
            parts_dist.append(f"{r.buy_signals}/{r.sell_signals}/{r.hold_signals:<9}")
    parts_dist.append(f"{'--':>10}")
    print("  ".join(parts_dist))

    # Training days
    parts_tr = [f"  {'Train / Test days':<28}"]
    for m in models:
        r = lookup.get(m)
        if r is None:
            parts_tr.append(f"{'--':>10}")
        else:
            parts_tr.append(f"{r.n_train}/{r.n_test:<9}")
    parts_tr.append(f"{'--':>10}")
    print("  ".join(parts_tr))

    # Avg confidence
    parts_conf = [f"  {'Avg Confidence':<28}"]
    for m in models:
        r = lookup.get(m)
        if r is None:
            parts_conf.append(f"{'--':>10}")
        else:
            parts_conf.append(f"{r.avg_confidence:>10.3f}")
    parts_conf.append(f"{'--':>10}")
    print("  ".join(parts_conf))

    # Train time
    parts_time = [f"  {'Train Time (s)':<28}"]
    for m in models:
        r = lookup.get(m)
        if r is None:
            parts_time.append(f"{'--':>10}")
        else:
            parts_time.append(f"{r.train_time_s:>10.2f}")
    parts_time.append(f"{'--':>10}")
    print("  ".join(parts_time))

    print(sep)
    print()


# ── pooled backtest ────────────────────────────────────────────────────────────


def fetch_prices_multi(tickers: list[str], max_days: int = 504) -> dict[str, pd.DataFrame]:
    db = get_session()
    try:
        result: dict[str, pd.DataFrame] = {}
        for ticker in tickers:
            inst = db.query(Instrument).filter(Instrument.ticker == ticker).first()
            if not inst:
                continue
            rows = (
                db.query(Price)
                .filter(Price.instrument_id == inst.id)
                .order_by(Price.date.asc())
                .all()
            )
            if not rows:
                continue
            records = [
                {
                    "date": r.date,
                    "open": r.open or 0.0,
                    "high": r.high or 0.0,
                    "low": r.low or 0.0,
                    "close": r.close or 0.0,
                    "volume": r.volume or 0,
                }
                for r in rows
            ]
            df = pd.DataFrame(records).tail(max_days + 200)
            df = df.dropna(subset=["close"]).reset_index(drop=True)
            if len(df) >= 80:
                result[ticker] = df
        return result
    finally:
        db.close()


def backtest_pooled(
    tickers: list[str],
    max_days: int = 504,
    retrain_every: int = RETRAIN_EVERY,
) -> dict[str, list[ModelBacktest]]:
    """Walk-forward pooled backtest: train one model per algorithm across all
    tickers, predict each ticker individually."""
    from src.analysis.ml.catboost_model import CatBoostClassifierModel
    from src.analysis.ml.lightgbm_model import LightGBMClassifier
    from src.analysis.ml.pooled import PooledMLClassifier
    from src.analysis.ml.xgboost_model import XGBoostClassifier

    raw = fetch_prices_multi(tickers, max_days=max_days)
    if not raw:
        print("  No data for any ticker")
        return {}

    # Build unified timeline (union of all dates) — normalise to Timestamp
    all_dates = sorted({pd.Timestamp(d) for df in raw.values() for d in pd.to_datetime(df["date"])})
    print(f"  Unified timeline: {len(all_dates)} trading days")

    # Initialise results per ticker
    results: dict[str, list[ModelBacktest]] = {
        t: [
            ModelBacktest(model_name="PooledXGB", ticker=t),
            ModelBacktest(model_name="PooledLGB", ticker=t),
            ModelBacktest(model_name="PooledCat", ticker=t),
        ]
        for t in raw
    }

    model_defs = [
        ("PooledXGB", XGBoostClassifier),
        ("PooledLGB", LightGBMClassifier),
        ("PooledCat", CatBoostClassifierModel),
    ]

    train_split = int(len(all_dates) * TRAIN_PCT)
    models: list[PooledMLClassifier | None] = [None] * len(model_defs)

    # Pre-compute per-ticker date → row index mapping
    ticker_idx: dict[str, dict[pd.Timestamp, int]] = {}
    for t, df in raw.items():
        dates = pd.DatetimeIndex(pd.to_datetime(df["date"]))
        ticker_idx[t] = {d: i for i, d in enumerate(dates)}

    for i in range(train_split, len(all_dates) - 1):
        current_date = all_dates[i]
        needs_retrain = (i - train_split) % retrain_every == 0 or i == train_split

        if needs_retrain:
            pooled_input: dict[str, pd.DataFrame] = {}
            for t, df in raw.items():
                dts = pd.to_datetime(df["date"])
                mask = dts <= current_date
                subset = df[mask.values].copy()
                if len(subset) >= 60:
                    pooled_input[t] = subset

            if len(pooled_input) >= 2:
                for mi, (name, factory) in enumerate(model_defs):
                    pm = PooledMLClassifier(factory)
                    if pm.train_pooled(pooled_input):
                        models[mi] = pm
                    else:
                        models[mi] = None

        # Predict each ticker
        for t, df in raw.items():
            idx = ticker_idx[t].get(current_date)
            if idx is None or idx + 1 >= len(df):
                continue

            fwd_ret = df.iloc[idx + 1]["close"] / df.iloc[idx]["close"] - 1

            for mi, (name, _) in enumerate(model_defs):
                pm = models[mi]
                if pm is None:
                    continue

                window = df.iloc[: idx + 1].copy().reset_index(drop=True)
                pm._ticker = t
                pred = pm.predict(window)

                action = pred.get("action", "HOLD")
                confidence = pred.get("confidence", 0.0)
                bt = results[t][mi]

                pnl = fwd_ret if action == "BUY" else (-fwd_ret if action == "SELL" else 0.0)
                bt.daily_pnl.append(pnl)
                bt.dates.append(str(current_date))
                if not hasattr(bt, "forward_rets"):
                    bt.forward_rets = []
                    bt.actions = []
                    bt.confidences = []
                bt.forward_rets.append(fwd_ret)
                bt.actions.append(action)
                bt.confidences.append(confidence)
    # Finalise results
    for t in raw:
        for bt in results[t]:
            n = len(bt.daily_pnl)
            bt.n_test = n
            bt.n_train = train_split
            if n < 5:
                continue

            pnl_arr = np.array(bt.daily_pnl)
            fwd_arr = np.array(getattr(bt, "forward_rets", []))
            act_arr = getattr(bt, "actions", [])
            conf_arr = np.array(getattr(bt, "confidences", []))

            bt.total_return = float(np.prod(1 + pnl_arr) - 1)
            bt.sharpe = compute_sharpe(pnl_arr)
            bt.max_drawdown = compute_max_drawdown(np.cumprod(1 + pnl_arr).tolist())
            bt.win_rate = compute_win_rate(pnl_arr)
            bt.profit_factor = compute_profit_factor(pnl_arr)
            bt.avg_forward_return = float(np.mean(fwd_arr)) if len(fwd_arr) > 0 else 0.0
            bt.avg_confidence = float(np.mean(conf_arr)) if len(conf_arr) > 0 else 0.0

            # Benchmark: buy & hold this ticker from split
            df_t = raw[t]
            split_idx = int(len(df_t) * TRAIN_PCT)
            bench_rets = []
            for j in range(split_idx, min(len(df_t) - 1, split_idx + n)):
                br = df_t.iloc[j + 1]["close"] / df_t.iloc[j]["close"] - 1
                bench_rets.append(br)
            if bench_rets:
                bench_rets = bench_rets[:n]
                bt.benchmark_daily = bench_rets
                bt.benchmark_return = float(np.prod(1 + np.array(bench_rets)) - 1)
                bt.benchmark_sharpe = compute_sharpe(np.array(bench_rets))
                bench_eq = np.cumprod(1 + np.array(bench_rets))
                bt.benchmark_max_dd = compute_max_drawdown(bench_eq.tolist())

            bt.alpha = bt.total_return - bt.benchmark_return
            bt.buy_signals = act_arr.count("BUY")
            bt.sell_signals = act_arr.count("SELL")
            bt.hold_signals = act_arr.count("HOLD")
            bt.total_signals = len(act_arr)

            if len(act_arr) == len(fwd_arr):
                correct = tp = fp = fn = 0
                for a, fr in zip(act_arr, fwd_arr):
                    if a == "BUY" and fr > 0 or a == "SELL" and fr < 0:
                        correct += 1
                        tp += 1
                    elif a in ("BUY", "SELL") and fr <= 0:
                        fp += 1
                        fn += 1
                non_hold = sum(1 for a in act_arr if a != "HOLD")
                bt.signal_accuracy = correct / non_hold if non_hold > 0 else 0.0
                bt.signal_precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
                bt.signal_recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
                bt.signal_f1 = (
                    2 * bt.signal_precision * bt.signal_recall / (bt.signal_precision + bt.signal_recall)
                    if (bt.signal_precision + bt.signal_recall) > 0 else 0.0
                )

            bt.valid = True

    return results


def _print_pooled_report(results: dict[str, list[ModelBacktest]]) -> None:
    sep = "=" * 95
    sep2 = "-" * 95

    for ticker, bt_list in results.items():
        valid = [bt for bt in bt_list if bt.valid]
        if not valid:
            continue
        print(f"\n{sep}")
        print(f"  Pooled Backtest — {ticker}")
        print(f"{sep}")
        print("  Strategy: long BUY, short SELL, flat HOLD")
        print(f"  Benchmark: buy & hold {ticker}")
        print(f"  Threshold: {OVERRIDE_THRESHOLD*100:.0f}% / {OVERRIDE_LOOKAHEAD}d lookahead")
        print(f"{sep2}\n")

        model_names = ["PooledXGB", "PooledLGB", "PooledCat"]
        lookup = {bt.model_name: bt for bt in valid}

        print(f"  {'Metric':<28} {'PooledXGB':<12} {'PooledLGB':<12} {'PooledCat':<12} {'Benchmark':<12}")
        print(sep2)

        rows = [
            ("OOS Return (%)", "total_return", 100, "{:+.2f}%%"),
            ("Sharpe Ratio", "sharpe", 1, "{:+.3f}"),
            ("Max Drawdown (%)", "max_drawdown", 100, "{:.2f}%%"),
            ("Win Rate (%)", "win_rate", 100, "{:.1f}%%"),
            ("Profit Factor", "profit_factor", 1, "{:.3f}"),
            ("Alpha (%)", "alpha", 100, "{:+.2f}%%"),
            ("Signal Accuracy (%)", "signal_accuracy", 100, "{:.1f}%%"),
        ]

        for label, attr, mul, _ in rows:
            parts = [f"  {label:<28}"]
            for m in model_names:
                r = lookup.get(m)
                if r is None:
                    parts.append(f"{'--':>10}")
                else:
                    val = getattr(r, attr, 0.0) * mul
                    if attr in ("total_return", "alpha"):
                        parts.append(f"{val:>+8.2f}%")
                    elif attr in ("max_drawdown", "win_rate", "signal_accuracy"):
                        parts.append(f"{val:>8.1f}%")
                    else:
                        parts.append(f"{val:>10.3f}")
            r0 = next(iter(lookup.values()), None)
            if r0 is not None:
                if attr == "total_return":
                    parts.append(f"{r0.benchmark_return * 100:>+8.2f}%")
                elif attr == "sharpe":
                    parts.append(f"{r0.benchmark_sharpe:>10.3f}")
                elif attr == "max_drawdown":
                    parts.append(f"{r0.benchmark_max_dd * 100:>8.1f}%")
                else:
                    parts.append(f"{'--':>10}")
            else:
                parts.append(f"{'--':>10}")
            print("  ".join(parts))

        print(sep2)
        parts = [f"  {'BUY / SELL / HOLD':<28}"]
        for m in model_names:
            r = lookup.get(m)
            if r is None:
                parts.append(f"{'--':>10}")
            else:
                parts.append(f"{r.buy_signals}/{r.sell_signals}/{r.hold_signals:<9}")
        parts.append(f"{'--':>10}")
        print("  ".join(parts))
        print()

    # Aggregate
    print("=" * 95)
    print("  POOLED AGGREGATE")
    print("=" * 95)
    model_names = ["PooledXGB", "PooledLGB", "PooledCat"]
    fields = ["total_return", "sharpe", "max_drawdown", "win_rate", "signal_accuracy"]
    agg: dict[str, dict[str, list[float]]] = {m: {f: [] for f in fields} for m in model_names}
    for ticker, bt_list in results.items():
        for bt in bt_list:
            if bt.valid and bt.model_name in agg:
                for f in fields:
                    agg[bt.model_name][f].append(getattr(bt, f, 0.0))

    print(sep2)
    print(f"  {'Metric':<28} {'PooledXGB':<12} {'PooledLGB':<12} {'PooledCat':<12}")
    print(sep2)
    for fname in fields:
        label = fname.replace("_", " ").title()
        parts = [f"  {label:<28}"]
        for m in model_names:
            vals = agg[m][fname]
            if vals:
                mean_val = np.mean(vals)
                if fname in ("total_return", "max_drawdown"):
                    parts.append(f"{mean_val * 100:>+8.2f}%")
                elif fname == "win_rate":
                    parts.append(f"{mean_val * 100:>8.1f}%")
                elif fname == "sharpe":
                    parts.append(f"{mean_val:>10.3f}")
                else:
                    parts.append(f"{mean_val * 100:>8.1f}%")
            else:
                parts.append(f"{'--':>10}")
        print("  ".join(parts))
    print(sep2)
    print()


# ── main ─────────────────────────────────────────────────────────────────────


def run_backtest(ticker: str, max_days: int = 504) -> list[ModelBacktest]:
    print(f"\n  Data: {ticker}")
    prices = fetch_prices(ticker, max_days=max_days)
    if len(prices) < 80:
        print(f"  SKIP: {len(prices)} prices (need 80+)")
        return []
    print(f"  Prices: {len(prices)} records ({prices.iloc[0]['date']} .. {prices.iloc[-1]['date']})")

    split = int(len(prices) * TRAIN_PCT)
    print(f"  Split: {split} train / {len(prices) - split} test")

    from src.analysis.ml.catboost_model import CatBoostClassifierModel
    from src.analysis.ml.ensemble import EnsemblePredictor
    from src.analysis.ml.lightgbm_model import LightGBMClassifier
    from src.analysis.ml.xgboost_model import XGBoostClassifier

    defs: list[tuple[str, Any]] = [
        ("XGBoost", XGBoostClassifier),
        ("LightGBM", LightGBMClassifier),
        ("CatBoost", CatBoostClassifierModel),
        ("Ensemble", EnsemblePredictor),
    ]

    results: list[ModelBacktest] = []

    for name, factory in defs:
        print(f"  {name}...", end=" ", flush=True)
        bt = backtest_model(
            model_name=name,
            model_factory=factory,
            df_full=prices,
            train_split=split,
            ticker=ticker,
        )
        if bt.valid:
            results.append(bt)
            print(f"return={bt.total_return:+.2%}  Sharpe={bt.sharpe:.2f}  "
                  f"Win={bt.win_rate:.1%}  Acc={bt.signal_accuracy:.1%}  "
                  f"Sigs={bt.buy_signals}b/{bt.sell_signals}s/{bt.hold_signals}h")
        else:
            print("SKIP (no predictions)")
        print()

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="ML Model Backtest Report")
    parser.add_argument("--ticker", default="SBER", help="Ticker to backtest")
    parser.add_argument("--days", type=int, default=504, help="Max days of history")
    parser.add_argument("--all", action="store_true", help="Run on top-5 liquid tickers")
    parser.add_argument("--threshold", type=float, default=OVERRIDE_THRESHOLD, help="Label threshold")
    parser.add_argument("--pooled", action="store_true", help="Run pooled training across all tickers")
    args = parser.parse_args()

    tickers = TICKERS_LIQUID if args.all else [args.ticker]
    thresh = args.threshold

    if args.pooled:
        with _override_ml_settings(
            threshold=thresh,
            lookahead=OVERRIDE_LOOKAHEAD,
            min_train_rows=20,
            min_predict_rows=30,
        ):
            pooled_tickers = TICKERS_LIQUID if len(tickers) < 2 else tickers
            print("=" * 95)
            print(f"  POOLED BACKTEST MODE — tickers: {pooled_tickers}")
            print("=" * 95)
            pooled_results = backtest_pooled(pooled_tickers, max_days=args.days)
            if pooled_results:
                _print_pooled_report(pooled_results)

                all_results = [bt for bt_list in pooled_results.values() for bt in bt_list if bt.valid]
                path = Path("tools/ml_backtest_report.json")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(
                        {
                            "generated_at": datetime.now(timezone.utc).isoformat(),
                            "mode": "pooled",
                            "seed": SEED,
                            "config": {
                                "threshold": thresh,
                                "lookahead": OVERRIDE_LOOKAHEAD,
                                "retrain_every": RETRAIN_EVERY,
                            },
                            "results": [bt.summary for bt in all_results],
                        },
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                print(f"  Results saved to: {path}")
        return

    with _override_ml_settings(
        threshold=thresh,
        lookahead=OVERRIDE_LOOKAHEAD,
        min_train_rows=20,
        min_predict_rows=30,
    ):
        all_data: dict[str, list[ModelBacktest]] = {}
        for ticker in tickers:
            try:
                res = run_backtest(ticker, max_days=args.days)
                if res:
                    all_data[ticker] = res
                    print_report(res, ticker)
            except Exception as e:
                logger.exception("Unhandled exception")
                print(f"  ERROR: {e}")

    if all_data:
        print("=" * 95)
        print(f"  AGGREGATE ({len(all_data)} ticker(s))")
        print("=" * 95)

        model_names = ["XGBoost", "LightGBM", "CatBoost", "Ensemble"]
        fields = ["total_return", "sharpe", "max_drawdown", "win_rate", "signal_accuracy"]

        agg: dict[str, dict[str, list[float]]] = {m: {f: [] for f in fields} for m in model_names}
        for ticker, results in all_data.items():
            for r in results:
                if r.valid and r.model_name in agg:
                    for f in fields:
                        agg[r.model_name][f].append(getattr(r, f, 0.0))

        sep2 = "-" * 95
        print(sep2)
        print(f"  {'Metric':<28} {'XGBoost':<12} {'LightGBM':<12} {'CatBoost':<12} {'Ensemble':<12}")
        print(sep2)
        for field in fields:
            label = field.replace("_", " ").title()
            parts = [f"  {label:<28}"]
            for m in model_names:
                vals = agg[m][field]
                if vals:
                    mean_val = np.mean(vals)
                    if field in ("total_return", "max_drawdown"):
                        parts.append(f"{mean_val * 100:>+8.2f}%")
                    elif field == "win_rate":
                        parts.append(f"{mean_val * 100:>8.1f}%")
                    elif field == "sharpe":
                        parts.append(f"{mean_val:>10.3f}")
                    else:
                        parts.append(f"{mean_val * 100:>8.1f}%")
                else:
                    parts.append(f"{'--':>10}")
            print("  ".join(parts))
        print(sep2)
        print()

        # Save JSON
        all_results = [r for rr in all_data.values() for r in rr if r.valid]
        path = Path("tools/ml_backtest_report.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "seed": SEED,
                    "config": {
                        "threshold": thresh,
                        "lookahead": OVERRIDE_LOOKAHEAD,
                        "train_pct": TRAIN_PCT,
                        "retrain_every": RETRAIN_EVERY,
                    },
                    "results": [r.summary for r in all_results],
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"  Results saved to: {path}")


if __name__ == "__main__":
    main()
