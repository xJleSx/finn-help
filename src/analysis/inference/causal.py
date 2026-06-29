from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from src.db.models import Instrument, News, NewsInstrument, Price

logger = logging.getLogger(__name__)

try:
    from statsmodels.tsa.stattools import grangercausalitytests
    _HAS_STATSMODELS = True
except ImportError:
    _HAS_STATSMODELS = False

_DEFAULT_MAX_LAG = 10


class GrangerCausality:
    """Test whether news sentiment Granger-causes price returns."""

    def __init__(self, max_lag: int = _DEFAULT_MAX_LAG):
        self.max_lag = max_lag

    def test_news_sentiment_impact(self, ticker: str, db_session: Any) -> dict[str, Any]:
        if not _HAS_STATSMODELS:
            return {"available": False}

        instrument = db_session.query(Instrument).filter(Instrument.ticker == ticker.upper()).first()
        if not instrument:
            return {"ticker": ticker, "error": "Instrument not found"}

        prices = (
            db_session.query(Price)
            .filter(Price.instrument_id == instrument.id, Price.close.isnot(None))
            .order_by(Price.date.asc())
            .all()
        )
        if len(prices) < self.max_lag + 5:
            return {"ticker": ticker, "error": "Not enough price data"}

        price_map = {p.date: p.close for p in prices}
        dates = sorted(price_map.keys())
        returns: dict[Any, float] = {}
        for i in range(1, len(dates)):
            prev, cur = price_map[dates[i - 1]], price_map[dates[i]]
            if prev and prev != 0:
                returns[dates[i]] = (cur - prev) / prev

        news_list = (
            db_session.query(News)
            .join(NewsInstrument)
            .filter(NewsInstrument.instrument_id == instrument.id, News.sentiment_score.isnot(None))
            .order_by(News.published_at.asc())
            .all()
        )

        daily_sentiment: dict[Any, list[float]] = {}
        for n in news_list:
            if n.published_at is not None:
                day = n.published_at.date()
                daily_sentiment.setdefault(day, []).append(n.sentiment_score)

        common = sorted(set(returns.keys()) & set(daily_sentiment.keys()))
        if len(common) < self.max_lag + 5:
            return {"ticker": ticker, "error": "Not enough overlapping data"}

        sentiment_series = [float(np.mean(daily_sentiment[d])) for d in common]
        return_series = [returns[d] for d in common]
        data = np.column_stack([return_series, sentiment_series])

        try:
            result = grangercausalitytests(data, maxlag=self.max_lag, verbose=False)
        except Exception as exc:
            return {"ticker": ticker, "error": str(exc)}

        best_lag = 1
        best_pvalue = 1.0
        for lag in range(1, self.max_lag + 1):
            if lag in result:
                pval = result[lag][0]["ssr_chi2test"][1]
                if pval < best_pvalue:
                    best_pvalue = pval
                    best_lag = lag

        return {
            "ticker": ticker,
            "lags_tested": self.max_lag,
            "best_lag": best_lag,
            "best_pvalue": round(float(best_pvalue), 6),
            "causal_direction": "sentiment -> returns",
            "significant": bool(best_pvalue < 0.05),
        }


class CausalImpactAnalyzer:
    """Simple before/after causal impact estimation with synthetic control."""

    def estimate_impact(
        self, ticker: str, event_date: datetime, db_session: Any, window_days: int = 30
    ) -> dict[str, Any]:
        if isinstance(event_date, datetime):
            event_date_only = event_date.date()
        else:
            event_date_only = event_date

        instrument = db_session.query(Instrument).filter(Instrument.ticker == ticker.upper()).first()
        if not instrument:
            return {"ticker": ticker, "event_date": str(event_date_only), "error": "Instrument not found"}

        before_end = event_date_only - timedelta(days=1)
        before_start = event_date_only - timedelta(days=window_days)
        after_start = event_date_only + timedelta(days=1)
        after_end = event_date_only + timedelta(days=window_days)

        before_prices = (
            db_session.query(Price)
            .filter(
                Price.instrument_id == instrument.id,
                Price.date >= before_start,
                Price.date <= before_end,
                Price.close.isnot(None),
            )
            .order_by(Price.date.asc())
            .all()
        )
        after_prices = (
            db_session.query(Price)
            .filter(
                Price.instrument_id == instrument.id,
                Price.date >= after_start,
                Price.date <= after_end,
                Price.close.isnot(None),
            )
            .order_by(Price.date.asc())
            .all()
        )

        if len(before_prices) < 2 or len(after_prices) < 2:
            return {
                "ticker": ticker,
                "event_date": str(event_date_only),
                "error": "Not enough price data",
            }

        before_returns = [
            (before_prices[i].close - before_prices[i - 1].close) / before_prices[i - 1].close
            for i in range(1, len(before_prices))
        ]
        after_returns = [
            (after_prices[i].close - after_prices[i - 1].close) / after_prices[i - 1].close
            for i in range(1, len(after_prices))
        ]

        before_avg = float(np.mean(before_returns)) if before_returns else 0.0
        after_avg = float(np.mean(after_returns)) if after_returns else 0.0
        observed_effect = after_avg - before_avg

        peers = (
            db_session.query(Instrument)
            .filter(Instrument.sector == instrument.sector, Instrument.ticker != ticker.upper())
            .all()
        )

        peer_before_all: list[float] = []
        peer_after_all: list[float] = []
        for peer in peers:
            pb = (
                db_session.query(Price)
                .filter(
                    Price.instrument_id == peer.id,
                    Price.date >= before_start,
                    Price.date <= before_end,
                    Price.close.isnot(None),
                )
                .order_by(Price.date.asc())
                .all()
            )
            pa = (
                db_session.query(Price)
                .filter(
                    Price.instrument_id == peer.id,
                    Price.date >= after_start,
                    Price.date <= after_end,
                    Price.close.isnot(None),
                )
                .order_by(Price.date.asc())
                .all()
            )
            if len(pb) >= 2 and len(pa) >= 2:
                peer_before_all.extend(
                    (pb[i].close - pb[i - 1].close) / pb[i - 1].close for i in range(1, len(pb))
                )
                peer_after_all.extend(
                    (pa[i].close - pa[i - 1].close) / pa[i - 1].close for i in range(1, len(pa))
                )

        if peer_before_all and peer_after_all:
            peer_before_avg = float(np.mean(peer_before_all))
            peer_after_avg = float(np.mean(peer_after_all))
            predicted_counterfactual = peer_after_avg - peer_before_avg
        else:
            predicted_counterfactual = 0.0

        impact = observed_effect - predicted_counterfactual

        all_peer = peer_before_all + peer_after_all
        if len(all_peer) >= 5:
            peer_std = float(np.std(all_peer))
            if peer_std > 0:
                z = abs(impact) / peer_std
                import math
                p_value = min(1.0, 2.0 * math.exp(-0.5 * z * z))
            else:
                p_value = 1.0
        else:
            p_value = 1.0

        return {
            "ticker": ticker,
            "event_date": str(event_date_only),
            "observed_effect": round(observed_effect, 6),
            "predicted_counterfactual": round(predicted_counterfactual, 6),
            "impact": round(impact, 6),
            "p_value_approximate": round(p_value, 4),
        }

    def analyze_news_event(self, news_article: Any, db_session: Any) -> dict[str, Any]:
        if not news_article.published_at:
            return {"error": "Article has no published_at"}

        linked = (
            db_session.query(Instrument)
            .join(NewsInstrument)
            .filter(NewsInstrument.news_id == news_article.id)
            .all()
        )
        if not linked:
            return {"error": "No linked instruments"}

        impacts = []
        for inst in linked:
            est = self.estimate_impact(inst.ticker, news_article.published_at, db_session)
            impacts.append(est)

        return {
            "news_id": news_article.id,
            "title": news_article.title,
            "published_at": news_article.published_at.isoformat() if news_article.published_at else None,
            "impacts": impacts,
        }


class InstrumentCausalGraph:
    """Causal relationships between instruments using Granger tests."""

    def __init__(self, max_lag: int = _DEFAULT_MAX_LAG):
        self.max_lag = max_lag

    def estimate_peer_impact(self, source_ticker: str, target_ticker: str, db_session: Any) -> dict[str, Any]:
        if not _HAS_STATSMODELS:
            return {"available": False}

        src = db_session.query(Instrument).filter(Instrument.ticker == source_ticker.upper()).first()
        tgt = db_session.query(Instrument).filter(Instrument.ticker == target_ticker.upper()).first()
        if not src or not tgt:
            return {"error": "One or both instruments not found"}

        def _get_returns(instrument: Instrument) -> dict[Any, float]:
            rows = (
                db_session.query(Price)
                .filter(Price.instrument_id == instrument.id, Price.close.isnot(None))
                .order_by(Price.date.asc())
                .all()
            )
            rets: dict[Any, float] = {}
            for i in range(1, len(rows)):
                prev, cur = rows[i - 1].close, rows[i].close
                if prev and prev != 0:
                    rets[rows[i].date] = (cur - prev) / prev
            return rets

        src_returns = _get_returns(src)
        tgt_returns = _get_returns(tgt)
        common = sorted(set(src_returns.keys()) & set(tgt_returns.keys()))
        if len(common) < self.max_lag + 5:
            return {
                "source": source_ticker,
                "target": target_ticker,
                "error": "Not enough overlapping data",
            }

        src_series = [src_returns[d] for d in common]
        tgt_series = [tgt_returns[d] for d in common]
        data = np.column_stack([tgt_series, src_series])

        try:
            result = grangercausalitytests(data, maxlag=self.max_lag, verbose=False)
        except Exception as exc:
            return {"source": source_ticker, "target": target_ticker, "error": str(exc)}

        best_lag = 1
        best_pvalue = 1.0
        for lag in range(1, self.max_lag + 1):
            if lag in result:
                pval = result[lag][0]["ssr_chi2test"][1]
                if pval < best_pvalue:
                    best_pvalue = pval
                    best_lag = lag

        return {
            "source": source_ticker,
            "target": target_ticker,
            "best_lag": best_lag,
            "best_pvalue": round(float(best_pvalue), 6),
            "causal_direction": f"{source_ticker} -> {target_ticker}",
            "significant": bool(best_pvalue < 0.05),
        }

    def find_influencers(self, ticker: str, db_session: Any, top_n: int = 5) -> list[dict[str, Any]]:
        if not _HAS_STATSMODELS:
            return []

        instrument = db_session.query(Instrument).filter(Instrument.ticker == ticker.upper()).first()
        if not instrument:
            return []

        candidates = (
            db_session.query(Instrument)
            .filter(Instrument.sector == instrument.sector, Instrument.ticker != ticker.upper())
            .all()
        )

        results: list[dict[str, Any]] = []
        for cand in candidates:
            est = self.estimate_peer_impact(cand.ticker, ticker, db_session)
            if "best_pvalue" in est:
                results.append(est)

        results.sort(key=lambda r: r["best_pvalue"])
        return results[:top_n]
