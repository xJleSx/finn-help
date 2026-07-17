from __future__ import annotations

from typing import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.analysis.service import AnalysisService
from src.core.auth_service import AuthService
from src.core.container import container, wire
from src.db.connection import get_async_session
from src.market.service import MarketService
from src.notifications.service import NotificationService
from src.portfolio.service import PortfolioService

wire()

__all__ = [
    "get_db",
    "get_read_db",
    "get_auth_service",
    "get_portfolio_service",
    "get_portfolio_service_readonly",
    "get_market_service",
    "get_market_service_readonly",
    "get_notification_service",
    "get_analysis_service",
    "get_analysis_service_from_container",
]


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_async_session() as session:
        yield session


async def get_read_db() -> AsyncIterator[AsyncSession]:
    from src.db.connection import get_read_replica_session

    async with get_read_replica_session() as session:
        yield session


def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(db)


def get_portfolio_service(db: AsyncSession = Depends(get_db)) -> PortfolioService:
    return PortfolioService(db)


def get_portfolio_service_readonly(db: AsyncSession = Depends(get_read_db)) -> PortfolioService:
    return PortfolioService(db)


def get_market_service(db: AsyncSession = Depends(get_db)) -> MarketService:
    _analysis = container.get("analysis_service")
    _llm = container.get("llm_router")
    _notif = container.get("notification_service")
    return MarketService(
        db=db,
        analysis_service=_analysis,
        llm_router=_llm,
        notification_service=_notif,
    )


def get_market_service_readonly(db: AsyncSession = Depends(get_read_db)) -> MarketService:
    _analysis = container.get("analysis_service")
    _llm = container.get("llm_router")
    _notif = container.get("notification_service")
    return MarketService(
        db=db,
        analysis_service=_analysis,
        llm_router=_llm,
        notification_service=_notif,
    )


def get_notification_service(db: AsyncSession = Depends(get_db)) -> NotificationService:
    return NotificationService(db=db)


def get_analysis_service() -> AnalysisService:
    return container.get("analysis_service")


get_analysis_service_from_container = get_analysis_service
