"""Base class for all data collectors."""

import asyncio
import logging
from abc import ABC
from typing import Any, Optional, Self

import httpx
from tenacity import (
    AsyncRetrying,
    before_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.core.resilience import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    get_circuit_breaker,
)

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    BASE_URL: str = ""
    MAX_RETRIES: int = 3
    RETRY_DELAY: float = 2.0
    TIMEOUT: float = 30.0

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None
        self._circuit_breaker: CircuitBreaker = get_circuit_breaker(self.__class__.__name__)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.TIMEOUT, follow_redirects=True)
        return self._client

    async def _fetch_json(self, url: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        async def _do_fetch() -> dict[str, Any]:
            client = await self._get_client()
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                raise ValueError(f"Expected dict response, got {type(data).__name__}")
            return data

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.MAX_RETRIES),
            wait=wait_exponential(multiplier=self.RETRY_DELAY, max=30.0),
            retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.RequestError, ValueError)),
            before=before_log(logger, logging.DEBUG),
            reraise=True,
        ):
            with attempt:
                try:
                    return await self._circuit_breaker.call(_do_fetch)
                except CircuitBreakerOpenError:
                    if attempt.retry_state.attempt_number < self.MAX_RETRIES:
                        delay = self.RETRY_DELAY * (2 ** (attempt.retry_state.attempt_number - 1))
                        logger.warning(
                            "circuit_breaker.open.%s attempt %d/%d, retrying in %.1fs",
                            self.__class__.__name__,
                            attempt.retry_state.attempt_number,
                            self.MAX_RETRIES,
                            delay,
                        )
                        await asyncio.sleep(delay)
                        raise
                    logger.error(
                        "circuit_breaker.open.%s exhausted after %d attempts",
                        self.__class__.__name__,
                        self.MAX_RETRIES,
                    )
                    raise

    async def _fetch_text(self, url: str, params: Optional[dict[str, Any]] = None, headers: Optional[dict[str, str]] = None) -> str:
        async def _do_fetch() -> str:
            client = await self._get_client()
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            return resp.text

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.MAX_RETRIES),
            wait=wait_exponential(multiplier=self.RETRY_DELAY, max=30.0),
            retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.RequestError)),
            before=before_log(logger, logging.DEBUG),
            reraise=True,
        ):
            with attempt:
                try:
                    return await self._circuit_breaker.call(_do_fetch)
                except CircuitBreakerOpenError:
                    if attempt.retry_state.attempt_number < self.MAX_RETRIES:
                        delay = self.RETRY_DELAY * (2 ** (attempt.retry_state.attempt_number - 1))
                        logger.warning(
                            "circuit_breaker.open.%s attempt %d/%d, retrying in %.1fs",
                            self.__class__.__name__,
                            attempt.retry_state.attempt_number,
                            self.MAX_RETRIES,
                            delay,
                        )
                        await asyncio.sleep(delay)
                        raise
                    logger.error(
                        "circuit_breaker.open.%s exhausted after %d attempts",
                        self.__class__.__name__,
                        self.MAX_RETRIES,
                    )
                    raise

    async def _fetch_json_or_list(self, url: str, params: Optional[dict[str, Any]] = None, headers: Optional[dict[str, str]] = None) -> dict[str, Any] | list[Any]:
        async def _do_fetch() -> dict[str, Any] | list[Any]:
            client = await self._get_client()
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.MAX_RETRIES),
            wait=wait_exponential(multiplier=self.RETRY_DELAY, max=30.0),
            retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.RequestError)),
            before=before_log(logger, logging.DEBUG),
            reraise=True,
        ):
            with attempt:
                try:
                    return await self._circuit_breaker.call(_do_fetch)
                except CircuitBreakerOpenError:
                    if attempt.retry_state.attempt_number < self.MAX_RETRIES:
                        delay = self.RETRY_DELAY * (2 ** (attempt.retry_state.attempt_number - 1))
                        logger.warning(
                            "circuit_breaker.open.%s attempt %d/%d, retrying in %.1fs",
                            self.__class__.__name__,
                            attempt.retry_state.attempt_number,
                            self.MAX_RETRIES,
                            delay,
                        )
                        await asyncio.sleep(delay)
                        raise
                    logger.error(
                        "circuit_breaker.open.%s exhausted after %d attempts",
                        self.__class__.__name__,
                        self.MAX_RETRIES,
                    )
                    raise

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
