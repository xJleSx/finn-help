import logging
from datetime import datetime, timedelta, timezone
from statistics import mean, stdev
from typing import Any, cast

from src.db.connection import get_session
from src.db.models import SentimentSignal

logger = logging.getLogger(__name__)


def _time_weight(dt: object, now: datetime, half_life_days: float = 3.0) -> float:
    if not isinstance(dt, datetime):
        return 0.1
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age = (now - dt).total_seconds() / 86400.0
    result: Any = 2.0 ** (-age / half_life_days)
    return cast(float, result)


def _calc_divergence(scores: list[float]) -> float:
    if len(scores) < 2:
        return 0.0
    try:
        sd = stdev(scores)
    except Exception:
        return 0.0
    return min(sd * 1.5, 1.0)


def _empty_result() -> dict[str, Any]:
    return {"score": 0.0, "divergence": 0.0, "source": "social", "count": 0}


class SocialAggregator:
    def get_ticker_sentiment(self, ticker: str, days: int = 7) -> dict[str, Any]:
        db = get_session()
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            rows: list[SentimentSignal] = (
                db.query(SentimentSignal)
                .filter(
                    SentimentSignal.ticker == ticker.upper(),
                    SentimentSignal.created_at >= cutoff,
                )
                .order_by(SentimentSignal.created_at)
                .all()
            )
            return self._aggregate(rows)
        finally:
            db.close()

    def get_all_ticker_sentiments(
        self, tickers: list[str], days: int = 7
    ) -> dict[str, dict[str, Any]]:
        if not tickers:
            return {}
        db = get_session()
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            rows: list[SentimentSignal] = (
                db.query(SentimentSignal)
                .filter(
                    SentimentSignal.ticker.in_([t.upper() for t in tickers]),
                    SentimentSignal.created_at >= cutoff,
                )
                .all()
            )
            by_ticker: dict[str, list[SentimentSignal]] = {}
            for r in rows:
                t = str(r.ticker or "")
                if t:
                    by_ticker.setdefault(t, []).append(r)

            result: dict[str, dict[str, Any]] = {}
            for t in tickers:
                upper = t.upper()
                result[upper] = self._aggregate(by_ticker.get(upper, []))
            return result
        finally:
            db.close()

    def get_market_overview(self, days: int = 1) -> list[dict[str, Any]]:
        db = get_session()
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            rows: list[SentimentSignal] = (
                db.query(SentimentSignal).filter(SentimentSignal.created_at >= cutoff).all()
            )
            if not rows:
                return []

            now = datetime.now(timezone.utc)
            by_ticker: dict[str, list[float]] = {}
            by_ticker_w: dict[str, list[float]] = {}
            for r in rows:
                t = str(r.ticker or "__market__")
                s = float(r.composite_score) if r.composite_score is not None else 0.0
                c = float(r.confidence) if r.confidence is not None else 0.0
                tw = _time_weight(r.created_at, now)
                w = tw * c
                by_ticker.setdefault(t, []).append(s)
                by_ticker_w.setdefault(t, []).append(w)

            overview = []
            for ticker, scores_list in sorted(by_ticker.items(), key=lambda x: -len(x[1])):
                w_list = by_ticker_w[ticker]
                total_w = sum(w_list)
                if total_w > 0:
                    avg_s = sum(s * w for s, w in zip(scores_list, w_list)) / total_w
                else:
                    avg_s = mean(scores_list) if scores_list else 0.0
                overview.append({
                    "ticker": None if ticker == "__market__" else ticker,
                    "avg_score": round(max(-1.0, min(1.0, avg_s)), 4),
                    "volume": len(scores_list),
                })
            return overview
        finally:
            db.close()

    @staticmethod
    def _aggregate(rows: list[SentimentSignal]) -> dict[str, Any]:
        if not rows:
            return _empty_result()

        now = datetime.now(timezone.utc)
        scores: list[float] = []
        confs: list[float] = []
        weights: list[float] = []

        for r in rows:
            s = float(r.composite_score) if r.composite_score is not None else 0.0
            c = float(r.confidence) if r.confidence is not None else 0.0
            w = _time_weight(r.created_at, now) * c * float(r.source_weight or 0.45)
            scores.append(s)
            confs.append(c)
            weights.append(w)

        total_w = sum(weights)
        if total_w > 0:
            weighted_score = sum(s * w for s, w in zip(scores, weights)) / total_w
            avg_conf = sum(c * w for c, w in zip(confs, weights)) / total_w
        else:
            weighted_score = mean(scores) if scores else 0.0
            avg_conf = mean(confs) if confs else 0.0

        return {
            "score": round(max(-1.0, min(1.0, weighted_score)), 4),
            "divergence": round(min(_calc_divergence(scores), 1.0), 4),
            "source": "social",
            "count": len(rows),
            "avg_confidence": round(avg_conf, 4),
        }


aggregator = SocialAggregator()
