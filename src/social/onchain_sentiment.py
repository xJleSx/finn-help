from __future__ import annotations

from typing import Any, Callable

import numpy as np
import pandas as pd

DEFAULT_BULLISH_KEYWORDS = [
    "breakout", "bullish", "buy", "accumulate", "long", "green", "pump",
    "moon", "upside", "growth", "rally", "surge", "positive", "strong",
    "overbought", " momentum ",
]

DEFAULT_BEARISH_KEYWORDS = [
    "breakdown", "bearish", "sell", "dump", "short", "red", "crash",
    "panic", "downside", "decline", "plunge", "drop", "negative", "weak",
    "oversold", "capitulation",
]


def funding_rate_sentiment(
    funding_rates: pd.Series, threshold: float = 0.001
) -> pd.Series:
    abs_rates = funding_rates.abs()
    extreme = abs_rates > threshold
    direction = np.sign(funding_rates)
    decay = np.exp(-abs_rates / threshold)
    scores = direction * (1 - extreme.astype(int) * (1 - decay))
    return scores.clip(-1.0, 1.0)


def long_short_ratio_sentiment(
    ratio: float, neutral: float = 1.0, threshold: float = 2.0
) -> float:
    if ratio <= 0:
        return 0.0
    if ratio >= threshold:
        return float(-min((ratio - neutral) / (threshold - neutral), 1.0))
    if ratio <= 1.0 / threshold:
        return float(min((neutral - ratio) / (neutral - 1.0 / threshold), 1.0))
    return float((ratio - neutral) / (threshold - neutral))


def exchange_flow_sentiment(
    net_inflow: pd.Series, threshold: float = 1.0
) -> pd.Series:
    raw = -net_inflow / threshold
    return raw.clip(-1.0, 1.0)


def contrarian_signal(
    sentiment_score: float, extreme_threshold: float = 0.8
) -> str:
    if sentiment_score < -extreme_threshold:
        return "contrarian_buy"
    if sentiment_score > extreme_threshold:
        return "contrarian_sell"
    return "neutral"


def keyword_sentiment(
    texts: list[str],
    positive_keywords: list[str] | None = None,
    negative_keywords: list[str] | None = None,
) -> list[float]:
    pos_words = positive_keywords or DEFAULT_BULLISH_KEYWORDS
    neg_words = negative_keywords or DEFAULT_BEARISH_KEYWORDS

    results: list[float] = []
    for text in texts:
        text_lower = text.lower()
        pos_count = sum(1 for kw in pos_words if kw.lower() in text_lower)
        neg_count = sum(1 for kw in neg_words if kw.lower() in text_lower)
        total = pos_count + neg_count
        if total == 0:
            results.append(0.0)
        else:
            results.append(float((pos_count - neg_count) / total))
    return results


class CompositeSentimentSource:
    def __init__(self) -> None:
        self._sources: list[tuple[str, Callable[[], float], float]] = []

    def add_source(
        self, name: str, signal_fn: Callable[[], float], weight: float = 1.0
    ) -> None:
        self._sources.append((name, signal_fn, weight))

    def compute(self) -> dict[str, Any]:
        if not self._sources:
            return {"composite_score": 0.0, "n_sources": 0, "signals": {}}

        total_weight = 0.0
        weighted_sum = 0.0
        signals: dict[str, float] = {}

        for name, fn, weight in self._sources:
            try:
                val = fn()
            except Exception:
                val = 0.0
            signals[name] = val
            weighted_sum += val * weight
            total_weight += weight

        composite = weighted_sum / total_weight if total_weight > 0 else 0.0

        return {
            "composite_score": round(float(np.clip(composite, -1.0, 1.0)), 4),
            "n_sources": len(self._sources),
            "signals": signals,
        }

    def contrarian(
        self, extreme_threshold: float = 0.8
    ) -> dict[str, Any]:
        result = self.compute()
        score = result["composite_score"]
        result["contrarian"] = contrarian_signal(score, extreme_threshold)
        return result
