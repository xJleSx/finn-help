#!/usr/bin/env python3
"""Validate technical scoring thresholds via walk-forward on real MOEX + synthetic data.

Usage:
  uv run python tools/validate_technical_thresholds.py
"""

import itertools
import json
import logging
import sys
import time
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.analysis.ml.walk_forward import temporal_split
from src.analysis.technical import TechnicalAnalyzer

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

CANDIDATE_THRESHOLDS = [round(t, 2) for t in np.arange(0.05, 0.55, 0.05)]
LOOKAHEAD = 5
MIN_ROWS = 100
MOEX_TICKERS = ["SBER", "GAZP", "LKOH", "VTBR", "MOEX", "NLMK", "MGNT", "TATN", "SNGS", "ROSN"]


def fetch_moex_data(ticker: str, days: int = 730) -> list[float] | None:
    url = (
        f"https://iss.moex.com/iss/engines/stock/markets/shares/securities/"
        f"{ticker}/candles.json?interval=24&limit={days}"
    )
    try:
        r = httpx.get(url, timeout=15)
        if r.status_code != 200:
            return None
        data = r.json()
        candles = data.get("candles", {}).get("data", [])
        if not candles:
            return None
        closes = [row[1] for row in candles if row[1] is not None]
        return closes if len(closes) >= MIN_ROWS else None
    except Exception:
        return None


def generate_scenarios(n: int = 500) -> dict[str, list[float]]:
    rng = np.random.default_rng(42)
    scenarios = {}

    trend = 100.0
    prices = []
    for _ in range(n):
        trend *= 1 + rng.normal(0.0006, 0.015)
        prices.append(trend)
    scenarios["uptrend"] = prices

    trend = 100.0
    prices = []
    for _ in range(n):
        trend *= 1 + rng.normal(-0.0006, 0.015)
        prices.append(trend)
    scenarios["downtrend"] = prices

    prices = [100.0]
    for _ in range(n - 1):
        reversion = (100.0 - prices[-1]) * 0.03
        prices.append(prices[-1] + reversion + rng.normal(0, 0.02) * prices[-1])
    scenarios["mean_reverting"] = prices

    prices = [100.0]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + rng.normal(0, 0.04)))
    scenarios["high_vol"] = prices

    prices = [100.0]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + rng.normal(0, 0.008)))
    scenarios["sideways"] = prices

    trend = 100.0
    prices = []
    for i in range(n):
        if i < 150:
            trend *= 1 + rng.normal(0.001, 0.012)
        elif i < 300:
            trend *= 1 + rng.normal(0.0001, 0.008)
        else:
            trend *= 1 + rng.normal(0.001, 0.012)
        prices.append(trend)
    scenarios["bull_flag"] = prices

    trend = 100.0
    prices = []
    for i in range(n):
        if 200 <= i <= 220:
            trend *= 1 + rng.normal(-0.03, 0.03)
        elif 221 <= i <= 280:
            trend *= 1 + rng.normal(0.005, 0.02)
        else:
            trend *= 1 + rng.normal(0.0003, 0.012)
        prices.append(trend)
    scenarios["crash_recovery"] = prices

    return scenarios


def make_df(prices: list[float]) -> pd.DataFrame:
    n = len(prices)
    return pd.DataFrame({
        "date": pd.date_range("2020-01-01", periods=n),
        "open": prices, "high": [c * 1.015 for c in prices],
        "low": [c * 0.985 for c in prices],
        "close": prices, "volume": [1_000_000] * n,
    })


def compute_scores(analyzer: TechnicalAnalyzer, df: pd.DataFrame) -> np.ndarray:
    scores = []
    for i in range(len(df)):
        sig = analyzer.generate_signal(df.iloc[: i + 1])
        scores.append(sig.get("score", 0.0))
    return np.array(scores)


def evaluate_threshold(scores: np.ndarray, close: np.ndarray, buy_th: float) -> dict:
    sell_th = -buy_th
    future_returns = np.full(len(close), np.nan)
    future_returns[:-LOOKAHEAD] = close[LOOKAHEAD:] / close[:-LOOKAHEAD] - 1

    valid = ~np.isnan(future_returns)
    s, f = scores[valid], future_returns[valid]
    if len(s) < MIN_ROWS:
        return {"n_signals": 0, "accuracy": 0.5, "avg_return": 0.0, "sharpe": 0.0, "win_rate": 0.0, "buy_pct": 0.0, "sell_pct": 0.0}

    actions = np.where(s > buy_th, 1, np.where(s < sell_th, 0, np.nan))
    pos = ~np.isnan(actions)
    if pos.sum() < 10:
        return {"n_signals": int(pos.sum()), "accuracy": 0.5, "avg_return": 0.0, "sharpe": 0.0, "win_rate": 0.0, "buy_pct": float((s > buy_th).mean()), "sell_pct": float((s < sell_th).mean())}

    a, f_pos = actions[pos], f[pos]
    correct = ((a == 1) & (f_pos > 0)) | ((a == 0) & (f_pos < 0))
    accuracy = float(correct.mean())
    buy_mask = a == 1
    wins = ((f_pos > 0) & buy_mask).sum()
    win_rate = wins / buy_mask.sum() if buy_mask.sum() > 0 else 0.0
    avg_ret = float(f_pos.mean())
    std = float(f_pos.std())
    sharpe = avg_ret / std if std > 0 else 0.0

    return {
        "n_signals": int(pos.sum()),
        "accuracy": round(accuracy, 4),
        "avg_return": round(avg_ret, 6),
        "sharpe": round(sharpe, 4),
        "win_rate": round(win_rate, 4),
        "buy_pct": round(float((s > buy_th).mean()), 4),
        "sell_pct": round(float((s < sell_th).mean()), 4),
    }


def walk_forward(scores: np.ndarray, close: np.ndarray, buy_th: float) -> dict:
    sell_th = -buy_th
    future_returns = np.full(len(close), np.nan)
    future_returns[:-LOOKAHEAD] = close[LOOKAHEAD:] / close[:-LOOKAHEAD] - 1

    valid = ~np.isnan(future_returns)
    s, f = scores[valid], future_returns[valid]
    if len(s) < MIN_ROWS:
        return {"fold_accuracy": [], "folds": 0, "avg_acc": 0.5}

    splits = temporal_split(len(s))
    results = []
    for name, sl in [("val", splits["val"]), ("test", splits["test"])]:
        if sl.stop <= sl.start or sl.start >= len(s):
            continue
        test_f = f[sl]
        test_s = s[sl]
        test_a = np.where(test_s > buy_th, 1, np.where(test_s < sell_th, 0, np.nan))
        pos = ~np.isnan(test_a)
        if pos.sum() < 5:
            continue
        correct = ((test_a[pos] == 1) & (test_f[pos] > 0)) | ((test_a[pos] == 0) & (test_f[pos] < 0))
        results.append({"fold": name, "accuracy": float(correct.mean()), "n": int(pos.sum())})

    if not results:
        return {"fold_accuracy": [], "folds": 0, "avg_acc": 0.5}
    accs = [r["accuracy"] for r in results]
    return {"fold_accuracy": results, "folds": len(results), "avg_acc": round(float(np.mean(accs)), 4)}


def run():
    logger.info("=" * 70)
    logger.info("TECHNICAL SCORING THRESHOLD VALIDATION")
    logger.info(f"Candidates: {CANDIDATE_THRESHOLDS}")
    logger.info(f"Lookahead: {LOOKAHEAD}d")
    logger.info("=" * 70)

    analyzer = TechnicalAnalyzer()

    # ── Collect data ──
    all_scenarios: dict[str, list[float]] = {}

    logger.info("\n--- FETCHING REAL MOEX DATA ---")
    for ticker in MOEX_TICKERS:
        prices = fetch_moex_data(ticker)
        if prices:
            all_scenarios[ticker] = prices
            logger.info(f"  {ticker}: {len(prices)} days OK")
        else:
            logger.info(f"  {ticker}: FAILED")
        time.sleep(0.3)

    logger.info(f"\n--- GENERATING SYNTHETIC SCENARIOS ---")
    synthetic = generate_scenarios()
    for name, prices in synthetic.items():
        all_scenarios[f"synth_{name}"] = prices
    logger.info(f"  {len(synthetic)} synthetic scenarios")

    logger.info(f"\nTotal scenarios: {len(all_scenarios)}")

    # ── Evaluate all thresholds ──
    all_results: list[dict] = []

    for sc_name, raw_prices in all_scenarios.items():
        df = make_df(raw_prices)
        df = analyzer.compute_all(df)
        scores = compute_scores(analyzer, df)
        close = df["close"].values

        for buy_th in CANDIDATE_THRESHOLDS:
            ev = evaluate_threshold(scores, close, buy_th)
            wf = walk_forward(scores, close, buy_th)
            all_results.append({
                "scenario": sc_name,
                "threshold": buy_th,
                "n_data": len(raw_prices),
                **ev,
                "wf_avg_acc": wf["avg_acc"],
                "wf_folds": wf["folds"],
            })

    results_df = pd.DataFrame(all_results)

    # ── Real vs synthetic metrics ──
    results_df["data_type"] = results_df["scenario"].apply(
        lambda x: "real" if x in MOEX_TICKERS else "synthetic"
    )

    # ── Summary ──
    logger.info(f"\n{'=' * 70}")
    logger.info("BEST THRESHOLD PER SCENARIO (by OOS accuracy)")
    logger.info(f"{'=' * 70}")

    best_rows = []
    for sc_name in all_scenarios:
        sc = results_df[results_df["scenario"] == sc_name]
        best = sc.loc[sc["wf_avg_acc"].idxmax()]
        best_rows.append(best)
        logger.info(
            f"  {sc_name:18s} th={best['threshold']:.2f}  "
            f"OOS={best['wf_avg_acc']:.3f}  acc={best['accuracy']:.3f}  "
            f"wr={best['win_rate']:.3f}  signals={int(best['n_signals'])}"
        )

    # ── Overall ranking (real data only, weighted by OOS folds) ──
    logger.info(f"\n{'=' * 70}")
    logger.info("OVERALL RANKING — REAL DATA ONLY")
    logger.info(f"{'=' * 70}")

    real = results_df[results_df["data_type"] == "real"]
    if len(real) > 0:
        real_rank = real.groupby("threshold").agg(
            avg_oos=("wf_avg_acc", "mean"),
            avg_acc=("accuracy", "mean"),
            avg_wr=("win_rate", "mean"),
            total_signals=("n_signals", "sum"),
            n_scenarios=("scenario", "nunique"),
        ).reset_index().sort_values("avg_oos", ascending=False)

        for _, r in real_rank.iterrows():
            logger.info(
                f"  th={r['threshold']:.2f}  OOS={r['avg_oos']:.3f}  "
                f"acc={r['avg_acc']:.3f}  wr={r['avg_wr']:.3f}  "
                f"signals={int(r['total_signals'])}  scenarios={int(r['n_scenarios'])}"
            )

        best_real = real_rank.iloc[0]
        logger.info(f"\n  >>> Best on REAL data: th={best_real['threshold']:.2f} "
                     f"(OOS={best_real['avg_oos']:.3f})")
    else:
        best_real = None

    # ── Overall ranking (all data) ──
    logger.info(f"\n{'=' * 70}")
    logger.info("OVERALL RANKING — ALL DATA")
    logger.info(f"{'=' * 70}")

    all_rank = results_df.groupby("threshold").agg(
        avg_oos=("wf_avg_acc", "mean"),
        avg_acc=("accuracy", "mean"),
        avg_wr=("win_rate", "mean"),
        total_signals=("n_signals", "sum"),
    ).reset_index().sort_values("avg_oos", ascending=False)

    for _, r in all_rank.iterrows():
        logger.info(
            f"  th={r['threshold']:.2f}  OOS={r['avg_oos']:.3f}  "
            f"acc={r['avg_acc']:.3f}  wr={r['avg_wr']:.3f}  "
            f"signals={int(r['total_signals'])}"
        )

    best_all = all_rank.iloc[0]

    # ── Consensus ──
    logger.info(f"\n{'=' * 70}")
    logger.info("CONSENSUS ANALYSIS")
    logger.info(f"{'=' * 70}")

    best_df = pd.DataFrame(best_rows)
    vote_counts = best_df["threshold"].value_counts().sort_index()
    for th, count in vote_counts.items():
        logger.info(f"  threshold {th:.2f}: {count} scenario(s) prefer this")
    consensus_th = vote_counts.idxmax() if len(vote_counts) > 0 else 0.30
    logger.info(f"\n  Consensus: {consensus_th:.2f} ({int(vote_counts[consensus_th])}/{len(best_rows)} scenarios)")

    # ── Current threshold evaluation ──
    logger.info(f"\n{'=' * 70}")
    logger.info("CURRENT THRESHOLD (0.30) ON REAL DATA")
    logger.info(f"{'=' * 70}")
    if len(real) > 0:
        cur = real[real["threshold"] == 0.30]
        if len(cur) > 0:
            cur_agg = cur.groupby("scenario").first().reset_index()
            logger.info(f"  Avg OOS:   {cur['wf_avg_acc'].mean():.3f}")
            logger.info(f"  Avg Acc:   {cur['accuracy'].mean():.3f}")
            logger.info(f"  Avg WinR:  {cur['win_rate'].mean():.3f}")
            logger.info(f"  Avg Signals: {cur['n_signals'].mean():.0f}")
            for _, r in cur_agg.iterrows():
                logger.info(f"    {r['scenario']:6s}: OOS={r['wf_avg_acc']:.3f} "
                             f"acc={r['accuracy']:.3f} wr={r['win_rate']:.3f} "
                             f"sig={int(r['n_signals'])}")
        else:
            logger.info("  Not evaluated on real data")

    # ── Recommendation ──
    logger.info(f"\n{'=' * 70}")
    recommended = best_real["threshold"] if best_real is not None else best_all["threshold"]
    # Sanity check: prefer threshold in [0.15, 0.40] range for practical balance
    if recommended < 0.15:
        close_alternatives = all_rank[all_rank["threshold"] >= 0.15].head(3)
        if len(close_alternatives) > 0:
            rec2 = close_alternatives.iloc[0]
            logger.info(f"  Note: best ({recommended:.2f}) is very low -> high signal count")
            logger.info(f"  Practical alternative: th={rec2['threshold']:.2f} "
                         f"(OOS={rec2['avg_oos']:.3f})")
            recommended = rec2["threshold"]
    if recommended > 0.45:
        close_alternatives = all_rank[all_rank["threshold"] <= 0.40].head(3)
        if len(close_alternatives) > 0:
            rec2 = close_alternatives.iloc[0]
            logger.info(f"  Note: best ({recommended:.2f}) is very high -> very few signals")
            logger.info(f"  Practical alternative: th={rec2['threshold']:.2f} "
                         f"(OOS={rec2['avg_oos']:.3f})")
            recommendation = rec2["threshold"]
        else:
            recommendation = recommended
    else:
        recommendation = recommended

    logger.info(f"\n>>> FINAL RECOMMENDATION: threshold = {recommendation:.2f}")
    logger.info(f"{'=' * 70}")

    # ── Save results ──
    out = Path(__file__).resolve().parent / "technical_threshold_validation.json"
    results_df.to_json(out, orient="records", indent=2)
    logger.info(f"\nFull results saved to {out}")

    return float(recommendation)


if __name__ == "__main__":
    run()
