"""Data processing module for news and risk analysis.

Components:
- news_filter: Spam and quality filtering
- news_classifier: LLM-based categorization
- news_processor: Deduplication and clustering
- sector_mapper: News to sector mapping
- impact_matrix: Impact calculations
- sector_impact_engine: Sector-level risk aggregation
- company_risk_aggregator: Company risk scoring
- geopolitical_risk_engine: Geopolitical risk assessment
- event_detector: News event detection and sentiment divergence
- signal_fusion_integration: Integration with Signal Fusion Engine
- dashboard_provider: Data for visualizations
- batch_processor: End-to-end pipeline orchestration
- news_system: Factory and initialization
"""

from src.data.batch_processor import NewsBatchProcessor
from src.data.company_risk_aggregator import CompanyRiskAggregator
from src.data.dashboard_provider import DashboardDataProvider
from src.data.event_detector import EventDetector, SentimentDivergenceDetector
from src.data.geopolitical_risk_engine import GeopoliticalRiskEngine
from src.data.impact_matrix import ImpactMatrix
from src.data.news_classifier import NewsClassifier
from src.data.news_filter import NewsFilter
from src.data.news_processor import NewsDeduplicator
from src.data.news_system import NewsSystemFactory, get_news_system, initialize_news_system
from src.data.sector_impact_engine import SectorImpactEngine
from src.data.sector_mapper import SectorMapper
from src.data.signal_fusion_integration import SignalFusionIntegration

__all__ = [
    "NewsFilter",
    "NewsClassifier",
    "NewsDeduplicator",
    "SectorMapper",
    "ImpactMatrix",
    "SectorImpactEngine",
    "CompanyRiskAggregator",
    "GeopoliticalRiskEngine",
    "EventDetector",
    "SentimentDivergenceDetector",
    "SignalFusionIntegration",
    "DashboardDataProvider",
    "NewsBatchProcessor",
    "NewsSystemFactory",
    "initialize_news_system",
    "get_news_system",
]
