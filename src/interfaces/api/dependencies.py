from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.analysis.service import AnalysisService
from src.core.auth_service import AuthService
from src.interfaces.api.auth import get_db
from src.market.service import MarketService
from src.notifications.service import NotificationService
from src.portfolio.service import PortfolioService


def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(db)


def get_portfolio_service(db: AsyncSession = Depends(get_db)) -> PortfolioService:
    return PortfolioService(db)


def get_market_service(db: AsyncSession = Depends(get_db)) -> MarketService:
    return MarketService(db)


def get_notification_service(db: AsyncSession = Depends(get_db)) -> NotificationService:
    return NotificationService(db=db)


def get_analysis_service() -> AnalysisService:
    return AnalysisService()
