import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import feedparser  # type: ignore[import-untyped]

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
    def __init__(self) -> None:
        self.feeds = RSS_FEEDS

    @staticmethod
    def collect_for_ticker_sync(db: Any, ticker: str) -> int:
        """Synchronous on-demand RSS fetch + DB save, linked to *ticker*.

        Returns number of new articles saved.
        """
        from src.constants import NEWS_MAX_PER_FEED
        from src.db.models import Instrument, News, NewsInstrument

        collector = NewsCollector()
        inst = db.query(Instrument).filter_by(ticker=ticker.upper()).first()
        if not inst:
            return 0

        ticker_map: dict[str, int] = {}
        for row in db.query(Instrument).all():
            ticker_map[row.ticker.upper()] = row.id

        saved = 0
        for feed in collector.feeds:
            try:
                articles = collector._fetch_feed(feed["url"], feed["name"], NEWS_MAX_PER_FEED)
            except Exception as exc:
                logger.warning("News feed error %s: %s", feed["name"], exc)
                continue
            for item in articles:
                exists = db.query(News).filter_by(url=item["url"]).first()
                if exists:
                    continue
                detail = item.get("sentiment_detail", {})
                n = News(
                    url=item["url"],
                    title=item["title"],
                    summary=item["summary"],
                    source_type=item["source_type"],
                    source_name=item["source_name"],
                    published_at=item.get("published_at"),
                    sentiment_score=item.get("sentiment_score"),
                    sentiment_weighted=item.get("sentiment_weighted"),
                    sentiment_bert_score=detail.get("bert_score"),
                    source_weight=detail.get("source_weight"),
                )
                db.add(n)
                db.flush()
                # Link to the target instrument
                if not db.query(NewsInstrument).filter_by(news_id=n.id, instrument_id=inst.id).first():
                    db.add(NewsInstrument(news_id=n.id, instrument_id=inst.id))
                # Also link to any other tickers mentioned
                search_text = f"{n.title or ''} {n.summary or ''}".upper()
                for t, iid in ticker_map.items():
                    if len(t) >= 2 and t in search_text and iid != inst.id:
                        if not db.query(NewsInstrument).filter_by(news_id=n.id, instrument_id=iid).first():
                            db.add(NewsInstrument(news_id=n.id, instrument_id=iid))
                saved += 1
        if saved:
            db.commit()
        return saved

    async def fetch_all(self, max_per_feed: int = 10) -> list[dict[str, Any]]:
        tasks = [self._fetch_feed_async(f["url"], f["name"], max_per_feed) for f in self.feeds]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_news: list[dict[str, Any]] = []
        for feed_name, result in zip([f["name"] for f in self.feeds], results):
            if isinstance(result, Exception):
                logger.warning("Ошибка загрузки %s: %s", feed_name, result)
            elif isinstance(result, list):
                all_news.extend(result)
        return all_news

    async def _fetch_feed_async(self, url: str, source: str, max_items: int) -> list[dict[str, Any]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._fetch_feed, url, source, max_items)

    def _fetch_feed(self, url: str, source: str, max_items: int) -> list[dict[str, Any]]:
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
