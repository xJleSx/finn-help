from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth_service import AuthService
from src.core.container import container, wire
from src.interfaces.api.auth import get_db, get_read_db
from src.analysis.service import AnalysisService
from src.market.service import MarketService
from src.notifications.service import NotificationService
from src.portfolio.service import PortfolioService

wire()


def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(db)


def get_portfolio_service(db: AsyncSession = Depends(get_db)) -> PortfolioService:
    return PortfolioService(db)


def get_portfolio_service_readonly(db: AsyncSession = Depends(get_read_db)) -> PortfolioService:
    return PortfolioService(db)


def get_market_service(db: AsyncSession = Depends(get_db)) -> MarketService:
    return MarketService(
        db=db,
        analysis_service=container.get("analysis_service"),
        llm_router=container.get("llm_router"),
        notification_service=container.get("notification_service"),
    )


def get_market_service_readonly(db: AsyncSession = Depends(get_read_db)) -> MarketService:
    return MarketService(
        db=db,
        analysis_service=container.get("analysis_service"),
        llm_router=container.get("llm_router"),
        notification_service=container.get("notification_service"),
    )


def get_notification_service(db: AsyncSession = Depends(get_db)) -> NotificationService:
    return NotificationService(db=db)


def get_analysis_service() -> AnalysisService:
    return container.get("analysis_service")  # type: ignore[no-any-return]
