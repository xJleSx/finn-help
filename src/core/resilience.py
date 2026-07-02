from __future__ import annotations

import asyncio
import enum
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, ParamSpec, TypeVar

logger = logging.getLogger(__name__)

P = ParamSpec("P")
RT = TypeVar("RT")

CircuitBreakerFn = Callable[..., Coroutine[Any, Any, Any]]


class CircuitState(enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    half_open_max_calls: int = 1
    name: str = "default"


@dataclass
class CircuitBreaker:
    config: CircuitBreakerConfig
    _state: CircuitState = CircuitState.CLOSED
    _failure_count: int = 0
    _last_failure_time: float = 0.0
    _half_open_calls: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def call(self, fn: CircuitBreakerFn, *args: Any, **kwargs: Any) -> Any:
        async with self._lock:
            if self._state is CircuitState.OPEN:
                if time.monotonic() - self._last_failure_time >= self.config.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                    logger.info("circuit_breaker.half_open", name=self.config.name)
                else:
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker '{self.config.name}' is OPEN"
                    )

            if self._state is CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.config.half_open_max_calls:
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker '{self.config.name}' is HALF_OPEN, "
                        f"max probe calls reached"
                    )
                self._half_open_calls += 1

        try:
            result = await fn(*args, **kwargs)
        except Exception as e:
            async with self._lock:
                self._failure_count += 1
                self._last_failure_time = time.monotonic()
                if self._failure_count >= self.config.failure_threshold:
                    self._state = CircuitState.OPEN
                    logger.warning(
                        "circuit_breaker.opened",
                        name=self.config.name,
                        failures=self._failure_count,
                    )
            raise e

        async with self._lock:
            if self._state is CircuitState.HALF_OPEN:
                logger.info("circuit_breaker.closed", name=self.config.name)
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._half_open_calls = 0

        return result

    async def reset(self) -> None:
        async with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._half_open_calls = 0

    @property
    def state(self) -> CircuitState:
        return self._state


class CircuitBreakerOpenError(Exception):
    pass


_circuit_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(name: str = "default") -> CircuitBreaker:
    if name not in _circuit_breakers:
        _circuit_breakers[name] = CircuitBreaker(CircuitBreakerConfig(name=name))
    return _circuit_breakers[name]


def with_circuit_breaker(name: str = "default") -> Callable[[CircuitBreakerFn], CircuitBreakerFn]:
    def decorator(fn: CircuitBreakerFn) -> CircuitBreakerFn:
        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            cb = get_circuit_breaker(name)
            return await cb.call(fn, *args, **kwargs)
        return wrapper
    return decorator


async def reset_circuit_breaker(name: str) -> None:
    cb = get_circuit_breaker(name)
    await cb.reset()


async def reset_all_circuit_breakers() -> None:
    for cb in _circuit_breakers.values():
        await cb.reset()
