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
                "https://iss.moex.com/iss/engines/futures/markets/forts/boards/RFUD/securities.json",
                params={
                    "securities.columns": "SECID,LASTTRADEDATE,PREVOPENPOSITION,ASSETCODE",
                    "iss.only": "securities",
                    "limit": "100",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            rows = (data.get("securities") or {}).get("data", [])
            cols = (data.get("securities") or {}).get("columns", [])

            contracts = []
            for row in rows:
                try:
                    asset_idx = cols.index("ASSETCODE")
                    secid_idx = cols.index("SECID")
                    ltd_idx = cols.index("LASTTRADEDATE")
                    oi_idx = cols.index("PREVOPENPOSITION")
                    if row[asset_idx] == "BR":
                        contracts.append({
                            "secid": row[secid_idx],
                            "last_trade": date.fromisoformat(row[ltd_idx]) if row[ltd_idx] else None,
                            "oi": int(row[oi_idx]) if row[oi_idx] else 0,
                        })
                except (ValueError, IndexError, TypeError):
                    continue

            if not contracts:
                return None

            today = date.today()
            active = [c for c in contracts if c["last_trade"] and c["last_trade"] >= today]
            if not active:
                active = contracts
            front = max(active, key=lambda c: c["oi"])

            resp2 = await client.get(
                f"https://iss.moex.com/iss/engines/futures/markets/forts/boards/RFUD/securities/{front['secid']}.json",
                params={
                    "iss.only": "marketdata",
                    "marketdata.columns": "SECID,LAST",
                },
            )
            resp2.raise_for_status()
            data2 = resp2.json()
            md_rows = (data2.get("marketdata") or {}).get("data", [])
            md_cols = (data2.get("marketdata") or {}).get("columns", [])

            for row in md_rows:
                try:
                    last_idx = md_cols.index("LAST")
                    val = row[last_idx]
                    if val is not None:
                        return {
                            "date": today,
                            "indicator_type": "brent",
                            "value": float(val),
                            "source": f"MOEX/{front['secid']}",
                        }
                except (ValueError, IndexError, TypeError):
                    continue
        return None

    async def _fetch_key_rate(self) -> dict | None:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://www.cbr.ru/hd_base/KeyRate",
                params={"UniDbQuery.Formatted": "True", "UniDbQuery.Date": date.today().strftime("%d.%m.%Y")},
            )
            resp.raise_for_status()
        from lxml import html

        tree = html.fromstring(resp.text)
        rows = tree.xpath("//table[@class='data']//tr")
        for row in rows[1:]:
            cells = row.xpath(".//td")
            if len(cells) >= 2:
                val = cells[1].text_content().strip().replace(",", ".")
                try:
                    return {
                        "date": date.today(),
                        "indicator_type": "key_rate",
                        "value": float(val),
                        "source": "CBR",
                    }
                except ValueError:
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
                "https://www.cbr.ru/hd_base/infl",
                params={"UniDbQuery.Formatted": "True", "UniDbQuery.Date": date.today().strftime("%d.%m.%Y")},
            )
            resp.raise_for_status()
        from lxml import html

        tree = html.fromstring(resp.text)
        rows = tree.xpath("//table[@class='data']//tr")
        for row in rows[1:]:
            cells = row.xpath(".//td")
            if len(cells) >= 2:
                val = cells[1].text_content().strip().replace(",", ".")
                try:
                    return {
                        "date": date.today(),
                        "indicator_type": "cpi",
                        "value": float(val),
                        "source": "CBR",
                    }
                except ValueError:
                    continue
        return None

    async def _fetch_ofz_yield(self) -> dict | None:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get("https://www.cbr.ru/hd_base/zcyc_params")
            resp.raise_for_status()
        from lxml import html

        tree = html.fromstring(resp.text)
        rows = tree.xpath("//table[contains(@class, 'data')]//tr")
        for row in rows[1:]:
            cells = row.xpath(".//td")
            if len(cells) >= 13:
                yield_10y = cells[9].text_content().strip().replace(",", ".")
                try:
                    return {
                        "date": date.today(),
                        "indicator_type": "ofz_10y",
                        "value": float(yield_10y),
                        "source": "CBR",
                    }
                except ValueError:
                    continue
        return None

    async def _fetch_m2(self) -> dict | None:
        logger.warning("M2 data source (CBR XML API) no longer available — skipped")
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
