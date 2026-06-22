import logging
from datetime import date

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.analysis.fundamental import FundamentalAnalyzer
from src.analysis.multi_timeframe import MultiTimeframeAnalyzer
from src.analysis.technical import TechnicalAnalyzer
from src.analysis.volatility import VolatilityRegimeDetector
from src.constants import NEWS_SENTIMENT_DAYS
from src.db.models import Dividend, GeoRiskScore, Indicator, Instrument, News, Price, Signal
from src.llm.router import llm
from src.signal.engine import SignalFusionEngine, compute_risk_metrics

logger = logging.getLogger(__name__)


class AnalysisService:
    def __init__(self):
        self.analyzer = TechnicalAnalyzer()
        self.fundamental = FundamentalAnalyzer()
        self.fusion = SignalFusionEngine()
        self._prophet = None
        self._ensemble = None
        self.volatility = VolatilityRegimeDetector()
        self.mtf = MultiTimeframeAnalyzer()

    def _get_prophet(self, ticker: str = ""):
        key = f"prophet_{ticker}"
        if not hasattr(self, "_prophet_cache"):
            self._prophet_cache = {}
        if key not in self._prophet_cache:
            from src.analysis.ml.prophet_model import ProphetPredictor

            self._prophet_cache[key] = ProphetPredictor(ticker=ticker)
        return self._prophet_cache[key]

    @property
    def prophet(self):
        return self._get_prophet()

    def _get_ensemble(self, ticker: str = ""):
        key = f"ensemble_{ticker}"
        if not hasattr(self, "_ensemble_cache"):
            self._ensemble_cache = {}
        if key not in self._ensemble_cache:
            from src.analysis.ml.ensemble import EnsemblePredictor

            self._ensemble_cache[key] = EnsemblePredictor(ticker=ticker)
        return self._ensemble_cache[key]

    @property
    def ensemble(self):
        return self._get_ensemble()

    def _price_df(self, prices: list[Price]) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"date": p.date, "open": p.open, "high": p.high, "low": p.low, "close": p.close, "volume": p.volume}
                for p in prices
            ]
        )

    def _indicator_df(self, rows: list[Indicator]) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "date": r.date,
                    "rsi": r.rsi,
                    "macd_line": r.macd_line,
                    "macd_signal": r.macd_signal,
                    "macd_hist": r.macd_hist,
                    "sma_20": r.sma_20,
                    "sma_50": r.sma_50,
                    "sma_200": r.sma_200,
                    "bb_upper": r.bb_upper,
                    "bb_lower": r.bb_lower,
                    "bb_mid": r.bb_mid,
                    "volume_sma_20": r.volume_sma_20,
                    "atr": r.atr,
                }
                for r in rows
            ]
        )

    def _dividend_df(self, divs: list[Dividend]) -> pd.DataFrame:
        return pd.DataFrame([{"date": d.date, "amount": d.amount} for d in divs])

    def _compute_ml(self, df: pd.DataFrame, ind_df: pd.DataFrame, ticker: str = "") -> dict | None:
        if len(df) < 60:
            return None
        try:
            pr = self._get_prophet(ticker).predict(df)
            ensemble = self._get_ensemble(ticker).predict(ind_df)
            ml = pr
            ml["ml_confidence"] = max(pr.get("confidence", 0), ensemble.get("confidence", 0))
            ml["xgb_action"] = ensemble.get("xgb_action", "NEUTRAL")
            ml["ensemble"] = {
                "lgb_action": ensemble.get("lgb_action", "NEUTRAL"),
                "cat_action": ensemble.get("cat_action", "NEUTRAL"),
                "model_votes": ensemble.get("model_votes", {}),
            }
            return ml
        except Exception:
            logger.warning("ML prediction failed", exc_info=True)
            return None

    async def _load_geo(self, db: AsyncSession) -> dict:
        result = await db.execute(select(GeoRiskScore).order_by(GeoRiskScore.date.desc()).limit(1))
        geo = result.scalar_one_or_none()
        return {"score": geo.score} if geo else {"score": 0.0}

    async def _load_macro(self, db: AsyncSession) -> dict:
        from src.collectors.macro import MacroCollector

        return await MacroCollector.latest_values_async(db)

    async def _load_sentiment(self, db: AsyncSession) -> dict:
        from datetime import datetime, timedelta, timezone

        from src.db.models import News

        cutoff = datetime.now(timezone.utc) - timedelta(days=NEWS_SENTIMENT_DAYS)
        result = await db.execute(select(News).where(News.created_at >= cutoff))
        recent = result.scalars().all()
        news_sentiment = {"score": 0.0, "divergence": 0.0, "source": "none", "count": 0}
        if recent:
            scores = [float(n.sentiment_weighted or n.sentiment_score or 0) for n in recent]
            mean_s = sum(scores) / len(scores)
            variance = sum((s - mean_s) ** 2 for s in scores) / len(scores) if len(scores) > 1 else 0.0
            news_sentiment = {
                "score": round(mean_s, 3),
                "divergence": round(min(variance * 2, 1.0), 3),
                "source": "rss",
                "count": len(scores),
            }

        try:
            from src.social.sentiment.aggregator import aggregator

            tickers = await db.execute(select(Instrument.ticker))
            all_tickers = [r[0] for r in tickers.all() if r[0]]
            all_social = aggregator.get_all_ticker_sentiments(all_tickers)
            social_with_data = [s for s in all_social.values() if s["count"] > 0]
        except Exception:
            social_with_data = []

        if not social_with_data:
            return news_sentiment

        avg_social = sum(s["score"] for s in social_with_data) / len(social_with_data)
        total_count = sum(s["count"] for s in social_with_data)
        all_social_scores = [s["score"] for s in social_with_data]
        divergence = (
            (max(all_social_scores) - min(all_social_scores)) / 2 if len(all_social_scores) > 1 else 0.0
        )

        if news_sentiment["count"] > 0:
            combined = news_sentiment["score"] * 0.4 + avg_social * 0.6
            source_str = "rss+social"
        else:
            combined = avg_social
            source_str = "social"

        return {
            "score": round(combined, 3),
            "divergence": round(min(divergence, 1.0), 3),
            "source": source_str,
            "count": news_sentiment["count"] + total_count,
        }

    async def _load_trends(self, db: AsyncSession, instrument_id: int) -> dict:
        from src.db.models import MetricSnapshot

        result = {}
        for period in ("daily", "weekly", "monthly"):
            snap = (
                await db.execute(
                    select(MetricSnapshot)
                    .where(MetricSnapshot.instrument_id == instrument_id, MetricSnapshot.period == period)
                    .order_by(MetricSnapshot.taken_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if snap:
                result[period] = {
                    "price_delta": snap.delta_price_pct,
                    "score_delta": snap.delta_score,
                    "rsi_delta": snap.delta_rsi,
                    "action_changed": snap.delta_action_changed,
                    "price": snap.price,
                    "rsi": snap.rsi,
                    "signal_action": snap.signal_action,
                    "signal_score": snap.signal_score,
                }
        return result

    async def analyze_single(self, db: AsyncSession, inst: Instrument, ticker: str, with_ml: bool = True) -> dict:
        price_result = await db.execute(select(Price).where(Price.instrument_id == inst.id).order_by(Price.date))
        prices = price_result.scalars().all()
        if len(prices) < 50:
            raise ValueError(f"Not enough price data for {ticker}")

        df = self._price_df(prices)

        ind_result = await db.execute(
            select(Indicator).where(Indicator.instrument_id == inst.id).order_by(Indicator.date)
        )
        ind_rows = ind_result.scalars().all()
        if len(ind_rows) < 2:
            raise ValueError(f"Not enough indicator data for {ticker}")
        ind_df = self._indicator_df(ind_rows)
        ind_df = ind_df.merge(df[["date", "close"]], on="date", how="left")

        tech_signal = self.analyzer.generate_signal(ind_df)

        div_result = await db.execute(select(Dividend).where(Dividend.instrument_id == inst.id))
        divs = div_result.scalars().all()
        div_df = self._dividend_df(divs)
        fund = self.fundamental.analyze(df, div_df)

        ml = self._compute_ml(df, ind_df, ticker=ticker) if with_ml else None
        geo = await self._load_geo(db)
        macro_context = await self._load_macro(db)
        sentiment = await self._load_sentiment(db)

        volatility_regime = self.volatility.detect(df, ind_df)

        risk_metrics = compute_risk_metrics(df["close"].tolist())

        mtf_data = self.mtf.compute_all(df)
        mtf_concordance = self.mtf.concordance(mtf_data) if mtf_data else None

        trends = await self._load_trends(db, inst.id)

        fused = self.fusion.fuse(
            ticker=ticker.upper(),
            technical=tech_signal,
            fundamental=fund,
            geo=geo,
            ml_prediction=ml,
            volatility_regime=volatility_regime,
            risk_metrics=risk_metrics,
            macro_context=macro_context,
            sentiment=sentiment,
            mtf=mtf_concordance,
        )
        fused["trends"] = trends
        return fused

    async def analyze_all(
        self, db: AsyncSession, updated_ids: set[int] | None = None, with_ml: bool = True
    ) -> list[dict]:
        q = select(Instrument)
        if updated_ids is not None:
            q = q.where(Instrument.id.in_(updated_ids))
        result = await db.execute(q)
        instruments = result.scalars().all()

        signals: list[dict] = []
        for inst in instruments:
            cached_result = await db.execute(
                select(Signal).where(
                    Signal.instrument_id == inst.id,
                    func.date(Signal.date) == date.today(),
                )
            )
            cached = cached_result.scalar_one_or_none()
            if cached and cached.fused_json:
                fused_json = cached.fused_json
                if isinstance(fused_json, dict):
                    signals.append(fused_json)
                continue

            try:
                fused = await self.analyze_single(db, inst, str(inst.ticker), with_ml=with_ml)
                await self.fusion.save_signal(db, inst.id, fused)
                signals.append(fused)
            except ValueError:
                continue
        return signals

    async def analyze_with_advice(
        self, db: AsyncSession, inst: Instrument, ticker: str, with_ml: bool = True
    ) -> tuple[dict, str]:
        fused = await self.analyze_single(db, inst, ticker, with_ml=with_ml)
        advice = await llm.advise(fused)
        return fused, advice

    def _load_trends_sync(self, db, instrument_id: int) -> dict:
        from src.db.models import MetricSnapshot

        result = {}
        for period in ("daily", "weekly", "monthly"):
            snap = (
                db.query(MetricSnapshot)
                .filter(MetricSnapshot.instrument_id == instrument_id, MetricSnapshot.period == period)
                .order_by(MetricSnapshot.taken_at.desc())
                .first()
            )
            if snap:
                result[period] = {
                    "price_delta": snap.delta_price_pct,
                    "score_delta": snap.delta_score,
                    "rsi_delta": snap.delta_rsi,
                    "action_changed": snap.delta_action_changed,
                    "price": snap.price,
                    "rsi": snap.rsi,
                    "signal_action": snap.signal_action,
                    "signal_score": snap.signal_score,
                }
        return result

    def _analyze_single_sync(self, db, inst, ticker: str, with_ml: bool = True) -> dict:
        prices = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date).all()
        if len(prices) < 50:
            raise ValueError(f"Not enough price data for {ticker}")
        df = self._price_df(prices)

        ind_rows = db.query(Indicator).filter_by(instrument_id=inst.id).order_by(Indicator.date).all()
        if len(ind_rows) < 2:
            raise ValueError(f"Not enough indicator data for {ticker}")
        ind_df = self._indicator_df(ind_rows)
        ind_df = ind_df.merge(df[["date", "close"]], on="date", how="left")

        tech_signal = self.analyzer.generate_signal(ind_df)

        divs = db.query(Dividend).filter_by(instrument_id=inst.id).all()
        div_df = self._dividend_df(divs)
        fund = self.fundamental.analyze(df, div_df)

        ml = self._compute_ml(df, ind_df, ticker=ticker) if with_ml else None

        geo_row = db.query(GeoRiskScore).order_by(GeoRiskScore.date.desc()).first()
        geo = {"score": geo_row.score} if geo_row else {"score": 0.0}

        from src.collectors.macro import MacroCollector

        macro_context = MacroCollector.latest_values(db)

        from datetime import datetime, timedelta, timezone

        cutoff = datetime.now(timezone.utc) - timedelta(days=NEWS_SENTIMENT_DAYS)
        recent = db.query(News).filter(News.created_at >= cutoff).all()
        news_sentiment = {"score": 0.0, "divergence": 0.0, "source": "none", "count": 0}
        if recent:
            scores = [float(n.sentiment_weighted or n.sentiment_score or 0) for n in recent]
            mean_s = sum(scores) / len(scores)
            variance = sum((s - mean_s) ** 2 for s in scores) / len(scores) if len(scores) > 1 else 0.0
            news_sentiment = {
                "score": round(mean_s, 3),
                "divergence": round(min(variance * 2, 1.0), 3),
                "source": "rss",
                "count": len(scores),
            }

        try:
            from src.social.sentiment.aggregator import aggregator

            social_entry = aggregator.get_ticker_sentiment(ticker)
        except Exception:
            social_entry = {"score": 0.0, "divergence": 0.0, "source": "social", "count": 0}

        if social_entry["count"] > 0 and news_sentiment["count"] > 0:
            combined = news_sentiment["score"] * 0.4 + social_entry["score"] * 0.6
            sentiment = {
                "score": round(combined, 3),
                "divergence": round(min(social_entry.get("divergence", 0), 1.0), 3),
                "source": "rss+social",
                "count": news_sentiment["count"] + social_entry["count"],
            }
        elif social_entry["count"] > 0:
            sentiment = {
                "score": round(social_entry["score"], 3),
                "divergence": round(min(social_entry.get("divergence", 0), 1.0), 3),
                "source": "social",
                "count": social_entry["count"],
            }
        else:
            sentiment = news_sentiment

        volatility_regime = self.volatility.detect(df, ind_df)
        risk_metrics = compute_risk_metrics(df["close"].tolist())
        mtf_data = self.mtf.compute_all(df)
        mtf_concordance = self.mtf.concordance(mtf_data) if mtf_data else None

        fused = self.fusion.fuse(
            ticker=ticker.upper(),
            technical=tech_signal,
            fundamental=fund,
            geo=geo,
            ml_prediction=ml,
            volatility_regime=volatility_regime,
            risk_metrics=risk_metrics,
            macro_context=macro_context,
            sentiment=sentiment,
            mtf=mtf_concordance,
        )
        fused["trends"] = self._load_trends_sync(db, inst.id)
        return fused

    def analyze_all_sync(self, db, updated_ids: set[int] | None = None, with_ml: bool = True) -> list[dict]:
        instruments = db.query(Instrument)
        if updated_ids is not None:
            instruments = instruments.filter(Instrument.id.in_(updated_ids))
        instruments = instruments.all()

        signals: list[dict] = []
        for inst in instruments:
            cached = (
                db.query(Signal)
                .filter(
                    Signal.instrument_id == inst.id,
                    func.date(Signal.date) == date.today(),
                )
                .first()
            )
            if cached and cached.fused_json:
                fused_json = cached.fused_json
                if isinstance(fused_json, dict):
                    signals.append(fused_json)
                continue

            try:
                fused = self._analyze_single_sync(db, inst, str(inst.ticker), with_ml=with_ml)
                self.fusion.save_signal_sync(db, inst.id, fused)
                signals.append(fused)
            except (ValueError, Exception) as e:
                logger.warning("analyze_all_sync failed for %s: %s", inst.ticker, e)
                continue
        return signals

    def train_models(self, db, ticker: str | None = None) -> dict[str, bool]:
        q = select(Instrument)
        if ticker:
            q = q.where(Instrument.ticker == ticker.upper())
        result = db.execute(q)
        instruments = result.scalars().all()

        all_results: dict[str, bool] = {}
        for inst in instruments:
            sym = str(inst.ticker or "")
            prices = (
                db.query(Price)
                .filter_by(instrument_id=inst.id)
                .order_by(Price.date)
                .all()
            )
            if len(prices) < 60:
                logger.info("Skipping %s: only %d prices", sym, len(prices))
                continue
            df = self._price_df(prices)

            ind_rows = (
                db.query(Indicator)
                .filter_by(instrument_id=inst.id)
                .order_by(Indicator.date)
                .all()
            )
            if len(ind_rows) < 2:
                logger.info("Skipping %s: no indicators", sym)
                continue
            ind_df = self._indicator_df(ind_rows)
            ind_df = ind_df.merge(df[["date", "close"]], on="date", how="left")

            ensemble = self._get_ensemble(sym)
            results = ensemble.train_all(df)
            all_results[sym] = all(results.values())
            logger.info(
                "Model training for %s: %s",
                sym,
                "OK" if all_results[sym] else "partial",
            )
        return all_results


analysis_service = AnalysisService()
