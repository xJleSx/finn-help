import logging
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import (
    BASE_POSITION_PCT,
    FUND_RISK_HIGH,
    GEO_RISK_ELEVATED,
    GEO_RISK_HIGH,
    MACRO_MAX_ADJUSTMENT,
    MACRO_THRESHOLDS,
)
from src.db.models import Signal as SignalModel

logger = logging.getLogger(__name__)

BASE_WEIGHTS = {
    "technical": 0.35,
    "fundamental": 0.18,
    "geo": 0.17,
    "ml": 0.13,
    "sentiment": 0.12,
    "mtf": 0.05,
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


def _calmar_ratio(returns: np.ndarray, prices: np.ndarray) -> float:
    if len(returns) < 2:
        return 0.0
    cagr = float(np.mean(returns) * 252)
    mdd = _max_drawdown(prices)
    return cagr / mdd if mdd > 0 else 0.0


def _omega_ratio(returns: np.ndarray, rf: float = 0.0) -> float:
    if len(returns) < 2:
        return 0.0
    threshold = rf / 252
    excess = returns - threshold
    gains = excess[excess > 0].sum()
    losses = abs(excess[excess < 0].sum())
    return float(gains / losses) if losses > 0 else float("inf")


def compute_risk_metrics(price_series: list[float]) -> dict:
    arr = np.array(price_series, dtype=float)
    if len(arr) < 10:
        return {"sharpe": 0.0, "sortino": 0.0, "max_drawdown": 0.0, "calmar": 0.0, "omega": 0.0}
    returns = np.diff(arr) / arr[:-1]
    return {
        "sharpe": round(_sharpe_ratio(returns), 2),
        "sortino": round(_sortino_ratio(returns), 2),
        "max_drawdown": round(_max_drawdown(arr), 4),
        "calmar": round(_calmar_ratio(returns, arr), 2),
        "omega": round(_omega_ratio(returns), 2),
    }


class SignalFusionEngine:
    def fuse(
        self,
        ticker: str,
        technical: Optional[dict] = None,
        fundamental: Optional[dict] = None,
        geo: Optional[dict] = None,
        ml_prediction: Optional[dict] = None,
        volatility_regime: Optional[dict] = None,
        risk_metrics: Optional[dict] = None,
        macro_context: Optional[dict] = None,
        sentiment: Optional[dict] = None,
        mtf: Optional[dict] = None,
        user_id: Optional[str] = None,
    ) -> dict:
        reasons = []
        if user_id:
            from src.user_profile import profile_manager

            weights = profile_manager.get_weights(user_id)
        else:
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

        macro_adjustment = 0.0
        macro_reasons = []

        mt = MACRO_THRESHOLDS

        sentiment_signal = 0.0
        sentiment_source = "нет данных"
        if sentiment is not None:
            raw = sentiment.get("score", 0.0)
            divergence = sentiment.get("divergence", 0.0)
            sentiment_signal = raw * (1 - min(divergence, 0.5))
            sentiment_source = sentiment.get("source", "rss")
            if raw > 0.3:
                reasons.append(f"Новости позитивные ({raw:.1f})")
            elif raw < -0.3:
                reasons.append(f"Новости негативные ({raw:.1f})")

        if macro_context:
            imoex = macro_context.get("imoex")
            cpi = macro_context.get("cpi")
            key_rate = macro_context.get("key_rate")
            ofz = macro_context.get("ofz_10y")
            m2 = macro_context.get("m2")

            def _apply(name: str, val: float | None, label: str):
                nonlocal macro_adjustment
                if val is None:
                    return
                cfg = mt.get(name)
                if not cfg:
                    return
                if val > cfg["high"]:
                    macro_adjustment += cfg["high_adj"]
                    macro_reasons.append(f"{label}>{cfg['high']}")
                elif val < cfg["low"]:
                    macro_adjustment += cfg["low_adj"]
                    macro_reasons.append(f"{label}<{cfg['low']}")

            _apply("brent", brent, "Brent")
            _apply("key_rate", key_rate, "Ключевая")
            _apply("cpi", cpi, "Инфляция")
            _apply("ofz_10y", ofz, "ОФЗ")

            if m2 is not None:
                cfg = mt.get("m2")
                if m2 > cfg["high"]:
                    macro_adjustment += cfg["high_adj"]
                    macro_reasons.append("M2 расширяется")
                elif m2 < cfg["low"]:
                    macro_adjustment += cfg["low_adj"]
                    macro_reasons.append("M2 сужается")

            if imoex is not None:
                cfg = mt.get("imoex")
                if imoex > cfg["high"]:
                    macro_adjustment += cfg["high_adj"]
                    macro_reasons.append("IMOEX сильно")
                elif imoex < cfg["low"]:
                    macro_adjustment += cfg["low_adj"]
                    macro_reasons.append("IMOEX слабый")

            if macro_reasons:
                reasons.append(f"Макро: {', '.join(macro_reasons)}")

        tech_action = technical.get("action", "NEUTRAL") if technical else "NEUTRAL"
        tech_conf = technical.get("confidence", 0.0) if technical else 0.0
        tech_score = technical.get("score", 0.0) if technical else 0.0
        tech_reasons = technical.get("reasons", []) if technical else []

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

        mtf_signal = 0.0
        mtf_agreement = 0.0
        if mtf:
            mtf_signal = mtf.get("direction", 0.0)
            mtf_agreement = mtf.get("agreement", 0.0)
            tfs = "/".join(mtf.get("details", {}).keys())
            if mtf_signal > 0.2:
                reasons.append(f"MTF ({tfs}): бычий консенсус ({mtf_agreement:.0%})")
            elif mtf_signal < -0.2:
                reasons.append(f"MTF ({tfs}): медвежий консенсус ({mtf_agreement:.0%})")

        weighted_score = (
            tech_score * weights["technical"]
            + fund_signal * weights["fundamental"]
            + geo_signal * weights["geo"]
            + ml_signal * weights["ml"]
            + sentiment_signal * weights["sentiment"]
            + mtf_signal * weights["mtf"]
            + macro_adjustment * MACRO_MAX_ADJUSTMENT
        )

        macro_max = MACRO_MAX_ADJUSTMENT
        w = weights
        all_except_geo = w["technical"] + w["fundamental"] + w["ml"] + w["sentiment"] + w["mtf"]
        all_weights = all_except_geo + w["geo"]
        max_positive = all_except_geo + macro_max
        max_negative = all_weights + macro_max
        max_possible = max_positive if weighted_score >= 0 else max_negative

        confidence = abs(weighted_score) / max_possible if max_possible > 0 else 0.0

        if risk_metrics:
            sharpe = risk_metrics.get("sharpe", 0.0)
            sortino = risk_metrics.get("sortino", 0.0)
            mdd = risk_metrics.get("max_drawdown", 0.0)
            calmar = risk_metrics.get("calmar", 0.0)
            omega = risk_metrics.get("omega", 0.0)
            risk_adj = 1.0
            risk_adj += min(sharpe * 0.05, 0.15)
            risk_adj += min(sortino * 0.03, 0.10)
            risk_adj -= min(mdd * 2, 0.20)
            risk_adj += min(calmar * 0.02, 0.08)
            risk_adj += min(omega * 0.01, 0.05)
            confidence *= max(risk_adj, 0.3)
            reasons.append(f"Risk: Sharpe={sharpe:.1f}, Calmar={calmar:.1f}, DD={mdd:.1%}")

        confidence = min(confidence, 1.0)

        if weighted_score > 0.02:
            action = "BUY"
        elif weighted_score < -0.02:
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

        if geo_score > GEO_RISK_HIGH:
            reasons.append(f"⚠️ ВЫСОКИЙ геополитический риск ({geo_score:.1f}/10)")
            if action == "BUY":
                action = "CAUTIOUS_BUY"
        elif geo_score > GEO_RISK_ELEVATED:
            reasons.append(f"⚠️ повышенный геополитический риск ({geo_score:.1f}/10)")

        max_portfolio_pct = self._calc_max_position(action, geo_score, fund_risk, user_id=user_id)

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
                "sentiment": {
                    "score": round(sentiment_signal, 3),
                    "source": sentiment_source,
                },
                "mtf": {
                    "direction": round(mtf_signal, 3) if mtf else 0,
                    "agreement": round(mtf_agreement, 3) if mtf else 0,
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

    def _calc_max_position(self, action: str, geo_risk: float, fund_risk: float, user_id: Optional[str] = None) -> int:
        pct = BASE_POSITION_PCT.get(action, 10)
        if user_id:
            from src.user_profile import profile_manager

            pct = min(pct, profile_manager.get_max_position(user_id))
        if geo_risk > GEO_RISK_HIGH:
            pct = min(pct, 10)
        if fund_risk > FUND_RISK_HIGH:
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

    def save_signal_sync(self, db, instrument_id: int, fused: dict) -> SignalModel:
        """Sync version for CLI / scheduler."""
        from src.db.models import Signal as SignalModel

        fused_clean = self._to_native(fused)
        signal = SignalModel(
            instrument_id=instrument_id,
            date=datetime.now(timezone.utc),
            action=fused["action"],
            confidence=fused_clean["confidence"],
            fused_json=fused_clean,
        )
        db.add(signal)
        db.commit()
        return signal

    async def save_signal(self, db: AsyncSession, instrument_id: int, fused: dict) -> SignalModel:
        fused_clean = self._to_native(fused)
        signal = SignalModel(
            instrument_id=instrument_id,
            date=datetime.now(timezone.utc),
            action=fused["action"],
            confidence=fused_clean["confidence"],
            fused_json=fused_clean,
        )
        db.add(signal)
        await db.commit()
        await db.refresh(signal)
        return signal
