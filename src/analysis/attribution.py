from __future__ import annotations

import logging
from typing import Any

import numpy as np

from src.analysis.ml.news_impact import NewsImpactModel
from src.analysis.ml.news_impact_features import ALL_FEATURE_COLS, extract_features

logger = logging.getLogger(__name__)

try:
    import shap
except ImportError:
    shap = None


class NewsAttribution:
    def __init__(self, model: NewsImpactModel) -> None:
        self._model = model
        self._explainers: dict[int, Any] = {}

    def _get_explainer(self, horizon_days: int) -> Any:
        if horizon_days in self._explainers:
            return self._explainers[horizon_days]
        xgb_model = self._model._models.get(horizon_days)
        if xgb_model is None:
            try:
                xgb_model = self._model.load(horizon_days)
            except (ValueError, FileNotFoundError):
                return None
        if shap is not None:
            try:
                explainer = shap.TreeExplainer(xgb_model)
                self._explainers[horizon_days] = explainer
                return explainer
            except Exception:
                pass
        return None

    def explain(
        self, db: Any, news_article: Any, horizon_days: int = 1,
    ) -> list[dict[str, Any]]:
        features = extract_features(db, news_article)
        vec = np.array(
            [features.get(c, 0.0) for c in ALL_FEATURE_COLS],
            dtype=np.float32,
        ).reshape(1, -1)

        explainer = self._get_explainer(horizon_days)
        if explainer is not None and shap is not None:
            try:
                shap_values = explainer.shap_values(vec)
                vals = shap_values[0] if shap_values.ndim > 1 else shap_values
                attributions = [
                    {
                        "feature": ALL_FEATURE_COLS[i],
                        "importance": round(float(abs(vals[i])), 6),
                        "sign": "positive" if vals[i] > 0 else "negative",
                    }
                    for i in range(len(ALL_FEATURE_COLS))
                ]
                attributions.sort(key=lambda x: x["importance"], reverse=True)
                return attributions
            except Exception:
                pass

        return self._coefficient_attribution(horizon_days)

    def _coefficient_attribution(self, horizon_days: int) -> list[dict[str, Any]]:
        xgb_model = self._model._models.get(horizon_days)
        if xgb_model is None:
            try:
                xgb_model = self._model.load(horizon_days)
            except (ValueError, FileNotFoundError):
                return []
        try:
            scores = xgb_model.feature_importances_
            indices = np.argsort(np.abs(scores))[::-1]
            return [
                {
                    "feature": ALL_FEATURE_COLS[i],
                    "importance": round(float(abs(scores[i])), 6),
                    "sign": "positive" if scores[i] > 0 else "negative",
                }
                for i in indices
            ]
        except Exception:
            return []

    def summary_stats(
        self, db: Any, ticker: str, n_articles: int = 100,
    ) -> dict[str, float]:
        from src.analysis.ml.news_impact_features import build_training_data

        df = build_training_data(db, ticker, max_articles=n_articles)
        if df.empty:
            return {}

        if shap is None:
            return self._coefficient_summary()

        all_importances: dict[str, list[float]] = {}
        for h in self._model.horizons:
            explainer = self._get_explainer(h)
            if explainer is None:
                continue
            for _, row in df.iterrows():
                vec = np.array(
                    [row.get(c, 0.0) for c in ALL_FEATURE_COLS],
                    dtype=np.float32,
                ).reshape(1, -1)
                try:
                    sv = explainer.shap_values(vec)
                    vals = sv[0] if sv.ndim > 1 else sv
                    for i, name in enumerate(ALL_FEATURE_COLS):
                        all_importances.setdefault(name, []).append(float(abs(vals[i])))
                except Exception:
                    continue

        result: dict[str, float] = {}
        for feature, vals in all_importances.items():
            result[feature] = round(float(np.mean(vals)), 6)
        return result

    def _coefficient_summary(self) -> dict[str, float]:
        for h in self._model.horizons:
            xgb_model = self._model._models.get(h)
            if xgb_model is None:
                try:
                    xgb_model = self._model.load(h)
                except (ValueError, FileNotFoundError):
                    continue
            try:
                scores = xgb_model.feature_importances_
                return {
                    ALL_FEATURE_COLS[i]: round(float(abs(scores[i])), 6)
                    for i in range(len(ALL_FEATURE_COLS))
                }
            except Exception:
                continue
        return {}
