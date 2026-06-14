import logging
from datetime import datetime
from typing import Optional

import numpy as np
from sqlalchemy.orm import Session

from src.db.models import Signal as SignalModel

logger = logging.getLogger(__name__)

BASE_WEIGHTS = {
    "technical": 0.45,
    "fundamental": 0.20,
    "geo": 0.20,
    "ml": 0.15,
}


def _sharpe_ratio(returns: np.ndarray, rf: float = 0.0) -> float:
    if len(returns) < 2 or np.std(returns) == 0:
        return 0.0
    excess = np.mean(returns) - rf / 252
    return float(excess / np.std(returns) * np.sqrt(252))


def _sortino_ratio(returns: np.ndarray, rf: float = 0.0) -> float:
    if len(returns) < 2:
        return 0.0
    downside = returns[returns < 0]
    if len(downside) == 0 or np.std(downside) == 0:
        return 0.0
    excess = np.mean(returns) - rf / 252
    return float(excess / np.std(downside) * np.sqrt(252))


def _max_drawdown(prices: np.ndarray) -> float:
    if len(prices) < 2:
        return 0.0
    peak = np.maximum.accumulate(prices)
    dd = (prices - peak) / peak
    return float(abs(dd.min()))


def compute_risk_metrics(price_series: list[float]) -> dict:
    arr = np.array(price_series, dtype=float)
    if len(arr) < 10:
        return {"sharpe": 0.0, "sortino": 0.0, "max_drawdown": 0.0}
    returns = np.diff(arr) / arr[:-1]
    return {
        "sharpe": round(_sharpe_ratio(returns), 2),
        "sortino": round(_sortino_ratio(returns), 2),
        "max_drawdown": round(_max_drawdown(arr), 4),
    }


class SignalFusionEngine:
    def fuse(
        self,
        ticker: str,
        technical: dict,
        fundamental: Optional[dict] = None,
        geo: Optional[dict] = None,
        ml_prediction: Optional[dict] = None,
        volatility_regime: Optional[dict] = None,
        risk_metrics: Optional[dict] = None,
    ) -> dict:
        reasons = []
        weights = dict(BASE_WEIGHTS)

        if volatility_regime and volatility_regime.get("adjustment"):
            adj = volatility_regime["adjustment"]
            for key in weights:
                mult_key = f"{key}_mult"
                if mult_key in adj:
                    weights[key] *= adj[mult_key]
            total = sum(weights.values())
            if total > 0:
                for key in weights:
                    weights[key] /= total
            reasons.append(f"Волатильность: {volatility_regime.get('regime', 'NORMAL')}")

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

        fund_signal = (1 - fund_risk) * 2 - 1
        geo_signal = -(geo_score / 10)

        weighted_score = (
            tech_score * weights["technical"]
            + fund_signal * weights["fundamental"]
            + geo_signal * weights["geo"]
            + ml_signal * weights["ml"]
        )

        max_positive = (
            1.0 * weights["technical"] + 1.0 * weights["fundamental"] + 0.0 * weights["geo"] + 1.0 * weights["ml"]
        )
        max_negative = (
            1.0 * weights["technical"] + 1.0 * weights["fundamental"] + 1.0 * weights["geo"] + 1.0 * weights["ml"]
        )
        max_possible = max_positive if weighted_score >= 0 else max_negative

        confidence = abs(weighted_score) / max_possible if max_possible > 0 else 0.0

        if risk_metrics:
            sharpe = risk_metrics.get("sharpe", 0.0)
            sortino = risk_metrics.get("sortino", 0.0)
            mdd = risk_metrics.get("max_drawdown", 0.0)
            risk_adj = 1.0 + min(sharpe * 0.05, 0.15) + min(sortino * 0.03, 0.10) - min(mdd * 2, 0.20)
            confidence *= max(risk_adj, 0.3)
            reasons.append(f"Risk: Sharpe={sharpe:.1f}, DD={mdd:.1%}")

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
            "reasons": reasons[:8],
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

        if risk_metrics:
            fused["risk_metrics"] = risk_metrics

        if volatility_regime:
            fused["volatility_regime"] = {
                "regime": volatility_regime.get("regime"),
                "atr_ratio": volatility_regime.get("atr_ratio"),
                "hv": volatility_regime.get("hv"),
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
