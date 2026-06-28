from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from src.db.models import News, NewsInstrument

logger = logging.getLogger(__name__)


@dataclass
class NewsCluster:
    topic: str
    articles: list[News] = field(default_factory=list)
    summary: str = ""
    key_tickers: list[str] = field(default_factory=list)

    def _dominant_sentiment(self) -> str:
        sentiments = [a.sentiment for a in self.articles if a.sentiment]
        if not sentiments:
            return "neutral"
        pos = sentiments.count("positive")
        neg = sentiments.count("negative")
        if pos > neg:
            return "positive"
        if neg > pos:
            return "negative"
        return "neutral"


class NewsSummarizer:
    def __init__(self, llm_client: Any | None = None) -> None:
        self._llm = llm_client

    def cluster_articles(self, db: Any, hours_back: int = 24) -> list[NewsCluster]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
        articles = (
            db.query(News)
            .filter(News.published_at >= cutoff, News.is_relevant)
            .order_by(News.category, News.subcategory, News.published_at.desc())
            .all()
        )
        if not articles:
            return []

        groups: OrderedDict[tuple[str, str], list[News]] = OrderedDict()
        for a in articles:
            key = (a.category or "UNCLASSIFIED", a.subcategory or "")
            groups.setdefault(key, []).append(a)

        clusters: list[NewsCluster] = []
        for (cat, subcat), group in groups.items():
            topic = f"{cat}{': ' + subcat if subcat else ''}"
            ticker_set: set[str] = set()
            for a in group:
                linked = db.query(NewsInstrument).filter(NewsInstrument.news_id == a.id).all()
                for li in linked:
                    inst = li.instrument
                    if inst is not None:
                        ticker_set.add(inst.ticker)
            clusters.append(NewsCluster(topic=topic, articles=group, key_tickers=sorted(ticker_set)))

        return clusters

    def generate_summary(self, cluster: NewsCluster, llm_client: Any | None = None) -> str:
        client = llm_client or self._llm
        if client is not None:
            try:
                articles_text = "\n\n".join(
                    f"Title: {a.title}\nSummary: {a.summary or ''}\nSentiment: {a.sentiment or 'neutral'}"
                    for a in cluster.articles[:10]
                )
                messages = [
                    {
                        "role": "system",
                        "content": (
                            "You are a financial news analyst. Summarize the following cluster "
                            "of news articles concisely in Russian. Include key tickers and overall sentiment."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Cluster topic: {cluster.topic}\n"
                            f"Key tickers: {', '.join(cluster.key_tickers)}\n\n"
                            f"Articles:\n{articles_text}"
                        ),
                    },
                ]
                result = client.chat(messages)
                return result.strip() if result else ""
            except Exception as exc:
                logger.warning("LLM summarization failed: %s", exc)

        return self._fallback_summary(cluster)

    def _fallback_summary(self, cluster: NewsCluster) -> str:
        if not cluster.articles:
            return ""
        sentiments = [a.sentiment for a in cluster.articles if a.sentiment]
        pos = sentiments.count("positive")
        neg = sentiments.count("negative")
        neu = sentiments.count("neutral")
        total = len(cluster.articles)
        sentiment_desc = "positive" if pos > neg else "negative" if neg > pos else "mixed"
        tickers = ", ".join(cluster.key_tickers[:5])
        return (
            f"Cluster: {cluster.topic} ({total} articles). "
            f"Sentiment: {sentiment_desc} ({pos}P/{neg}N/{neu}U). "
            f"Tickers: {tickers or 'N/A'}."
        )

    def save_clusters(self, db: Any, clusters: list[NewsCluster]) -> None:
        from src.db.models import NewsEvent

        for cluster in clusters:
            if not cluster.articles:
                continue
            first = cluster.articles[0]
            event = NewsEvent(
                title=cluster.topic,
                summary=cluster.summary,
                category=first.category or "UNCLASSIFIED",
                subcategory=first.subcategory or "",
                impact_score=sum(a.impact_score or 0.0 for a in cluster.articles) / len(cluster.articles),
                sentiment=cluster._dominant_sentiment(),
                article_count=len(cluster.articles),
                published_at=first.published_at,
            )
            db.add(event)
            db.flush()

            for article in cluster.articles:
                article.event_id = event.id

            db.commit()
            logger.info(
                "Saved cluster '%s' with %d articles (event_id=%d)",
                cluster.topic, len(cluster.articles), event.id,
            )

    def generate_daily_digest(self, db: Any, llm_client: Any | None = None) -> str:
        clusters = self.cluster_articles(db, hours_back=24)
        if not clusters:
            return "No news clusters for today."

        lines: list[str] = [
            f"Daily Digest — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
            "",
        ]
        for cl in clusters:
            summary = self.generate_summary(cl, llm_client=llm_client)
            cl.summary = summary
            lines.append(f"## {cl.topic}")
            lines.append(f"Tickers: {', '.join(cl.key_tickers) if cl.key_tickers else 'N/A'}")
            lines.append(f"Articles: {len(cl.articles)}")
            lines.append(summary)
            lines.append("")

        self.save_clusters(db, clusters)
        return "\n".join(lines)
