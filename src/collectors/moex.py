import logging
from datetime import date, timedelta
from typing import Optional

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


BOARD_MAP = {
    "stock": "/history/engines/stock/markets/shares/boards/TQBR/securities/{ticker}.json",
    "etf": "/history/engines/stock/markets/shares/boards/TQTF/securities/{ticker}.json",
    "bond": "/history/engines/stock/markets/bonds/boards/TQCB/securities/{ticker}.json",
    "shares": "/history/engines/stock/markets/shares/securities/{ticker}.json",
}

BOND_BOARDS = ["TQCB", "TQBD", "TQOB"]


class MOEXCollector:
    BASE = settings.moex_iss_url

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def _fetch_json(self, path: str, params: Optional[dict] = None) -> dict:
        url = f"{self.BASE}{path}"
        client = await self._get_client()
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_securities(self) -> list[dict]:
        data = await self._fetch_json("/securities.json", {"iss.meta": "off"})
        securities = data.get("securities", {})
        cols = securities.get("columns", [])
        rows = securities.get("data", [])
        return [dict(zip(cols, row)) for row in rows]

    async def get_stocks(self) -> list[dict]:
        data = await self._fetch_json(
            "/engines/stock/markets/shares/boards/TQBR/securities.json",
            {"iss.meta": "off"},
        )
        securities = data.get("securities", {})
        cols = securities.get("columns", [])
        rows = securities.get("data", [])
        return [dict(zip(cols, row)) for row in rows]

    async def get_etfs(self) -> list[dict]:
        data = await self._fetch_json(
            "/engines/stock/markets/shares/boards/TQTF/securities.json",
            {"iss.meta": "off"},
        )
        securities = data.get("securities", {})
        cols = securities.get("columns", [])
        rows = securities.get("data", [])
        return [dict(zip(cols, row)) for row in rows]

    async def get_history(
        self,
        ticker: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        board: str = "shares",
    ) -> list[dict]:
        if from_date is None:
            from_date = (date.today() - timedelta(days=365)).isoformat()
        if to_date is None:
            to_date = date.today().isoformat()

        if board == "bond":
            return await self._get_bond_history(ticker, from_date, to_date)

        path = BOARD_MAP.get(board)
        if not path:
            path = BOARD_MAP["shares"]

        data = await self._fetch_json(
            path.format(ticker=ticker),
            {"from": from_date, "till": to_date, "iss.meta": "off"},
        )
        history = data.get("history", {})
        cols = history.get("columns", [])
        rows = history.get("data", [])
        return [dict(zip(cols, row)) for row in rows]

    async def _get_bond_history(self, ticker: str, from_date: str, to_date: str) -> list[dict]:
        for board_id in BOND_BOARDS:
            path = f"/history/engines/stock/markets/bonds/boards/{board_id}/securities/{ticker}.json"
            try:
                data = await self._fetch_json(
                    path,
                    {"from": from_date, "till": to_date, "iss.meta": "off"},
                )
                history = data.get("history", {})
                rows = history.get("data", [])
                if rows:
                    cols = history.get("columns", [])
                    return [dict(zip(cols, row)) for row in rows]
            except Exception:
                continue
        return []

    async def get_dividends(self, ticker: str) -> list[dict]:
        data = await self._fetch_json(
            f"/securities/{ticker}/dividends.json",
            {"iss.meta": "off"},
        )
        dividends = data.get("dividends", {})
        cols = dividends.get("columns", [])
        rows = dividends.get("data", [])
        return [dict(zip(cols, row)) for row in rows]

    async def get_marketdata(self, ticker: str, itype: str = "stock") -> dict:
        if itype == "bond":
            for board_id in BOND_BOARDS:
                try:
                    data = await self._fetch_json(
                        f"/engines/stock/markets/bonds/boards/{board_id}/securities/{ticker}.json",
                        {"iss.meta": "off"},
                    )
                    marketdata = data.get("marketdata", {})
                    cols = marketdata.get("columns", [])
                    rows = marketdata.get("data", [])
                    if rows:
                        return dict(zip(cols, rows[0]))
                except Exception:
                    continue
            return {}
        data = await self._fetch_json(
            f"/engines/stock/markets/shares/securities/{ticker}.json",
            {"iss.meta": "off"},
        )
        marketdata = data.get("marketdata", {})
        cols = marketdata.get("columns", [])
        rows = marketdata.get("data", [])
        if rows:
            return dict(zip(cols, rows[0]))
        return {}

    async def get_bonds(self) -> list[dict]:
        seen = set()
        results = []
        for board_id in BOND_BOARDS:
            try:
                data = await self._fetch_json(
                    f"/engines/stock/markets/bonds/boards/{board_id}/securities.json",
                    {"iss.meta": "off"},
                )
                securities = data.get("securities", {})
                cols = securities.get("columns", [])
                rows = securities.get("data", [])
                for row in rows:
                    entry = dict(zip(cols, row))
                    secid = entry.get("SECID") or entry.get("secid")
                    if secid and secid not in seen:
                        seen.add(secid)
                        results.append(entry)
            except Exception:
                continue
        return results

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
