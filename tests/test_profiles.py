from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from src.collectors.profiles import (
    MOEXCorporateEventCollector,
    SmartLabProfileCollector,
    store_company_profile,
    store_corporate_event,
)


class TestSmartLabProfileCollector:
    def test_parse_int(self):
        assert SmartLabProfileCollector._parse_int("1 234") == 1234
        assert SmartLabProfileCollector._parse_int("") is None
        assert SmartLabProfileCollector._parse_int("N/A") is None

    def test_fetch_profile_http_error(self):
        collector = SmartLabProfileCollector()
        with patch.object(collector, "_get_client") as mock_get:
            client = MagicMock()
            resp = MagicMock()
            resp.raise_for_status.side_effect = Exception("HTTP error")
            client.get.return_value = resp
            mock_get.return_value = client
            result = collector.fetch_profile("SBER")
        assert result == {}  # graceful empty on error

    def test_fetch_profile_success(self):
        collector = SmartLabProfileCollector()
        html = """
        <html>
        <body>
        <h2>О компании</h2>
        <p>Сбер — крупнейший банк России.</p>
        <table class="simple">
        <tr><td>Сайт</td><td>sberbank.ru</td></tr>
        <tr><td>Сотрудники</td><td>250 000</td></tr>
        <tr><td>Год основания</td><td>1841</td></tr>
        <tr><td>Отрасль</td><td>Финансы</td></tr>
        </table>
        </body>
        </html>
        """
        with patch.object(collector, "_get_client") as mock_get:
            client = MagicMock()
            resp = MagicMock()
            resp.text = html
            resp.raise_for_status.return_value = None
            client.get.return_value = resp
            mock_get.return_value = client
            result = collector.fetch_profile("SBER")

        assert result["description"] == "Сбер — крупнейший банк России."
        assert result["website"] == "sberbank.ru"
        assert result["employees"] == 250000
        assert result["founded_year"] == 1841
        assert result["industry"] == "Финансы"


class TestMOEXCorporateEventCollector:
    def test_fetch_events_http_error(self):
        async def run():
            collector = MOEXCorporateEventCollector()
            with patch.object(collector, "_get_client") as mock_get:
                client = MagicMock()
                resp = MagicMock()
                resp.raise_for_status.side_effect = Exception("HTTP error")
                client.get.return_value = resp
                mock_get.return_value = client
                return await collector.fetch_corporate_events("SBER")
        result = asyncio.run(run())
        assert result == []

    def test_fetch_events_empty_response(self):
        async def run():
            collector = MOEXCorporateEventCollector()
            with patch.object(collector, "_get_client") as mock_get:
                client = MagicMock()
                resp = MagicMock()
                resp.raise_for_status.return_value = None
                resp.json.return_value = {"events": {"columns": [], "data": []}}
                client.get.return_value = resp
                mock_get.return_value = client
                return await collector.fetch_corporate_events("SBER")
        result = asyncio.run(run())
        assert result == []

    def test_normalize_dividend_event(self):
        raw = {
            "id": "123",
            "name": "Дивиденды за 2024",
            "event_type": "dividend",
            "announcement_date": "2024-03-15",
            "isin": "RU0009029544",
        }
        norm = MOEXCorporateEventCollector._normalize_event(raw)
        assert norm["event_type"] == "dividend"
        assert "announcement_date" in norm

    def test_normalize_split_event(self):
        raw = {
            "id": "456",
            "name": "Дробление акций",
            "event_type": "split",
        }
        norm = MOEXCorporateEventCollector._normalize_event(raw)
        assert norm["event_type"] == "split"

    def test_normalize_unknown_event(self):
        raw = {"id": "789", "name": "Общее собрание акционеров"}
        norm = MOEXCorporateEventCollector._normalize_event(raw)
        assert norm["event_type"] == "other"


class TestStoreCompanyProfile:
    def test_new_profile(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        instrument = MagicMock(id=1, ticker="SBER")
        profile = {"description": "Big bank", "website": "sber.ru", "employees": 250000}

        result = store_company_profile(db, instrument, profile)
        assert result is True
        db.add.assert_called_once()

    def test_existing_profile(self):
        existing = MagicMock()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = existing
        instrument = MagicMock(id=1, ticker="SBER")
        profile = {"description": "Updated desc"}

        result = store_company_profile(db, instrument, profile)
        assert result is True
        assert existing.description == "Updated desc"

    def test_store_failure(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.side_effect = Exception("DB error")
        instrument = MagicMock(id=1, ticker="SBER")
        result = store_company_profile(db, instrument, {"description": "test"})
        assert result is False


class TestStoreCorporateEvent:
    def test_new_event(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        instrument = MagicMock(id=1, ticker="SBER")
        event = {
            "event_type": "dividend",
            "announcement_date": "2024-03-15",
            "description": "Div for 2024",
        }
        result = store_corporate_event(db, instrument, event)
        assert result is True
        db.add.assert_called_once()

    def test_duplicate_event(self):
        existing = MagicMock()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = existing
        instrument = MagicMock(id=1, ticker="SBER")
        event = {
            "event_type": "dividend",
            "announcement_date": "2024-03-15",
        }
        result = store_corporate_event(db, instrument, event)
        assert result is True
        db.add.assert_not_called()  # deduplicated
