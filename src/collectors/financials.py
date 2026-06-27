import logging
import re
from typing import Any, Optional, Self

import httpx
from bs4 import BeautifulSoup  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)

SMARTLAB_URL = "https://smart-lab.ru/q/{ticker}/f/y/MSFO/"

FIELD_MAP: list[tuple[re.Pattern[Any], str]] = [
    # Ordered most-specific first → first match wins
    (re.compile(r"^чистые\s+актив", re.IGNORECASE), "total_equity"),
    (re.compile(r"^актив", re.IGNORECASE), "total_assets"),
    (re.compile(r"^чистая\s+прибыль", re.IGNORECASE), "net_profit"),
    (re.compile(r"^чист\.?\s*проц\.?\s*доход", re.IGNORECASE), "net_interest_income"),
    (re.compile(r"^выручк(?!а/|,%)", re.IGNORECASE), "revenue"),
    (re.compile(r"^кредитный\s+портфель", re.IGNORECASE), "loan_portfolio"),
    (re.compile(r"^депозиты(?:,|$)", re.IGNORECASE), "customer_deposits"),
    (re.compile(r"^roe", re.IGNORECASE), "roe"),
    (re.compile(r"^roa", re.IGNORECASE), "roa"),
    (re.compile(r"просроченн|npl", re.IGNORECASE), "npl_ratio"),
    (re.compile(r"^дост\.?\s*(?:осн|общ)?\.?\s*капитала", re.IGNORECASE), "capital_adequacy"),
    (re.compile(r"расходы[ /]доходы|cir|cost[ /]income", re.IGNORECASE), "cost_income_ratio"),
    (re.compile(r"(?:^чистая\s+)?процентная\s+марж|^чист\.?\s*процент\.?\s*марж", re.IGNORECASE), "net_margin"),
    (re.compile(r"^капитал(?:а,|,)", re.IGNORECASE), "total_equity"),
]


UNIT_MAP = {
    "трлн": 1e12,
    "млрд": 1e9,
    "млн": 1e6,
    "тыс": 1e3,
}


def _parse_value(text: str, unit: str = "") -> Optional[float]:
    text = text.strip()
    if not text or text in ("—", "-", "", "N/A"):
        return None
    if text.endswith(")"):
        text = "-" + text.strip("()")
    is_negative = text.startswith("-")
    text = text.lstrip("-+")

    # Determine multiplier: first from cell text, then from field unit
    multiplier = 1.0
    for unit_word, mul in UNIT_MAP.items():
        if unit_word in text:
            multiplier = mul
            text = text.replace(unit_word, "")
            break
    else:
        for unit_word, mul in UNIT_MAP.items():
            if unit_word in unit:
                multiplier = mul
                break

    text = text.replace("\xa0", " ").replace(" ", "").replace(",", ".").replace("%", "")
    try:
        val = float(text) * multiplier
        if is_negative:
            val = -val
        return val
    except (ValueError, TypeError):
        return None


class FinancialReportCollector:
    """Collects IFRS financial report data from SmartLab."""

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        return self._client

    async def fetch(self, ticker: str) -> dict[str, Any]:
        """Fetch latest IFRS financial data for a given ticker.

        Returns dict with period info and mapped fields, or empty dict on failure.
        """
        client = await self._get_client()
        url = SMARTLAB_URL.format(ticker=ticker.upper())
        try:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("SmartLab fetch failed for %s: %s", ticker, e)
            return {}
        return self._parse(resp.text)

    def _parse(self, html: str) -> dict[str, Any]:
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table", class_="financials")
        if not table:
            logger.warning("No financials table found in SmartLab response")
            return {}
        rows = table.find_all("tr")
        if len(rows) < 5:
            return {}

        # Data rows have a different cell layout than header rows:
        # Header (row 2): [colspan2_label, chart, 2021, 2022, 2023, 2024, 2025, spacing, LTM]
        # Data rows:      [field, ?, chart, 2021, 2022, 2023, 2024, 2025, spacing, LTM]
        # So header year indexes are offset by -1 relative to data rows.
        # The latest year value in data rows is at index 7, LTM at index 9.
        latest_year_col = 7
        ltm_col_idx = 9

        result: dict[str, Any] = {}
        period_type = "FY"
        report_date = None

        # Extract report date from row 3 (date row) or row 2
        if len(rows) > 3:
            date_cells = rows[3].find_all(["th", "td"])
            if len(date_cells) > latest_year_col:
                latest_date_cell = date_cells[latest_year_col].get_text(strip=True)
                dm = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", latest_date_cell)
                if dm:
                    report_date = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}"
            if len(date_cells) > ltm_col_idx:
                ltm_date_cell = date_cells[ltm_col_idx].get_text(strip=True)
                dm = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", ltm_date_cell)
                if dm:
                    report_date = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}"
                    period_type = "LTM"

        result["period_type"] = period_type
        if report_date:
            result["reporting_date"] = report_date

        # Parse data rows
        for row in rows[5:]:
            cells = row.find_all(["th", "td"])
            if len(cells) < 2:
                continue
            field_raw = cells[0].get_text(strip=True)
            skip = ("Доходы", "Расходы", "Прибыль", "Финансовый отчет", "Годовой отчет", "Презентация")
            if not field_raw or field_raw.strip(",") in skip:
                continue

            # Try LTM column first, then fall back to latest FY year column
            val_col = ltm_col_idx
            if val_col >= len(cells) or not cells[val_col].get_text(strip=True):
                val_col = latest_year_col
            elif latest_year_col < len(cells):
                # Heuristic: if LTM value looks like it's in a different unit than
                # the field name (e.g., value < 1000 but field says млрд), use FY column
                ltm_text = cells[val_col].get_text(strip=True)
                fy_text = cells[latest_year_col].get_text(strip=True)
                try:
                    ltm_num = float(ltm_text.replace(" ", "").replace(",", "."))
                    fy_num = float(fy_text.replace(" ", "").replace(",", "."))
                    if fy_num > 0 and ltm_num * 100 < fy_num:
                        val_col = latest_year_col
                except (ValueError, TypeError):
                    val_col = latest_year_col

            value_raw = cells[val_col].get_text(strip=True)
            # Extract unit from field name (e.g., "Чистая прибыль,млрд руб" -> "млрд")
            unit_match = re.search(r",(\w+)", field_raw)
            unit = unit_match.group(1) if unit_match else ""
            value = _parse_value(value_raw, unit)
            if value is None:
                continue
            mapped = self._match_field(field_raw)
            if mapped:
                result[mapped] = value

        return result

    @staticmethod
    def _match_field(field_raw: str) -> Optional[str]:
        for pattern, field_name in FIELD_MAP:
            if pattern.search(field_raw):
                return field_name
        return None

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
