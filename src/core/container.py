from __future__ import annotations

from typing import Any, Callable


class Container:
    """Simple DI container."""

    def __init__(self) -> None:
        self._instances: dict[str, Any] = {}
        self._factories: dict[str, Callable[[], Any]] = {}

    def register(self, key: str, instance: Any) -> None:
        self._instances[key] = instance

    def register_factory(self, key: str, factory: Callable[[], Any]) -> None:
        self._factories[key] = factory

    def get(self, key: str) -> Any:
        if key in self._instances:
            return self._instances[key]
        if key in self._factories:
            instance = self._factories[key]()
            self._instances[key] = instance
            return instance
        raise KeyError(f"No registration for {key}")

    def has(self, key: str) -> bool:
        return key in self._instances or key in self._factories


container = Container()


def wire(settings_override: Any = None) -> None:
    """Register all singleton services into the container."""

    from src.config import settings as _settings
    from src.analysis.service import analysis_service
    from src.analysis.sector import sector_analyzer
    from src.analysis.ml_coordinator import ml_coordinator
    from src.analysis.events import event_features
    from src.analysis.loader import data_loader
    from src.analysis.context import ticker_context_builder
    from src.analysis.correlation import correlation
    from src.analysis.rebalancing import rebalancing_engine
    from src.llm.router import llm as llm_router
    from src.notifications.service import NotificationService
    from src.portfolio.allocator import allocator
    from src.user_profile import profile_manager
    from src.alerts.push import AlertPushService
    from src.social.registry import registry as social_registry
    from src.social.sentiment.aggregator import aggregator as social_aggregator
    from src.social.sentiment.analyzer import analyzer as social_analyzer
    from src.scheduler.collectors import divergence as sched_divergence
    from src.scheduler.collectors import geo_risk as sched_geo_risk
    from src.scheduler.tasks import fusion as sched_fusion
    from src.interfaces.nlq import nlq
    from src.llm.rate_limiter import _retry_handler as groq_retry_handler

    settings = settings_override or _settings

    container.register("settings", settings)

    container.register("analysis_service", analysis_service)
    container.register("sector_analyzer", sector_analyzer)
    container.register("ml_coordinator", ml_coordinator)
    container.register("event_features", event_features)
    container.register("data_loader", data_loader)
    container.register("ticker_context_builder", ticker_context_builder)
    container.register("correlation_analyzer", correlation)
    container.register("rebalancing_engine", rebalancing_engine)
    container.register("profile_manager", profile_manager)
    container.register_factory("alert_push_service", lambda: AlertPushService())
    container.register("social_registry", social_registry)
    container.register("social_aggregator", social_aggregator)
    container.register("social_analyzer", social_analyzer)
    container.register_factory("position_tracker", lambda: __import__("src.trading.execution.stoploss", fromlist=["position_tracker"]).position_tracker)
    container.register("scheduler_divergence", sched_divergence)
    container.register("scheduler_geo_risk", sched_geo_risk)
    container.register("scheduler_fusion", sched_fusion)
    container.register("nlq_engine", nlq)
    container.register("groq_retry_handler", groq_retry_handler)
    container.register("portfolio_allocator", allocator)

    container.register("llm_router", llm_router)
    container.register_factory("notification_service", lambda: NotificationService())
    container.register_factory("telegram_bot", lambda: __import__("src.interfaces.telegram", fromlist=["run_bot"]).run_bot)
    container.register_factory("bot_app", lambda: __import__("src.interfaces.telegram", fromlist=["app"]).app)
    container.register_factory("run_analysis", lambda: __import__("src.cli", fromlist=["run_analysis"]).run_analysis)


def container_for_testing() -> Container:
    """Return a Container with mock services for test use."""
    from unittest.mock import MagicMock

    c = Container()
    c.register("settings", MagicMock())
    c.register("analysis_service", MagicMock())
    c.register("sector_analyzer", MagicMock())
    c.register("ml_coordinator", MagicMock())
    c.register("event_features", MagicMock())
    c.register("data_loader", MagicMock())
    c.register("ticker_context_builder", MagicMock())
    c.register("correlation_analyzer", MagicMock())
    c.register("rebalancing_engine", MagicMock())
    c.register("profile_manager", MagicMock())
    c.register("alert_push_service", MagicMock())
    c.register("social_registry", MagicMock())
    c.register("social_aggregator", MagicMock())
    c.register("social_analyzer", MagicMock())
    c.register("position_tracker", MagicMock())
    c.register("scheduler_divergence", MagicMock())
    c.register("scheduler_geo_risk", MagicMock())
    c.register("scheduler_fusion", MagicMock())
    c.register("nlq_engine", MagicMock())
    c.register("groq_retry_handler", MagicMock())
    c.register("portfolio_allocator", MagicMock())
    c.register("llm_router", MagicMock())
    c.register("notification_service", MagicMock())
    c.register("telegram_bot", MagicMock())
    c.register("bot_app", MagicMock())
    c.register("run_analysis", MagicMock())
    return c
