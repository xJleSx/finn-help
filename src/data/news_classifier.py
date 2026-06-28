"""LLM-based news classification engine with hierarchical categories.

Hierarchy:
  Level 0: MACRO, GEOPOLITICAL, SECTOR, COMPANY, MARKET
  Level 1: subcategory within parent
  Level 2: sub-subcategory (fine-grained)
- Sentiment: positive, negative, neutral
- Impact score: 0-10
"""

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

CATEGORY_HIERARCHY = {
    "MACRO": {
        "description": "Macroeconomic news",
        "children": {
            "monetary_policy": {
                "description": "Central bank decisions",
                "children": {
                    "central_bank_rate": "Interest rate changes",
                    "quantitative_easing": "QE / tightening programs",
                },
            },
            "inflation": {
                "description": "Inflation data and trends",
                "children": {
                    "cpi": "Consumer price index",
                    "ppi": "Producer price index",
                },
            },
            "gdp": {"description": "GDP growth and forecasts"},
            "unemployment": {"description": "Employment and labor market"},
            "exchange_rate": {"description": "Currency exchange rates"},
            "fiscal_policy": {
                "description": "Government fiscal policy",
                "children": {
                    "government_spending": "Budget spending",
                    "taxation": "Tax policy changes",
                },
            },
        },
    },
    "GEOPOLITICAL": {
        "description": "Geopolitical events and risks",
        "children": {
            "sanctions": {"description": "International sanctions"},
            "conflict": {
                "description": "Military conflicts and disputes",
                "children": {
                    "military_action": "Military operations",
                    "cyber_attack": "Cyber warfare",
                },
            },
            "trade_war": {"description": "Trade disputes and tariffs"},
            "diplomacy": {"description": "Diplomatic relations"},
            "border_dispute": {"description": "Border conflicts"},
            "terrorism": {"description": "Terrorist acts"},
        },
    },
    "SECTOR": {
        "description": "Sector-specific news",
        "children": {
            "energy": {
                "description": "Energy sector",
                "children": {
                    "oil_gas": "Oil and gas",
                    "renewable": "Renewable energy",
                    "nuclear": "Nuclear energy",
                },
            },
            "metals_mining": {
                "description": "Metals and mining",
                "children": {
                    "precious_metals": "Gold, silver, etc.",
                    "industrial_metals": "Steel, copper, etc.",
                },
            },
            "agriculture": {"description": "Agriculture sector"},
            "banking": {"description": "Banking and finance"},
            "retail": {"description": "Retail sector"},
            "technology": {
                "description": "Technology sector",
                "children": {
                    "software": "Software and services",
                    "hardware": "Hardware and devices",
                    "telecom": "Telecommunications",
                },
            },
            "healthcare": {
                "description": "Healthcare sector",
                "children": {
                    "pharmaceuticals": "Drug companies",
                    "biotech": "Biotechnology",
                },
            },
            "transport": {
                "description": "Transport sector",
                "children": {
                    "aviation": "Airlines",
                    "railway": "Rail transport",
                    "shipping": "Maritime transport",
                },
            },
            "utilities": {"description": "Utilities sector"},
        },
    },
    "COMPANY": {
        "description": "Company-specific news",
        "children": {
            "earnings": {
                "description": "Financial results",
                "children": {
                    "quarterly_results": "Quarterly earnings",
                    "annual_report": "Annual report",
                },
            },
            "merger_acquisition": {"description": "M&A activity"},
            "management_change": {
                "description": "Management changes",
                "children": {
                    "ceo_change": "CEO changes",
                    "board_change": "Board changes",
                },
            },
            "product_launch": {"description": "New product announcements"},
            "regulatory": {
                "description": "Regulatory matters",
                "children": {
                    "compliance": "Regulatory compliance",
                    "investigation": "Regulatory investigations",
                },
            },
            "bankruptcy": {"description": "Bankruptcy proceedings"},
            "stock_split": {"description": "Stock splits / buybacks"},
            "dividend": {
                "description": "Dividend announcements",
                "children": {
                    "dividend_increase": "Dividend hike",
                    "dividend_cut": "Dividend reduction",
                },
            },
        },
    },
    "MARKET": {
        "description": "General market news",
        "children": {
            "index_movement": {"description": "Index movements"},
            "volatility": {"description": "Market volatility"},
            "ipo": {"description": "IPOs and listings"},
            "delisting": {"description": "Delistings"},
            "earnings_season": {"description": "Earnings season overview"},
            "market_analysis": {"description": "Market analysis"},
            "bond_market": {"description": "Bond market"},
            "commodity_market": {"description": "Commodity market"},
        },
    },
}

SENTIMENTS = ["positive", "negative", "neutral"]


def _get_flat_subcategories() -> dict[str, dict[str, str]]:
    result = {}
    for parent, info in CATEGORY_HIERARCHY.items():
        for sub, sub_info in info.get("children", {}).items():
            result[f"{parent}:{sub}"] = {"description": sub_info["description"]}
            for subsub, subsub_desc in sub_info.get("children", {}).items():
                result[f"{parent}:{sub}:{subsub}"] = {"description": subsub_desc}
    return result


def _expand_keywords(keywords: list[str]) -> list[str]:
    return keywords + [kw.lower() for kw in keywords]

HIERARCHY_KEYWORDS = {
    "MACRO": _expand_keywords(["макро", "macro", "ввп", "gdp", "инфляци", "inflation", "ставк", "rate", "ключев"]),
    "monetary_policy": _expand_keywords(["ставк", "rate", "ключев", "цб", "central bank"]),
    "central_bank_rate": _expand_keywords(["ставк", "rate hike", "rate cut"]),
    "quantitative_easing": _expand_keywords(["qe", "quantitative easing", "программа"]),
    "inflation": _expand_keywords(["инфляци", "inflation", "cpi", "ppi"]),
    "cpi": _expand_keywords(["cpi", "потребительские цены"]),
    "ppi": _expand_keywords(["ppi", "цен производителей"]),
    "gdp": _expand_keywords(["ввп", "gdp", "валовый"]),
    "unemployment": _expand_keywords(["безработиц", "unemployment", "занятость"]),
    "exchange_rate": _expand_keywords(["курс", "рубл", "exchange", "валют"]),
    "fiscal_policy": _expand_keywords(["бюджет", "налог", "fiscal", "tax"]),
    "government_spending": _expand_keywords(["бюджетные расходы", "spending"]),
    "taxation": _expand_keywords(["налог", "tax rate", "ндс", "налогов"]),
    "GEOPOLITICAL": _expand_keywords(["санкции", "sanctions", "конфликт", "война", "war", "кибер", "дипломат"]),
    "sanctions": _expand_keywords(["санкции", "sanctions", "эмбарго"]),
    "conflict": _expand_keywords(["конфликт", "воен", "military", "война", "war", "кибер"]),
    "military_action": _expand_keywords(["воен", "military", "операция"]),
    "cyber_attack": _expand_keywords(["кибер", "hack", "атак"]),
    "trade_war": _expand_keywords(["пошлин", "tariff", "торгов"]),
    "diplomacy": _expand_keywords(["дипломат", "переговор", "meeting"]),
    "SECTOR": _expand_keywords(["нефть", "oil", "gas", "энерго", "банк", "tech", "gold", "золот", "metal", "металл"]),
    "energy": _expand_keywords(["нефть", "oil", "газ", "gas", "энерго"]),
    "oil_gas": _expand_keywords(["нефть", "oil", "газ", "gas", "бензин"]),
    "renewable": _expand_keywords(["возобнов", "renewable", "солнеч", "ветр"]),
    "nuclear": _expand_keywords(["атом", "nuclear", "аэс"]),
    "metals_mining": _expand_keywords(["металл", "metal", "gold", "золот", "steel", "сталь"]),
    "precious_metals": _expand_keywords(["gold", "золот", "silver", "серебр", "платин"]),
    "industrial_metals": _expand_keywords(["steel", "сталь", "copper", "медь", "алюмин"]),
    "agriculture": _expand_keywords(["сельхоз", "agriculture", "зерн", "wheat"]),
    "banking": _expand_keywords(["банк", "bank", "ипотек", "mortgage"]),
    "retail": _expand_keywords(["retail", "розниц", "wildberries", "ozon", "магазин"]),
    "technology": _expand_keywords(["tech", "технолог", "software", "программ", "it"]),
    "software": _expand_keywords(["software", "программ", "saas"]),
    "hardware": _expand_keywords(["hardware", "желез", "processor", "чип"]),
    "telecom": _expand_keywords(["telecom", "связ", "мобильн", "интернет"]),
    "healthcare": _expand_keywords(["health", "medical", "медицин", "фарм"]),
    "pharmaceuticals": _expand_keywords(["фарма", "pharma", "лекарств"]),
    "biotech": _expand_keywords(["biotech", "биотех"]),
    "transport": _expand_keywords(["transport", "транспорт", "авиа", "rail"]),
    "aviation": _expand_keywords(["авиа", "avia", "airline"]),
    "railway": _expand_keywords(["жд", "railway", "ржд", "поезд"]),
    "shipping": _expand_keywords(["shipping", "мор", "судоход", "порт"]),
    "utilities": _expand_keywords(["utility", "электроэнер", "электр"]),
    "COMPANY": _expand_keywords(["компания", "company", "акци", "корпора"]),
    "earnings": _expand_keywords(["earnings", "прибыль", "profit", "финрезульт", "отчет"]),
    "quarterly_results": _expand_keywords(["quarterly", "квартал"]),
    "annual_report": _expand_keywords(["годовой", "annual", "годовой отчет"]),
    "merger_acquisition": _expand_keywords(["merger", "слия", "поглощ", "acquisition"]),
    "management_change": _expand_keywords(["ceo", "management", "назначен", "уволен", "гендир"]),
    "ceo_change": _expand_keywords(["ceo", "гендиректор", "президент компании"]),
    "board_change": _expand_keywords(["board", "совет директор"]),
    "product_launch": _expand_keywords(["новый продукт", "запуск", "launch"]),
    "regulatory": _expand_keywords(["регулятор", "regulatory", "fda", "цб"]),
    "compliance": _expand_keywords(["compliance", "соответствие"]),
    "investigation": _expand_keywords(["расследова", "investigation", "проверка"]),
    "bankruptcy": _expand_keywords(["bankruptcy", "банкрот", "дефолт"]),
    "stock_split": _expand_keywords(["stock split", "buyback", "обратный выкуп"]),
    "dividend": _expand_keywords(["dividend", "дивиденд"]),
    "dividend_increase": _expand_keywords(["повысил дивиденд", "увеличил дивиден"]),
    "dividend_cut": _expand_keywords(["сократил дивиденд", "отменил дивиден"]),
    "MARKET": _expand_keywords(["рынок", "market", "индекс", "index"]),
    "index_movement": _expand_keywords(["индекс", "imoex", "rts", "s&p"]),
    "volatility": _expand_keywords(["волатиль", "volatility", "нестабиль"]),
    "ipo": _expand_keywords(["ipo", "размещен", "public offering"]),
    "delisting": _expand_keywords(["delisting", "делистинг"]),
    "earnings_season": _expand_keywords(["earnings season", "сезон отчет"]),
    "market_analysis": _expand_keywords(["анализ", "аналитик", "прогноз"]),
    "bond_market": _expand_keywords(["облигаци", "bond", "офз"]),
    "commodity_market": _expand_keywords(["commodity", "сырь"]),
}


CATEGORIES = {k: {"description": v["description"]} for k, v in CATEGORY_HIERARCHY.items()}


class NewsClassifier:
    """Classifies news articles into hierarchical categories with subcategories and sentiment."""

    def __init__(self, llm_provider: Optional[Any] = None):
        self.llm_provider = llm_provider
        self.categories = CATEGORIES

    # --- Hierarchy helpers ---

    @staticmethod
    def get_parent_category(subcategory: str) -> Optional[str]:
        for parent, info in CATEGORY_HIERARCHY.items():
            if subcategory in info.get("children", {}):
                return parent
        return None

    @staticmethod
    def get_children(category: str) -> list[str]:
        info = CATEGORY_HIERARCHY.get(category, {})
        return list(info.get("children", {}).keys())

    @staticmethod
    def get_subsubcategories(category: str, subcategory: str) -> list[str]:
        info = CATEGORY_HIERARCHY.get(category, {})
        sub_info = info.get("children", {}).get(subcategory)
        if sub_info:
            return list(sub_info.get("children", {}).keys())
        return []

    @staticmethod
    def get_full_path(category: str, subcategory: str = "", subsubcategory: str = "") -> str:
        parts = [category]
        if subcategory:
            parts.append(subcategory)
        if subsubcategory:
            parts.append(subsubcategory)
        return "/".join(parts)

    @staticmethod
    def get_all_categories() -> dict[str, list[str]]:
        result = {}
        for parent, info in CATEGORY_HIERARCHY.items():
            children = list(info.get("children", {}).keys())
            result[parent] = children
        return result

    @staticmethod
    def get_description(path: str) -> str:
        parts = path.split("/")
        parent = parts[0]
        info = CATEGORY_HIERARCHY.get(parent)
        if not info:
            return ""
        if len(parts) == 1:
            return info["description"]
        sub_info = info.get("children", {}).get(parts[1])
        if not sub_info:
            return ""
        if len(parts) == 2:
            return sub_info.get("description", "")
        subsub_desc = sub_info.get("children", {}).get(parts[2])
        return subsub_desc if subsub_desc else ""

    # --- Classification ---

    def classify_with_llm(
        self, title: str, summary: str, source_name: str = ""
    ) -> dict[str, Any]:
        if not self.llm_provider:
            return self._fallback_classification(title, summary)

        cats_lines = "\n".join(
            f"  - {cat}: {info['description']}" for cat, info in self.categories.items()
        )

        prompt = f"""Classify this news article:

Title: {title}
Summary: {summary}
Source: {source_name}

Classify into:
1. Top-level category (one of):
{cats_lines}

2. Subcategory (specific area within category)
3. Sub-subcategory (fine-grained topic, optional)
4. Sentiment (positive/negative/neutral)
5. Impact score (0-10, where 10 is extreme market impact)

Return valid JSON (no markdown, no backticks):
{{
  "category": "CATEGORY_NAME",
  "subcategory": "subcategory_name",
  "subsubcategory": "subsubcategory_name",
  "sentiment": "positive|negative|neutral",
  "impact_score": 5,
  "reasoning": "brief explanation"
}}
"""

        try:
            response = self.llm_provider.chat(prompt)
            result = json.loads(response)

            if result.get("category") not in self.categories:
                result["category"] = "MACRO"
            if result.get("sentiment") not in SENTIMENTS:
                result["sentiment"] = "neutral"
            if not isinstance(result.get("impact_score"), (int, float)):
                result["impact_score"] = 5

            return result
        except (json.JSONDecodeError, AttributeError, KeyError) as e:
            logger.warning(f"LLM classification failed: {e}, using fallback")
            return self._fallback_classification(title, summary)

    def _fallback_classification(self, title: str, summary: str) -> dict[str, Any]:
        text = f"{title} {summary}".lower()

        fallback = self._hierarchical_fallback(text)
        category = fallback["category"]
        subcategory = fallback["subcategory"]
        subsubcategory = fallback["subsubcategory"]

        impact_map = {
            "GEOPOLITICAL": 8,
            "MACRO": 7,
            "SECTOR": 6,
            "MARKET": 5,
            "COMPANY": 4,
        }
        impact_score = impact_map.get(category, 5)

        positive_count = sum(1 for w in _expand_keywords(
            ["рост", "growth", "прибыль", "profit", "выше", "above", "восстановление",
             "увелич", "increase", "повыш"]
        ) if w in text)
        negative_count = sum(1 for w in _expand_keywords(
            ["падение", "decline", "убыток", "loss", "ниже", "below", "кризис",
             "сократ", "уменьш"]
        ) if w in text)

        if positive_count > negative_count:
            sentiment = "positive"
        elif negative_count > positive_count:
            sentiment = "negative"
        else:
            sentiment = "neutral"

        return {
            "category": category,
            "subcategory": subcategory,
            "subsubcategory": subsubcategory,
            "sentiment": sentiment,
            "impact_score": min(10, max(0, impact_score)),
            "reasoning": "Rule-based hierarchical classification (LLM not available)",
        }

    def _hierarchical_fallback(self, text: str) -> dict[str, str]:
        cat = "MACRO"
        sub = ""
        subsub = ""

        # Score each category
        cat_scores = {}
        for parent in CATEGORY_HIERARCHY:
            kw = HIERARCHY_KEYWORDS.get(parent, [])
            cat_scores[parent] = sum(2 for k in kw if k in text) if kw else 0

        if any(v > 0 for v in cat_scores.values()):
            cat = max(cat_scores, key=cat_scores.get)

        # Score subcategories within selected parent
        parent_info = CATEGORY_HIERARCHY.get(cat, {})
        sub_scores = {}
        for sub_name, sub_info in parent_info.get("children", {}).items():
            kw = HIERARCHY_KEYWORDS.get(sub_name, [])
            sub_scores[sub_name] = sum(2 for k in kw if k in text) if kw else 0

        if any(v > 0 for v in sub_scores.values()):
            sub = max(sub_scores, key=sub_scores.get)

        # Score subsubcategories within selected subcategory
        if sub:
            sub_info = parent_info.get("children", {}).get(sub, {})
            subsub_scores = {}
            for subsub_name in sub_info.get("children", {}):
                kw = HIERARCHY_KEYWORDS.get(subsub_name, [])
                subsub_scores[subsub_name] = sum(2 for k in kw if k in text) if kw else 0
            if any(v > 0 for v in subsub_scores.values()):
                subsub = max(subsub_scores, key=subsub_scores.get)

        return {"category": cat, "subcategory": sub, "subsubcategory": subsub}

    def classify_hierarchical(
        self, title: str, summary: str, source_name: str = ""
    ) -> dict[str, Any]:
        result = self.classify_with_llm(title, summary, source_name)
        subsub = result.get("subsubcategory", "")

        path = self.get_full_path(
            result["category"], result.get("subcategory", ""), subsub
        )
        result["hierarchy_path"] = path
        return result

    def classify_article(self, title: str, summary: str, source_name: str = "") -> dict[str, Any]:
        return self.classify_with_llm(title, summary, source_name)

    def batch_classify(self, articles: list[dict[str, Any]], db_session: Any) -> dict[str, Any]:
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

                news_obj = db_session.query(News).filter(News.id == article.get("id")).first()
                if news_obj:
                    news_obj.category = classification.get("category", "MACRO")
                    news_obj.subcategory = classification.get("subcategory", "")
                    news_obj.sentiment = classification.get("sentiment", "neutral")
                    news_obj.impact_score = classification.get("impact_score", 5)

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
