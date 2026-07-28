import logging
from datetime import date, timedelta
from typing import Any, Optional

import numpy as np
import pandas as pd

from src.collectors.base import BaseCollector
from src.config import settings
from src.constants import DEFAULT_HISTORY_DAYS

try:
    from tests.data.moex_mock_data import _MOCK_BOND_HISTORY, _MOCK_BONDS, _MOCK_COUPONS, _MOCK_SECURITIES
except ImportError:
    _MOCK_BONDS = []
    _MOCK_BOND_HISTORY = {}
    _MOCK_COUPONS = {}
    _MOCK_SECURITIES = {}

logger = logging.getLogger(__name__)

MOCK_DATA_ENABLED = settings.use_mock_data

BOARD_MAP = {
    "stock": "/history/engines/stock/markets/shares/boards/TQBR/securities/{ticker}.json",
    "etf": "/history/engines/stock/markets/shares/boards/TQTF/securities/{ticker}.json",
    "etf_tqtd": "/history/engines/stock/markets/shares/boards/TQTD/securities/{ticker}.json",
    "bond": "/history/engines/stock/markets/bonds/boards/TQCB/securities/{ticker}.json",
    "shares": "/history/engines/stock/markets/shares/securities/{ticker}.json",
}

BOND_BOARDS = ["TQCB", "TQBD", "TQOB"]

ETF_SPLITS: dict[str, list[dict[str, Any]]] = {
    "TMON": [
        {"date": "2024-03-15", "ratio": 2.0},
    ],
    "LQDT": [
        {"date": "2024-06-20", "ratio": 2.0},
    ],
}


def adjust_for_splits(
    ticker: str,
    prices: list[dict[str, Any]],
    date_col: str = "date",
    price_cols: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    splits = ETF_SPLITS.get(ticker.upper())
    if not splits or not prices:
        return prices
    if price_cols is None:
        price_cols = ["close", "open", "high", "low"]
    sorted_splits = sorted(splits, key=lambda s: s["date"])
    adjusted = []
    for row in prices:
        row_date = row.get(date_col, "")
        cumulative_ratio = 1.0
        for sp in sorted_splits:
            if row_date < sp["date"]:
                cumulative_ratio *= sp["ratio"]
        if cumulative_ratio != 1.0:
            row = dict(row)
            for col in price_cols:
                if col in row and row[col] is not None:
                    row[col] = round(row[col] / cumulative_ratio, 4)
            if "volume" in row and row["volume"] is not None:
                row["volume"] = int(row["volume"] * cumulative_ratio)
        adjusted.append(row)
    return adjusted


class MOEXCollector(BaseCollector):
    BASE = settings.moex_iss_url

    async def _fetch_json(self, path: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        if MOCK_DATA_ENABLED:
            result = self._mock_fetch(path, params)
            if result is not None:
                return result
        return await super()._fetch_json(f"{self.BASE}{path}", params)

    @staticmethod
    def _mock_fetch(path: str, params: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
        logger.info("MOEX mock: %s", path)
        if "/securities.json" in path and "coupons" not in path:
            return _MOCK_SECURITIES
        if "/coupons.json" in path:
            return _MOCK_COUPONS
        if "/history/" in path:
            return _MOCK_BOND_HISTORY
        return None

    @staticmethod
    def _parse_table(data: dict[str, Any], table_name: str) -> list[dict[str, Any]]:
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

    async def get_securities(self) -> list[dict[str, Any]]:
        return await self._paginate("/securities.json", table_name="securities")

    async def get_stocks(self) -> list[dict[str, Any]]:
        return await self._paginate(
            "/engines/stock/markets/shares/boards/TQBR/securities.json",
            table_name="securities",
        )

    async def get_etfs(self) -> list[dict[str, Any]]:
        return await self._paginate(
            "/engines/stock/markets/shares/boards/TQTF/securities.json",
            table_name="securities",
        )

    async def get_history(
        self,
        ticker: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        board: str = "shares",
    ) -> list[dict[str, Any]]:
        if from_date is None:
            from_date = (date.today() - timedelta(days=DEFAULT_HISTORY_DAYS)).isoformat()
        if to_date is None:
            to_date = date.today().isoformat()

        if board == "bond":
            rows, _ = await self._get_bond_history(ticker, from_date, to_date)
            return rows

        path = BOARD_MAP.get(board)
        if not path:
            path = BOARD_MAP["shares"]

        return await self._paginate(
            path.format(ticker=ticker),
            params={"from": from_date, "till": to_date},
            table_name="history",
        )

    async def _get_bond_history(self, ticker: str, from_date: str, to_date: str) -> tuple[list[dict[str, Any]], str | None]:
        for board_id in BOND_BOARDS:
            path = f"/history/engines/stock/markets/bonds/boards/{board_id}/securities/{ticker}.json"
            try:
                rows = await self._paginate(
                    path,
                    params={"from": from_date, "till": to_date},
                    table_name="history",
                )
                if rows:
                    return rows, board_id
            except Exception as e:
                logger.debug("Bond history not found on %s for %s: %s", board_id, ticker, e)
                continue
        return [], None

    async def get_dividends(self, ticker: str) -> list[dict[str, Any]]:
        return await self._paginate(
            f"/securities/{ticker}/dividends.json",
            table_name="dividends",
        )

    async def get_marketdata(self, ticker: str, itype: str = "stock") -> dict[str, Any]:
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

    def get_bond_history_with_board(
        self,
        ticker: str,
        from_date: str,
        to_date: str,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Like get_history but also returns the MOEX board ID (TQCB/TQBD/TQOB)."""
        return self._get_bond_history(ticker, from_date, to_date)

    async def get_bonds(self, columns: Optional[list[str]] = None) -> list[dict[str, Any]]:
        seen = set()
        results = []
        params: dict[str, str] = {}
        if columns:
            params["securities.columns"] = ",".join(columns)
        for board_id in BOND_BOARDS:
            try:
                board_rows = await self._paginate(
                    f"/engines/stock/markets/bonds/boards/{board_id}/securities.json",
                    params=params or None,
                    table_name="securities",
                )
                for entry in board_rows:
                    secid = entry.get("SECID") or entry.get("secid")
                    if secid and secid not in seen:
                        seen.add(secid)
                        results.append(entry)
            except Exception as e:
                logger.debug("Bonds board %s failed: %s", board_id, e)
                continue
        return results

    async def get_security_info(self, ticker: str) -> dict[str, Any]:
        """Get basic security info: shares outstanding, sector, ISIN, face value."""
        data = await self._fetch_json(
            f"/securities/{ticker}.json",
            {"iss.meta": "off"},
        )
        desc = self._parse_table(data, "description")
        info: dict[str, Any] = {}
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

    async def get_coupons(self, ticker: str) -> list[dict[str, Any]]:
        """Get coupon schedule via MOEX ISS bondization endpoint."""
        data = await self._fetch_json(
            f"/statistics/engines/stock/markets/bonds/bondization/{ticker}.json",
            {"iss.meta": "off", "iss.only": "coupons", "start": 0, "limit": 100},
        )
        rows = self._parse_table(data, "coupons")
        for i, row in enumerate(rows, 1):
            if "couponnumber" not in row or row["couponnumber"] is None:
                row["couponnumber"] = i
            if "value" not in row and "value_rub" in row:
                row["value"] = row["value_rub"]
        return rows

    async def get_aggregates(self, ticker: str) -> list[dict[str, Any]]:
        """Get aggregated bond data (face value, accrued interest, etc.)."""
        data = await self._fetch_json(
            f"/securities/{ticker}/aggregates.json",
            {"iss.meta": "off"},
        )
        return self._parse_table(data, "aggregates")

    async def get_security_description(self, ticker: str) -> list[dict[str, Any]]:
        """Get full security description as name-value pairs."""
        data = await self._fetch_json(
            f"/securities/{ticker}.json",
            {"iss.meta": "off"},
        )
        return self._parse_table(data, "description")

    async def get_orderbook(self, ticker: str) -> Optional[dict[str, Any]]:
        """Get order book (BID, ASK, BIDDEPTH, ASKDEPTH) from MOEX."""
        for board_id in BOND_BOARDS:
            try:
                data = await self._fetch_json(
                    f"/engines/stock/markets/bonds/boards/{board_id}/securities/{ticker}/orderbook.json",
                    {"iss.meta": "off"},
                )
                rows = self._parse_table(data, "orderbook")
                if rows:
                    return rows[0]
            except Exception as e:
                logger.debug("Orderbook not found on %s for %s: %s", board_id, ticker, e)
                continue
        return None

    async def get_candles(
        self,
        ticker: str,
        interval: int = 24,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """Get candle data for liquidity analysis (Amihud ratio)."""
        for board_id in BOND_BOARDS:
            try:
                data = await self._fetch_json(
                    f"/engines/stock/markets/bonds/boards/{board_id}/securities/{ticker}/candles.json",
                    {"iss.meta": "off", "interval": str(interval), "iss.only": "candles", "start": 0, "limit": str(limit)},
                )
                rows = self._parse_table(data, "candles")
                if rows:
                    return rows
            except Exception as e:
                logger.debug("Candles not found on %s for %s: %s", board_id, ticker, e)
                continue
        return []


def fill_price_gaps(
    df: pd.DataFrame,
    date_col: str = "date",
    price_col: str = "close",
    max_gap_days: int = 5,
) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.sort_values(date_col).reset_index(drop=True)
    dates = pd.to_datetime(df[date_col])
    full_range = pd.date_range(start=dates.min(), end=dates.max(), freq="B")
    df = df.set_index(date_col)
    df.index = pd.to_datetime(df.index)
    df = df.reindex(full_range)
    gap_mask = df[price_col].isna()
    fill_count = gap_mask.astype(int).groupby((~gap_mask).cumsum()).cumsum()
    for col in df.columns:
        if col in (price_col, "open", "high", "low"):
            df[col] = df[col].ffill(limit=max_gap_days)
        elif col == "volume":
            df[col] = df[col].fillna(0)
    df.loc[fill_count > max_gap_days, [c for c in df.columns if c != "volume"]] = np.nan
    df.index.name = date_col
    return df.reset_index()
