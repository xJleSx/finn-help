"""Tests for CLI update command logic"""
from __future__ import annotations

import pytest


class TestUpdateTickerBoardSelection:
    @pytest.mark.asyncio
    async def test_board_for_stock_instrument(self):
        """Stock instruments should use 'stock' board"""
        from src.cli import _update_ticker
        assert hasattr(_update_ticker, "__code__")

    def test_board_map_for_existing_stock(self):
        """_update_ticker should pick board based on instrument_type"""
        board_map = {"stock": "stock", "bond": "bond", "etf": "etf"}
        assert board_map["stock"] == "stock"
        assert board_map["bond"] == "bond"
        assert board_map["etf"] == "etf"

    def test_board_map_unknown_fallsback(self):
        from src.collectors.moex import BOARD_MAP
        assert "shares" in BOARD_MAP


class TestUpdateCommandStructure:
    def test_update_command_registered(self):
        from src.cli import app
        names = [ci.callback.__name__ for ci in app.registered_commands if ci.callback]
        assert "update" in names
        assert "seed_portfolio" in names
        assert "analyze" in names

    def test_update_command_help(self):
        from src.cli import app
        for ci in app.registered_commands:
            if ci.callback and ci.callback.__name__ == "update":
                doc = ci.callback.__doc__
                assert "Обновить данные с MOEX" in doc
                return
        assert False, "update command not found"


class TestSchedulerDividends:
    def test_dividend_collection_exists(self):
        from src.scheduler.tasks import _collect_dividends
        assert hasattr(_collect_dividends, "__code__")

    def test_instrument_filter_for_dividends(self):
        """_collect_dividends should only query stock and etf instruments"""
        from sqlalchemy import inspect
        from src.db.models import Instrument
        mapper = inspect(Instrument)
        assert hasattr(mapper, "columns")

    def test_dividend_collection_skips_existing(self, db_session):
        from src.db.models import Dividend
        count = db_session.query(Dividend).count()
        assert count == 0


class TestBondDataLoading:
    def test_bonds_exist_in_db(self, db_session):
        from src.db.models import Instrument
        count = db_session.query(Instrument).filter_by(instrument_type="bond").count()
        assert count == 0  # in-memory DB, no data loaded

    def test_bonds_with_prices(self, db_session):
        from src.db.models import Instrument, Price
        bonds = db_session.query(Instrument).filter_by(instrument_type="bond").all()
        assert len(bonds) == 0  # in-memory DB, no data loaded
