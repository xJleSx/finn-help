from __future__ import annotations

from unittest.mock import MagicMock

from src.data.signal_fusion_integration import SignalFusionIntegration


class TestSignalFusionIntegration:
    def test_init(self):
        geo = MagicMock()
        sector = MagicMock()
        company = MagicMock()
        event = MagicMock()
        integration = SignalFusionIntegration(geo, sector, company, event)
        assert integration is not None

    def test_generate_news_risk_signal(self):
        integration = SignalFusionIntegration(MagicMock(), MagicMock(), MagicMock(), MagicMock())
        instrument = MagicMock()
        result = integration.generate_news_risk_signal(instrument, MagicMock())
        assert isinstance(result, dict)
