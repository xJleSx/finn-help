"""LLM-based news classification engine.

Classifies news into:
- Top-level: MACRO, GEOPOLITICAL, SECTOR, COMPANY, MARKET
- Subcategories: monetary_policy, sanctions, energy, conflict, etc.
- Sentiment: positive, negative, neutral
- Impact score: 0-10
"""

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Category hierarchy
CATEGORIES = {
    "MACRO": {
        "description": "Macroeconomic news",
        "subcategories": [
            "monetary_policy",
            "inflation",
            "gdp",
            "unemployment",
            "exchange_rate",
            "interest_rate",
            "fiscal_policy",
        ],
    },
    "GEOPOLITICAL": {
        "description": "Geopolitical events and risks",
        "subcategories": [
            "sanctions",
            "conflict",
            "trade_war",
            "diplomacy",
            "border_dispute",
            "terrorism",
        ],
    },
    "SECTOR": {
        "description": "Sector-specific news",
        "subcategories": [
            "energy",
            "metals",
            "agriculture",
            "banking",
            "retail",
            "tech",
            "healthcare",
            "transport",
            "utilities",
        ],
    },
    "COMPANY": {
        "description": "Company-specific news",
        "subcategories": [
            "earnings",
            "merger_acquisition",
            "management_change",
            "product_launch",
            "regulatory",
            "bankruptcy",
            "stock_split",
        ],
    },
    "MARKET": {
        "description": "General market news",
        "subcategories": [
            "index_movement",
            "volatility",
            "ipo",
            "delisting",
            "earnings_season",
            "market_analysis",
        ],
    },
}

SENTIMENTS = ["positive", "negative", "neutral"]


class NewsClassifier:
    """Classifies news articles into categories with subcategories and sentiment."""

    def __init__(self, llm_provider: Optional[Any] = None):
        """Initialize classifier.

        Args:
            llm_provider: LLM service with .classify() or .chat() method.
                         If None, will use rule-based classification.
        """
        self.llm_provider = llm_provider
        self.categories = CATEGORIES

    def classify_with_llm(
        self, title: str, summary: str, source_name: str = ""
    ) -> dict[str, Any]:
        """Use LLM to classify an article.

        Args:
            title: Article title
            summary: Article summary/content
            source_name: News source name

        Returns:
            Dict with category, subcategory, sentiment, impact_score
        """
        if not self.llm_provider:
            return self._fallback_classification(title, summary)

        categories_str = "\n".join(
            [
                f"  - {cat}: {info['description']}"
                for cat, info in self.categories.items()
            ]
        )

        prompt = f"""Classify this news article:

Title: {title}
Summary: {summary}
Source: {source_name}

Classify into:
1. Top-level category (one of):
{categories_str}

2. Subcategory (specific area within category)
3. Sentiment (positive/negative/neutral)
4. Impact score (0-10, where 10 is extreme market impact)

Return valid JSON (no markdown, no backticks):
{{
  "category": "CATEGORY_NAME",
  "subcategory": "subcategory_name",
  "sentiment": "positive|negative|neutral",
  "impact_score": 5,
  "reasoning": "brief explanation"
}}
"""

        try:
            response = self.llm_provider.chat(prompt)
            result = json.loads(response)

            # Validate response
            if result.get("category") not in self.categories:
                result["category"] = "MACRO"  # Default fallback
            if result.get("sentiment") not in SENTIMENTS:
                result["sentiment"] = "neutral"
            if not isinstance(result.get("impact_score"), (int, float)):
                result["impact_score"] = 5

            return result
        except (json.JSONDecodeError, AttributeError, KeyError) as e:
            logger.warning(f"LLM classification failed: {e}, using fallback")
            return self._fallback_classification(title, summary)

    def _fallback_classification(self, title: str, summary: str) -> dict[str, Any]:
        """Rule-based fallback classification.

        Args:
            title: Article title
            summary: Article summary/content

        Returns:
            Classification dict
        """
        text = f"{title} {summary}".lower()

        # Simple keyword matching for category detection
        category = "MACRO"
        subcategory = ""
        impact_score = 5

        # Geopolitical keywords
        if any(kw in text for kw in ["санкции", "sanctions", "конфликт", "war", "diplomacy"]):
            category = "GEOPOLITICAL"
            if "санкции" in text or "sanctions" in text:
                subcategory = "sanctions"
            elif "конфликт" in text or "war" in text:
                subcategory = "conflict"
            impact_score = 8

        # Sector keywords
        elif any(
            kw in text
            for kw in [
                "нефть",
                "gas",
                "энергия",
                "metals",
                "сельхоз",
                "банк",
                "технолог",
            ]
        ):
            category = "SECTOR"
            if "нефть" in text or "gas" in text:
                subcategory = "energy"
            elif "metals" in text:
                subcategory = "metals"
            impact_score = 6

        # Company keywords
        elif any(
            kw in text
            for kw in [
                "компания",
                "earnings",
                "слияние",
                "merger",
                "ceo",
                "новый продукт",
            ]
        ):
            category = "COMPANY"
            if "earnings" in text:
                subcategory = "earnings"
            elif "merger" in text or "слияние" in text:
                subcategory = "merger_acquisition"
            impact_score = 4

        # Market keywords
        elif any(
            kw in text
            for kw in ["индекс", "index", "волатильность", "ipo", "stock", "падение"]
        ):
            category = "MARKET"
            if "volatility" in text or "волатильность" in text:
                subcategory = "volatility"
            impact_score = 5

        # Monetary policy
        else:
            if any(kw in text for kw in ["ставка", "rate", "инфляция", "inflation"]):
                category = "MACRO"
                if "инфляция" in text or "inflation" in text:
                    subcategory = "inflation"
                else:
                    subcategory = "interest_rate"
                impact_score = 7

        # Sentiment detection
        positive_words = [
            "рост",
            "growth",
            "прибыль",
            "profit",
            "выше",
            "above",
            "восстановление",
        ]
        negative_words = [
            "падение",
            "decline",
            "убыток",
            "loss",
            "ниже",
            "below",
            "кризис",
        ]

        positive_count = sum(1 for w in positive_words if w in text)
        negative_count = sum(1 for w in negative_words if w in text)

        if positive_count > negative_count:
            sentiment = "positive"
        elif negative_count > positive_count:
            sentiment = "negative"
        else:
            sentiment = "neutral"

        return {
            "category": category,
            "subcategory": subcategory,
            "sentiment": sentiment,
            "impact_score": min(10, max(0, impact_score)),
            "reasoning": "Rule-based classification (LLM not available)",
        }

    def classify_article(self, title: str, summary: str, source_name: str = "") -> dict[str, Any]:
        """Classify a single article.

        Args:
            title: Article title
            summary: Article summary/content
            source_name: News source name

        Returns:
            Classification dict
        """
        return self.classify_with_llm(title, summary, source_name)

    def batch_classify(self, articles: list[dict[str, Any]], db_session: Any) -> dict[str, Any]:
        """Classify a batch of articles and update database.

        Args:
            articles: List of article dicts with 'id', 'title', 'summary', 'source_name'
            db_session: Database session

        Returns:
            Stats dict with classification results
        """
        from src.db.models import News

        stats = {
            "total": len(articles),
            "classified": 0,
            "categories": {},
            "sentiments": {"positive": 0, "negative": 0, "neutral": 0},
        }

        for article in articles:
            try:
                classification = self.classify_article(
                    article.get("title", ""),
                    article.get("summary", ""),
                    article.get("source_name", ""),
                )

                # Update database
                news_obj = db_session.query(News).filter(News.id == article.get("id")).first()
                if news_obj:
                    news_obj.category = classification.get("category", "MACRO")
                    news_obj.subcategory = classification.get("subcategory", "")
                    news_obj.sentiment = classification.get("sentiment", "neutral")
                    news_obj.impact_score = classification.get("impact_score", 5)

                    # Count stats
                    category = classification.get("category", "MACRO")
                    stats["categories"][category] = stats["categories"].get(category, 0) + 1
                    sentiment = classification.get("sentiment", "neutral")
                    stats["sentiments"][sentiment] += 1
                    stats["classified"] += 1

            except Exception as e:
                logger.warning(f"Error classifying article {article.get('id')}: {e}")
                continue

        db_session.commit()
        logger.info(f"Classification complete: {stats}")

        return stats
