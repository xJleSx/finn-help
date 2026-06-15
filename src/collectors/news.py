import asyncio
import logging
from datetime import datetime, timezone

import feedparser

from src.collectors.sentiment import analyze_sentiment

logger = logging.getLogger(__name__)

RSS_FEEDS = [
    {"url": "https://www.interfax.ru/rss.asp", "name": "Интерфакс"},
    {"url": "https://www.rbc.ru/v8/rss/yandex.rss", "name": "РБК"},
    {"url": "https://www.finam.ru/analysis/news/AllNews.rss", "name": "Финам"},
    {"url": "https://smart-lab.ru/rss", "name": "Smart-lab"},
    {"url": "https://www.kommersant.ru/RSS/main.xml", "name": "Коммерсантъ"},
    {"url": "https://econs.online/rss/", "name": "Econs"},
]


class NewsCollector:
    def __init__(self):
        self.feeds = RSS_FEEDS

    async def fetch_all(self, max_per_feed: int = 10) -> list[dict]:
        tasks = [self._fetch_feed_async(f["url"], f["name"], max_per_feed) for f in self.feeds]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_news: list[dict] = []
        for feed_name, result in zip([f["name"] for f in self.feeds], results):
            if isinstance(result, Exception):
                logger.warning("Ошибка загрузки %s: %s", feed_name, result)
            elif isinstance(result, list):
                all_news.extend(result)
        return all_news

    async def _fetch_feed_async(self, url: str, source: str, max_items: int) -> list[dict]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._fetch_feed, url, source, max_items)

    def _fetch_feed(self, url: str, source: str, max_items: int) -> list[dict]:
        parsed = feedparser.parse(url)
        items = []
        for entry in parsed.entries[:max_items]:
            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    published = datetime(
                        entry.published_parsed.tm_year,
                        entry.published_parsed.tm_mon,
                        entry.published_parsed.tm_mday,
                        entry.published_parsed.tm_hour,
                        entry.published_parsed.tm_min,
                        entry.published_parsed.tm_sec,
                        tzinfo=timezone.utc,
                    )
                except (ValueError, TypeError):
                    published = datetime.now(timezone.utc)

            summary = ""
            if hasattr(entry, "summary"):
                summary = entry.summary
            elif hasattr(entry, "description"):
                summary = entry.description

            text = f"{entry.get('title', '')} {summary}"
            sentiment = analyze_sentiment(text, source_name=source)

            items.append(
                {
                    "url": entry.get("link", ""),
                    "title": entry.get("title", ""),
                    "summary": summary[:500] if summary else "",
                    "source_type": "rss",
                    "source_name": source,
                    "published_at": published,
                    "sentiment_score": sentiment["score"],
                    "sentiment_weighted": sentiment["weighted_score"],
                    "sentiment_detail": sentiment,
                }
            )
        return items
