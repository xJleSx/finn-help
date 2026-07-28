from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, TypeVar, overload

T = TypeVar("T")


class Lifecycle(Enum):
    SINGLETON = "singleton"
    SCOPED = "scoped"
    TRANSIENT = "transient"


@dataclass
class Registration:
    instance: Any = None
    factory: Callable[[], Any] | None = None
    async_factory: Callable[[], Awaitable[Any]] | None = None
    lifecycle: Lifecycle = Lifecycle.SINGLETON


class Scope:
    def __init__(self, parent: Container) -> None:
        self._parent = parent
        self._locals: dict[str, Any] = {}

    def resolve(self, key: str) -> Any:
        if key in self._locals:
            return self._locals[key]
        reg = self._parent._registry.get(key)
        if reg is None:
            raise KeyError(f"No registration for {key}")
        if reg.lifecycle == Lifecycle.SCOPED:
            instance = self._instantiate(reg)
            self._locals[key] = instance
            return instance
        return self._parent._resolve(key)

    async def resolve_async(self, key: str) -> Any:
        if key in self._locals:
            return self._locals[key]
        reg = self._parent._registry.get(key)
        if reg is None:
            raise KeyError(f"No registration for {key}")
        if reg.lifecycle == Lifecycle.SCOPED:
            instance = await self._instantiate_async(reg)
            self._locals[key] = instance
            return instance
        return await self._parent._resolve_async(key)

    def _instantiate(self, reg: Registration) -> Any:
        if reg.factory:
            return reg.factory()
        if reg.async_factory:
            raise RuntimeError(f"Cannot sync-resolve async factory for {reg}")
        raise RuntimeError(f"Registration {reg} has no factory")

    async def _instantiate_async(self, reg: Registration) -> Any:
        if reg.async_factory:
            return await reg.async_factory()
        if reg.factory:
            return reg.factory()
        raise RuntimeError(f"Registration {reg} has no factory")


class Container:
    def __init__(self) -> None:
        self._instances: dict[str, Any] = {}
        self._factories: dict[str, Callable[[], Any]] = {}
        self._async_factories: dict[str, Callable[[], Awaitable[Any]]] = {}
        self._registry: dict[str, Registration] = {}

    def register(self, key: str, instance: Any) -> None:
        self._instances[key] = instance
        self._registry[key] = Registration(instance=instance, lifecycle=Lifecycle.SINGLETON)

    def register_factory(self, key: str, factory: Callable[[], Any], lifecycle: Lifecycle = Lifecycle.SINGLETON) -> None:
        self._factories[key] = factory
        self._registry[key] = Registration(factory=factory, lifecycle=lifecycle)

    def register_async_factory(self, key: str, factory: Callable[[], Awaitable[Any]], lifecycle: Lifecycle = Lifecycle.SINGLETON) -> None:
        self._async_factories[key] = factory
        self._registry[key] = Registration(async_factory=factory, lifecycle=lifecycle)

    def register_type(self, key: str, cls: type, lifecycle: Lifecycle = Lifecycle.SINGLETON) -> None:
        def _factory() -> Any:
            return cls()
        self.register_factory(key, _factory, lifecycle=lifecycle)

    def create_scope(self) -> Scope:
        return Scope(self)

    def _resolve(self, key: str) -> Any:
        if key in self._instances:
            reg = self._registry.get(key)
            if reg is not None and reg.lifecycle == Lifecycle.TRANSIENT:
                del self._instances[key]
            else:
                return self._instances[key]
        if key in self._factories:
            reg = self._registry[key]
            if reg.lifecycle == Lifecycle.SINGLETON:
                instance = self._factories[key]()
                self._instances[key] = instance
                return instance
            return self._factories[key]()
        raise KeyError(f"No registration for {key}")

    async def _resolve_async(self, key: str) -> Any:
        if key in self._instances:
            reg = self._registry.get(key)
            if reg is not None and reg.lifecycle == Lifecycle.TRANSIENT:
                del self._instances[key]
            else:
                return self._instances[key]
        if key in self._factories:
            reg = self._registry[key]
            if reg.lifecycle == Lifecycle.SINGLETON:
                instance = self._factories[key]()
                self._instances[key] = instance
                return instance
            return self._factories[key]()
        if key in self._async_factories:
            reg = self._registry[key]
            if reg.lifecycle == Lifecycle.SINGLETON:
                instance = await self._async_factories[key]()
                self._instances[key] = instance
                return instance
            return await self._async_factories[key]()
        raise KeyError(f"No registration for {key}")

    @overload
    def get(self, key: str) -> Any: ...

    @overload
    def get(self, cls: type[T]) -> T: ...

    def get(self, key_or_cls: str | type[T]) -> Any:
        if isinstance(key_or_cls, type):
            return self._resolve(key_or_cls.__name__)
        return self._resolve(key_or_cls)

    @overload
    async def get_async(self, key: str) -> Any: ...

    @overload
    async def get_async(self, cls: type[T]) -> T: ...

    async def get_async(self, key_or_cls: str | type[T]) -> Any:
        if isinstance(key_or_cls, type):
            return await self._resolve_async(key_or_cls.__name__)
        return await self._resolve_async(key_or_cls)

    def get_or_none(self, key: str) -> Any:
        try:
            return self._resolve(key)
        except KeyError:
            return None

    def has(self, key: str) -> bool:
        return key in self._registry

    def clear(self) -> None:
        self._instances.clear()
        self._factories.clear()
        self._async_factories.clear()
        self._registry.clear()

    def dispose(self) -> None:
        logger = logging.getLogger(__name__)
        for key, instance in self._instances.items():
            if hasattr(instance, "close") and callable(instance.close):
                try:
                    instance.close()
                except Exception as e:
                    logger.exception("Failed to dispose %s: %s", key, e)
        self.clear()


container = Container()


def wire(settings_override: Any = None) -> None:
    from src.config import settings as _settings
    settings = settings_override or _settings
    container.register("settings", settings)
    _register_analysis()
    _register_social()
    _register_scheduler()
    _register_services()
    _register_core()


def _register_analysis() -> None:
    from src.analysis.context import ticker_context_builder
    from src.analysis.events import event_features
    from src.analysis.loader import data_loader
    from src.analysis.market.correlation import correlation
    from src.analysis.market.sector import sector_analyzer
    from src.analysis.ml_coordinator import ml_coordinator
    from src.analysis.rebalancing import rebalancing_engine
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


def _register_core() -> None:
    container.register_factory("event_bus", lambda: importlib.import_module("src.core.event_bus").get_event_bus())
    container.register_factory("circuit_breaker", lambda: importlib.import_module("src.core.resilience").get_circuit_breaker())
    container.register_factory("rate_limiter", lambda: importlib.import_module("src.core.resilience").get_rate_limiter())


def _register_services() -> None:
    from src.alerts.push import AlertPushService
    from src.user_profile import profile_manager
    container.register("profile_manager", profile_manager)
    container.register_factory("nlq_engine", lambda: importlib.import_module("src.interfaces.nlq").nlq)
    container.register_factory("groq_retry_handler", lambda: importlib.import_module("src.llm.rate_limiter")._retry_handler)
    container.register_factory("portfolio_allocator", lambda: importlib.import_module("src.portfolio.allocator").allocator)
    container.register_factory("llm_router", lambda: importlib.import_module("src.llm.router").llm)
    container.register_factory("alert_push_service", lambda: AlertPushService())
    container.register_factory("notification_service", lambda: NotificationService())
    container.register_factory("position_tracker", lambda: importlib.import_module("src.trading.execution.stoploss").position_tracker)
    container.register_factory("telegram_bot", lambda: importlib.import_module("src.interfaces.telegram").run_bot)
    container.register_factory("bot_app", lambda: importlib.import_module("src.interfaces.telegram").app)
    container.register_factory("run_analysis", lambda: importlib.import_module("src.cli").run_analysis)


def container_for_testing(overrides: dict[str, Any] | None = None) -> Container:
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
    overrides = overrides or {}
    for key in keys:
        if key in overrides:
            c.register(key, overrides[key])
        else:
            c.register(key, MagicMock())
    missing_core = [k for k in ("settings",) if k not in overrides and k in keys]
    if missing_core:
        logger = logging.getLogger(__name__)
        logger.warning("container_for_testing: core deps %s are MagicMock, replace for real tests", missing_core)
    return c
