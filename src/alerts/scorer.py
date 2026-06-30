from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.config import settings
from src.db.models import News


def build_alert(
    article: News, ticker: str,
    anomaly: dict[str, Any], impact: dict[str, Any],
    in_portfolio: bool,
) -> dict[str, Any]:
    anomaly_score = anomaly.get("anomaly_score", 0.0)
    pred_return = impact.get("predicted_return", 0.0)
    impact_conf = impact.get("confidence", 0.0)
    impact_magnitude = min(abs(pred_return) * 20.0, 1.0)

    now = datetime.now(timezone.utc)
    published = article.published_at or now
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    hours_ago = (now - published).total_seconds() / 3600.0
    recency_score = max(0.0, 1.0 - hours_ago / 48.0)

    portfolio_score = 1.0 if in_portfolio else 0.3

    raw_score = (
        anomaly_score * settings.alert_weight_anomaly
        + impact_magnitude * settings.alert_weight_impact
        + portfolio_score * settings.alert_weight_portfolio
        + recency_score * settings.alert_weight_recency
    )

    priority, reason = classify_priority(anomaly_score, pred_return, in_portfolio)

    return {
        "news_id": article.id,
        "ticker": ticker,
        "title": article.title or "",
        "category": article.category or "",
        "subcategory": article.subcategory or "",
        "source_name": article.source_name or "",
        "published_at": published.isoformat(),
        "priority": priority,
        "priority_score": round(raw_score, 4),
        "anomaly_score": round(anomaly_score, 4),
        "predicted_return": round(pred_return, 4),
        "impact_confidence": round(impact_conf, 4),
        "in_portfolio": in_portfolio,
        "reason": reason,
    }


def classify_priority(
    anomaly_score: float, pred_return: float, in_portfolio: bool,
) -> tuple[str, str]:
    reasons: list[str] = []
    if anomaly_score >= 0.5:
        reasons.append(f"anomaly detected ({anomaly_score:.2f})")
    if abs(pred_return) >= settings.alert_min_impact_abs:
        direction = "positive" if pred_return > 0 else "negative"
        reasons.append(f"predicted {direction} return of {pred_return:.2%}")
    if in_portfolio:
        reasons.append("in your portfolio")

    abs_return = abs(pred_return)
    if anomaly_score >= settings.alert_critical_threshold or (
        in_portfolio and abs_return >= 0.02 and anomaly_score >= 0.5
    ):
        return "CRITICAL", "; ".join(reasons) if reasons else "high anomaly score"
    if anomaly_score >= settings.alert_high_threshold or (
        abs_return >= 0.01 and in_portfolio
    ):
        return "HIGH", "; ".join(reasons) if reasons else "elevated anomaly score"
    if anomaly_score >= settings.alert_medium_threshold or abs_return >= 0.005:
        return "MEDIUM", "; ".join(reasons) if reasons else "moderate signal"
    return "LOW", "; ".join(reasons) if reasons else "low priority"
