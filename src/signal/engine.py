import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.db.models import Signal as SignalModel, Instrument

logger = logging.getLogger(__name__)


class SignalFusionEngine:
    def fuse(
        self,
        ticker: str,
        technical: dict,
        fundamental: Optional[dict] = None,
        geo: Optional[dict] = None,
        ml_prediction: Optional[dict] = None,
    ) -> dict:
        reasons = []
        weights = {
            "technical": 0.35,
            "fundamental": 0.2,
            "geo": 0.2,
            "ml": 0.25,
        }

        tech_action = technical.get("action", "NEUTRAL")
        tech_conf = technical.get("confidence", 0.0)
        tech_score = technical.get("score", 0.0)
        tech_reasons = technical.get("reasons", [])

        fund_risk = fundamental.get("risk", 0.5) if fundamental else 0.5
        fund_anomalies = fundamental.get("anomalies", []) if fundamental else []

        geo_score = geo.get("score", 0.0) if geo else 0.0

        ml_signal = 0.0
        ml_confidence = 0.0
        ml_target = None
        ml_change = None
        if ml_prediction:
            ml_signal = ml_prediction.get("signal_score", 0.0)
            ml_confidence = ml_prediction.get("ml_confidence", ml_prediction.get("confidence", 0.0))
            ml_target = ml_prediction.get("target_price")
            ml_change = ml_prediction.get("price_change_pct")

        weighted_score = (
            tech_score * weights["technical"]
            + (-fund_risk) * weights["fundamental"]
            + (-geo_score / 10) * weights["geo"]
            + ml_signal * weights["ml"]
        )

        max_possible = (
            1.0 * weights["technical"]
            + 1.0 * weights["fundamental"]
            + 1.0 * weights["geo"]
            + 1.0 * weights["ml"]
        )

        confidence = abs(weighted_score) / max_possible if max_possible > 0 else 0.0
        confidence = min(confidence, 1.0)

        if weighted_score > 0.2:
            action = "BUY"
        elif weighted_score < -0.2:
            action = "SELL"
        else:
            action = "HOLD"

        reasons.extend(tech_reasons)

        if ml_prediction and ml_change is not None:
            arrow = "↗" if ml_change > 0 else "↘"
            reasons.append(f"ML-прогноз: {ml_change:+.1f}% ({arrow})")

        if fund_anomalies:
            reasons.append(f"⚠️ аномалии: {'; '.join(fund_anomalies[:3])}")
            action = self._downgrade_buy(action)

        if geo_score > 7:
            reasons.append(f"⚠️ ВЫСОКИЙ геополитический риск ({geo_score:.1f}/10)")
            if action == "BUY":
                action = "CAUTIOUS_BUY"
        elif geo_score > 5:
            reasons.append(f"⚠️ повышенный геополитический риск ({geo_score:.1f}/10)")

        max_portfolio_pct = self._calc_max_position(action, geo_score, fund_risk)

        fused = {
            "ticker": ticker,
            "action": action,
            "confidence": round(confidence, 2),
            "weighted_score": round(weighted_score, 2),
            "reasons": reasons[:6],
            "max_portfolio_pct": max_portfolio_pct,
            "components": {
                "technical": {"action": tech_action, "confidence": tech_conf, "score": tech_score},
                "fundamental_risk": fund_risk,
                "geo_risk": geo_score,
                "ml": {
                    "signal_score": ml_signal,
                    "confidence": ml_confidence,
                    "target_price": ml_target,
                    "change_pct": ml_change,
                },
            },
        }

        return fused

    def _downgrade_buy(self, action: str) -> str:
        if action == "BUY":
            return "CAUTIOUS_BUY"
        return action

    def _calc_max_position(self, action: str, geo_risk: float, fund_risk: float) -> int:
        base = {"BUY": 30, "CAUTIOUS_BUY": 15, "HOLD": 10, "SELL": 5, "NEUTRAL": 10}
        pct = base.get(action, 10)
        if geo_risk > 7:
            pct = min(pct, 10)
        if fund_risk > 0.6:
            pct = min(pct, 10)
        return pct

    def _to_native(self, obj):
        if isinstance(obj, dict):
            return {k: self._to_native(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._to_native(v) for v in obj]
        elif hasattr(obj, "item"):
            return obj.item()
        return obj

    def save_signal(self, db: Session, instrument_id: int, fused: dict) -> SignalModel:
        fused_clean = self._to_native(fused)
        signal = SignalModel(
            instrument_id=instrument_id,
            date=datetime.utcnow(),
            action=fused["action"],
            confidence=fused_clean["confidence"],
            fused_json=fused_clean,
        )
        db.add(signal)
        db.commit()
        return signal
