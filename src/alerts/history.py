from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func as sa_func

from src.db.models import AlertLog


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
