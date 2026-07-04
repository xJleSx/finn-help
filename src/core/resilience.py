from __future__ import annotations

import asyncio
import enum
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Optional, ParamSpec, TypeVar

logger = logging.getLogger(__name__)

P = ParamSpec("P")
RT = TypeVar("RT")

CircuitBreakerFn = Callable[..., Coroutine[Any, Any, Any]]
StateChangeCallback = Callable[[str, "CircuitState", "CircuitState"], None]


class CircuitState(enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    half_open_max_calls: int = 1
    success_threshold: int = 2
    name: str = "default"


@dataclass
class CircuitBreaker:
    config: CircuitBreakerConfig
    _state: CircuitState = CircuitState.CLOSED
    _failure_count: int = 0
    _last_failure_time: float = 0.0
    _half_open_calls: int = 0
    _consecutive_successes: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _on_state_change: Optional[StateChangeCallback] = None

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @property
    def is_open(self) -> bool:
        return self._state is CircuitState.OPEN

    @property
    def is_closed(self) -> bool:
        return self._state is CircuitState.CLOSED

    def on_state_change(self, callback: StateChangeCallback) -> None:
        self._on_state_change = callback

    def _transition(self, new_state: CircuitState) -> None:
        old_state = self._state
        if old_state == new_state:
            return
        self._state = new_state
        logger.info(
            "circuit_breaker.state_change name=%s old=%s new=%s failures=%d",
            self.config.name,
            old_state.value,
            new_state.value,
            self._failure_count,
        )
        if self._on_state_change:
            try:
                self._on_state_change(self.config.name, old_state, new_state)
            except Exception:
                logger.exception("circuit_breaker.on_state_change failed name=%s", self.config.name)

    async def call(
        self,
        fn: CircuitBreakerFn,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        async with self._lock:
            if self._state is CircuitState.OPEN:
                if time.monotonic() - self._last_failure_time >= self.config.recovery_timeout:
                    self._consecutive_successes = 0
                    self._half_open_calls = 0
                    self._transition(CircuitState.HALF_OPEN)
                else:
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker '{self.config.name}' is OPEN "
                        f"(failures={self._failure_count}, "
                        f"retry_in={self.config.recovery_timeout - (time.monotonic() - self._last_failure_time):.0f}s)"
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
                self._consecutive_successes = 0
                self._last_failure_time = time.monotonic()
                if self._state is CircuitState.HALF_OPEN:
                    self._transition(CircuitState.OPEN)
                elif self._failure_count >= self.config.failure_threshold:
                    self._transition(CircuitState.OPEN)
            raise e

        async with self._lock:
            if self._state is CircuitState.HALF_OPEN:
                self._consecutive_successes += 1
                if self._consecutive_successes >= self.config.success_threshold:
                    self._failure_count = 0
                    self._half_open_calls = 0
                    self._consecutive_successes = 0
                    self._transition(CircuitState.CLOSED)

        return result

    async def reset(self) -> None:
        async with self._lock:
            old = self._state
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._half_open_calls = 0
            self._consecutive_successes = 0
            if old != CircuitState.CLOSED:
                self._transition(CircuitState.CLOSED)

    def snapshot(self) -> dict[str, object]:
        return {
            "name": self.config.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.config.failure_threshold,
            "consecutive_successes": self._consecutive_successes,
            "success_threshold": self.config.success_threshold,
            "recovery_timeout": self.config.recovery_timeout,
            "last_failure_age": time.monotonic() - self._last_failure_time if self._last_failure_time else 0,
        }


class CircuitBreakerOpenError(Exception):
    pass


_circuit_breakers: dict[str, CircuitBreaker] = {}
_circuit_breakers_lock = asyncio.Lock()


def get_circuit_breaker(name: str = "default") -> CircuitBreaker:
    if name not in _circuit_breakers:
        _circuit_breakers[name] = CircuitBreaker(CircuitBreakerConfig(name=name))
    return _circuit_breakers[name]


def configure_circuit_breaker(name: str, **kwargs: Any) -> CircuitBreaker:
    cb = get_circuit_breaker(name)
    for k, v in kwargs.items():
        if hasattr(cb.config, k):
            setattr(cb.config, k, v)
    return cb


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


def get_all_circuit_states() -> dict[str, dict[str, object]]:
    return {name: cb.snapshot() for name, cb in _circuit_breakers.items()}
