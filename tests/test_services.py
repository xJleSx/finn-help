"""Tests for service layer: AuthService, PortfolioService, MarketService"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth_service import AuthService
from src.market.service import MarketService
from src.portfolio.service import PortfolioService

pytestmark = [pytest.mark.asyncio]


class TestAuthService:
    async def test_register_and_login(self, async_db_session: AsyncSession) -> None:
        svc = AuthService(async_db_session)
        result = await svc.register(username="testuser", password="secret123")
        assert result["username"] == "testuser"
        assert "access_token" in result
        assert result["token_type"] == "bearer"

        # login
        login_result = await svc.login(username="testuser", password="secret123")
        assert login_result["username"] == "testuser"
        assert "access_token" in login_result

    async def test_register_duplicate(self, async_db_session: AsyncSession) -> None:
        svc = AuthService(async_db_session)
        await svc.register(username="dupuser", password="secret123")
        with pytest.raises(HTTPException) as exc:
            await svc.register(username="dupuser", password="other123")
        assert exc.value.status_code == 400

    async def test_login_invalid(self, async_db_session: AsyncSession) -> None:
        svc = AuthService(async_db_session)
        with pytest.raises(HTTPException) as exc:
            await svc.login(username="nobody", password="x")
        assert exc.value.status_code == 401


class TestPortfolioService:
    async def test_empty_portfolio(self, async_db_session: AsyncSession) -> None:
        svc = PortfolioService(async_db_session)
        positions = await svc.get_positions(user_id=1)
        assert positions == []

    async def test_add_position_instrument_not_found(self, async_db_session: AsyncSession) -> None:
        svc = PortfolioService(async_db_session)
        with pytest.raises(HTTPException) as exc:
            await svc.add_position(user_id=1, ticker="NONEXIST", quantity=10)
        assert exc.value.status_code == 404

    async def test_get_signals_csv_empty(self, async_db_session: AsyncSession) -> None:
        svc = PortfolioService(async_db_session)
        signals = await svc.get_signals_for_csv()
        assert signals == []

    async def test_get_positions_for_csv_no_user(self, async_db_session: AsyncSession) -> None:
        svc = PortfolioService(async_db_session)
        positions = await svc.get_positions_for_csv(user_id=None)
        assert positions == []


class TestMarketService:
    async def test_list_instruments_empty(self, async_db_session: AsyncSession) -> None:
        svc = MarketService(async_db_session)
        result = await svc.list_instruments()
        assert result == []

    async def test_list_instruments_with_filter(self, async_db_session: AsyncSession) -> None:
        svc = MarketService(async_db_session)
        result = await svc.list_instruments(type_filter="stock")
        assert result == []

    async def test_get_instrument_not_found(self, async_db_session: AsyncSession) -> None:
        svc = MarketService(async_db_session)
        with pytest.raises(HTTPException) as exc:
            await svc.get_instrument("NONEXIST")
        assert exc.value.status_code == 404

    async def test_get_prices_instrument_not_found(self, async_db_session: AsyncSession) -> None:
        svc = MarketService(async_db_session)
        with pytest.raises(HTTPException) as exc:
            await svc.get_prices("NONEXIST")
        assert exc.value.status_code == 404

    async def test_get_indicators_instrument_not_found(self, async_db_session: AsyncSession) -> None:
        svc = MarketService(async_db_session)
        with pytest.raises(HTTPException) as exc:
            await svc.get_indicators("NONEXIST")
        assert exc.value.status_code == 404

    async def test_get_news_empty(self, async_db_session: AsyncSession) -> None:
        svc = MarketService(async_db_session)
        news = await svc.get_news(limit=10)
        assert news == []

    async def test_get_geo_risk_empty(self, async_db_session: AsyncSession) -> None:
        svc = MarketService(async_db_session)
        risks = await svc.get_geo_risk(days=30)
        assert risks == []
