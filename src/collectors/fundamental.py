import logging
from decimal import Decimal
from typing import Any, Optional, Self

from src.collectors.moex import MOEXCollector

logger = logging.getLogger(__name__)


class FundamentalDataCollector:
    """Сбор фундаментальных данных о компаниях.

    Текущий источник: MOEX ISS (shares outstanding, market cap via price × shares).
    P/E, P/B, ROE, EPS, Debt/Equity требуют внешнего источника (SmartLab, Cbonds и т.п.)
    и пока возвращаются как None.
    """

    def __init__(self) -> None:
        self._moex: Optional[MOEXCollector] = None

    async def _get_moex(self) -> MOEXCollector:
        if self._moex is None:
            self._moex = MOEXCollector()
            await self._moex.__aenter__()
        return self._moex

    async def fetch(self, ticker: str, last_price: Optional[float] = None) -> dict[str, Any]:
        moex = await self._get_moex()
        info = await moex.get_security_info(ticker)

        shares = info.get("shares_outstanding")
        market_cap: Optional[float] = None
        if shares is not None and last_price is not None and last_price > 0:
            face_value = info.get("face_value") or 1
            market_cap = float((Decimal(str(last_price)) / Decimal(str(face_value))) * Decimal(str(shares)))

        return {
            "market_cap": market_cap,
            "shares_outstanding": shares,
            "pe_ratio": None,
            "pb_ratio": None,
            "roe": None,
            "eps": None,
            "debt_equity": None,
            "book_value": None,
            "revenue": None,
            "net_income": None,
            "extra": {
                "face_value": info.get("face_value"),
                "issue_date": info.get("issue_date"),
                "list_level": info.get("list_level"),
                "secid": info.get("secid"),
                "shortname": info.get("shortname"),
            },
        }

    async def close(self) -> None:
        if self._moex:
            await self._moex.__aexit__(None, None, None)
            self._moex = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
