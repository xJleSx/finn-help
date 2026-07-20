from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

TOPIC_KEYWORDS: dict[str, list[str]] = {
    "macro": [
        "инфляци", "ключевая ставк", "цб", "центральн банк", "ввп", "курс рубл",
        "санкци", "эмбарго", "рецесси", "дефолт",
        "индекс делов", "промышлен", "безработиц", "ипц", "м2",
    ],
    "tech": [
        "ии", "ai", "искусственн интеллект", "нейросет", "gpt", "llm",
        "робот", "автоматизаци", "блокчейн", "криптовалют", "биткоин",
        "импортозамещен", "софт", "программн обеспечен",
    ],
    "oil_gas": [
        "нефть", "нефтян", "газ", "газов", "brent", "urals", "опек",
        "нефтепродукт", "нефтепереработк", "спг", "lng",
    ],
    "finance": [
        "банк", "сбер", "sber", "втб", "vtbr", "акци", "облигаци", "офз", "дивиденд",
        "ipo", "spо", "бирж", "moex", "инвестор", "портфел",
        "газпром", "gazp", "лукойл", "lkoh", "яндекс", "yand",
        "магнит", "mgnt", "ростел", "rtkm",
    ],
    "consumer": [
        "розниц", "потреблен", "магазин", "товар", "услуг", "торговл",
        "еда", "продукт", "одежд", "электроник",
    ],
    "politics": [
        "президент", "правительств", "дум", "министр", "закон", "указ",
        "выбор", "политик", "международн", "посол", "санкци",
    ],
    "real_estate": [
        "недвижимость", "жиль", "квартир", "ипотек", "строительств",
        "девелоп", "новостройк", "аренд",
    ],
}


def classify_topic(text: str) -> str:
    if not text:
        return "other"
    text_lower = text.lower()
    scores: dict[str, int] = {}
    for topic, keywords in TOPIC_KEYWORDS.items():
        score = 0
        for kw in keywords:
            if len(kw) <= 3:
                if re.search(r"(?<!\w)" + re.escape(kw) + r"(?!\w)", text_lower):
                    score += 1
            else:
                if kw in text_lower:
                    score += 1
        if score > 0:
            scores[topic] = score
    if not scores:
        return "other"
    return max(scores, key=scores.get)


def extract_key_entities(text: str) -> list[str]:
    ticker_pattern = re.findall(r"\b[A-Z]{4,5}\b", text)
    money_pattern = re.findall(r"\b\d{1,3}(?:\.\d{3})*(?:\s*₽|\s*руб|\s*\$|\s*%)\b", text)
    return ticker_pattern + money_pattern


def topic_summary(posts: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for post in posts:
        topic = classify_topic(post.get("text", ""))
        counts[topic] = counts.get(topic, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: -x[1]))


def extract_topics_batch(texts: list[str]) -> list[dict[str, object]]:
    return [
        {
            "text": t[:100],
            "topic": classify_topic(t),
            "entities": extract_key_entities(t),
        }
        for t in texts if t
    ]
