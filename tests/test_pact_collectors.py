"""Contract tests for MOEX ISS API collector using Pact + pytest-httpx.

Architecture:
  Section 1 — Pact consumer-driven contract (generates pact JSON files, skipped
              if pact-python is not installed).  The Pact mock server does not
              work reliably on Windows, so we only exercise interaction
              definition and file writing (the contract itself).
  Section 2 — MOEX ISS response parsing unit-tests (no HTTP).
  Section 3 — Consumer-side contract verification via ``pytest-httpx``.
  Section 4 — BaseCollector retry / circuit-breaker / rate-limiter contract tests.
"""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.collectors.base import BaseCollector
from src.collectors.moex import MOEXCollector

# ── Detect pact-python availability ─────────────────────────────────────────

pact_available: bool = False
try:
    from pact import Pact

    pact_available = True
except ImportError:
    pass


# ── Helpers ─────────────────────────────────────────────────────────────────


def _reset_cb() -> None:
    from src.core.resilience import reset_all_circuit_breakers

    asyncio.run(reset_all_circuit_breakers())


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Pact consumer-driven contract definition
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.skipif(not pact_available, reason="pact-python is not installed")
class TestPactContractDefinition:
    """Define interactions and generate Pact contract files.

    The Pact mock server requires the ``pact_ffi`` native library and is
    unreliable on Windows — we therefore limit ourselves to verifying that
    the contract can be *defined* and *serialised* correctly.
    """

    def _build_pact(self) -> Any:
        from pact import Pact

        return Pact("FinnApp", "MOEX_ISS")

    def test_stock_interaction_defines_correctly(self):
        p = self._build_pact()
        (
            p.upon_receiving("a request for stock SBER")
            .with_request("GET", "/iss/engines/stock/markets/shares/securities/SBER.json")
            .with_query_parameter("iss.meta", "off")
            .will_respond_with(200)
            .with_body(
                {
                    "marketdata": {
                        "columns": ["SECID", "SHORTNAME", "MARKETPRICE"],
                        "data": [["SBER", "Сбер", 285.50]],
                    }
                },
                part="Response",
            )
        )
        tmp = Path(tempfile.mkdtemp()) / "pacts"
        tmp.mkdir(parents=True, exist_ok=True)
        p.write_file(str(tmp))
        pact_file = tmp / "FinnApp-MOEX_ISS.json"
        assert pact_file.exists()
        with open(pact_file, encoding="utf-8") as f:
            contract = json.load(f)
        interactions = contract["interactions"]
        assert len(interactions) == 1
        i = interactions[0]
        assert i["request"]["method"] == "GET"
        assert i["request"]["path"] == "/iss/engines/stock/markets/shares/securities/SBER.json"
        assert i["request"]["query"] == {"iss.meta": ["off"]}
        assert i["response"]["status"] == 200

    def test_bond_interaction_defines_correctly(self):
        p = self._build_pact()
        (
            p.upon_receiving("a request for bonds on TQCB")
            .with_request(
                "GET",
                "/iss/engines/stock/markets/bonds/boards/TQCB/securities.json",
            )
            .with_query_parameter("iss.meta", "off")
            .will_respond_with(200)
            .with_body(
                {
                    "securities": {
                        "columns": ["SECID", "SHORTNAME", "ISIN"],
                        "data": [["SU26238RMFS5", "ОФЗ 26238", "RU000A101XE5"]],
                    }
                },
                part="Response",
            )
        )
        tmp = Path(tempfile.mkdtemp()) / "pacts"
        tmp.mkdir(parents=True, exist_ok=True)
        p.write_file(str(tmp))
        pact_file = tmp / "FinnApp-MOEX_ISS.json"
        assert pact_file.exists()
        with open(pact_file, encoding="utf-8") as f:
            contract = json.load(f)
        assert len(contract["interactions"]) == 1
        i = contract["interactions"][0]
        assert i["request"]["path"] == "/iss/engines/stock/markets/bonds/boards/TQCB/securities.json"

    def test_history_interaction_defines_correctly(self):
        p = self._build_pact()
        (
            p.upon_receiving("a request for SBER history from 2025-01-01")
            .with_request(
                "GET",
                "/iss/history/engines/stock/markets/shares/securities/SBER.json",
            )
            .with_query_parameter("iss.meta", "off")
            .with_query_parameter("from", "2025-01-01")
            .will_respond_with(200)
            .with_body(
                {
                    "history": {
                        "columns": ["BOARDID", "TRADEDATE", "CLOSE", "VOLUME"],
                        "data": [
                            ["TQBR", "2025-06-01", 280.0, 1_500_000],
                            ["TQBR", "2025-06-02", 282.5, 1_200_000],
                        ],
                    }
                },
                part="Response",
            )
        )
        tmp = Path(tempfile.mkdtemp()) / "pacts"
        tmp.mkdir(parents=True, exist_ok=True)
        p.write_file(str(tmp))
        pact_file = tmp / "FinnApp-MOEX_ISS.json"
        assert pact_file.exists()
        with open(pact_file, encoding="utf-8") as f:
            contract = json.load(f)
        assert len(contract["interactions"]) == 1
        i = contract["interactions"][0]
        assert i["request"]["query"]["from"] == ["2025-01-01"]

    def test_multiple_interactions_in_one_pact(self):
        p = self._build_pact()
        (
            p.upon_receiving("stocks request")
            .with_request("GET", "/iss/engines/stock/markets/shares/securities/SBER.json")
            .with_query_parameter("iss.meta", "off")
            .will_respond_with(200)
            .with_body({"marketdata": {"columns": ["SECID"], "data": [["SBER"]]}}, part="Response")
        )
        (
            p.upon_receiving("bonds request")
            .with_request("GET", "/iss/engines/stock/markets/bonds/boards/TQCB/securities.json")
            .with_query_parameter("iss.meta", "off")
            .will_respond_with(200)
            .with_body({"securities": {"columns": ["SECID"], "data": []}}, part="Response")
        )
        tmp = Path(tempfile.mkdtemp()) / "pacts"
        tmp.mkdir(parents=True, exist_ok=True)
        p.write_file(str(tmp))
        pact_file = tmp / "FinnApp-MOEX_ISS.json"
        with open(pact_file, encoding="utf-8") as f:
            contract = json.load(f)
        assert len(contract["interactions"]) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — MOEX ISS response parsing (no HTTP)
# ═══════════════════════════════════════════════════════════════════════════════

_STOCK_MOCK = {
    "marketdata": {
        "columns": ["SECID", "SHORTNAME", "MARKETPRICE", "LASTSETTLEPRICE", "LOTSIZE", "BOARDID"],
        "data": [["SBER", "Сбер", 285.50, 284.90, 10, "TQBR"]],
    },
    "securities": {
        "columns": ["SECID", "SHORTNAME", "ISIN", "LISTLEVEL", "SECTORID", "FACEVALUE", "ISSUESIZE", "ISSUEDATE"],
        "data": [["SBER", "Сбер", "RU0009029540", "1", "3", 1000.0, 500000000, "2000-01-01"]],
    },
}

_BOND_MOCK = {
    "securities": {
        "columns": [
            "SECID",
            "SHORTNAME",
            "PREVADMITTEDQUOTE",
            "ISIN",
            "FACEUNIT",
            "MATDATE",
            "COUPONPERCENT",
            "COUPONVALUE",
            "COUPONPERIOD",
            "NEXTCOUPON",
            "PREVCOUPONDATE",
        ],
        "data": [["SU26238RMFS5", "ОФЗ 26238", 98.5, "RU000A101XE5", "SUR", "2032-05-19", 11.85, 59.25, 182, "2026-07-15", "2026-01-15"]],
    }
}

_HISTORY_MOCK = {
    "history": {
        "columns": ["BOARDID", "TRADEDATE", "CLOSE", "VOLUME", "OPEN", "HIGH", "LOW"],
        "data": [
            ["TQBR", "2025-06-01", 280.0, 1_500_000, 278.0, 282.0, 277.5],
            ["TQBR", "2025-06-02", 282.5, 1_200_000, 280.0, 284.0, 279.0],
        ],
    }
}

_EMPTY_HISTORY = {"history": {"columns": ["TRADEDATE"], "data": []}}


class TestMOEXResponseParsing:
    """Test ``_parse_table`` against realistic MOEX ISS payloads."""

    def test_parse_stock_marketdata(self):
        rows = BaseCollector._parse_table(_STOCK_MOCK, "marketdata")
        assert len(rows) == 1
        row = rows[0]
        assert row["SECID"] == "SBER"
        assert row["SHORTNAME"] == "Сбер"
        assert row["MARKETPRICE"] == 285.50
        assert row["LOTSIZE"] == 10
        assert row["BOARDID"] == "TQBR"

    def test_parse_stock_securities(self):
        rows = BaseCollector._parse_table(_STOCK_MOCK, "securities")
        assert len(rows) == 1
        row = rows[0]
        assert row["ISIN"] == "RU0009029540"
        assert row["LISTLEVEL"] == "1"
        assert row["FACEVALUE"] == 1000.0

    def test_parse_bond_securities(self):
        rows = BaseCollector._parse_table(_BOND_MOCK, "securities")
        assert len(rows) == 1
        row = rows[0]
        assert row["SECID"] == "SU26238RMFS5"
        assert row["SHORTNAME"] == "ОФЗ 26238"
        assert row["PREVADMITTEDQUOTE"] == 98.5
        assert row["ISIN"] == "RU000A101XE5"
        assert row["COUPONPERCENT"] == 11.85
        assert row["MATDATE"] == "2032-05-19"

    def test_parse_history(self):
        rows = BaseCollector._parse_table(_HISTORY_MOCK, "history")
        assert len(rows) == 2
        assert rows[0]["TRADEDATE"] == "2025-06-01"
        assert rows[0]["CLOSE"] == 280.0
        assert rows[0]["VOLUME"] == 1_500_000
        assert rows[1]["TRADEDATE"] == "2025-06-02"
        assert rows[1]["CLOSE"] == 282.5

    def test_empty_history(self):
        rows = BaseCollector._parse_table(_EMPTY_HISTORY, "history")
        assert rows == []

    def test_missing_table(self):
        assert BaseCollector._parse_table({}, "nonexistent") == []

    def test_missing_columns(self):
        assert BaseCollector._parse_table({"history": {"data": [["a"]]}}, "history") == []

    def test_missing_data(self):
        assert BaseCollector._parse_table({"history": {"columns": ["X"]}}, "history") == []

    def test_null_values_in_row(self):
        data: dict[str, Any] = {
            "marketdata": {
                "columns": ["SECID", "MARKETPRICE", "VOLUME"],
                "data": [["SBER", None, 1000]],
            }
        }
        rows = BaseCollector._parse_table(data, "marketdata")
        assert rows[0]["SECID"] == "SBER"
        assert rows[0]["MARKETPRICE"] is None
        assert rows[0]["VOLUME"] == 1000


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Consumer-side contract verification via ``pytest-httpx``
# ═══════════════════════════════════════════════════════════════════════════════

_PAGINATION_RE = re.compile(r".*")


class TestCollectorWithHttpxMock:
    """Verify that ``MOEXCollector`` correctly handles realistic API responses.

    All responses use regex URL matching because ``_paginate`` appends
    ``&start=N`` to every request.
    """

    @pytest.fixture(autouse=True)
    def _reset_cb_before(self):
        _reset_cb()

    @pytest.fixture
    def collector(self) -> MOEXCollector:
        return MOEXCollector()

    @pytest.mark.asyncio
    async def test_get_stocks(self, httpx_mock, collector):
        httpx_mock.add_response(
            url=re.compile(r".*/engines/stock/markets/shares/boards/TQBR/securities.json.*"),
            json=_STOCK_MOCK,
        )
        result = await collector.get_stocks()
        assert len(result) == 1
        assert result[0]["SECID"] == "SBER"
        assert result[0]["SHORTNAME"] == "Сбер"

    @pytest.mark.asyncio
    async def test_get_bonds(self, httpx_mock, collector):
        for board in ["TQCB", "TQBD", "TQOB"]:
            httpx_mock.add_response(
                url=re.compile(rf".*/engines/stock/markets/bonds/boards/{board}/securities.json.*"),
                json=_BOND_MOCK,
                is_optional=board != "TQCB",
            )
        result = await collector.get_bonds()
        assert len(result) == 1
        assert result[0]["SECID"] == "SU26238RMFS5"
        assert result[0]["ISIN"] == "RU000A101XE5"

    @pytest.mark.asyncio
    async def test_get_history(self, httpx_mock, collector):
        httpx_mock.add_response(
            url=re.compile(r".*/history/engines/stock/markets/shares/boards/TQBR/securities/SBER.json.*"),
            json=_HISTORY_MOCK,
        )
        result = await collector.get_history("SBER", from_date="2025-01-01", board="stock")
        assert len(result) == 2
        assert result[0]["CLOSE"] == 280.0
        assert result[1]["CLOSE"] == 282.5

    @pytest.mark.asyncio
    async def test_get_stocks_empty_response(self, httpx_mock, collector):
        httpx_mock.add_response(
            url=re.compile(r".*/engines/stock/markets/shares/boards/TQBR/securities.json.*"),
            json={},
        )
        result = await collector.get_stocks()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_marketdata_parses_correctly(self, httpx_mock, collector):
        httpx_mock.add_response(
            url=re.compile(r".*/engines/stock/markets/shares/securities/SBER.json.*"),
            json=_STOCK_MOCK,
        )
        result = await collector.get_marketdata("SBER")
        assert result["SECID"] == "SBER"
        assert result["MARKETPRICE"] == 285.50
        assert result["LOTSIZE"] == 10

    @pytest.mark.asyncio
    async def test_get_security_info(self, httpx_mock, collector):
        httpx_mock.add_response(
            url=re.compile(r".*/securities/SBER.json.*"),
            json={
                "description": {
                    "columns": ["name", "value"],
                    "data": [
                        ["SECID", "SBER"],
                        ["SHORTNAME", "Сбер"],
                        ["ISIN", "RU0009029540"],
                        ["LISTLEVEL", "1"],
                        ["SECTORID", "3"],
                        ["ISSUESIZE", "500000000"],
                        ["FACEVALUE", "1000.0"],
                        ["ISSUEDATE", "2000-01-01"],
                    ],
                }
            },
        )
        info = await collector.get_security_info("SBER")
        assert info["secid"] == "SBER"
        assert info["isin"] == "RU0009029540"
        assert info["shares_outstanding"] == 500000000
        assert info["face_value"] == 1000.0


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — BaseCollector retry / circuit-breaker / rate-limiter contract tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestBaseCollectorRetryBehaviour:
    """Verify exponential backoff, circuit-breaker opening/closing, and rate-limiting."""

    @pytest.fixture(autouse=True)
    async def _reset_breakers(self):
        from src.core.resilience import reset_all_circuit_breakers

        await reset_all_circuit_breakers()

    @pytest.mark.asyncio
    async def test_retry_on_http_error_then_succeed(self, httpx_mock):
        url_re = re.compile(r".*/securities.json.*")
        httpx_mock.add_response(url=url_re, status_code=500)
        httpx_mock.add_response(url=url_re, status_code=500)
        httpx_mock.add_response(url=url_re, json={"securities": {"columns": ["SECID"], "data": [["SBER"]]}})
        collector = MOEXCollector()
        result = await collector.get_securities()
        assert result[0]["SECID"] == "SBER"

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_after_threshold(self, httpx_mock):
        from src.core.resilience import configure_circuit_breaker, get_circuit_breaker

        url_re = re.compile(r".*/securities.json.*")
        configure_circuit_breaker("MOEXCollector", failure_threshold=3, recovery_timeout=300)
        for _ in range(3):
            httpx_mock.add_response(url=url_re, status_code=500)
        collector = MOEXCollector()
        with pytest.raises(Exception):
            await collector.get_securities()
        cb = get_circuit_breaker("MOEXCollector")
        assert cb.is_open

    @pytest.mark.asyncio
    async def test_circuit_breaker_recovers_after_timeout(self):
        from src.core.resilience import configure_circuit_breaker, get_circuit_breaker

        configure_circuit_breaker("MOEXCollector", failure_threshold=2, recovery_timeout=0.05, success_threshold=1)
        collector = MOEXCollector()
        collector.MAX_RETRIES = 2

        async def failing(url: str, params: Any = None) -> httpx.Response:
            raise httpx.HTTPStatusError("fail", request=AsyncMock(), response=AsyncMock(status_code=502))

        with patch.object(collector, "_rate_limited_fetch", failing):
            with pytest.raises(httpx.HTTPStatusError):
                await collector._fetch_json("/test")

        cb = get_circuit_breaker("MOEXCollector")
        assert cb.is_open
        assert cb.failure_count == 2

        await asyncio.sleep(0.06)

        async def succeeding(url: str, params: Any = None) -> httpx.Response:
            resp = AsyncMock(status_code=200)
            resp.json = lambda: {"securities": {"columns": ["SECID"], "data": [["SBER"]]}}
            resp.raise_for_status = lambda: None
            return resp

        with patch.object(collector, "_rate_limited_fetch", succeeding):
            result = await collector._fetch_json("/test")

        assert result["securities"]["data"][0][0] == "SBER"
        assert cb.is_closed

    @pytest.mark.asyncio
    async def test_exponential_backoff(self):
        """Verify that successive retries wait longer each time."""
        import time as tm

        from src.core.resilience import configure_circuit_breaker, configure_rate_limiter

        configure_circuit_breaker("MOEXCollector", failure_threshold=100)
        configure_rate_limiter("MOEXCollector", max_rate=10000)
        collector = MOEXCollector()
        collector.MAX_RETRIES = 3
        collector.RETRY_DELAY = 0.05

        timings: list[float] = []

        async def failing_fetch(url: str, params: Any = None) -> httpx.Response:
            timings.append(tm.monotonic())
            msg = "upstream error"
            raise httpx.HTTPStatusError(msg, request=AsyncMock(), response=AsyncMock(status_code=502))

        with patch.object(collector, "_rate_limited_fetch", failing_fetch):
            with pytest.raises(httpx.HTTPStatusError):
                await collector._fetch_json("/test")
        assert len(timings) >= 3
        gaps = [timings[i + 1] - timings[i] for i in range(len(timings) - 1)]
        assert gaps[0] >= 0.005
        assert gaps[1] >= gaps[0] * 1.5

    @pytest.mark.asyncio
    async def test_max_retries_exhausted(self):
        collector = MOEXCollector()
        collector.MAX_RETRIES = 3

        async def failing(url: str, params: Any = None) -> httpx.Response:
            raise httpx.HTTPStatusError("fail", request=AsyncMock(), response=AsyncMock(status_code=503))

        with patch.object(collector, "_rate_limited_fetch", failing):
            with pytest.raises(httpx.HTTPStatusError):
                await collector._fetch_json("/test")

    @pytest.mark.asyncio
    async def test_non_retryable_error_propagates(self):
        collector = MOEXCollector()

        async def failing(url: str, params: Any = None) -> httpx.Response:
            raise ValueError("parse error")

        with patch.object(collector, "_rate_limited_fetch", failing):
            with pytest.raises(ValueError, match="parse error"):
                await collector._fetch_json("/test")
