from __future__ import annotations

import dataclasses
import logging
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
import structlog
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

logger = structlog.get_logger(__name__)


class ResilientClient:
    def __init__(
        self,
        name: str = "default",
        max_retries: int = 3,
        base_wait: float = 1.0,
        max_wait: float = 30.0,
        timeout: float = 30.0,
        circuit_breaker_failure_threshold: int = 5,
        circuit_breaker_recovery_timeout: float = 30.0,
    ) -> None:
        self._name = name
        self._max_retries = max_retries
        self._base_wait = base_wait
        self._max_wait = max_wait
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._closed: bool = False
        self._circuit_breaker_config = dataclasses.replace(
            get_circuit_breaker(name).config,
            failure_threshold=circuit_breaker_failure_threshold,
            recovery_timeout=circuit_breaker_recovery_timeout,
        )
        self._circuit_breaker: CircuitBreaker = CircuitBreaker(self._circuit_breaker_config)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._closed:
            raise RuntimeError("Client has been closed")
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        async def _do_request() -> httpx.Response:
            client = await self._get_client()
            resp = await client.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=self._base_wait, max=self._max_wait),
            retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.RequestError, httpx.TimeoutException)),
            before=before_log(logger, logging.DEBUG),
            reraise=True,
        ):
            with attempt:
                try:
                    return await self._circuit_breaker.call(_do_request)
                except CircuitBreakerOpenError:
                    if attempt.retry_state.attempt_number < self._max_retries:
                        logger.warning(
                            "circuit_breaker.open.retry",
                            name=self._name,
                            attempt=attempt.retry_state.attempt_number,
                        )
                        raise
                    raise
        raise RuntimeError(f"Request to {url} returned no result after {self._max_retries} retries")

    async def get_json(self, url: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        if params:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{urlencode(params, doseq=True)}"
        resp = await self.request("GET", url)
        data = resp.json()
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict response, got {type(data).__name__}")
        return data

    async def get_text(self, url: str, params: Optional[dict[str, Any]] = None) -> str:
        resp = await self.request("GET", url, params=params)
        return resp.text

    async def close(self) -> None:
        self._closed = True
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
