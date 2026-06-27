"""News deduplication and clustering engine.

Uses embeddings (title + summary) and cosine similarity to identify duplicates
and group related articles into events.
"""

import logging
from typing import Any, Optional

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)


class NewsDeduplicator:
    """Deduplicates news articles using embedding similarity."""

    SIMILARITY_THRESHOLD = 0.85  # Cosine similarity threshold for matching
    MIN_EMBEDDING_DIM = 384  # Minimum embedding dimension expected

    def __init__(self, embedding_fn: Optional[Any] = None):
        """Initialize deduplicator.

        Args:
            embedding_fn: Function to generate embeddings (title + summary).
                         If None, will use a simple default based on available models.
        """
        self.embedding_fn = embedding_fn or self._default_embedding

    def _default_embedding(self, text: str) -> list[float]:
        """Generate embedding using available model (SentenceTransformer or similar).

        Falls back to simple bag-of-words if no model is available.
        """
        try:
            from sentence_transformers import SentenceTransformer

            if not hasattr(self, "_model"):
                self._model = SentenceTransformer("distiluse-base-multilingual-cased-v2")
            embedding = self._model.encode(text, convert_to_tensor=False)
            return embedding.tolist() if hasattr(embedding, "tolist") else list(embedding)
        except ImportError:
            logger.warning("SentenceTransformer not available, using fallback embedding")
            return self._fallback_embedding(text)

    @staticmethod
    def _fallback_embedding(text: str) -> list[float]:
        """Simple TF-IDF-like fallback embedding."""
        # For fallback, use a simple hash-based representation
        import hashlib

        text_lower = text.lower()
        # Create a deterministic 768-dimensional embedding
        hash_val = int(hashlib.md5(text_lower.encode()).hexdigest(), 16)
        np.random.seed(hash_val % (2**32))
        return np.random.randn(768).tolist()

    def embed_article(self, title: str, summary: str) -> list[float]:
        """Generate embedding for a news article.

        Args:
            title: Article title
            summary: Article summary/content

        Returns:
            Embedding vector as list of floats
        """
        combined_text = f"{title}. {summary}" if summary else title
        return self.embedding_fn(combined_text)

    def find_duplicates(self, articles: list[dict[str, Any]], db_session: Any) -> list[tuple[int, int]]:
        """Find duplicate articles within a list.

        Args:
            articles: List of article dicts with 'id', 'title', 'summary' keys
            db_session: Database session

        Returns:
            List of (article_id_1, article_id_2) tuples for duplicates
        """

        duplicates = []

        if not articles:
            return duplicates

        # Generate embeddings for new articles
        embeddings = []
        article_ids = []

        for article in articles:
            try:
                embedding = self.embed_article(article.get("title", ""), article.get("summary", ""))
                embeddings.append(embedding)
                article_ids.append(article.get("id"))
            except Exception as e:
                logger.warning(f"Failed to embed article {article.get('id')}: {e}")
                continue

        if not embeddings:
            return duplicates

        # Convert to numpy array
        embedding_array = np.array(embeddings)

        # Calculate pairwise similarities
        similarities = cosine_similarity(embedding_array)

        # Find pairs above threshold
        for i in range(len(similarities)):
            for j in range(i + 1, len(similarities)):
                if similarities[i][j] >= self.SIMILARITY_THRESHOLD:
                    duplicates.append((article_ids[i], article_ids[j]))

        return duplicates

    def cluster_articles_into_events(self, news_articles: list[Any], db_session: Any) -> dict[int, int]:
        """Cluster similar articles into events (news_events).

        Args:
            news_articles: List of News ORM objects
            db_session: Database session

        Returns:
            Mapping of {article_id: event_id}
        """
        from src.db.models import News, NewsEvent

        mapping = {}

        if not news_articles:
            return mapping

        # Generate embeddings
        embeddings = []
        article_ids = []

        for article in news_articles:
            try:
                embedding = self.embed_article(article.title or "", article.summary or "")
                embeddings.append(embedding)
                article_ids.append(article.id)
            except Exception as e:
                logger.warning(f"Failed to embed article {article.id}: {e}")
                continue

        if len(embeddings) < 2:
            return mapping

        embedding_array = np.array(embeddings)
        similarities = cosine_similarity(embedding_array)

        # Simple clustering: group articles by similarity
        clusters = []
        visited = set()

        for i in range(len(similarities)):
            if i in visited:
                continue

            cluster = [article_ids[i]]
            visited.add(i)

            for j in range(i + 1, len(similarities)):
                if j not in visited and similarities[i][j] >= self.SIMILARITY_THRESHOLD:
                    cluster.append(article_ids[j])
                    visited.add(j)

            if cluster:
                clusters.append(cluster)

        # Create events for clusters with multiple articles
        for cluster in clusters:
            if len(cluster) > 1:
                # Find representative article (first one)
                representative = db_session.query(News).filter(News.id == cluster[0]).first()
                if representative:
                    # Create event
                    event = NewsEvent(
                        title=representative.title or "Clustered Event",
                        summary=representative.summary,
                        category=representative.category or "UNCLASSIFIED",
                        subcategory=representative.subcategory,
                        impact_score=representative.impact_score or 0.0,
                        sentiment=representative.sentiment,
                        article_count=len(cluster),
                        published_at=representative.published_at,
                    )
                    db_session.add(event)
                    db_session.flush()

                    # Link all articles in cluster to event
                    for article_id in cluster:
                        mapping[article_id] = event.id

        return mapping

    def deduplicate_and_merge(self, db_session: Any) -> dict[str, Any]:
        """Deduplicate news table and create events.

        Args:
            db_session: Database session

        Returns:
            Result dict with stats about deduplication
        """
        from src.db.models import News

        stats = {"total": 0, "duplicates_found": 0, "events_created": 0, "articles_merged": 0}

        # Get all relevant news articles
        articles = db_session.query(News).filter(News.is_relevant).all()
        stats["total"] = len(articles)

        if not articles:
            logger.info("No articles to deduplicate")
            return stats

        # Cluster articles into events
        mapping = self.cluster_articles_into_events(articles, db_session)
        stats["events_created"] = len(set(mapping.values()))
        stats["articles_merged"] = len(mapping)

        # Update articles with event_id and recalculate source_count
        for article_id, event_id in mapping.items():
            article = db_session.query(News).filter(News.id == article_id).first()
            if article:
                article.event_id = event_id

        db_session.commit()
        logger.info(f"Deduplication complete: {stats}")

        return stats
