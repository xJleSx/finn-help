"""News System Initialization and Factory.

Initializes all components and provides factory methods for dependency injection.
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class NewsSystemFactory:
    """Factory for creating and managing news system components."""

    _instance: Optional["NewsSystemFactory"] = None
    _components: dict[str, Any] = {}

    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def initialize(cls) -> "NewsSystemFactory":
        """Initialize all system components.

        Returns:
            NewsSystemFactory instance
        """
        factory = cls()

        if not factory._components:
            try:
                # Import all modules
                from src.data.batch_processor import NewsBatchProcessor
                from src.data.company_risk_aggregator import CompanyRiskAggregator
                from src.data.dashboard_provider import DashboardDataProvider
                from src.data.event_detector import EventDetector, SentimentDivergenceDetector
                from src.data.geopolitical_risk_engine import GeopoliticalRiskEngine
                from src.data.impact_matrix import ImpactMatrix
                from src.data.news_classifier import NewsClassifier
                from src.data.news_filter import NewsFilter
                from src.data.news_processor import NewsDeduplicator
                from src.data.sector_impact_engine import SectorImpactEngine
                from src.data.sector_mapper import SectorMapper
                from src.data.signal_fusion_integration import SignalFusionIntegration

                # Create instances
                factory._components["filter"] = NewsFilter()
                factory._components["classifier"] = NewsClassifier()
                factory._components["deduplicator"] = NewsDeduplicator()
                factory._components["sector_mapper"] = SectorMapper()
                factory._components["impact_matrix"] = ImpactMatrix()

                # Wire dependencies
                factory._components["sector_impact_engine"] = SectorImpactEngine(
                    factory._components["impact_matrix"],
                    factory._components["sector_mapper"],
                )

                factory._components["company_aggregator"] = CompanyRiskAggregator()
                factory._components["geo_engine"] = GeopoliticalRiskEngine()
                factory._components["event_detector"] = EventDetector()
                factory._components["sentiment_divergence"] = SentimentDivergenceDetector()

                factory._components["signal_fusion"] = SignalFusionIntegration(
                    factory._components["geo_engine"],
                    factory._components["sector_impact_engine"],
                    factory._components["company_aggregator"],
                    factory._components["event_detector"],
                )

                factory._components["dashboard"] = DashboardDataProvider()

                factory._components["batch_processor"] = NewsBatchProcessor(
                    factory._components["filter"],
                    factory._components["classifier"],
                    factory._components["deduplicator"],
                    factory._components["sector_mapper"],
                    factory._components["sector_impact_engine"],
                    factory._components["company_aggregator"],
                    factory._components["geo_engine"],
                    factory._components["event_detector"],
                )

                logger.info("News system initialized successfully")

            except ImportError as e:
                logger.error(f"Failed to import news modules: {e}")
                raise

        return factory

    def get(self, component_name: str) -> Any:
        """Get a component by name.

        Args:
            component_name: Component name (filter, classifier, etc)

        Returns:
            Component instance

        Raises:
            ValueError if component not found
        """
        if component_name not in self._components:
            raise ValueError(f"Component '{component_name}' not found")

        return self._components[component_name]

    def get_all(self) -> dict[str, Any]:
        """Get all initialized components.

        Returns:
            Dict of {name: component}
        """
        return self._components.copy()

    def get_filter(self) -> Any:
        """Get NewsFilter instance."""
        return self.get("filter")

    def get_classifier(self) -> Any:
        """Get NewsClassifier instance."""
        return self.get("classifier")

    def get_deduplicator(self) -> Any:
        """Get NewsDeduplicator instance."""
        return self.get("deduplicator")

    def get_sector_mapper(self) -> Any:
        """Get SectorMapper instance."""
        return self.get("sector_mapper")

    def get_impact_matrix(self) -> Any:
        """Get ImpactMatrix instance."""
        return self.get("impact_matrix")

    def get_sector_impact_engine(self) -> Any:
        """Get SectorImpactEngine instance."""
        return self.get("sector_impact_engine")

    def get_company_aggregator(self) -> Any:
        """Get CompanyRiskAggregator instance."""
        return self.get("company_aggregator")

    def get_geo_engine(self) -> Any:
        """Get GeopoliticalRiskEngine instance."""
        return self.get("geo_engine")

    def get_event_detector(self) -> Any:
        """Get EventDetector instance."""
        return self.get("event_detector")

    def get_sentiment_divergence(self) -> Any:
        """Get SentimentDivergenceDetector instance."""
        return self.get("sentiment_divergence")

    def get_signal_fusion(self) -> Any:
        """Get SignalFusionIntegration instance."""
        return self.get("signal_fusion")

    def get_dashboard(self) -> Any:
        """Get DashboardDataProvider instance."""
        return self.get("dashboard")

    def get_batch_processor(self) -> Any:
        """Get NewsBatchProcessor instance."""
        return self.get("batch_processor")


# Convenience functions for initialization
def initialize_news_system() -> NewsSystemFactory:
    """Initialize the news system."""
    return NewsSystemFactory.initialize()


def get_news_system() -> NewsSystemFactory:
    """Get initialized news system (assumes already initialized)."""
    factory = NewsSystemFactory()
    if not factory._components:
        return factory.initialize()
    return factory
