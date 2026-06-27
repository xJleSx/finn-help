"""News Event Detection and Sentiment Divergence Analysis.

Groups articles into events and detects when sentiment diverges significantly.
Divergence = high uncertainty/contrarian signal.
"""

import logging
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


class EventDetector:
    """Detects news events and clusters related articles."""

    def __init__(self, similarity_threshold: float = 0.80):
        """Initialize detector.

        Args:
            similarity_threshold: Min cosine similarity to group articles (0-1)
        """
        self.threshold = similarity_threshold

    def detect_related_articles(
        self, reference_article: Any, candidate_articles: list[Any]
    ) -> list[Any]:
        """Find articles related to a reference article.

        Args:
            reference_article: Anchor News ORM object
            candidate_articles: List of News ORM objects to check

        Returns:
            List of related articles (above similarity threshold)
        """
        if not reference_article.embedding:
            return []

        related = []
        ref_embedding = reference_article.embedding

        for candidate in candidate_articles:
            if not candidate.embedding or candidate.id == reference_article.id:
                continue

            # Simple cosine similarity
            similarity = self._cosine_similarity(ref_embedding, candidate.embedding)

            if similarity >= self.threshold:
                related.append((candidate, similarity))

        # Sort by similarity
        related.sort(key=lambda x: x[1], reverse=True)
        return [a for a, _ in related]

    @staticmethod
    def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
        """Calculate cosine similarity between two vectors.

        Args:
            vec_a: First vector
            vec_b: Second vector

        Returns:
            Similarity score (0-1)
        """
        if not vec_a or not vec_b or len(vec_a) != len(vec_b):
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
        mag_a = sum(a ** 2 for a in vec_a) ** 0.5
        mag_b = sum(b ** 2 for b in vec_b) ** 0.5

        if mag_a == 0 or mag_b == 0:
            return 0.0

        return dot_product / (mag_a * mag_b)

    def cluster_into_events(
        self, articles: list[Any], db_session: Any, time_window_days: int = 3
    ) -> dict[int, int]:
        """Cluster articles into events based on similarity and time.

        Args:
            articles: List of News ORM objects
            db_session: Database session
            time_window_days: Articles within this window can be in same event

        Returns:
            Mapping {article_id: event_id}
        """
        from src.db.models import NewsEvent

        if len(articles) < 2:
            return {}

        mapping = {}
        clusters = []
        visited = set()

        # Build clusters using connected components
        for i, article in enumerate(articles):
            if i in visited:
                continue

            cluster = [article]
            visited.add(i)

            # Find all articles similar to this one
            for j in range(i + 1, len(articles)):
                if j in visited:
                    continue

                # Check time window
                time_diff = abs(
                    (articles[j].published_at or datetime.utcnow())
                    - (article.published_at or datetime.utcnow())
                ).days

                if time_diff > time_window_days:
                    continue

                # Check similarity
                similarity = self._cosine_similarity(
                    article.embedding or [],
                    articles[j].embedding or [],
                )

                if similarity >= self.threshold:
                    cluster.append(articles[j])
                    visited.add(j)

            if len(cluster) > 1:
                clusters.append(cluster)

        # Create events for clusters
        for cluster in clusters:
            # Use first article as representative
            rep = cluster[0]
            event = NewsEvent(
                title=rep.title or "Clustered Event",
                summary=rep.summary,
                category=rep.category or "UNCLASSIFIED",
                subcategory=rep.subcategory,
                impact_score=max(a.impact_score or 0 for a in cluster),
                sentiment=self._get_cluster_sentiment(cluster),
                article_count=len(cluster),
                published_at=rep.published_at,
            )
            db_session.add(event)
            db_session.flush()

            # Map articles to event
            for article in cluster:
                mapping[article.id] = event.id

        return mapping

    @staticmethod
    def _get_cluster_sentiment(articles: list[Any]) -> str:
        """Determine overall sentiment for a cluster.

        Args:
            articles: List of News ORM objects

        Returns:
            Dominant sentiment (positive/negative/neutral)
        """
        sentiments = [a.sentiment for a in articles if a.sentiment]
        if not sentiments:
            return "neutral"

        positive = sum(1 for s in sentiments if s == "positive")
        negative = sum(1 for s in sentiments if s == "negative")
        neutral = sum(1 for s in sentiments if s == "neutral")

        if positive > negative and positive > neutral:
            return "positive"
        elif negative > positive and negative > neutral:
            return "negative"
        return "neutral"


class SentimentDivergenceDetector:
    """Detects divergence in sentiment around a topic/sector."""

    def __init__(self, divergence_threshold: float = 0.4):
        """Initialize detector.

        Args:
            divergence_threshold: Min ratio of sentiment divergence to flag (0-1)
        """
        self.threshold = divergence_threshold

    def analyze_sector_sentiment_divergence(
        self, sector: str, db_session: Any, days: int = 7
    ) -> dict[str, Any]:
        """Analyze sentiment divergence for a sector.

        Args:
            sector: Sector name
            db_session: Database session
            days: Time window to analyze

        Returns:
            Divergence analysis dict
        """
        from src.db.models import Instrument, News, NewsInstrument

        # Get instruments in sector
        instruments = db_session.query(Instrument).filter_by(sector=sector).all()
        instrument_ids = [i.id for i in instruments]

        if not instrument_ids:
            return {
                "sector": sector,
                "divergence": 0.0,
                "has_divergence": False,
                "consensus": "no_data",
            }

        # Get recent news for these instruments
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        news_items = db_session.query(News).join(
            NewsInstrument, NewsInstrument.news_id == News.id
        ).filter(
            NewsInstrument.instrument_id.in_(instrument_ids),
            News.published_at >= cutoff_date,
            News.is_relevant,
        ).all()

        if not news_items:
            return {
                "sector": sector,
                "divergence": 0.0,
                "has_divergence": False,
                "consensus": "no_data",
            }

        # Count sentiments
        positive = sum(1 for n in news_items if n.sentiment == "positive")
        negative = sum(1 for n in news_items if n.sentiment == "negative")
        neutral = sum(1 for n in news_items if n.sentiment == "neutral")

        total = len(news_items)

        # Calculate divergence (standard deviation of sentiment distribution)
        # High divergence = lots of conflicting sentiment
        ratios = [positive / total, negative / total, neutral / total]
        divergence = sum((r - 1/3) ** 2 for r in ratios) ** 0.5  # Euclidean from uniform

        # Determine consensus (if not divergent)
        if positive > negative and positive > neutral:
            consensus = "positive"
        elif negative > positive and negative > neutral:
            consensus = "negative"
        else:
            consensus = "mixed"

        has_divergence = divergence > self.threshold

        return {
            "sector": sector,
            "divergence": divergence,
            "has_divergence": has_divergence,
            "consensus": consensus,
            "positive_ratio": positive / total,
            "negative_ratio": negative / total,
            "neutral_ratio": neutral / total,
            "article_count": total,
            "signal_strength": "HIGH" if has_divergence else "LOW",
        }

    def analyze_company_sentiment_divergence(
        self, instrument: Any, db_session: Any, days: int = 7
    ) -> dict[str, Any]:
        """Analyze sentiment divergence for a specific company.

        Args:
            instrument: Instrument ORM object
            db_session: Database session
            days: Time window to analyze

        Returns:
            Divergence analysis dict
        """
        from src.db.models import News, NewsInstrument

        # Get recent news
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        news_items = db_session.query(News).join(
            NewsInstrument, NewsInstrument.news_id == News.id
        ).filter(
            NewsInstrument.instrument_id == instrument.id,
            News.published_at >= cutoff_date,
            News.is_relevant,
        ).all()

        if not news_items:
            return {
                "ticker": instrument.ticker,
                "divergence": 0.0,
                "has_divergence": False,
                "consensus": "no_data",
            }

        # Count sentiments
        positive = sum(1 for n in news_items if n.sentiment == "positive")
        negative = sum(1 for n in news_items if n.sentiment == "negative")
        neutral = sum(1 for n in news_items if n.sentiment == "neutral")

        total = len(news_items)

        # Calculate divergence
        ratios = [positive / total, negative / total, neutral / total]
        divergence = sum((r - 1/3) ** 2 for r in ratios) ** 0.5

        # Determine consensus
        if positive > negative and positive > neutral:
            consensus = "positive"
        elif negative > positive and negative > neutral:
            consensus = "negative"
        else:
            consensus = "mixed"

        has_divergence = divergence > self.threshold

        return {
            "ticker": instrument.ticker,
            "divergence": divergence,
            "has_divergence": has_divergence,
            "consensus": consensus,
            "positive_ratio": positive / total,
            "negative_ratio": negative / total,
            "neutral_ratio": neutral / total,
            "article_count": total,
            "signal_type": "UNCERTAINTY" if has_divergence else "CONSENSUS",
            "actionable": has_divergence,
        }

    def find_all_divergences(
        self, db_session: Any, min_articles: int = 5
    ) -> list[dict[str, Any]]:
        """Find all sectors/companies with significant sentiment divergence.

        Args:
            db_session: Database session
            min_articles: Minimum articles to analyze

        Returns:
            List of divergence signals sorted by strength
        """
        from src.db.models import Instrument

        divergences = []

        # Analyze all sectors
        sectors = db_session.query(Instrument.sector).distinct().all()
        for (sector,) in sectors:
            if not sector:
                continue

            div = self.analyze_sector_sentiment_divergence(sector, db_session)
            if div["has_divergence"] and div["article_count"] >= min_articles:
                divergences.append(div)

        # Analyze top instruments by volume
        top_instruments = (
            db_session.query(Instrument)
            .order_by(Instrument.id)
            .limit(100)
            .all()
        )

        for instrument in top_instruments:
            div = self.analyze_company_sentiment_divergence(instrument, db_session)
            if div["has_divergence"] and div["article_count"] >= min_articles:
                divergences.append(div)

        # Sort by divergence strength
        divergences.sort(key=lambda x: x["divergence"], reverse=True)

        return divergences
