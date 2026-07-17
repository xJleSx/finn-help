"""Tests for bond alert broadcasting."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_broadcast_bond_alerts_no_app():
    with patch("src.interfaces.telegram_broadcaster.app", None):
        from src.interfaces.telegram_broadcaster import broadcast_bond_alerts
        result = await broadcast_bond_alerts(alert_type="all")
        assert result is None


@pytest.mark.asyncio
async def test_broadcast_bond_alerts_no_alerts():
    mock_app = MagicMock()
    mock_app.bot = AsyncMock()

    with patch("src.interfaces.telegram_broadcaster.app", mock_app):
        with patch("src.alerts.generators.generate_bond_coupon_alerts", return_value=[]):
            with patch("src.alerts.generators.generate_bond_maturity_alerts", return_value=[]):
                with patch("src.alerts.generators.generate_bond_rating_alerts", return_value=[]):
                    with patch("src.alerts.generators.generate_bond_spread_alerts", return_value=[]):
                        from src.interfaces.telegram_broadcaster import broadcast_bond_alerts
                        await broadcast_bond_alerts(alert_type="all")
                        mock_app.bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_broadcast_bond_alerts_sends_message():
    mock_app = MagicMock()
    mock_app.bot = AsyncMock()

    mock_alert = {
        "alert_type": "bond_coupon",
        "ticker": "SU26238",
        "title": "Coupon Alert",
        "message": "Coupon payment of 42.50 due in 5 days",
    }

    mock_ns = MagicMock()
    mock_ns.get_subscribers = MagicMock(return_value=[(12345, 12345)])

    with patch("src.interfaces.telegram_broadcaster.app", mock_app):
        with patch("src.interfaces.telegram_broadcaster.NotificationService", return_value=mock_ns):
            with patch("src.alerts.generators.generate_bond_coupon_alerts", return_value=[mock_alert]):
                with patch("src.alerts.generators.generate_bond_maturity_alerts", return_value=[]):
                    with patch("src.alerts.generators.generate_bond_rating_alerts", return_value=[]):
                        with patch("src.alerts.generators.generate_bond_spread_alerts", return_value=[]):
                            from src.interfaces.telegram_broadcaster import broadcast_bond_alerts
                            await broadcast_bond_alerts(alert_type="bond_coupon")
                            mock_app.bot.send_message.assert_called_once()
                            args, kwargs = mock_app.bot.send_message.call_args
                            assert kwargs["chat_id"] == 12345
                            assert "SU26238" in kwargs["text"]
                            assert "Coupon Alert" in kwargs["text"]
