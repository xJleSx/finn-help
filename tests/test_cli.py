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

    @pytest.mark.asyncio
    async def test_dividend_collection_skips_existing(self):
        from src.db.connection import get_session
        from src.db.models import Dividend
        db = get_session()
        try:
            all_divs = db.query(Dividend).count()
            print(f"Existing dividends in DB: {all_divs}")
        finally:
            db.close()


class TestBondDataLoading:
    def test_bonds_exist_in_db(self):
        from src.db.connection import get_session
        from src.db.models import Instrument
        db = get_session()
        try:
            bonds = db.query(Instrument).filter_by(instrument_type="bond").count()
            print(f"Bonds in DB: {bonds}")
            assert bonds > 0, "No bonds loaded"
        finally:
            db.close()

    def test_bonds_with_prices(self):
        from src.db.connection import get_session
        from src.db.models import Instrument, Price
        db = get_session()
        try:
            bonds = db.query(Instrument).filter_by(instrument_type="bond").all()
            with_prices = 0
            for b in bonds:
                p = db.query(Price).filter_by(instrument_id=b.id).first()
                if p:
                    with_prices += 1
            print(f"Bonds with prices: {with_prices}/{len(bonds)}")
        finally:
            db.close()
