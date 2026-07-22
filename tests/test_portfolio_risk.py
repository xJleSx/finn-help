from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.portfolio.risk import _compute_risk_from_closes, item_risk, item_risk_async


def _make_price(close: float | None) -> MagicMock:
    p = MagicMock()
    p.close = close
    p.date = "2024-01-01"
    return p


class TestItemRisk:
    def test_short_price_list_returns_defaults(self):
        item = {"id": 1}
        db = MagicMock()
        db.query.return_value.filter_by.return_value.order_by.return_value.limit.return_value.all.return_value = [
            _make_price(100.0) for _ in range(5)
        ]
        result = item_risk(item, db)
        assert result == {"var_95": 0.0, "stop_loss_pct": 0.0, "position_limit_pct": 5.0}

    def test_few_close_values_after_none_filter_returns_defaults(self):
        item = {"id": 1}
        db = MagicMock()
        prices = [_make_price(100.0) for _ in range(10)]
        prices[0].close = None
        prices[1].close = None
        db.query.return_value.filter_by.return_value.order_by.return_value.limit.return_value.all.return_value = prices
        result = item_risk(item, db)
        assert result == {"var_95": 0.0, "stop_loss_pct": 0.0, "position_limit_pct": 5.0}

    @patch("src.portfolio.risk._compute_risk_from_closes")
    def test_delegates_to_compute_risk_from_closes(self, mock_compute):
        item = {"id": 1}
        db = MagicMock()
        prices = [_make_price(float(i)) for i in range(60, 0, -1)]
        db.query.return_value.filter_by.return_value.order_by.return_value.limit.return_value.all.return_value = prices
        mock_compute.return_value = {"var_95": 1.5, "stop_loss_pct": -10.0, "position_limit_pct": 5.0}
        result = item_risk(item, db, capital=50_000)
        mock_compute.assert_called_once()
        assert result["var_95"] == 1.5

    @patch("src.portfolio.risk._compute_risk_from_closes")
    def test_passes_correct_close_vals(self, mock_compute):
        item = {"id": 1}
        db = MagicMock()
        prices = [_make_price(float(i)) for i in range(60, 0, -1)]
        db.query.return_value.filter_by.return_value.order_by.return_value.limit.return_value.all.return_value = prices
        mock_compute.return_value = {"var_95": 0.0}
        item_risk(item, db)
        close_vals = mock_compute.call_args[0][0]
        assert close_vals == [float(i) for i in range(60, 0, -1)]


class TestItemRiskAsync:
    @pytest.mark.asyncio
    async def test_short_price_list_returns_defaults(self):
        item = {"id": 1}
        db = AsyncMock()
        result_proxy = MagicMock()
        result_proxy.scalars.return_value.all.return_value = [_make_price(100.0) for _ in range(5)]
        db.execute.return_value = result_proxy
        result = await item_risk_async(item, db)
        assert result == {"var_95": 0.0, "stop_loss_pct": 0.0, "position_limit_pct": 5.0}

    @pytest.mark.asyncio
    async def test_few_close_values_after_none_filter_returns_defaults(self):
        item = {"id": 1}
        db = AsyncMock()
        prices = [_make_price(100.0) for _ in range(10)]
        prices[0].close = None
        prices[1].close = None
        result_proxy = MagicMock()
        result_proxy.scalars.return_value.all.return_value = prices
        db.execute.return_value = result_proxy
        result = await item_risk_async(item, db)
        assert result == {"var_95": 0.0, "stop_loss_pct": 0.0, "position_limit_pct": 5.0}

    @pytest.mark.asyncio
    @patch("src.portfolio.risk._compute_risk_from_closes")
    async def test_delegates_to_compute_risk_from_closes(self, mock_compute):
        item = {"id": 1}
        db = AsyncMock()
        prices = [_make_price(float(i)) for i in range(60, 0, -1)]
        result_proxy = MagicMock()
        result_proxy.scalars.return_value.all.return_value = prices
        db.execute.return_value = result_proxy
        mock_compute.return_value = {"var_95": 2.0}
        result = await item_risk_async(item, db, capital=75_000)
        mock_compute.assert_called_once()
        assert result["var_95"] == 2.0

    @pytest.mark.asyncio
    @patch("src.portfolio.risk._compute_risk_from_closes")
    async def test_passes_correct_close_vals(self, mock_compute):
        item = {"id": 1}
        db = AsyncMock()
        prices = [_make_price(float(i)) for i in range(60, 0, -1)]
        result_proxy = MagicMock()
        result_proxy.scalars.return_value.all.return_value = prices
        db.execute.return_value = result_proxy
        mock_compute.return_value = {"var_95": 0.0}
        await item_risk_async(item, db)
        close_vals = mock_compute.call_args[0][0]
        assert close_vals == [float(i) for i in range(60, 0, -1)]


class TestComputeRiskFromCloses:
    @patch("src.trading.risk.manager.compute_var")
    @patch("src.trading.risk.manager.compute_stop_loss")
    @patch("src.trading.risk.manager.compute_position_size")
    @patch("src.trading.risk.manager.compute_concentration_limit")
    @patch("src.trading.risk.manager.compute_risk_score")
    def test_returns_expected_structure(
        self, mock_risk_score, mock_conc, mock_sizing, mock_stop, mock_var
    ):
        mock_var.return_value = {"var_95": 1.5, "var_99": 3.0, "cvar_95": 2.0}
        mock_stop.return_value = {"stop_loss": 90.0, "stop_loss_pct": -10.0}
        mock_sizing.return_value = {"shares": 100, "amount": 10000.0}
        mock_conc.return_value = {"shares": 500, "amount": 50000.0}
        mock_risk_score.return_value = 0.35

        result = _compute_risk_from_closes(
            close_vals=[100.0, 101.0, 102.0],
            item={"id": 1},
            capital=100_000,
        )

        assert result["var_95"] == 1.5
        assert result["var_99"] == 3.0
        assert result["cvar_95"] == 2.0
        assert result["stop_loss"] == 90.0
        assert result["stop_loss_pct"] == -10.0
        assert result["suggested_shares"] == 100
        assert result["risk_amount"] == 10000.0
        assert result["risk_per_trade_pct"] == 2.0
        assert result["max_position_shares"] == 500
        assert result["max_position_amount"] == 50000.0
        assert result["risk_score"] == 0.35

    @patch("src.trading.risk.manager.compute_var")
    @patch("src.trading.risk.manager.compute_stop_loss")
    @patch("src.trading.risk.manager.compute_position_size")
    @patch("src.trading.risk.manager.compute_concentration_limit")
    @patch("src.trading.risk.manager.compute_risk_score")
    def test_stop_loss_none(
        self, mock_risk_score, mock_conc, mock_sizing, mock_stop, mock_var
    ):
        mock_var.return_value = {"var_95": 0.0, "var_99": 0.0, "cvar_95": 0.0}
        mock_stop.return_value = None
        mock_sizing.return_value = {"shares": 0, "amount": 0.0}
        mock_conc.return_value = {"shares": 0, "amount": 0.0}
        mock_risk_score.return_value = 0.0

        result = _compute_risk_from_closes(
            close_vals=[100.0],
            item={"id": 1},
            capital=100_000,
        )

        assert result["stop_loss"] is None
        assert result["stop_loss_pct"] == 0.0

    @patch("src.trading.risk.manager.compute_var")
    @patch("src.trading.risk.manager.compute_stop_loss")
    @patch("src.trading.risk.manager.compute_position_size")
    @patch("src.trading.risk.manager.compute_concentration_limit")
    @patch("src.trading.risk.manager.compute_risk_score")
    def test_zero_var_handling(
        self, mock_risk_score, mock_conc, mock_sizing, mock_stop, mock_var
    ):
        mock_var.return_value = {"var_95": 0.0, "var_99": 0.0, "cvar_95": 0.0}
        mock_stop.return_value = {"stop_loss": 95.0, "stop_loss_pct": -5.0}
        mock_sizing.return_value = {"shares": 50, "amount": 5000.0}
        mock_conc.return_value = {"shares": 200, "amount": 20000.0}
        mock_risk_score.return_value = 0.1

        result = _compute_risk_from_closes(
            close_vals=[100.0],
            item={"id": 1},
            capital=100_000,
        )

        assert result["var_95"] == 0.0
        assert result["var_99"] == 0.0
        assert result["cvar_95"] == 0.0

    @patch("src.trading.risk.manager.compute_var")
    @patch("src.trading.risk.manager.compute_stop_loss")
    @patch("src.trading.risk.manager.compute_position_size")
    @patch("src.trading.risk.manager.compute_concentration_limit")
    @patch("src.trading.risk.manager.compute_risk_score")
    def test_missing_var_keys(
        self, mock_risk_score, mock_conc, mock_sizing, mock_stop, mock_var
    ):
        mock_var.return_value = {}
        mock_stop.return_value = {"stop_loss": 90.0, "stop_loss_pct": -10.0}
        mock_sizing.return_value = {"shares": 100, "amount": 10000.0}
        mock_conc.return_value = {"shares": 500, "amount": 50000.0}
        mock_risk_score.return_value = 0.2

        result = _compute_risk_from_closes(
            close_vals=[100.0],
            item={"id": 1},
            capital=100_000,
        )

        assert result["var_95"] == 0.0
        assert result["var_99"] == 0.0
        assert result["cvar_95"] == 0.0
