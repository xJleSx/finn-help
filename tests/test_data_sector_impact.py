from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from src.data.sector_impact_engine import EWMARiskCalculator, SectorCorrelationTracker, SectorImpactEngine


class TestEWMARiskCalculator:
    def test_init_defaults(self):
        calc = EWMARiskCalculator()
        assert calc.alpha == 0.3
        assert calc.momentum_window == 7

    def test_calculate_empty(self):
        calc = EWMARiskCalculator()
        assert calc.calculate([]) == 0.0

    def test_calculate_single(self):
        calc = EWMARiskCalculator()
        assert calc.calculate([5.0]) == 5.0

    def test_calculate_with_weights(self):
        calc = EWMARiskCalculator()
        result = calc.calculate([1.0, 2.0], weights=[0.5, 0.5])
        assert result == 1.5

    def test_calculate_mismatched_weights(self):
        calc = EWMARiskCalculator()
        result = calc.calculate([1.0, 2.0], weights=[0.5])
        assert result > 0

    def test_momentum_insufficient_data(self):
        calc = EWMARiskCalculator()
        assert calc.momentum([1.0]) == 0.0

    def test_momentum_positive(self):
        calc = EWMARiskCalculator(momentum_window=3)
        result = calc.momentum([1.0, 2.0, 3.0, 4.0, 5.0])
        assert result > 0

    def test_confidence_zero_articles(self):
        calc = EWMARiskCalculator()
        assert calc.confidence(0) == 0.0

    def test_confidence_max(self):
        calc = EWMARiskCalculator()
        assert calc.confidence(100) == 1.0


class TestSectorCorrelationTracker:
    def test_init(self):
        tracker = SectorCorrelationTracker()
        assert tracker.matrix == {}

    def test_get_contagion_risk_unknown(self):
        tracker = SectorCorrelationTracker()
        assert tracker.get_contagion_risk("unknown") == []

    def test_get_contagion_risk_with_data(self):
        tracker = SectorCorrelationTracker()
        tracker.matrix = {"energy": {"energy": 1.0, "metals": 0.8}}
        result = tracker.get_contagion_risk("energy", threshold=0.5)
        assert len(result) == 1
        assert result[0][0] == "metals"


class TestSectorImpactEngine:
    def test_init(self):
        impact_matrix = MagicMock()
        sector_mapper = MagicMock()
        engine = SectorImpactEngine(impact_matrix, sector_mapper)
        assert engine is not None

    def test_calculate_sector_impact_no_news(self):
        impact_matrix = MagicMock()
        sector_mapper = MagicMock()
        engine = SectorImpactEngine(impact_matrix, sector_mapper)
        article = MagicMock(is_relevant=False)
        result = engine.calculate_sector_impact_from_news(article, None)
        assert result == {}
