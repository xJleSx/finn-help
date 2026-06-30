from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import numpy as np
from scipy.stats import ks_2samp

from sqlalchemy import func

from src.db.connection import get_session
from src.db.models import FeatureCache, Price
from src.analysis.feature_store import FEATURE_TYPE_TTL, bump_version, invalidate

logger = logging.getLogger(__name__)

DRIFT_THRESHOLD_DEFAULT = 0.15
DEFAULT_WINDOW_DAYS = 30


def detect_drift(
    feature_type: str,
    window_days: int = DEFAULT_WINDOW_DAYS,
    threshold: float = DRIFT_THRESHOLD_DEFAULT,
) -> list[dict[str, Any]]:
    drift_results: list[dict[str, Any]] = []
    db = get_session()
    try:
        cutoff = date.today() - timedelta(days=window_days)
        rows = (
            db.query(FeatureCache)
            .filter(
                FeatureCache.feature_type == feature_type,
                FeatureCache.date >= cutoff,
            )
            .order_by(FeatureCache.date)
            .all()
        )
        if len(rows) < 4:
            return drift_results

        by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_ticker[row.ticker].append({"date": row.date, "value": row.value_json})

        for ticker, entries in by_ticker.items():
            if len(entries) < 4:
                continue

            keys = _collect_numeric_keys(entries[0]["value"])
            if not keys:
                continue

            mid = len(entries) // 2
            recent = _extract_vectors(entries[mid:], keys)
            older = _extract_vectors(entries[:mid], keys)

            for key in keys:
                if key not in recent or key not in older:
                    continue
                r_vec = recent[key]
                o_vec = older[key]
                if len(r_vec) < 3 or len(o_vec) < 3:
                    continue
                try:
                    stat, p_value = ks_2samp(r_vec, o_vec)
                    drift_score = max(0.0, min(1.0, 1.0 - p_value))
                    if drift_score > threshold:
                        drift_results.append(
                            {
                                "ticker": ticker,
                                "feature_type": feature_type,
                                "field": key,
                                "drift_score": round(drift_score, 4),
                                "p_value": round(p_value, 4),
                                "samples_recent": len(r_vec),
                                "samples_older": len(o_vec),
                            }
                        )
                except Exception:
                    continue
    finally:
        db.close()
    return drift_results


def auto_handle_drift(
    feature_type: str,
    threshold: float = DRIFT_THRESHOLD_DEFAULT,
    max_fields_drifted: int = 3,
) -> list[dict[str, Any]]:
    drifts = detect_drift(feature_type, threshold=threshold)
    tickers_to_invalidate: set[str] = set()
    fields_drifted: dict[str, int] = defaultdict(int)

    for d in drifts:
        fields_drifted[d["ticker"]] += 1

    for ticker, count in fields_drifted.items():
        if count >= max_fields_drifted:
            tickers_to_invalidate.add(ticker)

    if tickers_to_invalidate:
        bump_version(feature_type)
        for ticker in tickers_to_invalidate:
            invalidate(ticker, feature_type)
            logger.info("Auto-invalidated %s/%s due to drift", ticker, feature_type)

    return drifts


def _collect_numeric_keys(value: dict[str, Any], prefix: str = "") -> list[str]:
    keys: list[str] = []
    for k, v in value.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys.extend(_collect_numeric_keys(v, full_key))
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            keys.append(full_key)
    return keys


def _extract_vectors(entries: list[dict[str, Any]], keys: list[str]) -> dict[str, list[float]]:
    result: dict[str, list[float]] = defaultdict(list)
    for entry in entries:
        val = entry["value"]
        for key in keys:
            parts = key.split(".")
            current = val
            try:
                for p in parts:
                    current = current[p]
                if isinstance(current, (int, float)):
                    result[key].append(float(current))
            except (KeyError, TypeError):
                continue
    return dict(result)


def summary() -> dict[str, Any]:
    db = get_session()
    try:
        active_feature_types = (
            db.query(FeatureCache.feature_type, func.count(FeatureCache.id))
            .group_by(FeatureCache.feature_type)
            .all()
        )
        return {
            "feature_types": {row[0]: row[1] for row in active_feature_types},
            "drift_threshold": DRIFT_THRESHOLD_DEFAULT,
            "window_days": DEFAULT_WINDOW_DAYS,
        }
    finally:
        db.close()
