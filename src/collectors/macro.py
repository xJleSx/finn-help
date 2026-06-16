import logging
from datetime import date

import httpx

logger = logging.getLogger(__name__)

MACRO_TYPES = (
    "brent",
    "key_rate",
    "usd_rate",
    "imoex",
    "cpi",
    "ofz_10y",
    "m2",
)


class MacroCollector:
    async def fetch_all(self) -> list[dict]:
        results = []
        for method in (
            self._fetch_brent,
            self._fetch_key_rate,
            self._fetch_usd_rate,
            self._fetch_imoex,
            self._fetch_cpi,
            self._fetch_ofz_yield,
            self._fetch_m2,
        ):
            try:
                item = await method()
                if item:
                    results.append(item)
            except Exception as e:
                logger.warning(f"{method.__name__} failed: {e}")
        return results

    async def _fetch_brent(self) -> dict | None:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://iss.moex.com/iss/engines/market/pips/securities.json",
                params={"securities": "BRENT", "iss.only": "marketdata"},
            )
            resp.raise_for_status()
            data = resp.json()
            rows = (data.get("marketdata") or {}).get("data", [])
            cols = (data.get("marketdata") or {}).get("columns", [])
            if not rows or not cols:
                return None
            for row in rows:
                try:
                    idx = cols.index("LAST")
                    val = row[idx]
                    if val is not None:
                        return {
                            "date": date.today(),
                            "indicator_type": "brent",
                            "value": float(val),
                            "source": "MOEX",
                        }
                except (ValueError, IndexError, TypeError):
                    continue
        return None

    async def _fetch_key_rate(self) -> dict | None:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://www.cbr.ru/hd_base/KeyRate/XML",
                params={"date_req": date.today().strftime("%d.%m.%Y")},
            )
            resp.raise_for_status()
        import xml.etree.ElementTree as ET

        root = ET.fromstring(resp.content)
        for rate in root.findall(".//Rate"):
            try:
                val = rate.find("Value")
                if val is not None and val.text:
                    return {
                        "date": date.today(),
                        "indicator_type": "key_rate",
                        "value": float(val.text.replace(",", ".")),
                        "source": "CBR",
                    }
            except (AttributeError, ValueError):
                continue
        return None

    async def _fetch_usd_rate(self) -> dict | None:
        from src.collectors.cbr import CBRCollector

        cbr = CBRCollector()
        rates = await cbr.get_rates()
        usd = next((r for r in rates if r["code"] == "USD"), None)
        if usd:
            return {
                "date": date.today(),
                "indicator_type": "usd_rate",
                "value": usd["value"],
                "source": "CBR",
            }
        return None

    async def _fetch_imoex(self) -> dict | None:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://iss.moex.com/iss/engines/stock/markets/index/securities/IMOEX.json",
                params={"iss.only": "marketdata"},
            )
            resp.raise_for_status()
            data = resp.json()
            rows = (data.get("marketdata") or {}).get("data", [])
            cols = (data.get("marketdata") or {}).get("columns", [])
            if not rows or not cols:
                return None
            for row in rows:
                try:
                    idx = cols.index("LAST")
                    val = row[idx]
                    if val is not None:
                        return {
                            "date": date.today(),
                            "indicator_type": "imoex",
                            "value": float(val),
                            "source": "MOEX",
                        }
                except (ValueError, IndexError, TypeError):
                    continue
        return None

    async def _fetch_cpi(self) -> dict | None:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://www.cbr.ru/hd_base/infl/XML",
                params={"date_req": date.today().strftime("%d.%m.%Y")},
            )
            resp.raise_for_status()
        import xml.etree.ElementTree as ET

        root = ET.fromstring(resp.content)
        for item in root.findall(".//Infl"):
            try:
                val = item.find("Value")
                if val is not None and val.text:
                    return {
                        "date": date.today(),
                        "indicator_type": "cpi",
                        "value": float(val.text.replace(",", ".")),
                        "source": "CBR",
                    }
            except (AttributeError, ValueError):
                continue
        return None

    async def _fetch_ofz_yield(self) -> dict | None:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://www.cbr.ru/hd_base/zcyc_params/XML",
                params={"date_req": date.today().strftime("%d.%m.%Y")},
            )
            resp.raise_for_status()
        import xml.etree.ElementTree as ET

        root = ET.fromstring(resp.content)
        for item in root.findall(".//Param"):
            try:
                period = item.find("Period")
                val = item.find("Value")
                if period is not None and period.text and val is not None and val.text:
                    if "10" in period.text:
                        return {
                            "date": date.today(),
                            "indicator_type": "ofz_10y",
                            "value": float(val.text.replace(",", ".")),
                            "source": "CBR",
                        }
            except (AttributeError, ValueError):
                continue
        return None

    async def _fetch_m2(self) -> dict | None:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://www.cbr.ru/hd_base/mb/XML",
                params={"date_req": date.today().strftime("%d.%m.%Y")},
            )
            resp.raise_for_status()
        import xml.etree.ElementTree as ET

        root = ET.fromstring(resp.content)
        for item in root.findall(".//MB"):
            try:
                val = item.find("Value")
                if val is not None and val.text:
                    return {
                        "date": date.today(),
                        "indicator_type": "m2",
                        "value": float(val.text.replace(",", ".")),
                        "source": "CBR",
                    }
            except (AttributeError, ValueError):
                continue
        return None

    @staticmethod
    def latest_values(db) -> dict:
        from src.db.models import MacroIndicator

        today = date.today()
        result = {}
        for indicator_type in MACRO_TYPES:
            row = (
                db.query(MacroIndicator)
                .filter(MacroIndicator.indicator_type == indicator_type, MacroIndicator.date <= today)
                .order_by(MacroIndicator.date.desc())
                .first()
            )
            if row:
                result[indicator_type] = row.value
        return result

    @staticmethod
    async def latest_values_async(db) -> dict:
        from sqlalchemy import select

        from src.db.models import MacroIndicator

        today = date.today()
        result = {}
        for indicator_type in MACRO_TYPES:
            stmt = (
                select(MacroIndicator)
                .where(
                    MacroIndicator.indicator_type == indicator_type,
                    MacroIndicator.date <= today,
                )
                .order_by(MacroIndicator.date.desc())
                .limit(1)
            )
            row_result = await db.execute(stmt)
            row = row_result.scalar_one_or_none()
            if row:
                result[indicator_type] = row.value
        return result
