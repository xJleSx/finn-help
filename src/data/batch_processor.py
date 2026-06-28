"""Batch news processing pipeline and orchestration.

Coordinates all components (filter, classify, sector map, cluster, risk calc)
to process news articles end-to-end.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func

logger = logging.getLogger(__name__)


class NewsBatchProcessor:
    """Orchestrates complete news processing pipeline."""

    def __init__(
        self,
        filter_engine: Any,
        classifier: Any,
        deduplicator: Any,
        sector_mapper: Any,
        impact_engine: Any,
        company_aggregator: Any,
        geo_engine: Any,
        event_detector: Any,
    ):
        """Initialize processor with all engines.

        Args:
            filter_engine: NewsFilter instance
            classifier: NewsClassifier instance
            deduplicator: NewsDeduplicator instance
            sector_mapper: SectorMapper instance
            impact_engine: SectorImpactEngine instance
            company_aggregator: CompanyRiskAggregator instance
            geo_engine: GeopoliticalRiskEngine instance
            event_detector: EventDetector instance
        """
        self.filter_engine = filter_engine
        self.classifier = classifier
        self.deduplicator = deduplicator
        self.sector_mapper = sector_mapper
        self.impact_engine = impact_engine
        self.company_aggregator = company_aggregator
        self.geo_engine = geo_engine
        self.event_detector = event_detector

    def process_new_articles(
        self, db_session: Any, limit: int = 1000
    ) -> dict[str, Any]:
        """Process new unclassified articles through full pipeline.

        Args:
            db_session: Database session
            limit: Max articles to process

        Returns:
            Processing stats
        """
        from src.db.models import News

        stats = {
            "total_processed": 0,
            "filtered_out": 0,
            "classified": 0,
            "clustered": 0,
            "events_created": 0,
            "sector_impacts_calc": 0,
            "company_risks_calc": 0,
            "geo_risks_updated": False,
            "errors": [],
        }

        try:
            # Step 1: Get unprocessed articles
            articles = db_session.query(News).filter(
                News.category.is_(None),  # Not yet classified
            ).limit(limit).all()

            stats["total_processed"] = len(articles)

            if not articles:
                logger.info("No new articles to process")
                return stats

            # Step 2: Filter out spam/low-quality
            for article in articles:
                try:
                    evaluation = self.filter_engine.evaluate_article(
                        article.title or "",
                        article.summary or "",
                        article.source_name or "",
                    )
                    article.is_relevant = evaluation["is_relevant"]

                    if not evaluation["is_relevant"]:
                        stats["filtered_out"] += 1

                except Exception as e:
                    logger.error(f"Filter error for article {article.id}: {e}")
                    stats["errors"].append(f"Filter: {e}")

            db_session.commit()

            # Step 3: Classify remaining articles
            relevant_articles = [a for a in articles if a.is_relevant]
            for article in relevant_articles:
                try:
                    classification = self.classifier.classify_article(
                        article.title or "",
                        article.summary or "",
                        article.source_name or "",
                    )
                    article.category = classification.get("category", "MACRO")
                    article.subcategory = classification.get("subcategory", "")
                    article.sentiment = classification.get("sentiment", "neutral")
                    article.impact_score = classification.get("impact_score", 5)

                    stats["classified"] += 1

                except Exception as e:
                    logger.error(f"Classification error for article {article.id}: {e}")
                    stats["errors"].append(f"Classify: {e}")

            db_session.commit()

            # Step 3.5: Generate embeddings & enhanced clustering
            try:
                from src.data.news_clusterer import NewsClusterer

                clusterer = NewsClusterer()
                cluster_result = clusterer.run_pipeline(db_session, hours_back=48)
                stats["embedded"] = cluster_result.get("total_articles", 0)
                stats["events_created"] = cluster_result.get("events_created", 0)
                stats["clustered"] = cluster_result.get("articles_clustered", 0)
                logger.info("NewsClusterer pipeline: %s", cluster_result)
            except Exception as e:
                logger.error(f"Enhanced clustering error: {e}")
                stats["errors"].append(f"EnhancedCluster: {e}")

            # Step 4: Cluster into events (legacy)
            try:
                event_mapping = self.event_detector.cluster_into_events(
                    relevant_articles, db_session
                )
                stats["clustered"] = stats.get("clustered", 0) + len(event_mapping)

                for article_id, event_id in event_mapping.items():
                    article = db_session.query(News).get(article_id)
                    if article and article.event_id is None:
                        article.event_id = event_id

                db_session.commit()

            except Exception as e:
                logger.error(f"Clustering error: {e}")
                stats["errors"].append(f"Cluster: {e}")

            # Step 5: Calculate sector impacts and risks
            for article in relevant_articles:
                try:
                    sector_impacts = self.impact_engine.calculate_sector_impact_from_news(
                        article, db_session
                    )

                    if sector_impacts:
                        count = self.impact_engine.store_news_sector_impacts(
                            article, sector_impacts, db_session
                        )
                        stats["sector_impacts_calc"] += count

                except Exception as e:
                    logger.error(f"Sector impact error for article {article.id}: {e}")
                    stats["errors"].append(f"Sector impact: {e}")

            db_session.commit()

            # Step 6: Calculate company-level impacts
            from src.db.models import Instrument, NewsInstrument

            for article in relevant_articles:
                try:
                    linked_instruments = db_session.query(Instrument).join(
                        NewsInstrument, NewsInstrument.instrument_id == Instrument.id
                    ).filter(
                        NewsInstrument.news_id == article.id
                    ).all()

                    for instrument in linked_instruments:
                        from src.db.models import NewsCompanyImpact

                        impact = NewsCompanyImpact(
                            news_id=article.id,
                            instrument_id=instrument.id,
                            impact_type=article.subcategory or "general",
                            impact_score=article.impact_score or 5,
                        )
                        db_session.add(impact)
                        stats["company_risks_calc"] += 1

                except Exception as e:
                    logger.error(f"Company impact error for article {article.id}: {e}")
                    stats["errors"].append(f"Company impact: {e}")

            db_session.commit()

            # Step 7: Update daily risk scores
            try:
                from src.db.models import Instrument

                all_sectors = db_session.query(Instrument.sector).distinct().all()

                for (sector,) in all_sectors:
                    if not sector:
                        continue

                    risk = self.impact_engine.calculate_daily_sector_risk(
                        sector, db_session
                    )
                    if risk["article_count"] > 0:
                        self.impact_engine.store_daily_sector_risk(
                            sector, risk, db_session
                        )

                db_session.commit()

            except Exception as e:
                logger.error(f"Sector risk calc error: {e}")
                stats["errors"].append(f"Sector risk: {e}")

            # Step 8: Update geopolitical risk
            try:
                geo_risk = self.geo_engine.calculate_daily_geopolitical_risk(db_session)
                self.geo_engine.store_geopolitical_risk(geo_risk, db_session)
                stats["geo_risks_updated"] = True
                db_session.commit()

            except Exception as e:
                logger.error(f"Geo risk calc error: {e}")
                stats["errors"].append(f"Geo risk: {e}")

            # Step 9: Update company risks
            try:
                instruments = db_session.query(Instrument).limit(100).all()

                for instrument in instruments:
                    company_risk = self.company_aggregator.calculate_company_risk(
                        instrument, db_session
                    )
                    self.company_aggregator.store_company_risk(company_risk, db_session)

                db_session.commit()

            except Exception as e:
                logger.error(f"Company risk calc error: {e}")
                stats["errors"].append(f"Company risk: {e}")

            logger.info(f"Batch processing complete: {stats}")

        except Exception as e:
            logger.error(f"Batch processing failed: {e}")
            stats["errors"].append(f"Fatal: {e}")

        return stats

    def calculate_all_daily_risks(self, db_session: Any) -> dict[str, Any]:
        """Calculate all risk metrics for the day.

        Args:
            db_session: Database session

        Returns:
            Daily risk calculation stats
        """
        from src.db.models import Instrument

        stats = {
            "sector_risks_updated": 0,
            "company_risks_updated": 0,
            "geo_risk_updated": False,
        }

        try:
            # Update sector risks
            sectors = db_session.query(Instrument.sector).distinct().all()
            for (sector,) in sectors:
                if not sector:
                    continue

                risk = self.impact_engine.calculate_daily_sector_risk(sector, db_session)
                if self.impact_engine.store_daily_sector_risk(sector, risk, db_session):
                    stats["sector_risks_updated"] += 1

            # Update geopolitical risk
            geo_risk = self.geo_engine.calculate_daily_geopolitical_risk(db_session)
            if self.geo_engine.store_geopolitical_risk(geo_risk, db_session):
                stats["geo_risk_updated"] = True

            # Update company risks for top instruments
            top_instruments = db_session.query(Instrument).limit(200).all()
            for instrument in top_instruments:
                company_risk = self.company_aggregator.calculate_company_risk(
                    instrument, db_session
                )
                if self.company_aggregator.store_company_risk(company_risk, db_session):
                    stats["company_risks_updated"] += 1

            db_session.commit()
            logger.info(f"Daily risks calculated: {stats}")

        except Exception as e:
            logger.error(f"Daily risk calculation failed: {e}")
            stats["error"] = str(e)

        return stats

    def get_processing_summary(self, db_session: Any) -> dict[str, Any]:
        """Get summary of recent processing activity.

        Args:
            db_session: Database session

        Returns:
            Summary statistics
        """
        from src.db.models import News, NewsEvent, SectorRiskHistory

        today = datetime.utcnow().date()
        last_week = today - timedelta(days=7)

        # Count news by category
        categories = {}
        news_by_cat = db_session.query(
            News.category,
            func.count(News.id).label("count"),
        ).filter(
            News.created_at >= last_week
        ).group_by(News.category).all()

        for cat, count in news_by_cat:
            categories[cat] = count

        # Event stats
        events_last_week = db_session.query(NewsEvent).filter(
            NewsEvent.created_at >= last_week
        ).count()

        # Sector risk stats
        high_risk_sectors = db_session.query(SectorRiskHistory).filter(
            SectorRiskHistory.date == today,
            SectorRiskHistory.risk_score > 6,
        ).count()

        return {
            "date": today.isoformat(),
            "news_last_week": sum(categories.values()),
            "categories": categories,
            "events_last_week": events_last_week,
            "high_risk_sectors_today": high_risk_sectors,
        }
