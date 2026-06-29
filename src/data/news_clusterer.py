from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def _get_embedder():
    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer("distiluse-base-multilingual-cased-v2")
        logger.info("Loaded SentenceTransformer model")
        return model
    except ImportError:
        logger.warning("sentence-transformers not available, using fallback")
        return None


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    a = np.array(vec_a, dtype=float)
    b = np.array(vec_b, dtype=float)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _get_or_create_event(db: Any, cluster: list[Any]) -> Any:
    from src.db.models import NewsEvent

    rep = cluster[0]
    sentiments = [a.sentiment for a in cluster if a.sentiment]
    positive = sum(1 for s in sentiments if s == "positive")
    negative = sum(1 for s in sentiments if s == "negative")
    neutral = sum(1 for s in sentiments if s == "neutral")
    if positive > negative and positive > neutral:
        dom_sentiment = "positive"
    elif negative > positive and negative > neutral:
        dom_sentiment = "negative"
    else:
        dom_sentiment = "neutral"

    event = NewsEvent(
        title=rep.title or "Clustered Event",
        summary=rep.summary,
        category=rep.category or "UNCLASSIFIED",
        subcategory=rep.subcategory,
        impact_score=max((a.impact_score or 0) for a in cluster),
        sentiment=dom_sentiment,
        article_count=len(cluster),
        published_at=rep.published_at,
    )
    return event


class NewsClusterer:
    def __init__(self, similarity_threshold: float = 0.85, time_window_days: int = 3):
        self.threshold = similarity_threshold
        self.time_window_days = time_window_days
        self._embedder = _get_embedder()

    def generate_embedding(self, title: str, summary: str) -> list[float]:
        text = f"{title}. {summary}" if summary else title
        if self._embedder is not None:
            try:
                emb = self._embedder.encode(text, convert_to_tensor=False)
                return emb.tolist() if hasattr(emb, "tolist") else list(emb)
            except Exception as e:
                logger.warning("Embedding failed: %s", e)
        return self._fallback_embedding(text)

    @staticmethod
    def _fallback_embedding(text: str) -> list[float]:
        import hashlib

        h = int(hashlib.md5(text.lower().encode()).hexdigest(), 16)
        np.random.seed(h % (2**32))
        return np.random.randn(768).tolist()

    def embed_articles(self, articles: list[Any]) -> None:
        for article in articles:
            if article.embedding:
                continue
            try:
                article.embedding = self.generate_embedding(
                    article.title or "", article.summary or ""
                )
            except Exception as e:
                logger.warning("Failed to embed article %s: %s", article.id, e)

    def cluster_articles(
        self, articles: list[Any]
    ) -> list[list[Any]]:
        if len(articles) < 2:
            return []

        self.embed_articles(articles)

        clusters: list[list[Any]] = []
        visited: set[int] = set()

        for i, article in enumerate(articles):
            if i in visited or not article.embedding:
                continue
            cluster = [article]
            visited.add(i)
            for j in range(i + 1, len(articles)):
                if j in visited or not articles[j].embedding:
                    continue
                t_a = article.published_at or datetime.now(timezone.utc)
                t_b = articles[j].published_at or datetime.now(timezone.utc)
                if t_a.tzinfo is None:
                    t_a = t_a.replace(tzinfo=timezone.utc)
                if t_b.tzinfo is None:
                    t_b = t_b.replace(tzinfo=timezone.utc)
                if abs((t_a - t_b).days) > self.time_window_days:
                    continue
                sim = _cosine_similarity(article.embedding, articles[j].embedding)
                if sim >= self.threshold:
                    cluster.append(articles[j])
                    visited.add(j)
            if len(cluster) > 1:
                clusters.append(cluster)

        return clusters

    def cluster_and_save(self, db: Any, articles: list[Any]) -> dict[int, int]:
        mapping: dict[int, int] = {}
        clusters = self.cluster_articles(articles)
        for cluster in clusters:
            event = _get_or_create_event(db, cluster)
            db.add(event)
            db.flush()
            for article in cluster:
                article.event_id = event.id
                mapping[article.id] = event.id
        db.commit()
        return mapping

    def run_pipeline(self, db: Any, hours_back: int = 48) -> dict[str, int]:
        from src.db.models import News

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)
        articles = (
            db.query(News)
            .filter(News.published_at >= cutoff, News.is_relevant)
            .all()
        )
        total = len(articles)
        before = db.query(News).filter(News.event_id.isnot(None)).count()
        mapping = self.cluster_and_save(db, articles)
        after = db.query(News).filter(News.event_id.isnot(None)).count()
        return {
            "total_articles": total,
            "events_created": len(set(mapping.values())),
            "articles_clustered": len(mapping),
            "articles_with_event_before": before,
            "articles_with_event_after": after,
        }
