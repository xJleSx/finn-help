import logging
import re
from datetime import datetime, timezone

import feedparser

logger = logging.getLogger(__name__)

RSS_FEEDS = [
    {"url": "https://www.interfax.ru/rss.asp", "name": "Интерфакс"},
    {"url": "https://www.rbc.ru/v8/rss/yandex.rss", "name": "РБК"},
    {"url": "https://www.finam.ru/analysis/news/AllNews.rss", "name": "Финам"},
    {"url": "https://smart-lab.ru/rss", "name": "Smart-lab"},
    {"url": "https://www.kommersant.ru/RSS/main.xml", "name": "Коммерсантъ"},
    {"url": "https://econs.online/rss/", "name": "Econs"},
]

POSITIVE_WORDS = {
    "рост",
    "увеличение",
    "прибыль",
    "успех",
    "развитие",
    "выгода",
    "восстановление",
    "повышение",
    "рекорд",
    "доход",
    "укрепление",
    "стабильность",
    "профицит",
    "диверсификация",
    "модернизация",
    "инвестиция",
    "капитализация",
    "рост",
    "уверенный",
    "позитивный",
    "перспективный",
    "эффективность",
}

NEGATIVE_WORDS = {
    "падение",
    "убыток",
    "кризис",
    "санкции",
    "обвал",
    "потери",
    "снижение",
    "дефолт",
    "банкротство",
    "нестабильность",
    "отток",
    "инфляция",
    "рецессия",
    "девальвация",
    "эмбарго",
    "блокировка",
    "отзыв",
    "ликвидация",
    "долг",
    "риск",
    "ущерб",
    "потеря",
    "ограничение",
    "негативный",
    "заморозка",
}


class NewsCollector:
    def __init__(self):
        self.feeds = RSS_FEEDS

    def fetch_all(self, max_per_feed: int = 10) -> list[dict]:
        all_news = []
        for feed in self.feeds:
            try:
                items = self._fetch_feed(feed["url"], feed["name"], max_per_feed)
                all_news.extend(items)
            except Exception as e:
                logger.warning(f"Ошибка загрузки {feed['name']}: {e}")
        return all_news

    def _fetch_feed(self, url: str, source: str, max_items: int) -> list[dict]:
        parsed = feedparser.parse(url)
        items = []
        for entry in parsed.entries[:max_items]:
            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    published = datetime.now(timezone.utc)

            summary = ""
            if hasattr(entry, "summary"):
                summary = entry.summary
            elif hasattr(entry, "description"):
                summary = entry.description

            text = f"{entry.get('title', '')} {summary}"
            sentiment_score = self._estimate_sentiment(text)

            items.append(
                {
                    "url": entry.get("link", ""),
                    "title": entry.get("title", ""),
                    "summary": summary[:500] if summary else "",
                    "source_type": "rss",
                    "source_name": source,
                    "published_at": published,
                    "sentiment_score": sentiment_score,
                }
            )
        return items

    def _estimate_sentiment(self, text: str) -> float:
        words = set(re.findall(r"[а-яёa-z]+", text.lower()))
        pos_count = len(words & POSITIVE_WORDS)
        neg_count = len(words & NEGATIVE_WORDS)
        total = pos_count + neg_count
        if total == 0:
            return 0.0
        return round((pos_count - neg_count) / total, 3)
