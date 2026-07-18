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
    AsyncRateLimiter,
    CircuitBreaker,
    CircuitBreakerOpenError,
    RateLimiterConfig,
    get_circuit_breaker,
    get_rate_limiter,
)

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    BASE_URL: str = ""
    MAX_RETRIES: int = 3
    RETRY_DELAY: float = 2.0
    TIMEOUT: float = 30.0
    RATE_LIMIT: float = 10.0  # max requests per second (MOEX ISS default)

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None
        self._circuit_breaker: CircuitBreaker = get_circuit_breaker(self.__class__.__name__)
        self._rate_limiter: AsyncRateLimiter = get_rate_limiter(
            self.__class__.__name__,
            RateLimiterConfig(max_rate=self.RATE_LIMIT, burst_multiplier=3),
        )

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.TIMEOUT, follow_redirects=True)
        return self._client

    async def _rate_limited_fetch(self, url: str, params: Optional[dict[str, Any]] = None) -> httpx.Response:
        client = await self._get_client()
        async with self._rate_limiter:
            return await client.get(url, params=params)

    async def _fetch_json(self, url: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        async def _do_fetch() -> dict[str, Any]:
            resp = await self._rate_limited_fetch(url, params)
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
        return None

    async def _fetch_text(self, url: str, params: Optional[dict[str, Any]] = None, headers: Optional[dict[str, str]] = None) -> str:
        async def _do_fetch() -> str:
            async with self._rate_limiter:
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
        return None

    async def _fetch_json_or_list(
        self, url: str, params: Optional[dict[str, Any]] = None, headers: Optional[dict[str, str]] = None
    ) -> dict[str, Any] | list[Any]:
        async def _do_fetch() -> dict[str, Any] | list[Any]:
            async with self._rate_limiter:
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
        return None

    async def _paginate(
        self,
        path: str,
        params: Optional[dict[str, Any]] = None,
        table_name: str = "securities",
        page_size: int = 100,
        max_pages: int = 50,
    ) -> list[dict[str, Any]]:
        """Generic cursor-based pagination for MOEX ISS endpoints.

        Iterates through pages using the 'start' cursor parameter
        and reading '{table_name}.cursor' from the response.
        """
        all_rows: list[dict[str, Any]] = []
        base_params = dict(params or {})
        base_params.setdefault("iss.meta", "off")
        start = 0

        for _ in range(max_pages):
            page_params = {**base_params, "start": str(start)}
            data = await self._fetch_json(path, page_params)
            rows = self._parse_table(data, table_name)
            if not rows:
                break
            all_rows.extend(rows)

            cursor = data.get(f"{table_name}.cursor") or data.get("cursor")
            if isinstance(cursor, dict):
                cursor_rows = cursor.get("data", [])
                if cursor_rows and len(cursor_rows[0]) > 1:
                    total = int(cursor_rows[0][1])
                    if start + len(rows) >= total:
                        break
                    start += len(rows)
                    continue
            break

        return all_rows

    @staticmethod
    def _parse_table(data: dict[str, Any], table_name: str) -> list[dict[str, Any]]:
        """Parse a named table from a MOEX ISS JSON response."""
        table = data.get(table_name)
        if not isinstance(table, dict):
            return []
        cols = table.get("columns")
        rows = table.get("data")
        if not isinstance(cols, list) or not isinstance(rows, list):
            return []
        return [dict(zip(cols, row)) for row in rows]

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
