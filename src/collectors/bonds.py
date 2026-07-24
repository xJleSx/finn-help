import asyncio
import contextlib
import logging
from datetime import date
from typing import Any, Optional, Self

from src.collectors.base import BaseCollector
from src.collectors.moex import MOEXCollector

logger = logging.getLogger(__name__)

CONCURRENCY_LIMIT = 10


class BondOfferingCollector(BaseCollector):
    """Collects bond offering details from MOEX ISS."""

    def __init__(self) -> None:
        super().__init__()
        self._moex: Optional[MOEXCollector] = None
        self._semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

    async def _get_moex(self) -> MOEXCollector:
        if self._moex is None:
            self._moex = MOEXCollector()
            await self._moex.__aenter__()
        return self._moex

    async def fetch_all(self) -> list[dict[str, Any]]:
        moex = await self._get_moex()
        bonds_list = await moex.get_bonds()
        results: list[dict[str, Any]] = []

        async def _fetch_one(bond: dict[str, Any]) -> Optional[dict[str, Any]]:
            secid = bond.get("SECID") or bond.get("secid")
            if not secid:
                return None
            async with self._semaphore:
                try:
                    return await self._fetch_bond_info(moex, secid)
                except Exception as e:
                    logger.warning("Bond info fetch failed for %s: %s", secid, e)
                    return None

        tasks = [_fetch_one(b) for b in bonds_list]
        for coro in asyncio.as_completed(tasks):
            info = await coro
            if info:
                results.append(info)
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

        desc = await self._fetch_full_description(ticker)
        result.update(desc)

        marketdata = await moex.get_marketdata(ticker, itype="bond")
        if marketdata:
            ytm = marketdata.get("YIELD") or marketdata.get("yield")
            if ytm is not None:
                result["yield_to_maturity"] = float(ytm)
            last_price = marketdata.get("LAST") or marketdata.get("last")
            if last_price is not None:
                result["current_price_pct"] = float(last_price)
            duration = marketdata.get("DURATION")
            if duration is not None:
                with contextlib.suppress(ValueError, TypeError):
                    result["duration_years"] = float(duration)

        # Calculate YTM if not provided by MOEX
        if "yield_to_maturity" not in result and result.get("coupon_rate") and result.get("maturity_date") and result.get("current_price_pct"):
            try:
                from src.analysis.bonds_math import ytm_solver as _ytm_solver

                years_to_mat = (result["maturity_date"] - date.today()).days / 365.25 if result.get("maturity_date") else 0
                if years_to_mat > 0:
                    ytm_calc = _ytm_solver(
                        price_pct=result["current_price_pct"],
                        coupon_rate=result["coupon_rate"],
                        years_to_maturity=years_to_mat,
                        nominal=result.get("nominal_price") or 100,
                        frequency=2,
                    )
                    if ytm_calc is not None:
                        result["yield_to_maturity"] = ytm_calc
            except Exception as e:
                logger.debug("YTM solver failed for %s: %s", ticker, e)

        # Calculate duration if not provided by MOEX
        if "duration_years" not in result and result.get("maturity_date") and result.get("yield_to_maturity"):
            result["duration_years"] = _estimate_duration(
                maturity_date=result["maturity_date"],
                ytm=result.get("yield_to_maturity"),
            )

        # Fetch coupon schedule in parallel
        try:
            coupons = await moex.get_coupons(ticker)
            if coupons:
                result["coupon_schedule"] = coupons
                if not result.get("coupon_value") and coupons:
                    with contextlib.suppress(ValueError, TypeError):
                        result["coupon_value"] = float(coupons[0].get("value", 0))
        except Exception as e:
            logger.debug("Coupon schedule fetch failed for %s: %s", ticker, e)

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
                with contextlib.suppress(ValueError, TypeError):
                    result["coupon_rate"] = float(value) if value else None
            elif name == "COUPONVALUE":
                with contextlib.suppress(ValueError, TypeError):
                    result["coupon_value"] = float(value) if value else None
            elif name == "COUPONPERIOD":
                with contextlib.suppress(ValueError, TypeError):
                    result["coupon_period_days"] = int(value) if value else None
            elif name == "COUPONTYPE":
                result["coupon_type"] = value
            elif name == "CREDITRATING":
                result["credit_rating"] = value
            elif name == "ISSUESIZE":
                with contextlib.suppress(ValueError, TypeError):
                    result["volume"] = float(value) if value else None
            elif name == "FACEVALUE":
                with contextlib.suppress(ValueError, TypeError):
                    result["nominal_price"] = float(value) if value else None
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
                with contextlib.suppress(ValueError, TypeError):
                    result["list_level"] = int(value) if value else None
            elif name == "SHORTNAME":
                result["short_name"] = value
            elif name == "SECNAME":
                result["full_name"] = value
            elif name == "MINLOT":
                with contextlib.suppress(ValueError, TypeError):
                    result["min_lot_rub"] = float(value) if value else None
            elif name == "QUALIFIEDINVESTOR":
                qual_value = str(value).lower() if value else ""
                result["qual_investor_only"] = qual_value in ("yes", "1", "true", "да")
            elif name == "EMITTER_ID":
                with contextlib.suppress(ValueError, TypeError):
                    result["emitter_id"] = int(value) if value else None
            elif name == "NAME":
                result["company_name"] = self._parse_company_name(value or "")
        return result

    @staticmethod
    def _parse_company_name(bond_name: str) -> str:
        """Extract issuer company name from bond full name (e.g. 'ПР-Лизинг 003Р-02' -> 'ПР-Лизинг')."""
        import re
        name = bond_name.strip()
        # Remove series suffix like 001P, 003P-02, БО-01, etc.
        name = re.sub(r"\s+[0-9БBOРPС\-]+$", "", name)
        # Remove common bond-type suffixes
        name = re.sub(r"\s+(БО|облигация|биржевая|exchange|bond).*", "", name, flags=re.IGNORECASE)
        return name.strip() or bond_name.strip()

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


def _estimate_duration(maturity_date: date, ytm: Optional[float], amortizing_schedule: Optional[list[dict[str, Any]]] = None) -> Optional[float]:
    if not ytm or ytm <= 0:
        return None
    today = date.today()
    if maturity_date <= today:
        return 0.0
    # TODO: support amortizing bonds with varying notional
    if amortizing_schedule:
        # For amortizing bonds, compute weighted average duration across principal repayments
        total_weight = 0.0
        weighted = 0.0
        for payment in amortizing_schedule:
            pmt_date = payment.get("date")
            pmt_amount = payment.get("amount", 0)
            if pmt_date and pmt_amount:
                days = (pmt_date - today).days
                if days > 0:
                    years = days / 365.25
                    w = pmt_amount * years
                    total_weight += pmt_amount
                    weighted += w * (1 - 1 / (1 + ytm / 100) ** years) / (1 - 1 / (1 + ytm / 100)) if ytm != 0 else years
        return round(weighted / total_weight, 2) if total_weight > 0 else None
    years_to_maturity = (maturity_date - today).days / 365.25
    return round(years_to_maturity * (1 - 1 / (1 + ytm / 100) ** years_to_maturity) / (1 - 1 / (1 + ytm / 100)), 2)
