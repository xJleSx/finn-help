import asyncio
import logging

import httpx

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
        async with self._lock:
            try:
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
            except httpx.TimeoutException:
                logger.warning("WolframAlpha timeout for: %s", input_text)
                return ""
            except httpx.HTTPStatusError as e:
                logger.warning("WolframAlpha HTTP %s for: %s", e.response.status_code, input_text)
                return ""
            except Exception as e:
                logger.warning("WolframAlpha error for '%s': %s", input_text, e)
                return ""
