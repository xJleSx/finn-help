"""Company profile and corporate events collectors.

Sources:
  - SmartLab for company descriptions
  - MOEX ISS for corporate events (dividends, buybacks, splits)
"""

import asyncio
import logging
import re
from datetime import datetime
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup

from src.collectors.base import BaseCollector
from src.config import settings
from src.db.models import Instrument

logger = logging.getLogger(__name__)

SMARTLAB_BASE = "https://smart-lab.ru/q"


class SmartLabProfileCollector(BaseCollector):
    """Fetches company profile info from smart-lab.ru."""

    def __init__(self) -> None:
        super().__init__()

    async def _fetch_profile_async(self, ticker: str) -> dict[str, Any]:
        url = f"{SMARTLAB_BASE}/{ticker}/"
        profile: dict[str, Any] = {}
        try:
            html = await self._fetch_text(url, headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(html, "html.parser")
            desc_section = soup.find("h2", string=re.compile(r"О компании|Описание", re.IGNORECASE))
            if desc_section:
                desc_p = desc_section.find_next("p")
                if desc_p:
                    profile["description"] = desc_p.get_text(strip=True)
            info_table = soup.find("table", class_="simple")
            if info_table:
                for row in info_table.find_all("tr"):
                    cols = row.find_all("td")
                    if len(cols) < 2:
                        continue
                    label = cols[0].get_text(strip=True).lower()
                    value = cols[1].get_text(strip=True)
                    if "сайт" in label or "website" in label:
                        profile["website"] = value
                    elif "сотрудник" in label or "employees" in label:
                        profile["employees"] = self._parse_int(value)
                    elif "основан" in label or "founded" in label or "год" in label:
                        profile["founded_year"] = self._parse_int(value)
                    elif "отрасль" in label or "industry" in label:
                        profile["industry"] = value
                    elif "регистратор" in label:
                        profile["registrar"] = value
                    elif "аудитор" in label:
                        profile["auditor"] = value
                    elif "огрн" in label:
                        profile["state_reg_number"] = value
                    elif "инн" in label:
                        profile["tax_id"] = value
        except httpx.HTTPError as e:
            logger.warning("SmartLab profile fetch failed for %s: %s", ticker, e)
        except Exception as e:
            logger.error("Unexpected error fetching profile for %s: %s", ticker, e)
        return profile

    def fetch_profile(self, ticker: str) -> dict[str, Any]:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self._fetch_profile_async(ticker))
        finally:
            loop.close()

    @staticmethod
    def _parse_int(value: str) -> Optional[int]:
        cleaned = re.sub(r"[^\d]", "", value)
        try:
            return int(cleaned) if cleaned else None
        except ValueError:
            return None


class MOEXCorporateEventCollector(BaseCollector):
    """Fetches corporate events from MOEX ISS API."""

    BASE = settings.moex_iss_url

    def __init__(self) -> None:
        super().__init__()

    async def fetch_corporate_events(self, ticker: str) -> list[dict[str, Any]]:
        """Fetch corporate events for a ticker with pagination.

        MOEX endpoint: /securities/{ticker}/events.json
        """
        try:
            rows = await self._paginate(
                f"{self.BASE}/securities/{ticker}/events.json",
                table_name="events",
            )

            result = []
            for row in rows:
                if row.get("isin") or row.get("id"):
                    result.append(self._normalize_event(row))
            return result

        except httpx.HTTPError as e:
            logger.debug("MOEX events fetch failed for %s: %s", ticker, e)
            return []
        except Exception as e:
            logger.error("Unexpected error fetching events for %s: %s", ticker, e)
            return []

    @staticmethod
    def _normalize_event(raw: dict[str, Any]) -> dict[str, Any]:
        event: dict[str, Any] = {}
        event_type_raw = (raw.get("event_type") or raw.get("name", "")).lower()

        if any(kw in event_type_raw for kw in ["дивиденд", "dividend"]):
            event["event_type"] = "dividend"
        elif any(kw in event_type_raw for kw in ["buyback", "выкуп"]):
            event["event_type"] = "buyback"
        elif any(kw in event_type_raw for kw in ["split", "дробление", "консолидация"]):
            event["event_type"] = "split"
        elif any(kw in event_type_raw for kw in ["эмисси", "emission", "дополнительн"]):
            event["event_type"] = "emission"
        else:
            event["event_type"] = "other"

        for date_field in ["announcement_date", "ex_date", "record_date", "payment_date"]:
            raw_val = raw.get(date_field) or raw.get(date_field.replace("_", ""))
            if raw_val and isinstance(raw_val, str):
                try:
                    parsed = datetime.strptime(raw_val[:10], "%Y-%m-%d").date()
                    event[date_field] = parsed.isoformat()
                except ValueError:
                    logger.debug("Could not parse event date: %s", raw_val[:10])

        event["description"] = raw.get("description") or raw.get("name", "")
        event["extra"] = raw
        return event


# ── DB helpers ───────────────────────────────────────────────────────────────


def store_company_profile(db: Any, instrument: Instrument, profile: dict[str, Any]) -> bool:
    """Store/update company profile."""
    from src.db.models import CompanyProfile

    try:
        existing = db.query(CompanyProfile).filter(CompanyProfile.instrument_id == instrument.id).first()

        if existing:
            for key, value in profile.items():
                if value is not None and hasattr(existing, key):
                    setattr(existing, key, value)
        else:
            profile["instrument_id"] = instrument.id
            record = CompanyProfile(**{k: v for k, v in profile.items() if hasattr(CompanyProfile, k)})
            db.add(record)

        db.flush()
        return True
    except Exception as e:
        logger.error("Failed to store company profile for %s: %s", instrument.ticker, e)
        return False


def store_corporate_event(db: Any, instrument: Instrument, event: dict[str, Any]) -> bool:
    """Store corporate event (deduplicated by type + date + description)."""
    from src.db.models import CorporateEvent

    try:
        existing = (
            db.query(CorporateEvent)
            .filter(
                CorporateEvent.instrument_id == instrument.id,
                CorporateEvent.event_type == event.get("event_type"),
                CorporateEvent.announcement_date
                == (datetime.fromisoformat(event["announcement_date"]).date() if event.get("announcement_date") else None),
            )
            .first()
        )

        if existing:
            return True  # already stored

        mapped = {
            "instrument_id": instrument.id,
            "event_type": event.get("event_type"),
            "status": "announced",
            "announcement_date": (datetime.fromisoformat(event["announcement_date"]).date() if event.get("announcement_date") else None),
            "ex_date": (datetime.fromisoformat(event["ex_date"]).date() if event.get("ex_date") else None),
            "record_date": (datetime.fromisoformat(event["record_date"]).date() if event.get("record_date") else None),
            "payment_date": (datetime.fromisoformat(event["payment_date"]).date() if event.get("payment_date") else None),
            "description": event.get("description"),
        }

        # Remove None values so they use DB defaults
        mapped = {k: v for k, v in mapped.items() if v is not None}

        record = CorporateEvent(**mapped)
        db.add(record)
        db.flush()
        return True
    except Exception as e:
        logger.error("Failed to store corporate event for %s: %s", instrument.ticker, e)
        return False
