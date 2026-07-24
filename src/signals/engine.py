from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.analysis.metrics import compute_max_drawdown
from src.constants import (
    BASE_POSITION_PCT,
    FUND_RISK_HIGH,
    GEO_RISK_ELEVATED,
    GEO_RISK_HIGH,
    MACRO_MAX_ADJUSTMENT,
    MACRO_THRESHOLDS,
)
from src.db.models import Signal as SignalModel
from src.signals.schemas import FusedSignal, RiskMetrics, SignalComponents, VolatilityRegime

logger = structlog.get_logger(__name__)

BASE_WEIGHTS: dict[str, float] = {
    "technical": 0.35,
    "fundamental": 0.18,
    "geo": 0.17,
    "ml": 0.13,
    "sentiment": 0.12,
    "mtf": 0.05,
}

BOND_WEIGHTS: dict[str, float] = {
    "technical": 0.10,
    "fundamental": 0.40,
    "geo": 0.15,
    "ml": 0.10,
    "sentiment": 0.05,
    "mtf": 0.20,
}

# ── Dynamic weight bounds ───────────────────────────────────────────────
WEIGHT_RANGES: dict[str, dict[str, float]] = {
    "technical": {"min": 0.15, "max": 0.55},
    "fundamental": {"min": 0.08, "max": 0.35},
    "geo": {"min": 0.05, "max": 0.30},
    "ml": {"min": 0.05, "max": 0.25},
    "sentiment": {"min": 0.03, "max": 0.20},
    "mtf": {"min": 0.02, "max": 0.15},
}

# ── Volatility regime multipliers ───────────────────────────────────────
VOLATILITY_ADJUSTMENTS: dict[str, dict[str, float]] = {
    "LOW": {"ml_mult": 0.8, "technical_mult": 1.1, "sentiment_mult": 0.7},
    "NORMAL": {"ml_mult": 1.0, "technical_mult": 1.0, "sentiment_mult": 1.0},
    "HIGH": {"ml_mult": 1.2, "technical_mult": 0.9, "sentiment_mult": 1.2},
    "EXTREME": {"ml_mult": 1.4, "technical_mult": 0.7, "sentiment_mult": 1.4},
}

# ── Multiplicative risk penalties (per dimension) ───────────────────────
RISK_PENALTY_MULTIPLIERS: dict[str, float] = {
    "high_fundamental_risk": 0.85,
    "high_geo_risk": 0.80,
    "anomaly_detected": 0.75,
    "low_liquidity": 0.90,
    "high_concentration": 0.85,
    "negative_trend": 0.90,
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


def _calmar_ratio(returns: np.ndarray, prices: np.ndarray) -> float:
    if len(returns) < 2:
        return 0.0
    cagr = float(np.mean(returns) * 252)
    mdd = abs(compute_max_drawdown(prices.tolist()))
    return cagr / mdd if mdd > 0 else 0.0


def _omega_ratio(returns: np.ndarray, rf: float = 0.0) -> float:
    if len(returns) < 2:
        return 0.0
    threshold = rf / 252
    excess = returns - threshold
    gains = excess[excess > 0].sum()
    losses = abs(excess[excess < 0].sum())
    return float(gains / losses) if losses > 0 else float("inf")


def compute_risk_metrics(price_series: list[float]) -> dict[str, Any]:
    arr = np.array(price_series, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) < 10:
        return {"sharpe": 0.0, "sortino": 0.0, "max_drawdown": 0.0, "calmar": 0.0, "omega": 0.0}
    returns = np.diff(arr) / arr[:-1]
    return {
        "sharpe": round(_sharpe_ratio(returns), 2),
        "sortino": round(_sortino_ratio(returns), 2),
        "max_drawdown": round(abs(compute_max_drawdown(arr.tolist())), 4),
        "calmar": round(_calmar_ratio(returns, arr), 2),
        "omega": round(_omega_ratio(returns), 2),
    }


class SignalFusionEngine:
    """Full signal fusion with dynamic weights and multiplicative risk adjustments.

    Architecture reference:
      - docs/ARCHITECTURE.md — overall fusion pipeline
      - docs/FinAdvisor_Technical_Documentation.docx — detailed signal fusion spec
      - docs/adr/ADR-001-package-decomposition.md — why signals is a standalone module
    """

    def _get_base_weights(self, instrument_type: str, user_id: str | None = None) -> dict[str, float]:
        if instrument_type == "bond":
            return dict(BOND_WEIGHTS)
        if user_id:
            try:
                from src.user_profile import profile_manager
                return profile_manager.get_weights(user_id)
            except Exception:
                pass
        return dict(BASE_WEIGHTS)

    def _apply_volatility_adjustment(
        self, weights: dict[str, float], regime: str | None, reasons: list[str],
    ) -> dict[str, float]:
        if not regime or regime not in VOLATILITY_ADJUSTMENTS:
            return weights
        adj = VOLATILITY_ADJUSTMENTS[regime]
        for key in list(weights.keys()):
            mult_key = f"{key}_mult"
            if mult_key in adj:
                weights[key] *= adj[mult_key]
        total = sum(weights.values())
        if total > 0:
            for key in weights:
                weights[key] /= total
        reasons.append(f"Волатильность: {regime}")
        return weights

    def _apply_weight_bounds(self, weights: dict[str, float]) -> dict[str, float]:
        for key in weights:
            bounds = WEIGHT_RANGES.get(key)
            if bounds:
                weights[key] = max(bounds["min"], min(bounds["max"], weights[key]))
        total = sum(weights.values())
        if total > 0:
            for key in weights:
                weights[key] /= total
        return weights

    def _apply_multiplicative_risk(
        self, weights: dict[str, float], risk_flags: dict[str, bool], reasons: list[str],
    ) -> dict[str, float]:
        penalty = 1.0
        for flag, active in risk_flags.items():
            if active and flag in RISK_PENALTY_MULTIPLIERS:
                penalty *= RISK_PENALTY_MULTIPLIERS[flag]
                reasons.append(f"Риск-фактор: {flag}")
        if penalty < 1.0:
            for key in weights:
                weights[key] *= penalty
        return weights

    def fuse(
        self,
        ticker: str,
        instrument_type: str = "stock",
        technical: Optional[dict[str, Any]] = None,
        fundamental: Optional[dict[str, Any]] = None,
        geo: Optional[dict[str, Any]] = None,
        ml_prediction: Optional[dict[str, Any]] = None,
        volatility_regime: Optional[dict[str, Any]] = None,
        risk_metrics: Optional[dict[str, Any]] = None,
        macro_context: Optional[dict[str, Any]] = None,
        sentiment: Optional[dict[str, Any]] = None,
        mtf: Optional[dict[str, Any]] = None,
        event_context: Optional[dict[str, Any]] = None,
        trade_plan: Optional[dict[str, Any]] = None,
        user_id: Optional[str] = None,
        bond_offering: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        reasons: list[str] = []
        is_bond = instrument_type == "bond"
        if not any([technical, fundamental, geo, ml_prediction, sentiment, mtf, macro_context, volatility_regime]):
            return FusedSignal(
                ticker=ticker,
                instrument_type=instrument_type,
                action="HOLD",
                confidence=0.0,
                weighted_score=0.0,
                reasons=["No component data available"],
                max_portfolio_pct=10,
            ).model_dump(exclude_none=True)

        # ── 1. Initial weights ──────────────────────────────────────────
        weights = self._get_base_weights(instrument_type, user_id)

        # ── 2. Volatility regime adjustment ─────────────────────────────
        regime = volatility_regime.get("regime") if volatility_regime else None
        weights = self._apply_volatility_adjustment(weights, regime, reasons)

        # ── 3. Technical score boost ────────────────────────────────────
        tech_score_raw = technical.get("score", 0.0) if technical else 0.0
        if tech_score_raw < 0:
            boost = 0.10
            weights["technical"] += boost
            for k in ["sentiment", "mtf", "geo"]:
                if weights.get(k, 0) >= boost * 0.5:
                    weights[k] -= boost * 0.4
            total = sum(weights.values())
            if total > 0:
                for k in weights:
                    weights[k] /= total
            reasons.append("Технический вес повышен — негативная техническая оценка")

        # ── 4. Multiplicative risk penalties ────────────────────────────
        risk_flags = {
            "high_fundamental_risk": fundamental is not None and fundamental.get("risk", 0.5) > 0.7,
            "high_geo_risk": geo is not None and geo.get("score", 0) > GEO_RISK_HIGH,
            "anomaly_detected": fundamental is not None and len(fundamental.get("anomalies", [])) > 0,
            "low_liquidity": volatility_regime is not None and volatility_regime.get("atr_ratio", 1) > 3,
            "negative_trend": ml_prediction is not None and ml_prediction.get("trend_slope", 0) < -0.01,
        }
        weights = self._apply_multiplicative_risk(weights, risk_flags, reasons)

        # ── 5. Clamp to bounds ─────────────────────────────────────────
        weights = self._apply_weight_bounds(weights)

        macro_adjustment = 0.0
        macro_reasons: list[str] = []

        mt = MACRO_THRESHOLDS

        trend_adjustment = 0.0
        if ml_prediction:
            ts = ml_prediction.get("trend_slope", 0.0)
            if ts != 0.0:
                strength = ml_prediction.get("trend_strength", 0.5)
                trend_adjustment = ts * 0.08 * strength
                if ml_prediction.get("trend_changed") and ts < 0:
                    trend_adjustment -= 0.05
                if trend_adjustment > 0.01:
                    reasons.append(f"Prophet тренд: восходящий ({ts:.2f})")
                elif trend_adjustment < -0.01:
                    reasons.append(f"Prophet тренд: нисходящий ({ts:.2f})")

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
            brent = macro_context.get("brent")
            m2 = macro_context.get("m2")

            def _apply(name: str, val: float | None, label: str) -> None:
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
                cfg_m2 = mt.get("m2")
                if cfg_m2 is not None:
                    if m2 > cfg_m2["high"]:
                        macro_adjustment += cfg_m2["high_adj"]
                        macro_reasons.append("M2 расширяется")
                    elif m2 < cfg_m2["low"]:
                        macro_adjustment += cfg_m2["low_adj"]
                        macro_reasons.append("M2 сужается")

            if imoex is not None:
                cfg_imoex = mt.get("imoex")
                if cfg_imoex is not None:
                    if imoex > cfg_imoex["high"]:
                        macro_adjustment += cfg_imoex["high_adj"]
                        macro_reasons.append("IMOEX сильно")
                    elif imoex < cfg_imoex["low"]:
                        macro_adjustment += cfg_imoex["low_adj"]
                        macro_reasons.append("IMOEX слабый")

            if macro_reasons:
                reasons.append(f"Макро: {', '.join(macro_reasons)}")

        event_penalty = 0.0
        if event_context:
            event_risk = event_context.get("event_risk_score", 0.0)
            event_penalty = event_risk * 0.05
            if event_context.get("sanctions_spike"):
                event_penalty += 0.03
                reasons.append("Санкционная активность за последние 7 дней")
            if event_risk > 0.5:
                reasons.append(f"Высокая событийная волатильность ({event_risk:.0%} дней)")
            elif event_risk > 0.2:
                reasons.append(f"Повышенная событийная активность ({event_risk:.0%} дней)")

        tech_action = technical.get("action", "NEUTRAL") if technical else "NEUTRAL"
        tech_conf = technical.get("confidence", 0.0) if technical else 0.0
        tech_score = tech_score_raw
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
            + trend_adjustment * weights["ml"]
            + event_penalty
        )

        # Bond-specific scoring override
        if is_bond and bond_offering:
            from src.analysis.signals.bond_signals import analyze_bond

            key_rate = macro_context.get("key_rate") if macro_context else None
            ofz_yield = macro_context.get("ofz_10y") if macro_context else None
            bond_signal = analyze_bond(bond_offering, key_rate=key_rate, ofz_yield=ofz_yield)
            bond_score = bond_signal.get("score", 0.0)
            bond_risk = bond_signal.get("risk", 0.5)
            weighted_score = bond_score * weights["fundamental"] * 2 + weighted_score * 0.5
            reasons.extend(bond_signal.get("reasons", []))
            if fundamental:
                fundamental["risk"] = max(fundamental.get("risk", 0.5), bond_risk)
            else:
                fundamental = {"risk": bond_risk, "anomalies": [], "signals": []}

        macro_max = MACRO_MAX_ADJUSTMENT
        w = weights
        all_except_geo = w["technical"] + w["fundamental"] + w["ml"] + w["sentiment"] + w["mtf"]
        all_weights = all_except_geo + w["geo"]
        max_absolute = max(all_weights, all_except_geo) + macro_max + 0.08

        confidence = abs(weighted_score) / max_absolute if max_absolute > 0 else 0.0

        if risk_metrics:
            sharpe = risk_metrics.get("sharpe", 0.0)
            sortino = risk_metrics.get("sortino", 0.0)
            mdd = risk_metrics.get("max_drawdown", 0.0)
            calmar = risk_metrics.get("calmar", 0.0)
            omega = risk_metrics.get("omega", 0.0)
            if np.isnan(sharpe): sharpe = 0.0
            if np.isnan(sortino): sortino = 0.0
            if np.isnan(mdd): mdd = 0.0
            if np.isnan(calmar): calmar = 0.0
            if np.isnan(omega): omega = 0.0
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

        bearish_smas = sum(1 for r in tech_reasons if r.startswith("Цена ниже"))
        bullish_smas = sum(1 for r in tech_reasons if r.startswith("Цена выше"))
        if action == "BUY" and bearish_smas >= 2 and tech_score < 0:
            action = "HOLD"
            reasons.append(f"Технический анализ: цена ниже {bearish_smas} скользящих средних — BUY отклонён")
        elif action == "BUY" and tech_action == "SELL" and tech_conf > 0.3:
            action = "HOLD"
            reasons.append("Технический анализ сигнализирует о продаже — BUY отклонён")
        if action == "SELL" and bullish_smas >= 2 and tech_score > 0:
            action = "HOLD"
            reasons.append(f"Технический анализ: цена выше {bullish_smas} скользящих средних — SELL отклонён")
        elif action == "SELL" and tech_action == "BUY" and tech_conf > 0.3:
            action = "HOLD"
            reasons.append("Технический анализ сигнализирует о покупке — SELL отклонён")

        if action == "BUY" and trend_adjustment < -0.02 and ml_signal < 0.1:
            action = "HOLD"
            reasons.append("Нисходящий тренд: цена продолжает падать — BUY отклонён")

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

        fused = FusedSignal(
            ticker=ticker,
            instrument_type=instrument_type,
            action=action,
            confidence=round(confidence, 2),
            weighted_score=round(weighted_score, 2),
            reasons=reasons[:8],
            max_portfolio_pct=max_portfolio_pct,
            components=SignalComponents(
                technical={"action": tech_action, "confidence": tech_conf, "score": tech_score},
                fundamental_risk=fund_risk,
                geo_risk=geo_score,
                ml={
                    "signal_score": ml_signal,
                    "confidence": ml_confidence,
                    "target_price": ml_target,
                    "change_pct": ml_change,
                },
                sentiment={
                    "score": round(sentiment_signal, 3),
                    "source": sentiment_source,
                },
                mtf={
                    "direction": round(mtf_signal, 3) if mtf else 0,
                    "agreement": round(mtf_agreement, 3) if mtf else 0,
                },
            ),
        )

        if risk_metrics:
            fused.risk_metrics = RiskMetrics(**risk_metrics)

        if volatility_regime:
            fused.volatility_regime = VolatilityRegime(
                regime=volatility_regime.get("regime", "NORMAL"),
                atr_ratio=volatility_regime.get("atr_ratio"),
                hv=volatility_regime.get("hv"),
            )

        if trade_plan:
            fused.trade_plan = trade_plan

        return fused.model_dump(exclude_none=True)

    def _downgrade_buy(self, action: str) -> str:
        if action == "BUY":
            return "CAUTIOUS_BUY"
        if action == "CAUTIOUS_BUY":
            return "HOLD"
        return action

    def _calc_max_position(
        self, action: str, geo_risk: float, fund_risk: float, user_id: str | None = None,
    ) -> int:
        pct = BASE_POSITION_PCT.get(action, 10)
        if user_id:
            from src.user_profile import profile_manager
            pct = min(pct, profile_manager.get_max_position(user_id))
        if geo_risk > GEO_RISK_HIGH:
            pct = min(pct, 10)
        if fund_risk > FUND_RISK_HIGH:
            pct = min(pct, 10)
        return pct

    @staticmethod
    def _to_native(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: SignalFusionEngine._to_native(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [SignalFusionEngine._to_native(v) for v in obj]
        if hasattr(obj, "item"):
            return obj.item()
        return obj

    def save_signal_sync(self, db: Any, instrument_id: int, fused: dict[str, Any]) -> SignalModel:
        fused_clean = self._to_native(fused)
        signal = SignalModel(
            instrument_id=instrument_id,
            date=datetime.now(timezone.utc),
            action=fused.get("action", "HOLD"),
            confidence=fused_clean.get("confidence", 0),
            fused_json=fused_clean,
        )
        db.add(signal)
        db.commit()
        logger.info("signal_saved_sync", instrument_id=instrument_id, action=fused.get("action"))
        return signal

    async def save_signal(self, db: AsyncSession, instrument_id: int, fused: dict[str, Any]) -> SignalModel:
        fused_clean = self._to_native(fused)
        signal = SignalModel(
            instrument_id=instrument_id,
            date=datetime.now(timezone.utc),
            action=fused.get("action", "HOLD"),
            confidence=fused_clean.get("confidence", 0),
            fused_json=fused_clean,
        )
        db.add(signal)
        await db.commit()
        await db.refresh(signal)
        logger.info("signal_saved_async", instrument_id=instrument_id, action=fused.get("action"))
        return signal
