"""Base class for all data collectors."""

import asyncio
import logging
from abc import ABC
from typing import Any, Optional, Self

import httpx

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    BASE_URL: str = ""
    MAX_RETRIES: int = 3
    RETRY_DELAY: float = 2.0
    TIMEOUT: float = 30.0

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.TIMEOUT)
        return self._client

    async def _fetch_json(self, url: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        client = await self._get_client()
        last_exc = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, dict):
                    raise ValueError(f"Expected dict response, got {type(data).__name__}")
                return data
            except (httpx.HTTPStatusError, httpx.RequestError, ValueError) as exc:
                last_exc = exc
                if attempt < self.MAX_RETRIES:
                    delay = self.RETRY_DELAY * (2 ** (attempt - 1))
                    logger.warning(
                        "Attempt %d/%d failed for %s: %s — retrying in %.1fs",
                        attempt, self.MAX_RETRIES, url, exc, delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error("Failed after %d attempts for %s: %s", self.MAX_RETRIES, url, exc)
        raise last_exc  # type: ignore[misc]

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
