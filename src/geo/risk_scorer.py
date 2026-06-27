import logging
from typing import Any

logger = logging.getLogger(__name__)


class GeoRiskScorer:
    def __init__(self) -> None:
        self.sanctions_keywords = [
            "санкции",
            "sanctions",
            "ограничения",
            "блокировка",
            "эмбарго",
            "заморозка",
            "активов",
        ]
        self.instability_keywords = [
            "дефолт",
            "кризис",
            "обвал",
            "падение",
            "шок",
            "нестабильность",
            "отток",
            "капитала",
        ]

    def score(self, news_list: list[dict[str, Any]], currency_volatility: float = 0.0) -> dict[str, Any]:
        components = {
            "sanctions_risk": self._count_keywords(news_list, self.sanctions_keywords),
            "instability": self._count_keywords(news_list, self.instability_keywords),
            "currency_stress": min(abs(currency_volatility) * 10, 2.0),
            "volume_anomaly": 0.0,
        }

        raw_score = (
            components["sanctions_risk"]
            + components["instability"]
            + components["currency_stress"]
            + components["volume_anomaly"]
        )

        normalized_score = max(0, min(raw_score, 10.0))

        result: dict[str, Any] = {
            "score": round(normalized_score, 1),
            "level": self._level(normalized_score),
            "components": components,
            "signals": [],
        }

        if components["sanctions_risk"] > 2:
            result["signals"].append(f"высокая активность санкционных новостей ({components['sanctions_risk']:.1f})")
        if components["currency_stress"] > 1:
            result["signals"].append("повышенная волатильность валюты")
        if normalized_score > 7:
            result["signals"].append("⚠️ КРИТИЧЕСКИЙ геополитический риск")
        elif normalized_score > 5:
            result["signals"].append("⚠️ высокий геополитический риск")

        return result

    def _count_keywords(self, news_list: list[dict[str, Any]], keywords: list[str]) -> float:
        if not news_list:
            return 0.0
        count = 0
        for news in news_list:
            text = f"{news.get('title', '')} {news.get('summary', '')}".lower()
            for kw in keywords:
                if kw.lower() in text:
                    count += 1
                    break
        score = (count / max(len(news_list), 1)) * 10
        return min(score, 4.0)

    def _level(self, score: float) -> str:
        if score >= 7:
            return "CRITICAL"
        elif score >= 5:
            return "HIGH"
        elif score >= 3:
            return "MODERATE"
        else:
            return "LOW"
