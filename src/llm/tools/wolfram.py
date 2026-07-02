import asyncio
import logging
from typing import Any

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
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    get_circuit_breaker,
)

logger = logging.getLogger(__name__)

WOLFRAM_LLM_URL = "https://www.wolframalpha.com/api/v1/llm-api"

FINANCIAL_QUERIES: dict[str, list[str]] = {
    "pe": ["P/E ratio {ticker}", "PE ratio {ticker}", "price to earnings {ticker}"],
    "market_cap": ["market capitalization {ticker}", "market cap {ticker}"],
    "revenue": ["revenue {ticker}", "{ticker} revenue 2024"],
    "eps": ["EPS {ticker}", "earnings per share {ticker}"],
    "dividend": ["dividend yield {ticker}", "{ticker} dividend"],
    "sector": ["{ticker} industry sector"],
    "high_low": ["{ticker} 52 week high low"],
    "beta": ["beta {ticker}", "{ticker} beta"],
}


class WolframAlphaClient:
    def __init__(self, app_id: str, rate_limiter: asyncio.Lock | None = None) -> None:
        self._app_id = app_id
        self._lock = rate_limiter or asyncio.Lock()
        self._circuit_breaker: CircuitBreaker = get_circuit_breaker("wolfram")

    async def enrich_signal(self, ticker: str, queries: list[str]) -> dict[str, str]:
        results: dict[str, str] = {}
        for query in queries:
            text = await self._query(query)
            if text:
                results[query] = text
        return results

    async def enrich_stock(self, ticker: str) -> dict[str, str]:
        queries = [q.format(ticker=ticker) for q in self._build_queries(ticker)]
        return await self.enrich_signal(ticker, queries)

    def _build_queries(self, ticker: str) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for key in ("pe", "market_cap", "revenue", "dividend", "sector", "beta", "eps", "high_low"):
            for tmpl in FINANCIAL_QUERIES[key]:
                q = tmpl.format(ticker=ticker)
                if q not in seen:
                    seen.add(q)
                    out.append(q)
                    break
        return out

    async def _query(self, input_text: str) -> str:
        if not self._app_id:
            return ""

        async def _do_query() -> str:
            async with self._lock:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(
                        WOLFRAM_LLM_URL,
                        params={"input": input_text, "appid": self._app_id, "maxchars": 500},
                    )
                    if resp.status_code == 501:
                        logger.debug("WolframAlpha 501 for: %s", input_text)
                        return ""
                    resp.raise_for_status()
                    text = resp.text.strip()
                    if text and not text.startswith("Wolfram|Alpha did not understand"):
                        return text
                    return ""

        try:
            return await self._circuit_breaker.call(_do_query)
        except CircuitBreakerOpenError:
            logger.warning("wolfram.circuit_breaker.open, skipping query: %s", input_text)
            return ""
        except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError):
            logger.warning("WolframAlpha failed for: %s", input_text, exc_info=True)
            return ""
