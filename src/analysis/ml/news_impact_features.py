from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import numpy as np
import pandas as pd

from src.config import settings
from src.db.models import Instrument, News, NewsInstrument, Price

logger = logging.getLogger(__name__)

CATEGORY_VALUES = ["MACRO", "GEOPOLITICAL", "SECTOR", "COMPANY", "MARKET"]
SUBCATEGORY_VALUES = [
    "sanctions", "conflict", "earnings", "merger_acquisition",
    "monetary_policy", "inflation", "energy", "banking",
]

NEWS_FEATURE_COLS = [
    "sentiment_score", "impact_score", "source_weight", "source_count",
    "sentiment_positive", "sentiment_negative",
]
for c in CATEGORY_VALUES:
    NEWS_FEATURE_COLS.append(f"cat_{c}")
for s in SUBCATEGORY_VALUES:
    NEWS_FEATURE_COLS.append(f"subcat_{s}")
NEWS_FEATURE_COLS += ["hour_of_day", "day_of_week"]

MARKET_FEATURE_COLS = [
    "return_5d_before", "volatility_20d", "volume_change_5d",
]

ALL_FEATURE_COLS = NEWS_FEATURE_COLS + MARKET_FEATURE_COLS


def extract_features(
    db: Any, news_article: News, days_market: int = 30,
) -> dict[str, float]:
    ts = news_article.published_at or news_article.created_at or datetime.now(timezone.utc)
    score = float(news_article.sentiment_score or 0.0)

    features: dict[str, float] = {
        "sentiment_score": score,
        "impact_score": float(news_article.impact_score or 0.0),
        "source_weight": float(news_article.source_weight or 0.5),
        "source_count": float(news_article.source_count or 1),
        "sentiment_positive": 1.0 if news_article.sentiment == "positive" else 0.0,
        "sentiment_negative": 1.0 if news_article.sentiment == "negative" else 0.0,
        "hour_of_day": float(ts.hour),
        "day_of_week": float(ts.weekday()),
    }
    cat = news_article.category or "MACRO"
    for c in CATEGORY_VALUES:
        features[f"cat_{c}"] = 1.0 if cat == c else 0.0
    sub = news_article.subcategory or ""
    for s in SUBCATEGORY_VALUES:
        features[f"subcat_{s}"] = 1.0 if sub == s else 0.0

    linked = (
        db.query(NewsInstrument)
        .filter(NewsInstrument.news_id == news_article.id)
        .first()
    )
    if linked:
        mkt = _market_features(db, linked.instrument_id, ts, days_market)
        features.update(mkt)
    else:
        for c in MARKET_FEATURE_COLS:
            features.setdefault(c, 0.0)

    return features


def _market_features(
    db: Any, instrument_id: int, before: datetime, days: int,
) -> dict[str, float]:
    cutoff = before - timedelta(days=days)
    prices = (
        db.query(Price)
        .filter(
            Price.instrument_id == instrument_id,
            Price.date >= cutoff.date(),
            Price.date < before.date(),
        )
        .order_by(Price.date)
        .all()
    )
    result: dict[str, float] = {c: 0.0 for c in MARKET_FEATURE_COLS}
    if len(prices) < 5:
        return result

    closes = np.array([float(p.close) for p in prices if p.close], dtype=float)
    if len(closes) < 5:
        return result

    returns = np.where(closes[:-1] != 0, np.diff(closes) / closes[:-1], 0.0)
    ret_5d = float(closes[-1] / closes[max(0, len(closes) - 6)] - 1) if len(closes) > 5 else 0.0
    vol_20d = float(np.std(returns) * np.sqrt(252)) if len(returns) > 1 else 0.0

    volumes = np.array([float(p.volume or 0) for p in prices if p.volume], dtype=float)
    vol_change = 0.0
    if len(volumes) >= 10:
        recent = float(np.mean(volumes[-5:]))
        prior = float(np.mean(volumes[-10:-5]))
        vol_change = recent / max(prior, 1.0) - 1.0 if prior > 0 else 0.0

    result["return_5d_before"] = round(ret_5d, 4)
    result["volatility_20d"] = round(min(vol_20d, 10.0), 4)
    result["volume_change_5d"] = round(vol_change, 4)
    return result


def forward_return(
    db: Any, instrument_id: int, after: datetime, days: int,
) -> float:
    start = after.date()
    end = start + timedelta(days=days + 1)

    p0 = (
        db.query(Price)
        .filter(Price.instrument_id == instrument_id, Price.date >= start)
        .order_by(Price.date)
        .first()
    )
    p1 = (
        db.query(Price)
        .filter(
            Price.instrument_id == instrument_id,
            Price.date >= start + timedelta(days=max(1, days)),
            Price.date <= end,
        )
        .order_by(Price.date)
        .first()
    )
    if not p0 or not p1 or not p0.close or not p1.close or p0.close <= 0:
        return 0.0
    return float((p1.close - p0.close) / p0.close)


def build_training_data(
    db: Any, ticker: str,
    max_articles: int = 500, days_back: Optional[int] = None,
) -> pd.DataFrame:
    if days_back is None:
        days_back = settings.ml_impact_days_back
    horizons = sorted(int(h) for h in settings.ml_impact_horizons.split(","))

    instrument = db.query(Instrument).filter_by(ticker=ticker.upper()).first()
    if not instrument:
        return pd.DataFrame()

    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    articles = (
        db.query(News)
        .join(NewsInstrument, NewsInstrument.news_id == News.id)
        .filter(
            NewsInstrument.instrument_id == instrument.id,
            News.is_relevant,
            News.published_at >= cutoff,
        )
        .order_by(News.published_at.desc())
        .limit(max_articles)
        .all()
    )
    if not articles:
        return pd.DataFrame()

    rows = []
    for article in articles:
        feat = extract_features(db, article)
        for h in horizons:
            ret = forward_return(db, instrument.id, article.published_at or article.created_at, h)
            feat[f"return_{h}d"] = ret
        rows.append(feat)

    return pd.DataFrame(rows)
