from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from src.data.impact_matrix import ImpactMatrix


class TestImpactMatrix:
    def test_init(self):
        matrix = ImpactMatrix()
        assert matrix is not None

    def test_get_impact_known_combination(self):
        matrix = ImpactMatrix()
        result = matrix.get_impact("sanctions", "energy", 0.5)
        assert isinstance(result, float)
        assert 0 <= result <= 10

    def test_get_impact_unknown_event_type_fallsback(self):
        matrix = ImpactMatrix()
        result = matrix.get_impact("unknown_event", "energy", 0.5)
        assert isinstance(result, float)
        assert result > 0

    def test_get_impact_zero_base(self):
        matrix = ImpactMatrix()
        result = matrix.get_impact("sanctions", "energy", 0.0)
        assert result == 0.0

    def test_get_impact_max_adjustment(self):
        matrix = ImpactMatrix()
        result = matrix.get_impact("sanctions", "energy", 10.0)
        assert result <= 10.0

    def test_calculate_decay_fresh(self):
        matrix = ImpactMatrix()
        now = datetime.now(timezone.utc)
        assert matrix.calculate_decay(now, now) == 1.0

    def test_calculate_decay_old(self):
        matrix = ImpactMatrix()
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=365)
        assert matrix.calculate_decay(old, now) < 0.5

    def test_calculate_decay_recent(self):
        matrix = ImpactMatrix()
        now = datetime.now(timezone.utc)
        recent = now - timedelta(hours=1)
        assert matrix.calculate_decay(recent, now) > 0.9

    def test_calculate_decay_negative_age(self):
        matrix = ImpactMatrix()
        now = datetime.now(timezone.utc)
        future = now + timedelta(days=1)
        assert matrix.calculate_decay(future, now) == 1.0

    def test_calculate_sector_daily_risk_empty(self):
        matrix = ImpactMatrix()
        result = matrix.calculate_sector_daily_risk("energy", [])
        assert result["total_risk"] == 0.0
