from __future__ import annotations

import asyncio
import importlib
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")


class Container:
    """Async-aware DI container with scoped lifecycle support.

    Architecture reference:
      - docs/ARCHITECTURE.md — DI overview
      - docs/adr/ADR-003-dependency-injection.md — decision rationale
      - src/interfaces/api/dependencies.py — FastAPI Depends wiring
    """

    def __init__(self) -> None:
        self._instances: dict[str, Any] = {}
        self._factories: dict[str, Callable[[], Any]] = {}
        self._async_factories: dict[str, Callable[[], Awaitable[Any]]] = {}

    def register(self, key: str, instance: Any) -> None:
        self._instances[key] = instance

    def register_factory(self, key: str, factory: Callable[[], Any]) -> None:
        self._factories[key] = factory

    def register_async_factory(self, key: str, factory: Callable[[], Awaitable[Any]]) -> None:
        self._async_factories[key] = factory

    def get(self, key: str) -> Any:
        if key in self._instances:
            return self._instances[key]
        if key in self._factories:
            instance = self._factories[key]()
            self._instances[key] = instance
            return instance
        raise KeyError(f"No registration for {key}")

    async def get_async(self, key: str) -> Any:
        if key in self._instances:
            return self._instances[key]
        if key in self._factories:
            instance = self._factories[key]()
            self._instances[key] = instance
            return instance
        if key in self._async_factories:
            instance = await self._async_factories[key]()
            self._instances[key] = instance
            return instance
        raise KeyError(f"No registration for {key}")

    def get_or_none(self, key: str) -> Any:
        try:
            return self.get(key)
        except KeyError:
            return None

    def has(self, key: str) -> bool:
        return key in self._instances or key in self._factories or key in self._async_factories

    def clear(self) -> None:
        self._instances.clear()
        self._factories.clear()
        self._async_factories.clear()


container = Container()


def wire(settings_override: Any = None) -> None:
    """Register all singleton services into the container.

    Uses lazy imports and supports both sync and async factories.
    """
    from src.config import settings as _settings

    settings = settings_override or _settings
    container.register("settings", settings)

    _register_analysis()
    _register_social()
    _register_scheduler()
    _register_services()


def _register_analysis() -> None:
    from src.analysis.context import ticker_context_builder
    from src.analysis.correlation import correlation
    from src.analysis.events import event_features
    from src.analysis.loader import data_loader
    from src.analysis.ml_coordinator import ml_coordinator
    from src.analysis.rebalancing import rebalancing_engine
    from src.analysis.sector import sector_analyzer
    from src.analysis.service import analysis_service

    container.register("analysis_service", analysis_service)
    container.register("sector_analyzer", sector_analyzer)
    container.register("ml_coordinator", ml_coordinator)
    container.register("event_features", event_features)
    container.register("data_loader", data_loader)
    container.register("ticker_context_builder", ticker_context_builder)
    container.register("correlation_analyzer", correlation)
    container.register("rebalancing_engine", rebalancing_engine)


def _register_social() -> None:
    from src.social.registry import registry as social_registry
    from src.social.sentiment.aggregator import aggregator as social_aggregator
    from src.social.sentiment.analyzer import analyzer as social_analyzer

    container.register("social_registry", social_registry)
    container.register("social_aggregator", social_aggregator)
    container.register("social_analyzer", social_analyzer)


def _register_scheduler() -> None:
    from src.scheduler.collectors import divergence as sched_divergence
    from src.scheduler.collectors import geo_risk as sched_geo_risk
    from src.scheduler.tasks import fusion as sched_fusion

    container.register("scheduler_divergence", sched_divergence)
    container.register("scheduler_geo_risk", sched_geo_risk)
    container.register("scheduler_fusion", sched_fusion)


def _register_services() -> None:
    from src.alerts.push import AlertPushService
    from src.interfaces.nlq import nlq
    from src.llm.rate_limiter import _retry_handler as groq_retry_handler
    from src.llm.router import llm as llm_router
    from src.notifications.service import NotificationService
    from src.portfolio.allocator import allocator
    from src.user_profile import profile_manager

    container.register("profile_manager", profile_manager)
    container.register("nlq_engine", nlq)
    container.register("groq_retry_handler", groq_retry_handler)
    container.register("portfolio_allocator", allocator)
    container.register("llm_router", llm_router)

    container.register_factory("alert_push_service", lambda: AlertPushService())
    container.register_factory("notification_service", lambda: NotificationService())
    container.register_factory("position_tracker", lambda: importlib.import_module("src.trading.execution.stoploss").position_tracker)
    container.register_factory("telegram_bot", lambda: importlib.import_module("src.interfaces.telegram").run_bot)
    container.register_factory("bot_app", lambda: importlib.import_module("src.interfaces.telegram").app)
    container.register_factory("run_analysis", lambda: importlib.import_module("src.cli").run_analysis)


def container_for_testing() -> Container:
    """Return a Container with mock services for test use."""
    from unittest.mock import MagicMock

    c = Container()
    keys = [
        "settings", "analysis_service", "sector_analyzer", "ml_coordinator",
        "event_features", "data_loader", "ticker_context_builder",
        "correlation_analyzer", "rebalancing_engine", "profile_manager",
        "alert_push_service", "social_registry", "social_aggregator",
        "social_analyzer", "position_tracker", "scheduler_divergence",
        "scheduler_geo_risk", "scheduler_fusion", "nlq_engine",
        "groq_retry_handler", "portfolio_allocator", "llm_router",
        "notification_service", "telegram_bot", "bot_app", "run_analysis",
    ]
    for key in keys:
        c.register(key, MagicMock())
    return c
