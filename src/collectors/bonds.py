import logging
from datetime import date
from typing import Any, Optional, Self

from src.collectors.moex import MOEXCollector

logger = logging.getLogger(__name__)


class BondOfferingCollector:
    """Collects bond offering details from MOEX ISS."""

    def __init__(self) -> None:
        self._moex: Optional[MOEXCollector] = None

    async def _get_moex(self) -> MOEXCollector:
        if self._moex is None:
            self._moex = MOEXCollector()
            await self._moex.__aenter__()
        return self._moex

    async def fetch_all(self) -> list[dict[str, Any]]:
        moex = await self._get_moex()
        bonds_list = await moex.get_bonds()
        results: list[dict[str, Any]] = []
        for bond in bonds_list:
            secid = bond.get("SECID") or bond.get("secid")
            if not secid:
                continue
            try:
                info = await self._fetch_bond_info(moex, secid)
                if info:
                    results.append(info)
            except Exception as e:
                logger.warning("Bond info fetch failed for %s: %s", secid, e)
        return results

    async def fetch_by_ticker(self, ticker: str) -> dict[str, Any]:
        moex = await self._get_moex()
        return await self._fetch_bond_info(moex, ticker)

    async def _fetch_bond_info(self, moex: MOEXCollector, ticker: str) -> dict[str, Any]:
        info = await moex.get_security_info(ticker)
        if not info.get("isin"):
            return {}

        result: dict[str, Any] = {
            "ticker": ticker,
            "isin": info.get("isin"),
            "nominal_price": info.get("face_value"),
            "offering_date": _parse_date(info.get("issue_date")),
            "has_amortization": False,
            "has_offer": False,
        }

        # extended description has more fields — refetch to get all name-value pairs
        desc = await self._fetch_full_description(ticker)
        result.update(desc)

        # current market data
        marketdata = await moex.get_marketdata(ticker, itype="bond")
        if marketdata:
            ytm = marketdata.get("YIELD") or marketdata.get("yield")
            if ytm is not None:
                result["yield_to_maturity"] = float(ytm)
            last_price = marketdata.get("LAST") or marketdata.get("last")
            if last_price is not None:
                result["current_price_pct"] = float(last_price)

        return result

    async def _fetch_full_description(self, ticker: str) -> dict[str, Any]:
        moex = await self._get_moex()
        desc = await moex.get_security_description(ticker)
        result: dict[str, Any] = {}
        for row in desc:
            name = row.get("name", "")
            value = row.get("value")
            if name == "MATURITYDATE":
                result["maturity_date"] = _parse_date(value)
            elif name == "COUPONPERCENT":
                try:
                    result["coupon_rate"] = float(value) if value else None
                except (ValueError, TypeError):
                    pass
            elif name == "COUPONVALUE":
                try:
                    result["coupon_value"] = float(value) if value else None
                except (ValueError, TypeError):
                    pass
            elif name == "COUPONPERIOD":
                try:
                    result["coupon_period_days"] = int(value) if value else None
                except (ValueError, TypeError):
                    pass
            elif name == "COUPONTYPE":
                result["coupon_type"] = value
            elif name == "CREDITRATING":
                result["credit_rating"] = value
            elif name == "ISSUESIZE":
                try:
                    result["volume"] = float(value) if value else None
                except (ValueError, TypeError):
                    pass
            elif name == "FACEVALUE":
                try:
                    result["nominal_price"] = float(value) if value else None
                except (ValueError, TypeError):
                    pass
            elif name == "ISSUEDATE":
                result["offering_date"] = _parse_date(value)
            elif name == "AMORTIZATION":
                amort_value = str(value).lower() if value else ""
                result["has_amortization"] = amort_value in ("yes", "1", "true", "да")
            elif name == "OFFERDATE":
                result["has_offer"] = value is not None and str(value).strip() != ""
                if value:
                    result["offer_date"] = _parse_date(value)
            elif name == "LISTLEVEL":
                try:
                    result["list_level"] = int(value) if value else None
                except (ValueError, TypeError):
                    pass
            elif name == "SHORTNAME":
                result["short_name"] = value
            elif name == "SECNAME":
                result["full_name"] = value
        return result

    async def close(self) -> None:
        if self._moex:
            await self._moex.__aexit__(None, None, None)
            self._moex = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()


def _parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except (ValueError, TypeError):
            pass
    return None
