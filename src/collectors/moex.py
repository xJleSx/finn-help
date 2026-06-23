import asyncio
import logging
from datetime import date, timedelta
from typing import Optional

import httpx

from src.config import settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 2.0


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
        last_exc = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, dict):
                    raise ValueError(
                        f"MOEX API returned non-dict response for {path}: {type(data).__name__}"
                    )
                return data
            except (httpx.HTTPStatusError, httpx.RequestError, ValueError) as exc:
                last_exc = exc
                if attempt < MAX_RETRIES:
                    delay = RETRY_DELAY * (2 ** (attempt - 1))
                    logger.warning("MOEX API attempt %d/%d failed for %s: %s — retrying in %.1fs", attempt, MAX_RETRIES, path, exc, delay)
                    await asyncio.sleep(delay)
                else:
                    logger.error("MOEX API failed after %d attempts for %s: %s", MAX_RETRIES, path, exc)
        raise last_exc  # type: ignore[misc]

    @staticmethod
    def _parse_table(data: dict, table_name: str) -> list[dict]:
        table = data.get(table_name)
        if not isinstance(table, dict):
            logger.warning("MOEX API: table '%s' not found or not a dict in response", table_name)
            return []
        cols = table.get("columns")
        rows = table.get("data")
        if not isinstance(cols, list) or not isinstance(rows, list):
            logger.warning("MOEX API: table '%s' missing columns or data", table_name)
            return []

        return [dict(zip(cols, row)) for row in rows]

    async def get_securities(self) -> list[dict]:
        data = await self._fetch_json("/securities.json", {"iss.meta": "off"})
        return self._parse_table(data, "securities")

    async def get_stocks(self) -> list[dict]:
        data = await self._fetch_json(
            "/engines/stock/markets/shares/boards/TQBR/securities.json",
            {"iss.meta": "off"},
        )
        return self._parse_table(data, "securities")

    async def get_etfs(self) -> list[dict]:
        data = await self._fetch_json(
            "/engines/stock/markets/shares/boards/TQTF/securities.json",
            {"iss.meta": "off"},
        )
        return self._parse_table(data, "securities")

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
        return self._parse_table(data, "history")

    async def _get_bond_history(self, ticker: str, from_date: str, to_date: str) -> list[dict]:
        for board_id in BOND_BOARDS:
            path = f"/history/engines/stock/markets/bonds/boards/{board_id}/securities/{ticker}.json"
            try:
                data = await self._fetch_json(
                    path,
                    {"from": from_date, "till": to_date, "iss.meta": "off"},
                )
                rows = self._parse_table(data, "history")
                if rows:
                    return rows
            except Exception as e:
                logger.debug("Bond history not found on %s for %s: %s", board_id, ticker, e)
                continue
        return []

    async def get_dividends(self, ticker: str) -> list[dict]:
        data = await self._fetch_json(
            f"/securities/{ticker}/dividends.json",
            {"iss.meta": "off"},
        )
        return self._parse_table(data, "dividends")

    async def get_marketdata(self, ticker: str, itype: str = "stock") -> dict:
        if itype == "bond":
            for board_id in BOND_BOARDS:
                try:
                    data = await self._fetch_json(
                        f"/engines/stock/markets/bonds/boards/{board_id}/securities/{ticker}.json",
                        {"iss.meta": "off"},
                    )
                    rows = self._parse_table(data, "marketdata")
                    if rows:
                        return rows[0]
                except Exception as e:
                    logger.debug("Marketdata not found on %s for %s: %s", board_id, ticker, e)
                    continue
            return {}
        data = await self._fetch_json(
            f"/engines/stock/markets/shares/securities/{ticker}.json",
            {"iss.meta": "off"},
        )
        rows = self._parse_table(data, "marketdata")
        return rows[0] if rows else {}

    async def get_bonds(self) -> list[dict]:
        seen = set()
        results = []
        for board_id in BOND_BOARDS:
            try:
                data = await self._fetch_json(
                    f"/engines/stock/markets/bonds/boards/{board_id}/securities.json",
                    {"iss.meta": "off"},
                )
                for entry in self._parse_table(data, "securities"):
                    secid = entry.get("SECID") or entry.get("secid")
                    if secid and secid not in seen:
                        seen.add(secid)
                        results.append(entry)
            except Exception as e:
                logger.debug("Bonds board %s failed: %s", board_id, e)
                continue
        return results

    async def get_security_info(self, ticker: str) -> dict:
        """Get basic security info: shares outstanding, sector, ISIN, face value."""
        data = await self._fetch_json(
            f"/securities/{ticker}.json",
            {"iss.meta": "off"},
        )
        desc = self._parse_table(data, "description")
        info = {}
        for row in desc:
            name = row.get("name", "")
            value = row.get("value")
            if name == "ISSUESIZE":
                info["shares_outstanding"] = int(value) if value else None
            elif name == "FACEVALUE":
                info["face_value"] = float(value) if value else None
            elif name == "ISIN":
                info["isin"] = value
            elif name == "SECTORID":
                info["sector_id"] = value
            elif name == "LISTLEVEL":
                info["list_level"] = int(value) if value else None
            elif name == "SECID":
                info["secid"] = value
            elif name == "SHORTNAME":
                info["shortname"] = value
            elif name == "ISSUEDATE":
                info["issue_date"] = value
        return info

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
