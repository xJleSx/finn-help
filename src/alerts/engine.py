from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import func as sa_func
from sqlalchemy import select

from src.analysis.anomaly.detector import AnomalyDetector
from src.analysis.ml.news_impact import NewsImpactModel
from src.config import settings
from src.db.models import AlertLog, Instrument, News, NewsInstrument, Portfolio

logger = logging.getLogger(__name__)


class AlertHistory:
    def __init__(self, db: Any | None = None, json_path: str | Path | None = None) -> None:
        self._db = db
        self._json_path = Path(json_path) if json_path else None
        self._memory: list[dict[str, Any]] = []

    def log_alert(self, alert_dict: dict[str, Any]) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": alert_dict.get("priority", alert_dict.get("alert_type", "UNKNOWN")),
            "ticker": alert_dict.get("ticker", ""),
            "severity": alert_dict.get("severity", alert_dict.get("priority_score", 0.0)),
            "message": alert_dict.get("reason", alert_dict.get("message", "")),
            "title": alert_dict.get("title", alert_dict.get("summary", "")),
            "user_id": alert_dict.get("user_id"),
            "read": False,
        }
        if self._db is not None:
            try:
                log = AlertLog(
                    ticker=entry["ticker"],
                    alert_type=entry["type"],
                    severity=float(entry["severity"]),
                    title=entry["title"],
                    message=entry["message"],
                    read=False,
                    user_id=entry["user_id"],
                )
                self._db.add(log)
                self._db.commit()
            except Exception:
                self._db.rollback()
                self._memory.append(entry)
        elif self._json_path:
            self._memory.append(entry)
            self._flush_json()
        else:
            self._memory.append(entry)

    def get_recent(
        self, days: int = 7, ticker: str | None = None, alert_type: str | None = None,
    ) -> list[dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        results: list[dict[str, Any]] = []
        if self._db is not None:
            query = self._db.query(AlertLog).filter(AlertLog.created_at >= cutoff)
            if ticker:
                query = query.filter(AlertLog.ticker == ticker)
            if alert_type:
                query = query.filter(AlertLog.alert_type == alert_type)
            query = query.order_by(AlertLog.created_at.desc())
            results = [
                {
                    "id": r.id,
                    "ticker": r.ticker,
                    "alert_type": r.alert_type,
                    "severity": r.severity,
                    "title": r.title,
                    "message": r.message,
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                    "read": r.read,
                    "user_id": r.user_id,
                }
                for r in query.all()
            ]
        cutoff_str = cutoff.isoformat()
        memory_results = [
            e for e in self._memory
            if e.get("timestamp", "") >= cutoff_str
            and e not in results
        ]
        if ticker:
            memory_results = [e for e in memory_results if e.get("ticker") == ticker]
        if alert_type:
            memory_results = [e for e in memory_results if e.get("type") == alert_type]
        results.extend(memory_results)
        results.sort(key=lambda e: e.get("timestamp", e.get("created_at", "")), reverse=True)
        return results

    def get_stats(self, days: int = 30) -> dict[str, Any]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        if self._db is not None:
            rows = (
                self._db.query(
                    AlertLog.alert_type,
                    sa_func.count(AlertLog.id),
                )
                .filter(AlertLog.created_at >= cutoff)
                .group_by(AlertLog.alert_type)
                .all()
            )
            severity_rows = (
                self._db.query(
                    AlertLog.severity,
                    sa_func.count(AlertLog.id),
                )
                .filter(AlertLog.created_at >= cutoff)
                .group_by(AlertLog.severity)
                .all()
            )
            return {
                "total": sum(r[1] for r in rows),
                "by_type": dict(rows),
                "by_severity": dict(severity_rows),
            }
        cutoff_str = cutoff.isoformat()
        recent = [e for e in self._memory if e.get("timestamp", "") >= cutoff_str]
        by_type: dict[str, int] = defaultdict(int)
        by_severity: dict[str, int] = defaultdict(int)
        for e in recent:
            by_type[e.get("type", "UNKNOWN")] += 1
            sev = e.get("severity", 0)
            if isinstance(sev, (int, float)):
                bucket = "low" if sev < 0.4 else "medium" if sev < 0.7 else "high"
                by_severity[bucket] += 1
        return {
            "total": len(recent),
            "by_type": dict(by_type),
            "by_severity": dict(by_severity),
        }

    def _flush_json(self) -> None:
        if self._json_path:
            self._json_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._json_path, "w", encoding="utf-8") as f:
                json.dump(self._memory, f, ensure_ascii=False, indent=2)


class AlertAggregator:
    def __init__(self, window_minutes: int = 60) -> None:
        self._window = timedelta(minutes=window_minutes)

    def aggregate(self, alerts: list[dict[str, Any]]) -> dict[str, Any]:
        if not alerts:
            return {"summary": "No alerts", "count": 0, "alerts": []}

        now = datetime.now(timezone.utc)
        window_start = now - self._window
        recent = [a for a in alerts if self._parse_ts(a) >= window_start]

        groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for alert in recent:
            cat = alert.get("category", alert.get("alert_type", "GENERAL"))
            ticker = alert.get("ticker", "N/A")
            groups[(cat, ticker)].append(alert)

        summary_parts: list[str] = []
        all_grouped: list[dict[str, Any]] = []
        total_count = 0
        for (cat, ticker), group in groups.items():
            count = len(group)
            total_count += count
            summary_parts.append(f"{count} {cat} alerts about {ticker}")
            all_grouped.extend(group)

        remaining = [a for a in alerts if a not in all_grouped]
        all_grouped.extend(remaining)

        return {
            "summary": "; ".join(summary_parts) if summary_parts else "No recent alerts",
            "count": total_count,
            "alerts": all_grouped,
        }

    @staticmethod
    def _parse_ts(alert: dict[str, Any]) -> datetime:
        raw = alert.get("timestamp", alert.get("created_at", alert.get("published_at", "")))
        if isinstance(raw, datetime):
            return raw
        if isinstance(raw, str):
            try:
                return datetime.fromisoformat(raw)
            except (ValueError, TypeError):
                pass
        return datetime.now(timezone.utc)


class UserAlertPreferences:
    SEVERITY_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}

    def __init__(self, user_id: int | None = None) -> None:
        self.user_id = user_id
        self._db_preferences: dict[int, dict[str, Any]] = {}

    def get_preferences(self, user_id: int, db_session: Any | None = None) -> dict[str, Any]:
        cached = self._db_preferences.get(user_id)
        if cached is not None:
            return cached

        prefs: dict[str, Any] = {
            "min_severity": "LOW",
            "muted_tickers": [],
            "quiet_hours_start": None,
            "quiet_hours_end": None,
        }

        if db_session is not None:
            try:
                from src.db.models import UserSetting

                rows = db_session.query(UserSetting).filter(
                    UserSetting.key.like(f"alert_prefs_{user_id}_%")
                ).all()
                for row in rows:
                    key = row.key.replace(f"alert_prefs_{user_id}_", "")
                    if key == "min_severity":
                        prefs["min_severity"] = row.value
                    elif key == "muted_tickers":
                        prefs["muted_tickers"] = json.loads(row.value)
                    elif key == "quiet_hours_start":
                        prefs["quiet_hours_start"] = row.value
                    elif key == "quiet_hours_end":
                        prefs["quiet_hours_end"] = row.value
            except Exception:
                logger.warning("Failed to load alert prefs for user %d", user_id)

        self._db_preferences[user_id] = prefs
        return prefs

    def filter_alerts(
        self, alerts: list[dict[str, Any]], preferences: dict[str, Any],
    ) -> list[dict[str, Any]]:
        min_severity = preferences.get("min_severity", "LOW")
        muted = set(preferences.get("muted_tickers", []))
        qh_start = preferences.get("quiet_hours_start")
        qh_end = preferences.get("quiet_hours_end")

        min_level = self.SEVERITY_ORDER.get(min_severity, 0)

        now = datetime.now(timezone.utc)
        now_time = now.strftime("%H:%M")

        in_quiet_hours = False
        if qh_start and qh_end:
            if qh_start <= qh_end:
                in_quiet_hours = qh_start <= now_time <= qh_end
            else:
                in_quiet_hours = now_time >= qh_start or now_time <= qh_end

        result = []
        for alert in alerts:
            priority = alert.get("priority", alert.get("severity", "LOW"))
            if isinstance(priority, (int, float)):
                alert_level = 2 if priority >= 0.6 else 1 if priority >= 0.4 else 0
            else:
                alert_level = self.SEVERITY_ORDER.get(priority, 0)
            if alert_level < min_level:
                continue

            ticker = alert.get("ticker", "")
            if ticker in muted:
                continue

            if in_quiet_hours:
                if alert_level < 3:
                    continue

            result.append(alert)

        return result

    def clear_cache(self, user_id: int | None = None) -> None:
        if user_id:
            self._db_preferences.pop(user_id, None)
        else:
            self._db_preferences.clear()


class AlertPushService:
    def __init__(self) -> None:
        self._subscribers: dict[str, Callable[[dict[str, Any]], None]] = {}

    def subscribe(self, client_id: str) -> None:
        def _noop(alert: dict[str, Any]) -> None:
            pass

        self._subscribers[client_id] = _noop
        logger.info("AlertPushService: client %s subscribed", client_id)

    def unsubscribe(self, client_id: str) -> None:
        self._subscribers.pop(client_id, None)
        logger.info("AlertPushService: client %s unsubscribed", client_id)

    def publish(self, alert: dict[str, Any]) -> None:
        logger.info(
            "AlertPushService: publishing alert for %s — %s",
            alert.get("ticker", "N/A"),
            alert.get("reason", alert.get("message", "")),
        )
        for client_id, handler in self._subscribers.items():
            try:
                handler(alert)
            except Exception:
                logger.exception(
                    "AlertPushService: handler for %s failed", client_id
                )

    def broadcast(self, alerts: list[dict[str, Any]]) -> None:
        for alert in alerts:
            self.publish(alert)


class AlertDeduplicator:
    def __init__(self, hours: int = 24) -> None:
        self._hours = hours
        self._seen: dict[str, datetime] = {}

    def is_duplicate(self, article: News) -> bool:
        key = f"{article.category}:{article.subcategory}:{article.source_name}"
        now = datetime.now(timezone.utc)
        last = self._seen.get(key)
        if last and (now - last).total_seconds() < self._hours * 3600:
            return True
        self._seen[key] = now
        return False

    def reset(self) -> None:
        self._seen.clear()


class AlertTimer:
    def __init__(self, cooldown_minutes: int = 60) -> None:
        self._cooldown = cooldown_minutes
        self._last_sent: dict[str, datetime] = {}

    def can_send(self, ticker: str) -> bool:
        now = datetime.now(timezone.utc)
        last = self._last_sent.get(ticker)
        if last and (now - last).total_seconds() < self._cooldown * 60:
            return False
        self._last_sent[ticker] = now
        return True

    def reset(self) -> None:
        self._last_sent.clear()


class AlertEngine:
    def __init__(self) -> None:
        self.anomaly_detector = AnomalyDetector()
        self._anomaly_trained = False
        self._trained_tickers: set[str] = set()
        self.deduplicator = AlertDeduplicator(settings.alert_dedup_hours)
        self.timer = AlertTimer(settings.alert_cooldown_minutes)

    def train_anomaly(self, db: Any) -> dict[str, Any]:
        result = self.anomaly_detector.train_all(db)
        self._anomaly_trained = any(
            v.get("trained", False) for v in result.values()
        )
        return result

    def train_impact(self, db: Any, tickers: list[str] | None = None) -> dict[str, Any]:
        if tickers is None:
            rows = db.execute(select(Instrument.ticker)).all()
            tickers = [r[0] for r in rows]
        results: dict[str, Any] = {}
        for ticker in tickers:
            model = NewsImpactModel(ticker)
            result = model.train(db)
            if result.get("trained"):
                self._trained_tickers.add(ticker)
            results[ticker] = result
        return results

    def process_articles(
        self, db: Any, articles: list[News], portfolio_tickers: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        if portfolio_tickers is None:
            portfolio_tickers = set()

        candidates: list[dict[str, Any]] = []
        for article in articles:
            if self.deduplicator.is_duplicate(article):
                continue

            tickers = self._article_tickers(db, article)
            if not tickers:
                continue

            anomaly = (
                self.anomaly_detector.predict_article(db, article)
                if self._anomaly_trained
                else {"anomaly_score": 0.0, "is_anomaly": False, "details": {}}
            )

            for ticker in tickers:
                if not self.timer.can_send(ticker):
                    continue

                impact = self._predict_impact(db, article, ticker)
                in_portfolio = ticker in portfolio_tickers
                alert = self._build_alert(article, ticker, anomaly, impact, in_portfolio)
                candidates.append(alert)

        candidates.sort(key=lambda a: a["priority_score"], reverse=True)
        return candidates[: settings.alert_max_alerts_per_run]

    def process_portfolio_articles(
        self, db: Any, articles: list[News], user_id: int = 0,
    ) -> list[dict[str, Any]]:
        rows = (
            db.execute(
                select(Instrument.ticker)
                .join(Portfolio, Portfolio.instrument_id == Instrument.id)
                .where(Portfolio.user_id == user_id)
            )
            .all()
        )
        portfolio_tickers = {r[0] for r in rows}
        return self.process_articles(db, articles, portfolio_tickers)

    def _article_tickers(self, db: Any, article: News) -> list[str]:
        rows = (
            db.execute(
                select(Instrument.ticker)
                .join(NewsInstrument, NewsInstrument.instrument_id == Instrument.id)
                .where(NewsInstrument.news_id == article.id)
            )
            .all()
        )
        return [r[0] for r in rows]

    def _predict_impact(self, db: Any, article: News, ticker: str) -> dict[str, Any]:
        if ticker not in self._trained_tickers:
            return {"predicted_return": 0.0, "confidence": 0.0, "model_loaded": False}
        model = NewsImpactModel(ticker)
        return model.predict(db, article, horizon_days=1)

    def _build_alert(
        self, article: News, ticker: str,
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

        priority, reason = self._classify(anomaly_score, pred_return, in_portfolio)

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

    def _classify(
        self, anomaly_score: float, pred_return: float, in_portfolio: bool,
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

    def reset(self) -> None:
        self.deduplicator.reset()
        self.timer.reset()
