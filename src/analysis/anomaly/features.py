from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import func, select

from src.analysis.ml.news_impact_features import ALL_FEATURE_COLS
from src.analysis.ml.news_impact_features import extract_features as extract_impact_features
from src.config import settings
from src.db.models import Instrument, News, NewsInstrument


def article_counts_per_day(
    db: Any, ticker: str, days_back: int | None = None
) -> pd.DataFrame:
    days = days_back or settings.ml_anomaly_days_back
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.execute(
            select(
                func.date(News.published_at).label("day"),
                func.count(News.id).label("count"),
            )
            .join(NewsInstrument, NewsInstrument.news_id == News.id)
            .join(Instrument, Instrument.id == NewsInstrument.instrument_id)
            .where(News.published_at >= cutoff)
            .where(Instrument.ticker == ticker)
            .group_by(func.date(News.published_at))
            .order_by(func.date(News.published_at))
        )
        .mappings()
        .all()
    )
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["day", "count"])
    df = df.set_index("day")
    full_idx = pd.date_range(df.index.min(), df.index.max(), freq="D")
    df = df.reindex(full_idx, fill_value=0)
    df.index.name = "day"
    return df


def rolling_volume_features(
    db: Any, ticker: str, days_back: int | None = None
) -> pd.DataFrame:
    days = days_back or settings.ml_anomaly_days_back
    df = article_counts_per_day(db, ticker, days)
    if df.empty or len(df) < 5:
        return pd.DataFrame()
    windows = [int(w) for w in settings.ml_anomaly_window_sizes.split(",")]
    for w in windows:
        df[f"vol_ma_{w}d"] = df["count"].rolling(w, min_periods=1).mean()
        df[f"vol_std_{w}d"] = df["count"].rolling(w, min_periods=1).std().fillna(0)
    df["vol_zscore_7d"] = (df["count"] - df["vol_ma_7d"]) / df["vol_std_7d"].replace(0, 1)
    df = df.fillna(0)
    return df


def sentiment_features_per_day(
    db: Any, ticker: str, days_back: int | None = None
) -> pd.DataFrame:
    days = days_back or settings.ml_anomaly_days_back
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.execute(
            select(
                func.date(News.published_at).label("day"),
                func.avg(News.sentiment_score).label("avg_score"),
                func.count(News.id).label("count"),
            )
            .join(NewsInstrument, NewsInstrument.news_id == News.id)
            .join(Instrument, Instrument.id == NewsInstrument.instrument_id)
            .where(News.published_at >= cutoff)
            .where(Instrument.ticker == ticker)
            .group_by(func.date(News.published_at))
            .order_by(func.date(News.published_at))
        )
        .mappings()
        .all()
    )
    records = []
    for r in rows:
        records.append(
            {
                "day": r["day"],
                "sentiment_mean": float(r["avg_score"] or 0.0),
                "article_count": int(r["count"]),
            }
        )
    df = pd.DataFrame(records)
    if df.empty:
        return pd.DataFrame(columns=["day", "sentiment_mean", "article_count"])
    df = df.set_index("day")
    full_idx = pd.date_range(df.index.min(), df.index.max(), freq="D")
    df = df.reindex(full_idx).fillna(0)
    df.index.name = "day"

    windows = [int(w) for w in settings.ml_anomaly_window_sizes.split(",")]
    for w in windows:
        df[f"sent_ma_{w}d"] = df["sentiment_mean"].rolling(w, min_periods=1).mean()
        df[f"sent_std_{w}d"] = (
            df["sentiment_mean"].rolling(w, min_periods=1).std().fillna(0)
        )
    df["sent_change_1d"] = df["sentiment_mean"].diff().fillna(0)
    df["sent_change_3d"] = df["sentiment_mean"].diff(3).fillna(0)
    df = df.fillna(0)
    return df


def source_frequencies(
    db: Any, category: str | None = None
) -> dict[str, dict[str, float]]:
    query = select(News.source_name, News.category, func.count(News.id).label("cnt"))
    if category:
        query = query.where(News.category == category)
    query = query.group_by(News.source_name, News.category)
    rows = db.execute(query).mappings().all()

    cat_total: dict[str, int] = Counter()
    source_cat: dict[str, dict[str, int]] = defaultdict(Counter)
    for r in rows:
        src = r["source_name"] or "unknown"
        cat = r["category"] or "UNCLASSIFIED"
        source_cat[src][cat] += int(r["cnt"])
        cat_total[cat] += int(r["cnt"])

    result: dict[str, dict[str, float]] = {}
    for src, cats in source_cat.items():
        result[src] = {}
        total = sum(cats.values())
        for cat, cnt in cats.items():
            expected = cat_total[cat] * total / max(sum(cat_total.values()), 1)
            result[src][cat] = cnt / max(expected, 1)
    return result


def topic_frequencies(db: Any) -> dict[str, dict[tuple[str, str], int]]:
    query = (
        select(
            Instrument.ticker,
            News.category,
            News.subcategory,
            func.count(News.id).label("cnt"),
        )
        .join(NewsInstrument, NewsInstrument.news_id == News.id)
        .join(Instrument, Instrument.id == NewsInstrument.instrument_id)
        .group_by(Instrument.ticker, News.category, News.subcategory)
    )
    rows = db.execute(query).mappings().all()
    result: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        ticker = r["ticker"]
        topic: tuple[str, str] = (
            r["category"] or "UNCLASSIFIED",
            r["subcategory"] or "GENERAL",
        )
        result[ticker][topic] += int(r["cnt"])
    return dict(result)


def build_anomaly_feature_vector(db: Any, news_article: News) -> np.ndarray:
    impact_features = extract_impact_features(db, news_article)
    vec = np.array(
        [impact_features.get(c, 0.0) for c in ALL_FEATURE_COLS], dtype=np.float32
    )
    return vec
