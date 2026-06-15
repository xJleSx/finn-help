import logging
from datetime import date

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.analysis.fundamental import FundamentalAnalyzer
from src.analysis.ml.ensemble import EnsemblePredictor
from src.analysis.ml.prophet_model import ProphetPredictor
from src.analysis.multi_timeframe import MultiTimeframeAnalyzer
from src.analysis.technical import TechnicalAnalyzer
from src.analysis.volatility import VolatilityRegimeDetector
from src.db.models import Dividend, GeoRiskScore, Indicator, Instrument, Price, Signal
from src.llm.router import llm
from src.signal.engine import SignalFusionEngine, compute_risk_metrics

logger = logging.getLogger(__name__)


class AnalysisService:
    def __init__(self):
        self.analyzer = TechnicalAnalyzer()
        self.fundamental = FundamentalAnalyzer()
        self.fusion = SignalFusionEngine()
        self.prophet = ProphetPredictor()
        self.ensemble = EnsemblePredictor()
        self.volatility = VolatilityRegimeDetector()
        self.mtf = MultiTimeframeAnalyzer()

    def _price_df(self, prices: list[Price]) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "date": p.date,
                    "open": p.open,
                    "high": p.high,
                    "low": p.low,
                    "close": p.close,
                    "volume": p.volume,
                }
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

    def _compute_ml(self, df: pd.DataFrame, ind_df: pd.DataFrame) -> dict | None:
        if len(df) < 60:
            return None
        try:
            pr = self.prophet.predict(df)
            ensemble = self.ensemble.predict(ind_df)
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

    def _load_geo(self, db: Session) -> dict:
        geo = db.query(GeoRiskScore).order_by(GeoRiskScore.date.desc()).first()
        return {"score": geo.score} if geo else {"score": 0.0}

    def _load_macro(self, db: Session) -> dict:
        from src.collectors.macro import MacroCollector

        return MacroCollector.latest_values(db)

    def _load_sentiment(self, db: Session) -> dict:
        from datetime import datetime, timedelta

        from src.db.models import News

        cutoff = datetime.utcnow() - timedelta(days=3)
        recent = db.query(News).filter(News.created_at >= cutoff).all()
        if not recent:
            return {"score": 0.0, "divergence": 0.0, "source": "none"}
        scores = [n.sentiment_weighted or n.sentiment_score or 0.0 for n in recent]
        mean = sum(scores) / len(scores)
        variance = sum((s - mean) ** 2 for s in scores) / len(scores) if len(scores) > 1 else 0.0
        return {
            "score": round(mean, 3),
            "divergence": round(min(variance * 2, 1.0), 3),
            "source": "rss",
            "count": len(scores),
        }

    def analyze_single(self, db: Session, inst: Instrument, ticker: str, with_ml: bool = True) -> dict:
        prices = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date).all()
        if len(prices) < 50:
            raise ValueError("Not enough price data for %s", ticker)

        df = self._price_df(prices)

        ind_rows = db.query(Indicator).filter_by(instrument_id=inst.id).order_by(Indicator.date).all()
        if len(ind_rows) < 2:
            raise ValueError("Not enough indicator data for %s", ticker)
        ind_df = self._indicator_df(ind_rows)
        ind_df = ind_df.merge(df[["date", "close"]], on="date", how="left")

        tech_signal = self.analyzer.generate_signal(ind_df)

        divs = db.query(Dividend).filter_by(instrument_id=inst.id).all()
        div_df = self._dividend_df(divs)
        fund = self.fundamental.analyze(df, div_df)

        ml = self._compute_ml(df, ind_df) if with_ml else None
        geo = self._load_geo(db)
        macro_context = self._load_macro(db)
        sentiment = self._load_sentiment(db)

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
        return fused

    def analyze_all(self, db: Session, updated_ids: set[int] | None = None, with_ml: bool = True) -> list[dict]:
        q = db.query(Instrument)
        if updated_ids is not None:
            q = q.filter(Instrument.id.in_(updated_ids))
        instruments = q.all()

        signals = []
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
                signals.append(cached.fused_json)
                continue

            try:
                fused = self.analyze_single(db, inst, inst.ticker, with_ml=with_ml)
                self.fusion.save_signal(db, inst.id, fused)
                signals.append(fused)
            except ValueError:
                continue
        return signals

    async def analyze_with_advice(
        self, db: Session, inst: Instrument, ticker: str, with_ml: bool = True
    ) -> tuple[dict, str]:
        fused = self.analyze_single(db, inst, ticker, with_ml=with_ml)
        advice = await llm.advise(fused)
        return fused, advice


analysis_service = AnalysisService()
