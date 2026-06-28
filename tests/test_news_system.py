import pytest
from src.db.models import (
    News,
    NewsEvent,
    NewsInstrument,
    NewsSectorImpact,
    NewsCompanyImpact,
    SectorRiskHistory,
    CompanyRiskHistory,
    GeopoliticalRiskHistory,
)


class TestModuleImports:
    def test_news_filter_import(self):
        from src.data.news_filter import NewsFilter
        assert NewsFilter is not None

    def test_news_classifier_import(self):
        from src.data.news_classifier import NewsClassifier
        assert NewsClassifier is not None

    def test_news_processor_import(self):
        from src.data.news_processor import NewsDeduplicator
        assert NewsDeduplicator is not None

    def test_sector_mapper_import(self):
        from src.data.sector_mapper import SectorMapper
        assert SectorMapper is not None

    def test_impact_matrix_import(self):
        from src.data.impact_matrix import ImpactMatrix
        assert ImpactMatrix is not None

    def test_sector_impact_engine_import(self):
        from src.data.sector_impact_engine import SectorImpactEngine
        assert SectorImpactEngine is not None

    def test_company_risk_aggregator_import(self):
        from src.data.company_risk_aggregator import CompanyRiskAggregator
        assert CompanyRiskAggregator is not None

    def test_geopolitical_risk_engine_import(self):
        from src.data.geopolitical_risk_engine import GeopoliticalRiskEngine
        assert GeopoliticalRiskEngine is not None

    def test_event_detector_import(self):
        from src.data.event_detector import EventDetector, SentimentDivergenceDetector
        assert EventDetector is not None
        assert SentimentDivergenceDetector is not None

    def test_signal_fusion_integration_import(self):
        from src.data.signal_fusion_integration import SignalFusionIntegration
        assert SignalFusionIntegration is not None

    def test_dashboard_provider_import(self):
        from src.data.dashboard_provider import DashboardDataProvider
        assert DashboardDataProvider is not None

    def test_batch_processor_import(self):
        from src.data.batch_processor import NewsBatchProcessor
        assert NewsBatchProcessor is not None

    def test_news_system_factory_import(self):
        from src.data.news_system import NewsSystemFactory, initialize_news_system, get_news_system
        assert NewsSystemFactory is not None
        assert initialize_news_system is not None
        assert get_news_system is not None


class TestDBModels:
    def test_news_model(self):
        assert hasattr(News, "__tablename__")
        assert News.__tablename__ == "news"

    def test_news_event_model(self):
        assert NewsEvent.__tablename__ == "news_events"

    def test_news_instrument_model(self):
        assert NewsInstrument.__tablename__ == "news_instruments"

    def test_news_sector_impact_model(self):
        assert NewsSectorImpact.__tablename__ == "news_sector_impacts"

    def test_news_company_impact_model(self):
        assert NewsCompanyImpact.__tablename__ == "news_company_impacts"

    def test_sector_risk_history_model(self):
        assert SectorRiskHistory.__tablename__ == "sector_risk_history"

    def test_company_risk_history_model(self):
        assert CompanyRiskHistory.__tablename__ == "company_risk_history"

    def test_geopolitical_risk_history_model(self):
        assert GeopoliticalRiskHistory.__tablename__ == "geopolitical_risk_history"


class TestNewsFilter:
    def test_basic_instantiation(self):
        from src.data.news_filter import NewsFilter
        f = NewsFilter()
        assert f is not None

    def test_content_quality_short_title(self):
        from src.data.news_filter import NewsFilter
        f = NewsFilter()
        result = f.check_content_quality("Hi", "This is a longer summary that should pass the minimum length test easily.")
        assert "title_too_short" in result["issues"]

    def test_content_quality_good_content(self):
        from src.data.news_filter import NewsFilter
        f = NewsFilter()
        result = f.check_content_quality(
            "This is a proper news title about markets",
            "This is a summary with enough content. It has multiple sentences. And passes all checks."
        )
        assert result["is_quality"]

    def test_keyword_blacklist_detects_spam(self):
        from src.data.news_filter import NewsFilter
        f = NewsFilter()
        result = f.check_keyword_blacklist("купить дешево", "реклама казино")
        assert result["is_spam"]

    def test_keyword_blacklist_clean(self):
        from src.data.news_filter import NewsFilter
        f = NewsFilter()
        result = f.check_keyword_blacklist("Рынки растут на фоне новостей", "Нефть дорожает")
        assert not result["is_spam"]

    def test_evaluate_article_spam(self):
        from src.data.news_filter import NewsFilter
        f = NewsFilter()
        result = f.evaluate_article("купить дешево", "реклама казино лотерея")
        assert not result["is_relevant"]

    def test_evaluate_article_good(self):
        from src.data.news_filter import NewsFilter
        f = NewsFilter()
        result = f.evaluate_article(
            "Рынки растут на фоне новостей",
            "Нефть дорожает. Индекс Мосбиржи обновил максимум. Рубль укрепляется."
        )
        assert result["is_relevant"]

    def test_detect_press_release(self):
        from src.data.news_filter import NewsFilter
        f = NewsFilter()
        result = f.detect_press_release("Компания сообщает", "пресс-релиз о результатах")
        assert result["is_press_release"]

    def test_evaluate_empty(self):
        from src.data.news_filter import NewsFilter
        f = NewsFilter()
        result = f.evaluate_article("", "")
        assert not result["is_relevant"]


class TestNewsClassifier:
    def test_basic_instantiation(self):
        from src.data.news_classifier import NewsClassifier
        c = NewsClassifier()
        assert c is not None

    def test_fallback_classification_geopolitical(self):
        from src.data.news_classifier import NewsClassifier
        c = NewsClassifier()
        result = c._fallback_classification("Санкции против России", "Новые ограничения")
        assert result["category"] == "GEOPOLITICAL"
        assert result["subcategory"] == "sanctions"

    def test_fallback_classification_macro(self):
        from src.data.news_classifier import NewsClassifier
        c = NewsClassifier()
        result = c._fallback_classification("Ставка ЦБ", "Ключевая ставка повышена")
        assert result["category"] == "MACRO"

    def test_fallback_classification_sector_energy(self):
        from src.data.news_classifier import NewsClassifier
        c = NewsClassifier()
        result = c._fallback_classification("Цены на нефть", "Нефть дорожает")
        assert result["category"] == "SECTOR"

    def test_fallback_sentiment_positive(self):
        from src.data.news_classifier import NewsClassifier
        c = NewsClassifier()
        result = c._fallback_classification("Рост прибыли компании", "Прибыль выше ожиданий")
        assert result["sentiment"] == "positive"

    def test_fallback_sentiment_negative(self):
        from src.data.news_classifier import NewsClassifier
        c = NewsClassifier()
        result = c._fallback_classification("Падение рынка", "Кризис и убытки")
        assert result["sentiment"] == "negative"

    def test_classify_article_uses_fallback_without_llm(self):
        from src.data.news_classifier import NewsClassifier
        c = NewsClassifier()
        result = c.classify_article("Санкции", "Новые ограничения против банков")
        assert "category" in result


class TestSectorMapper:
    def test_basic_instantiation(self):
        from src.data.sector_mapper import SectorMapper
        m = SectorMapper()
        assert m is not None

    def test_extract_sectors_from_text(self):
        from src.data.sector_mapper import SectorMapper
        m = SectorMapper()
        sectors = m.extract_sectors_from_text("нефть газ золото банк")
        assert "energy" in sectors
        assert "metals" in sectors
        assert "banking" in sectors

    def test_extract_geographic_context(self):
        from src.data.sector_mapper import SectorMapper
        m = SectorMapper()
        regions = m.extract_geographic_context("россия сша китай")
        assert "russia" in regions
        assert "usa" in regions
        assert "china" in regions


class TestImpactMatrix:
    def test_basic_instantiation(self):
        from src.data.impact_matrix import ImpactMatrix
        m = ImpactMatrix()
        assert m is not None

    def test_get_impact(self):
        from src.data.impact_matrix import ImpactMatrix
        m = ImpactMatrix()
        impact = m.get_impact("sanctions", "energy", 8.0)
        assert 0 < impact <= 10

    def test_calculate_decay_fresh(self):
        from datetime import datetime, timedelta
        from src.data.impact_matrix import ImpactMatrix
        m = ImpactMatrix()
        decay = m.calculate_decay(datetime.utcnow())
        assert decay == 1.0

    def test_calculate_decay_old(self):
        from datetime import datetime, timedelta
        from src.data.impact_matrix import ImpactMatrix
        m = ImpactMatrix()
        decay = m.calculate_decay(datetime.utcnow() - timedelta(days=120))
        assert decay < 0.1


class TestEventDetector:
    def test_basic_instantiation(self):
        from src.data.event_detector import EventDetector
        d = EventDetector()
        assert d is not None

    def test_cosine_similarity_identical(self):
        from src.data.event_detector import EventDetector
        d = EventDetector()
        sim = d._cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        assert sim == 1.0

    def test_cosine_similarity_orthogonal(self):
        from src.data.event_detector import EventDetector
        d = EventDetector()
        sim = d._cosine_similarity([1.0, 0.0], [0.0, 1.0])
        assert sim == 0.0

    def test_cosine_similarity_empty(self):
        from src.data.event_detector import EventDetector
        d = EventDetector()
        sim = d._cosine_similarity([], [1.0, 0.0])
        assert sim == 0.0

    def test_cosine_similarity_half(self):
        from src.data.event_detector import EventDetector
        d = EventDetector()
        sim = d._cosine_similarity([1.0, 0.0], [0.5, 0.5])
        expected = 0.5 / (1.0 * (0.5**2 + 0.5**2)**0.5)
        assert abs(sim - expected) < 0.01


class TestSentimentDivergenceDetector:
    def test_basic_instantiation(self):
        from src.data.event_detector import SentimentDivergenceDetector
        d = SentimentDivergenceDetector()
        assert d is not None
        assert d.threshold == 0.4


class TestGeopoliticalRiskEngine:
    def test_basic_instantiation(self):
        from src.data.geopolitical_risk_engine import GeopoliticalRiskEngine
        e = GeopoliticalRiskEngine()
        assert e is not None

    def test_extract_region_from_news_russia(self):
        from src.data.geopolitical_risk_engine import GeopoliticalRiskEngine
        e = GeopoliticalRiskEngine()
        region = e.extract_region_from_news("Россия вводит ответные меры", "")
        assert region == "russia"

    def test_extract_region_from_news_none(self):
        from src.data.geopolitical_risk_engine import GeopoliticalRiskEngine
        e = GeopoliticalRiskEngine()
        region = e.extract_region_from_news("Погода на сегодня", "")
        assert region is None

    def test_get_risk_alert_level(self):
        from src.data.geopolitical_risk_engine import GeopoliticalRiskEngine
        e = GeopoliticalRiskEngine()
        assert e.get_risk_alert_level(2.0) == "low"
        assert e.get_risk_alert_level(4.0) == "medium"
        assert e.get_risk_alert_level(6.0) == "high"
        assert e.get_risk_alert_level(8.0) == "critical"


class TestDashboardProvider:
    def test_basic_instantiation(self):
        from src.data.dashboard_provider import DashboardDataProvider
        p = DashboardDataProvider()
        assert p is not None

    def test_get_risk_color(self):
        from src.data.dashboard_provider import DashboardDataProvider
        assert DashboardDataProvider._get_risk_color(1) == "green"
        assert DashboardDataProvider._get_risk_color(3) == "yellow"
        assert DashboardDataProvider._get_risk_color(6) == "orange"
        assert DashboardDataProvider._get_risk_color(8) == "red"

    def test_get_risk_level(self):
        from src.data.dashboard_provider import DashboardDataProvider
        assert DashboardDataProvider._get_risk_level(2) == "low"
        assert DashboardDataProvider._get_risk_level(4) == "medium"
        assert DashboardDataProvider._get_risk_level(6) == "high"
        assert DashboardDataProvider._get_risk_level(8) == "critical"


class TestNewsSystemFactory:
    def test_singleton(self):
        from src.data.news_system import NewsSystemFactory
        f1 = NewsSystemFactory()
        f2 = NewsSystemFactory()
        assert f1 is f2

    def test_initialize(self):
        from src.data.news_system import NewsSystemFactory
        NewsSystemFactory._instance = None
        NewsSystemFactory._components = {}
        factory = NewsSystemFactory.initialize()
        assert factory is not None
        assert "filter" in factory._components
        assert "classifier" in factory._components
        assert "batch_processor" in factory._components

    def test_get_component(self):
        from src.data.news_system import NewsSystemFactory
        NewsSystemFactory._instance = None
        NewsSystemFactory._components = {}
        factory = NewsSystemFactory.initialize()
        assert factory.get_filter() is not None
        assert factory.get_classifier() is not None
        assert factory.get_batch_processor() is not None

    def test_get_unknown_component(self):
        from src.data.news_system import NewsSystemFactory
        NewsSystemFactory._instance = None
        NewsSystemFactory._components = {}
        factory = NewsSystemFactory.initialize()
        with pytest.raises(ValueError, match="not found"):
            factory.get("nonexistent")


class TestNewsClusterer:
    def test_basic_instantiation(self):
        from src.data.news_clusterer import NewsClusterer
        c = NewsClusterer()
        assert c is not None
        assert c.threshold == 0.85
        assert c.time_window_days == 3

    def test_cosine_similarity_identical(self):
        from src.data.news_clusterer import _cosine_similarity
        sim = _cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        assert sim == 1.0

    def test_cosine_similarity_orthogonal(self):
        from src.data.news_clusterer import _cosine_similarity
        sim = _cosine_similarity([1.0, 0.0], [0.0, 1.0])
        assert sim == 0.0

    def test_cosine_similarity_empty(self):
        from src.data.news_clusterer import _cosine_similarity
        assert _cosine_similarity([], [1.0, 0.0]) == 0.0

    def test_generate_embedding_no_embedder(self, monkeypatch):
        from src.data.news_clusterer import NewsClusterer
        c = NewsClusterer()
        c._embedder = None
        emb = c.generate_embedding("test", "summary here")
        assert isinstance(emb, list)
        assert len(emb) == 768

    def test_generate_embedding_fallback_deterministic(self, monkeypatch):
        from src.data.news_clusterer import NewsClusterer
        c = NewsClusterer()
        c._embedder = None
        emb1 = c.generate_embedding("same text", "same summary")
        emb2 = c.generate_embedding("same text", "same summary")
        assert emb1 == emb2

    def test_cluster_no_articles(self, monkeypatch):
        from src.data.news_clusterer import NewsClusterer
        c = NewsClusterer()
        c._embedder = None
        result = c.cluster_articles([])
        assert result == []

    def test_cluster_single_article(self, monkeypatch):
        from src.data.news_clusterer import NewsClusterer
        import datetime
        article = type("Article", (), {
            "id": 1,
            "embedding": [0.1] * 768,
            "published_at": datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc),
            "title": "test",
            "summary": "",
            "sentiment": "positive",
            "category": "ECONOMY",
            "subcategory": None,
            "impact_score": 0.5,
        })
        c = NewsClusterer()
        c._embedder = None
        result = c.cluster_articles([article])
        assert result == []

    def test_cluster_two_similar(self, monkeypatch):
        from src.data.news_clusterer import NewsClusterer
        import datetime, hashlib, numpy as np
        text = "Russia raises key rate"
        h = int(hashlib.md5(text.lower().encode()).hexdigest(), 16)
        np.random.seed(h % (2**32))
        emb = np.random.randn(768).tolist()
        a1 = type("Article", (), {
            "id": 1,
            "embedding": emb,
            "published_at": datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc),
            "title": "Russia raises key rate",
            "summary": "Central bank decision",
            "sentiment": "negative",
            "category": "ECONOMY",
            "subcategory": None,
            "impact_score": 0.8,
        })
        a2 = type("Article", (), {
            "id": 2,
            "embedding": emb,
            "published_at": datetime.datetime(2025, 1, 2, tzinfo=datetime.timezone.utc),
            "title": "Russia raises key rate",
            "summary": "Central bank decision",
            "sentiment": "negative",
            "category": "ECONOMY",
            "subcategory": None,
            "impact_score": 0.7,
        })
        c = NewsClusterer()
        c._embedder = None
        result = c.cluster_articles([a1, a2])
        assert len(result) == 1
        assert len(result[0]) == 2

    def test_cluster_time_window_exceeded(self, monkeypatch):
        from src.data.news_clusterer import NewsClusterer
        import datetime, hashlib, numpy as np
        text = "Some news"
        h = int(hashlib.md5(text.lower().encode()).hexdigest(), 16)
        np.random.seed(h % (2**32))
        emb = np.random.randn(768).tolist()
        a1 = type("Article", (), {
            "id": 1,
            "embedding": emb,
            "published_at": datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc),
            "title": "",
            "summary": "",
            "sentiment": "neutral",
            "category": "GENERAL",
            "subcategory": None,
            "impact_score": 0.0,
        })
        a2 = type("Article", (), {
            "id": 2,
            "embedding": emb,
            "published_at": datetime.datetime(2025, 1, 10, tzinfo=datetime.timezone.utc),
            "title": "",
            "summary": "",
            "sentiment": "neutral",
            "category": "GENERAL",
            "subcategory": None,
            "impact_score": 0.0,
        })
        c = NewsClusterer(time_window_days=3)
        c._embedder = None
        result = c.cluster_articles([a1, a2])
        assert result == []

    def test_fallback_embedding_deterministic(self):
        from src.data.news_clusterer import NewsClusterer
        emb1 = NewsClusterer._fallback_embedding("test text")
        emb2 = NewsClusterer._fallback_embedding("test text")
        assert emb1 == emb2
        assert len(emb1) == 768

    def test_fallback_embedding_different_texts_differ(self):
        from src.data.news_clusterer import NewsClusterer
        emb1 = NewsClusterer._fallback_embedding("hello world")
        emb2 = NewsClusterer._fallback_embedding("goodbye world")
        assert emb1 != emb2

    def test_get_or_create_event(self):
        from src.data.news_clusterer import _get_or_create_event
        import datetime
        a1 = type("Article", (), {
            "id": 1,
            "title": "Main event",
            "summary": "details",
            "category": "POLITICS",
            "subcategory": "conflict",
            "impact_score": 0.9,
            "sentiment": "negative",
            "published_at": datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc),
        })
        a2 = type("Article", (), {
            "id": 2,
            "title": "Follow up",
            "summary": "more details",
            "category": "POLITICS",
            "subcategory": "conflict",
            "impact_score": 0.7,
            "sentiment": "positive",
            "published_at": datetime.datetime(2025, 1, 2, tzinfo=datetime.timezone.utc),
        })
        event = _get_or_create_event(None, [a1, a2])
        assert event.title == "Main event"
        assert event.category == "POLITICS"
        assert event.subcategory == "conflict"
        assert event.impact_score == 0.9
        assert event.article_count == 2


class TestNewsDeduplicator:
    def test_basic_instantiation(self):
        from src.data.news_processor import NewsDeduplicator
        d = NewsDeduplicator()
        assert d is not None

    def test_fallback_embedding_produces_list(self):
        from src.data.news_processor import NewsDeduplicator
        d = NewsDeduplicator()
        emb = d._fallback_embedding("test text")
        assert isinstance(emb, list)
        assert len(emb) > 0


class TestCompanyRiskAggregator:
    def test_basic_instantiation(self):
        from src.data.company_risk_aggregator import CompanyRiskAggregator
        a = CompanyRiskAggregator()
        assert a is not None


class TestSignalFusionIntegration:
    def test_instantiation_requires_deps(self):
        from src.data.signal_fusion_integration import SignalFusionIntegration
        from src.data.geopolitical_risk_engine import GeopoliticalRiskEngine
        from src.data.sector_impact_engine import SectorImpactEngine
        from src.data.company_risk_aggregator import CompanyRiskAggregator
        from src.data.event_detector import EventDetector
        from src.data.impact_matrix import ImpactMatrix
        from src.data.sector_mapper import SectorMapper

        geo = GeopoliticalRiskEngine()
        impact = ImpactMatrix()
        mapper = SectorMapper()
        sector = SectorImpactEngine(impact, mapper)
        company = CompanyRiskAggregator()
        event = EventDetector()
        integration = SignalFusionIntegration(geo, sector, company, event)
        assert integration is not None
