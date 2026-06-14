import logging
from datetime import date

import httpx

logger = logging.getLogger(__name__)


class MacroCollector:
    async def fetch_all(self) -> list[dict]:
        results = []
        try:
            brent = await self._fetch_brent()
            if brent:
                results.append(brent)
        except Exception as e:
            logger.warning(f"Brent fetch failed: {e}")

        try:
            key_rate = await self._fetch_key_rate()
            if key_rate:
                results.append(key_rate)
        except Exception as e:
            logger.warning(f"Key rate fetch failed: {e}")

        usd_rate = await self._fetch_usd_rate()
        if usd_rate:
            results.append(usd_rate)

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
            resp = await client.get("https://www.cbr.ru/hd_base/KeyRate/XML", params={"date_req": date.today().strftime("%d.%m.%Y")})
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

    @staticmethod
    def latest_values(db) -> dict:
        from src.db.models import MacroIndicator
        today = date.today()
        result = {}
        for indicator_type in ("brent", "key_rate", "usd_rate"):
            row = (
                db.query(MacroIndicator)
                .filter(MacroIndicator.indicator_type == indicator_type, MacroIndicator.date <= today)
                .order_by(MacroIndicator.date.desc())
                .first()
            )
            if row:
                result[indicator_type] = row.value
        return result
