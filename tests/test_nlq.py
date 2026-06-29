from __future__ import annotations

from unittest.mock import MagicMock

from src.interfaces.nlq import NLQueryEngine


class TestEntityExtraction:
    def setup_method(self):
        self.engine = NLQueryEngine(llm_client=None)

    def test_extract_tickers_from_query(self):
        entities = self.engine._extract_entities("Compare SBER and VTBR performance")
        assert "SBER" in entities["tickers"]
        assert "VTBR" in entities["tickers"]

    def test_extract_tickers_with_db_filter(self):
        db = MagicMock()
        db.execute.return_value.all.return_value = [("SBER",), ("GAZP",)]
        entities = self.engine._extract_entities("What about SBER and YNDX?", db)
        assert "SBER" in entities["tickers"]
        assert "YNDX" not in entities["tickers"]

    def test_extract_sectors(self):
        entities = self.engine._extract_entities("Show me нефть and IT sector stocks")
        assert "нефть" in entities["sectors"]

    def test_extract_amounts(self):
        entities = self.engine._extract_entities("5% growth and 1000 руб profit")
        assert 5.0 in entities["amounts"]
        assert 1000.0 in entities["amounts"]

    def test_extract_timeframe(self):
        entities = self.engine._extract_entities("Performance this month")
        assert entities["timeframe"] == "1m"


class TestFuzzyMatching:
    def setup_method(self):
        self.engine = NLQueryEngine(llm_client=None)

    def test_misspelled_portfolio(self):
        intent = self.engine.classify_query("стоимость портфеля")
        assert intent == "portfolio_value"

    def test_misspelled_news(self):
        intent = self.engine.classify_query("последние новости по SBER")
        assert intent == "news_impact"

    def test_misspelled_fallback(self):
        intent = self.engine.classify_query("потрфель баланс")
        assert intent == "portfolio_value"

    def test_unrelated_query_returns_unknown(self):
        intent = self.engine.classify_query("hello world foo bar baz")
        assert intent == "unknown"


class TestQueryExpansion:
    def setup_method(self):
        self.engine = NLQueryEngine(llm_client=None)

    def test_expand_sber_abbreviation(self):
        expanded = self.engine._expand_query("сбер банк")
        assert "сбер банк" in expanded

    def test_english_to_russian_mapping(self):
        expanded = self.engine._expand_query("portfolio news")
        assert "портфель" in expanded
        assert "новости" in expanded

    def test_expand_gdp_to_vvp(self):
        expanded = self.engine._expand_query("gdp growth")
        assert "ввп" in expanded

    def test_expansion_enables_intent_match(self):
        intent = self.engine.classify_query("gdp growth")
        assert intent == "macro_query"


class TestNewIntents:
    def setup_method(self):
        self.engine = NLQueryEngine(llm_client=None)

    def test_instrument_info_intent(self):
        intent = self.engine.classify_query("tell me about SBER")
        assert intent == "instrument_info"

    def test_instrument_info_intent_russian(self):
        intent = self.engine.classify_query("информация о компании SBER")
        assert intent == "instrument_info"

    def test_macro_query_intent(self):
        intent = self.engine.classify_query("какая ключевая ставка цб")
        assert intent == "macro_query"

    def test_compare_intent(self):
        intent = self.engine.classify_query("сравни SBER и VTBR")
        assert intent == "compare"

    def test_compare_intent_english(self):
        intent = self.engine.classify_query("compare SBER and GAZP")
        assert intent == "compare"

    def test_instrument_info_handler(self):
        db = MagicMock()
        db.execute.return_value.all.return_value = [("SBER",)]
        first_row = (
            MagicMock(),
            MagicMock(),
        )
        first_row[0].ticker = "SBER"
        first_row[0].full_name = "Sberbank"
        first_row[0].sector = "Финансы"
        first_row[0].id = 1
        first_row[1].close = 250.0
        db.execute.return_value.first.return_value = first_row
        db.execute.return_value.scalar_one_or_none.return_value = None
        result = self.engine._handle_instrument_info("tell me about SBER", db, 1)
        assert result["intent"] == "instrument_info"
        assert result["count"] > 0
        assert result["instruments"][0]["ticker"] == "SBER"

    def test_macro_query_handler(self):
        db = MagicMock()
        row = MagicMock()
        row.value = 21.0
        row.date = MagicMock()
        row.date.isoformat.return_value = "2026-06-01"
        db.execute.return_value.scalar_one_or_none.return_value = row
        result = self.engine._handle_macro_query("cbr rate", db, 1)
        assert result["intent"] == "macro_query"
        assert "cbr_rate" in result["indicators"]

    def test_compare_handler_needs_two_tickers(self):
        db = MagicMock()
        result = self.engine._handle_compare("compare SBER", db, 1)
        assert "error" in result
        assert "two tickers" in result["error"]


class TestContextMemory:
    def setup_method(self):
        NLQueryEngine._conversation_memory.clear()
        self.engine = NLQueryEngine(llm_client=None)

    def test_store_and_retrieve_context(self):
        data = {"intent": "portfolio_value", "total": 1000, "positions": [], "count": 0}
        self.engine._store_memory(42, "portfolio value", data)
        ctx = self.engine._get_context(42)
        assert "portfolio value" in ctx
        assert "История диалога" in ctx

    def test_context_empty_for_unknown_user(self):
        ctx = self.engine._get_context(999)
        assert ctx == ""

    def test_context_limited_to_last_three(self):
        for i in range(5):
            data = {"intent": "portfolio_value", "total": i, "positions": [], "count": 0}
            self.engine._store_memory(1, f"query {i}", data)
        ctx = self.engine._get_context(1)
        assert "query 0" not in ctx
        assert "query 2" in ctx
        assert "query 4" in ctx


class TestFallback:
    def setup_method(self):
        self.engine = NLQueryEngine(llm_client=None)

    def test_fallback_with_tickers_extracts_info(self):
        db = MagicMock()
        db.execute.return_value.all.return_value = [("SBER",)]
        first_row = (
            MagicMock(),
            MagicMock(),
        )
        first_row[0].ticker = "SBER"
        first_row[0].full_name = "Sberbank"
        first_row[0].sector = "Финансы"
        first_row[0].id = 1
        first_row[1].close = 250.0
        db.execute.return_value.first.return_value = first_row
        db.execute.return_value.scalar_one_or_none.return_value = None
        result = self.engine._handle_unknown("SBER something weird", db, 1)
        assert "fallback_tickers" in result
        assert "SBER" in result["fallback_tickers"]
        assert result["instruments"][0]["ticker"] == "SBER"

    def test_fallback_no_tickers_returns_error(self):
        db = MagicMock()
        result = self.engine._handle_unknown("hello world", db, 1)
        assert "error" in result
        assert "Unrecognized" in result["error"]

    def test_format_unknown_with_tickers(self):
        data = {"intent": "unknown", "fallback_tickers": ["SBER"]}
        text = self.engine._format_unknown(data)
        assert "SBER" in text

    def test_format_unknown_no_tickers(self):
        data = {"intent": "unknown", "error": "I couldn't process that query."}
        text = self.engine._format_unknown(data)
        assert "I couldn't process" in text


class TestExistingIntents:
    def setup_method(self):
        self.engine = NLQueryEngine(llm_client=None)

    def test_portfolio_value_still_works(self):
        intent = self.engine.classify_query("how much is my portfolio worth")
        assert intent == "portfolio_value"

    def test_risk_metrics_still_works(self):
        intent = self.engine.classify_query("show value at risk and drawdown")
        assert intent == "risk_metrics"

    def test_top_picks_still_works(self):
        intent = self.engine.classify_query("лучшие сигналы на покупку")
        assert intent == "top_picks"
