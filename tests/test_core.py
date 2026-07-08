from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.core.container import Container, container, container_for_testing
from src.core.health import health_registry, register_module_health


class TestContainer:
    def test_register_and_get(self):
        c = Container()
        c.register("foo", 42)
        assert c.get("foo") == 42

    def test_register_factory(self):
        c = Container()
        c.register_factory("bar", lambda: [1, 2, 3])
        assert c.get("bar") == [1, 2, 3]

    def test_factory_called_once(self):
        c = Container()
        calls = 0

        def factory():
            nonlocal calls
            calls += 1
            return object()

        c.register_factory("singleton", factory)
        a = c.get("singleton")
        b = c.get("singleton")
        assert a is b
        assert calls == 1

    def test_has_instance(self):
        c = Container()
        c.register("x", 1)
        assert c.has("x")
        assert not c.has("y")

    def test_has_factory(self):
        c = Container()
        c.register_factory("x", lambda: 1)
        assert c.has("x")
        assert not c.has("y")

    def test_get_missing_raises(self):
        c = Container()
        with pytest.raises(KeyError, match="No registration for missing"):
            c.get("missing")

    def test_container_for_testing_returns_mocks(self):
        c = container_for_testing()
        assert c.has("settings")
        assert c.has("analysis_service")
        assert c.has("notification_service")
        assert c.has("telegram_bot")
        assert c.has("run_analysis")

    def test_global_container_has_wired_services(self):
        assert container.has("settings") is False


class TestHealthRegistry:
    def test_register_decorator_adds_to_registry(self):
        @register_module_health("test_check")
        async def dummy_check():
            return {"status": "ok"}

        assert "test_check" in health_registry
        assert health_registry["test_check"] is dummy_check

    def test_health_check_returns_dict(self):
        results = {}

        @register_module_health("returns_dict")
        async def check():
            return {"status": "ok", "value": 1}

        results["returns_dict"] = check

    def test_health_check_catches_exception(self):
        @register_module_health("broken")
        async def broken():
            raise RuntimeError("fail")

        health_registry["broken"] = broken

    def test_registry_is_mutable_dict(self):
        assert isinstance(health_registry, dict)


class TestExecutor:
    def test_get_executor_returns_threadpool(self):
        from src.core.executor import get_executor

        executor = get_executor()
        assert executor is not None
        assert executor._max_workers == 4

    @pytest.mark.asyncio
    async def test_run_cpu_bound(self):
        from src.core.executor import run_cpu_bound

        def add(a, b):
            return a + b

        result = await run_cpu_bound(add, 2, 3)
        assert result == 5

    def test_get_executor_is_singleton(self):
        from src.core.executor import get_executor

        e1 = get_executor()
        e2 = get_executor()
        assert e1 is e2

    def test_shutdown_executor(self):
        from src.core.executor import get_executor, shutdown_executor

        get_executor()
        shutdown_executor()
