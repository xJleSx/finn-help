import logging
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

import pandas as pd

logger = logging.getLogger(__name__)

Profile = Literal["conservative", "balanced", "aggressive"]

PROFILES: dict[Profile, dict[str, Any]] = {
    "conservative": {"tp_count": 1, "tp_levels": [0.05], "stop_atr": 2.0, "trailing_after": 0.03},
    "balanced": {"tp_count": 2, "tp_levels": [0.07, 0.12], "stop_atr": 1.5, "trailing_after": 0.05},
    "aggressive": {"tp_count": 3, "tp_levels": [0.07, 0.14, 0.20], "stop_atr": 1.0, "trailing_after": 0.05},
}

ENTRY_ATR_FACTOR = 0.3

CONFIDENCE_TO_WIDTH: dict[float, float] = {
    0.0: 0.50,
    0.3: 0.30,
    0.5: 0.20,
    0.7: 0.10,
    0.9: 0.05,
}


def _interval_width(confidence: float) -> float:
    keys = sorted(CONFIDENCE_TO_WIDTH.keys())
    if confidence <= keys[0]:
        return CONFIDENCE_TO_WIDTH[keys[0]]
    if confidence >= keys[-1]:
        return CONFIDENCE_TO_WIDTH[keys[-1]]
    for i in range(len(keys) - 1):
        if keys[i] <= confidence <= keys[i + 1]:
            ratio = (confidence - keys[i]) / (keys[i + 1] - keys[i])
            return CONFIDENCE_TO_WIDTH[keys[i]] + ratio * (CONFIDENCE_TO_WIDTH[keys[i + 1]] - CONFIDENCE_TO_WIDTH[keys[i]])
    return 0.20


@dataclass
class PredictionInterval:
    lower: float
    upper: float
    confidence: float


@dataclass
class EntryZone:
    low: float
    high: float
    current: float


@dataclass
class TakeProfit:
    level: float
    type: str
    return_pct: float
    rr: float


@dataclass
class TradePlan:
    entry_zone: EntryZone
    targets: list[TakeProfit]
    stop_loss: float
    trailing_after: float
    risk_reward: float
    prediction_interval: Optional[PredictionInterval] = None


def compute_entry_zone(close: float, sma20: float, atr: float) -> EntryZone:
    ref = sma20 if sma20 > 0 else close
    return EntryZone(
        low=round(ref - ENTRY_ATR_FACTOR * atr, 2),
        high=round(ref + ENTRY_ATR_FACTOR * atr, 2),
        current=round(close, 2),
    )


def compute_support_resistance(df: pd.DataFrame, lookback: int = 60) -> tuple[float | None, float | None]:
    if df.empty or len(df) < 10:
        return None, None
    recent = df.tail(lookback).copy()
    close = recent["close"].values
    low = recent["low"].values if "low" in recent.columns else close
    high = recent["high"].values if "high" in recent.columns else close

    pivots_low: list[float] = []
    pivots_high: list[float] = []
    window = 3
    for i in range(window, len(recent) - window):
        if low[i] == min(low[i - window : i + window + 1]):
            pivots_low.append(low[i])
        if high[i] == max(high[i - window : i + window + 1]):
            pivots_high.append(high[i])

    current = close[-1]
    support_candidates = [p for p in pivots_low if p < current]
    resistance_candidates = [p for p in pivots_high if p > current]

    nearest_support = max(support_candidates) if support_candidates else None
    nearest_resistance = min(resistance_candidates) if resistance_candidates else None
    return nearest_support, nearest_resistance


def compute_take_profits(
    entry: float, resistance: float | None, atr: float, profile: Profile = "balanced"
) -> list[TakeProfit]:
    cfg = PROFILES[profile]
    targets: list[TakeProfit] = []
    for i, pct in enumerate(cfg["tp_levels"]):
        level = round(entry * (1 + pct), 2)
        if resistance is not None and resistance > entry and resistance < level:
            level = round(resistance, 2)
            pct = (level - entry) / entry
        rr = (level - entry) / (atr * cfg["stop_atr"]) if atr > 0 else 1.0
        targets.append(
            TakeProfit(
                level=level,
                type=f"tp{i + 1}",
                return_pct=round(pct * 100, 1),
                rr=round(max(rr, 0.5), 1),
            )
        )
    return targets


def compute_stop_loss(entry: float, atr: float, side: Literal["buy", "sell"], profile: Profile = "balanced") -> float:
    cfg = PROFILES[profile]
    if side == "buy":
        stop = entry - atr * cfg["stop_atr"]
    else:
        stop = entry + atr * cfg["stop_atr"]
    return float(round(max(stop, 0.01), 2))


def compute_risk_reward(entry: float, targets: list[TakeProfit], stop: float) -> float:
    if not targets:
        return 0.0
    avg_target = sum(t.level for t in targets) / len(targets)
    risk = abs(entry - stop)
    if risk == 0:
        return 0.0
    reward = abs(avg_target - entry)
    return round(reward / risk, 1)


def build_trade_plan(
    close: float,
    sma20: float,
    atr: float,
    df: pd.DataFrame,
    side: Literal["buy", "sell"] = "buy",
    profile: Profile = "balanced",
    confidence: Optional[float] = None,
) -> TradePlan:
    entry_zone = compute_entry_zone(close, sma20, atr)
    support, resistance = compute_support_resistance(df)
    entry_price = close

    if side == "buy":
        targets = compute_take_profits(entry_price, resistance, atr, profile)
        stop_loss = compute_stop_loss(entry_price, atr, "buy", profile)
    else:
        targets = compute_take_profits(entry_price, support, atr, profile)
        stop_loss = compute_stop_loss(entry_price, atr, "sell", profile)

    cfg = PROFILES[profile]
    trailing_after = (
        round(entry_price * (1 + cfg["trailing_after"]), 2)
        if side == "buy"
        else round(entry_price * (1 - cfg["trailing_after"]), 2)
    )
    risk_reward = compute_risk_reward(entry_price, targets, stop_loss)

    prediction_interval = None
    if confidence is not None and targets:
        width = _interval_width(confidence)
        mid = targets[0].level
        interval = PredictionInterval(
            lower=round(mid * (1 - width), 2),
            upper=round(mid * (1 + width), 2),
            confidence=round(confidence, 2),
        )
        prediction_interval = interval

    return TradePlan(
        entry_zone=entry_zone,
        targets=targets,
        stop_loss=stop_loss,
        trailing_after=trailing_after,
        risk_reward=risk_reward,
        prediction_interval=prediction_interval,
    )


def to_dict(plan: TradePlan) -> dict[str, Any]:
    result: dict[str, Any] = {
        "entry_zone": {"low": plan.entry_zone.low, "high": plan.entry_zone.high, "current": plan.entry_zone.current},
        "targets": [{"level": t.level, "type": t.type, "return_pct": t.return_pct, "rr": t.rr} for t in plan.targets],
        "stop_loss": plan.stop_loss,
        "trailing_after": plan.trailing_after,
        "risk_reward": plan.risk_reward,
    }
    if plan.prediction_interval is not None:
        result["prediction_interval"] = {
            "lower": plan.prediction_interval.lower,
            "upper": plan.prediction_interval.upper,
            "confidence": plan.prediction_interval.confidence,
        }
    return result
