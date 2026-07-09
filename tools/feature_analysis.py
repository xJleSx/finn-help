"""Feature importance analysis for ML models.

Trains models on latest data and extracts built-in feature importance.
Usage:
    uv run python tools/feature_analysis.py SBER
    uv run python tools/feature_analysis.py --all --top 20
"""

import argparse
import sys
import warnings

import pandas as pd

from src.analysis.ml._base import BASE_FEATURE_COLS, MACRO_FEATURE_COLS, enrich_macro, prepare_features
from src.analysis.ml.walk_forward import build_labels, compute_threshold
from src.analysis.technical import TechnicalAnalyzer
from src.config import settings
from src.db.connection import get_session
from src.db.models import Instrument, Price

warnings.filterwarnings("ignore")

TICKERS_LIQUID = ["SBER", "GAZP", "LKOH", "VTBR", "MOEX"]
MACRO_FEATURE_COLS_ALL = list(MACRO_FEATURE_COLS)


def load_data(ticker: str, days: int = 1825) -> pd.DataFrame:
    db = get_session()
    try:
        inst = db.query(Instrument).filter_by(ticker=ticker).first()
        if not inst:
            return pd.DataFrame()
        rows = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date).limit(days).all()
        return pd.DataFrame([
            {"date": r.date, "open": float(r.open or 0), "high": float(r.high or 0),
             "low": float(r.low or 0), "close": float(r.close or 0), "volume": float(r.volume or 0)}
            for r in rows
        ])
    finally:
        db.close()


def analyze(ticker: str, top_n: int = 15):
    print(f"\n{'='*60}")
    print(f"  {ticker}")
    print(f"{'='*60}")

    df = load_data(ticker)
    if df.empty:
        print("  No data found")
        return

    tech = TechnicalAnalyzer()
    d = tech.compute_all(df)
    d = enrich_macro(d)
    features = prepare_features(d)
    cols = [c for c in features.columns if c in BASE_FEATURE_COLS or c in MACRO_FEATURE_COLS_ALL]
    features = features[cols].dropna()
    if features.empty:
        print("  No features after dropna")
        return

    threshold = compute_threshold(d["close"], fallback=settings.ml_threshold)
    y_raw, mask = build_labels(d["close"], lookahead=settings.ml_lookahead, threshold=threshold)
    n = min(len(features), len(y_raw))
    x, y = features.values[:n][mask[:n]], y_raw[:n][mask[:n]].astype(int)

    if len(x) < 50:
        print(f"  Too few samples: {len(x)}")
        return

    for name, make in [("XGBoost", lambda: __import__("xgboost").XGBClassifier(n_estimators=100, max_depth=4, random_state=42, verbosity=0)),
                        ("LightGBM", lambda: __import__("lightgbm").LGBMClassifier(n_estimators=100, max_depth=4, random_state=42, verbose=-1)),
                        ("CatBoost", lambda: __import__("catboost").CatBoostClassifier(n_estimators=100, max_depth=4, random_seed=42, verbose=0))]:
        try:
            model = make()
            model.fit(x, y)
            if hasattr(model, "feature_importances_"):
                imp = model.feature_importances_
            elif hasattr(model, "get_feature_importance"):
                imp = model.get_feature_importance()
            else:
                imp = model.booster_.feature_importance(importance_type="gain")
        except Exception as e:
            print(f"  {name}: error — {e}")
            continue

        ranked = sorted(zip(cols, imp), key=lambda x: -x[1])
        total = sum(imp)
        print(f"\n  [{name}]")
        print(f"  {'Rank':<5} {'Feature':<25} {'Importance':<10} {'Cumul%':<8}")
        print(f"  {'-'*48}")
        cumul = 0.0
        for i, (feat, val) in enumerate(ranked[:top_n]):
            cumul += val
            print(f"  {i+1:<5} {feat:<25} {val:<10.4f} {cumul/total*100:<8.1f}")
        print(f"  Top {top_n} explain: {cumul/total*100:.1f}%")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("ticker", nargs="?", help="Ticker")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--top", type=int, default=15)
    args = parser.parse_args()

    tickers = TICKERS_LIQUID if args.all else ([args.ticker] if args.ticker else [])
    if not tickers:
        print("Specify ticker or --all")
        sys.exit(1)

    for t in tickers:
        analyze(t, args.top)


if __name__ == "__main__":
    main()
