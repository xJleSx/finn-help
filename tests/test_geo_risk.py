from __future__ import annotations

from src.geo.risk_scorer import GeoRiskScorer


class TestCountKeywords:
    def setup_method(self):
        self.scorer = GeoRiskScorer()

    def test_empty_news(self):
        assert self.scorer._count_keywords([], ["санкции"]) == 0.0

    def test_matches_keyword(self):
        news = [{"title": "Новые санкции против", "summary": ""}]
        score = self.scorer._count_keywords(news, ["санкции"])
        assert score > 0

    def test_no_match(self):
        news = [{"title": "Хорошие новости", "summary": "Рост рынка"}]
        score = self.scorer._count_keywords(news, ["санкции", "кризис"])
        assert score == 0.0

    def test_capped_at_4(self):
        news = [{"title": f"санкции {i}"} for i in range(20)]
        score = self.scorer._count_keywords(news, ["санкции"])
        assert score <= 4.0


class TestLevel:
    def setup_method(self):
        self.scorer = GeoRiskScorer()

    def test_critical(self):
        assert self.scorer._level(8.0) == "CRITICAL"

    def test_high(self):
        assert self.scorer._level(6.0) == "HIGH"

    def test_moderate(self):
        assert self.scorer._level(4.0) == "MODERATE"

    def test_low(self):
        assert self.scorer._level(1.0) == "LOW"

    def test_boundaries(self):
        assert self.scorer._level(7.0) == "CRITICAL"
        assert self.scorer._level(5.0) == "HIGH"
        assert self.scorer._level(3.0) == "MODERATE"


class TestScore:
    def setup_method(self):
        self.scorer = GeoRiskScorer()

    def test_zero_risk(self):
        result = self.scorer.score([], 0.0)
        assert result["score"] == 0.0
        assert result["level"] == "LOW"

    def test_sanctions_risk(self):
        news = [{"title": "санкции против экономики", "summary": ""}]
        result = self.scorer.score(news, 0.0)
        assert result["score"] > 0
        assert "санкционных" in str(result["signals"])

    def test_currency_stress(self):
        result = self.scorer.score([], currency_volatility=0.15)
        assert result["components"]["currency_stress"] > 0

    def test_critical_risk(self):
        news = [{"title": f"санкции кризис обвал шок дефолт {i}"} for i in range(10)]
        result = self.scorer.score(news, 0.5)
        assert result["level"] == "CRITICAL"

    def test_returns_expected_keys(self):
        result = self.scorer.score([], 0.0)
        assert set(result.keys()) == {"score", "level", "components", "signals"}
