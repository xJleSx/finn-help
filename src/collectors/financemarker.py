"""FinanceMarker collector — company profiles, ratios, dividends, events, analyst ideas, insider trades.

Wraps the FinanceMarker API (https://financemarker.ru/api/fm/v2) behind
the BaseCollector interface with retry + circuit breaker.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from src.collectors.base import BaseCollector
from src.config import settings

logger = logging.getLogger(__name__)


class FinanceMarkerCollector(BaseCollector):
    BASE_URL = "https://financemarker.ru/api/fm/v2"

    def __init__(self) -> None:
        super().__init__()
        self._api_token = settings.fm_api_token

    async def _request(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        url = f"{self.BASE_URL}{path}"
        headers = {"Authorization": f"Bearer {self._api_token}"}

        async def _do_fetch() -> Any:
            client = await self._get_client()
            resp = await client.get(url, params=params or {}, headers=headers)
            resp.raise_for_status()
            return resp.json()

        return await self._with_retry(_do_fetch, (httpx.HTTPStatusError, httpx.RequestError, ValueError))

    async def get_company_overview(self, exchange: str, code: str) -> dict[str, Any]:
        """Company profile + ratios + summary for a single ticker.

        Uses ``?include=ratios,summary`` to pull the full info block.
        """
        data = await self._request(f"/stocks/{exchange}:{code}", params={"include": "ratios,summary"})
        return data if isinstance(data, dict) else {}

    async def get_ratios(self, exchange: str, code: str) -> dict[str, Any]:
        """P/E, EV/EBITDA, ROE, EPS, book value, revenue, net income, etc.

        Extracts ``summary`` and ``ratios`` from the company detail payload.
        Keys match the gap in ``FundamentalDataCollector.fetch()``.
        """
        overview = await self.get_company_overview(exchange, code)
        summary = overview.get("summary") or {}
        ratios = overview.get("ratios") or {}
        return {
            "pe": summary.get("pe"),
            "pb": ratios.get("pb"),
            "roe": summary.get("roe"),
            "ev_ebitda": ratios.get("ev_ebitda"),
            "eps": ratios.get("eps"),
            "debt_equity": ratios.get("debt_equity"),
            "book_value": ratios.get("book_value"),
            "revenue": ratios.get("revenue"),
            "net_income": ratios.get("net_income"),
            "market_cap": summary.get("capital"),
            "dividend_yield_12m": summary.get("dividend_yield_12m"),
            "graham_target": summary.get("graham_target"),
        }

    async def get_dividends(self, mode: str = "upcoming", **kwargs: Any) -> list[dict[str, Any]]:
        """Dividend calendar — upcoming or past.

        Accepts pagination keywords (limit, offset, sort_by, sort_order).
        """
        params: dict[str, Any] = {"mode": mode}
        params.update(kwargs)
        data = await self._request("/dividends", params=params)
        if isinstance(data, list):
            return data
        return data.get("items") or data.get("data") or []

    async def get_corporate_events(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Corporate events calendar.

        Accepts pagination keywords (limit, offset, sort_by, sort_order).
        """
        data = await self._request("/calendar", params=kwargs or None)
        if isinstance(data, list):
            return data
        return data.get("items") or data.get("data") or []

    async def get_analyst_ideas(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Analyst consensus / ideas list.

        Accepts pagination keywords (limit, offset, sort_by, sort_order,
        updated_in_days).
        """
        data = await self._request("/ideas", params=kwargs or None)
        if isinstance(data, list):
            return data
        return data.get("items") or data.get("data") or []

    async def get_insider_transactions(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Insider trades.

        Accepts pagination keywords (limit, offset, sort_by, sort_order,
        updated_in_days).
        """
        data = await self._request("/insider_transactions", params=kwargs or None)
        if isinstance(data, list):
            return data
        return data.get("items") or data.get("data") or []
