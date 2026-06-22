"""Integration tests exercising real business logic against an in-memory SQLite DB."""

from datetime import date, timedelta

from src.db.models import Dividend, Indicator, Instrument, Price
from src.db.models import Portfolio as PortModel
from src.db.models import Signal as SignalModel


def _clean_tables(db):
    for table in [Price, Dividend, PortModel, Indicator, SignalModel, Instrument]:
        db.query(table).delete()
    db.commit()


def _seed_instrument(db, ticker: str, itype: str = "stock", sector: str | None = None) -> Instrument:
    inst = Instrument(ticker=ticker, full_name=f"Test {ticker}", instrument_type=itype, sector=sector)
    db.add(inst)
    db.flush()
    return inst


def _seed_prices(db, inst_id: int, days: int = 100, base_price: float = 100.0):
    today = date.today()
    for i in range(days, 0, -1):
        d = today - timedelta(days=i)
        price = Price(
            instrument_id=inst_id,
            date=d,
            open=base_price + i * 0.1,
            high=base_price + i * 0.15,
            low=base_price + i * 0.05,
            close=base_price + i * 0.1,
            volume=1_000_000,
        )
        db.add(price)
    db.flush()


def _seed_dividend(db, inst_id: int, amount: float = 10.0, days_ago: int = 350):
    div = Dividend(
        instrument_id=inst_id,
        date=date.today() - timedelta(days=days_ago),
        amount=amount,
        currency="RUB",
    )
    db.add(div)
    db.flush()


def _seed_indicator(db, inst_id: int, rsi: float = 55.0, days_ago: int = 0, count: int = 2):
    for i in range(count):
        ind = Indicator(
            instrument_id=inst_id,
            date=date.today() - timedelta(days=days_ago + i),
            rsi=rsi,
            macd_line=0.5,
            macd_signal=0.3,
            macd_hist=0.2,
            sma_20=102.0,
            sma_50=98.0,
            sma_200=95.0,
        )
        db.add(ind)
    db.flush()


class TestAllocatorIntegration:
    """Integration tests for PortfolioAllocator with real DB."""

    def test_allocate_with_real_data(self, db_session):
        _clean_tables(db_session)
        from src.portfolio.allocator import PortfolioAllocator

        sber = _seed_instrument(db_session, "SBER", "stock", "Банки")
        lkoh = _seed_instrument(db_session, "LKOH", "stock", "Нефть и газ")
        fxrl = _seed_instrument(db_session, "FXRL", "etf", "ETF")
        _seed_prices(db_session, sber.id, days=100, base_price=100.0)
        _seed_prices(db_session, lkoh.id, days=100, base_price=60.0)
        _seed_prices(db_session, fxrl.id, days=100, base_price=120.0)
        _seed_dividend(db_session, sber.id)
        _seed_dividend(db_session, lkoh.id)
        db_session.commit()

        allocator = PortfolioAllocator()
        result = allocator.allocate(capital=1_000_000, db=db_session)

        assert result["capital"] == 1_000_000
        assert result["total_allocated"] > 0
        for cat_data in result["plan"].values():
            for item in cat_data["items"]:
                assert "risk" in item

    def test_allocate_zero_capital(self, db_session):
        _clean_tables(db_session)
        from src.portfolio.allocator import PortfolioAllocator

        allocator = PortfolioAllocator()
        result = allocator.allocate(capital=0, db=db_session)

        assert result["capital"] == 0
        assert result["total_allocated"] == 0
        assert all(len(cat["items"]) == 0 for cat in result["plan"].values())

    def test_recommend_returns_picks(self, db_session):
        _clean_tables(db_session)
        from src.portfolio.allocator import PortfolioAllocator

        sber = _seed_instrument(db_session, "SBER", "stock", "Банки")
        fxrl = _seed_instrument(db_session, "FXRL", "etf", "ETF")
        _seed_prices(db_session, sber.id)
        _seed_prices(db_session, fxrl.id)
        _seed_dividend(db_session, sber.id)
        db_session.commit()

        allocator = PortfolioAllocator()
        picks = allocator.recommend(capital=500_000, db=db_session)

        assert len(picks) > 0
        for pick in picks:
            assert "ticker" in pick
            assert "score" in pick
            assert pick["score"] > 0

    def test_allocator_portfolio_context(self, db_session):
        _clean_tables(db_session)
        from src.portfolio.allocator import PortfolioAllocator

        inst = _seed_instrument(db_session, "SBER", "stock", "Банки")
        _seed_prices(db_session, inst.id)
        db_session.add(PortModel(instrument_id=inst.id, quantity=10, avg_price=100.0))
        db_session.commit()

        allocator = PortfolioAllocator()
        ctx = allocator._get_current_portfolio(db_session)
        assert len(ctx) == 1
        assert ctx[0]["ticker"] == "SBER"


class TestSignalEngineIntegration:
    """Integration tests for signal generation pipeline."""

    def test_signal_fuse_returns_action(self, db_session):
        from src.signal.engine import SignalFusionEngine

        engine = SignalFusionEngine()
        result = engine.fuse(
            ticker="SBER",
            technical={"action": "BUY", "confidence": 0.7, "score": 0.5, "reasons": ["test"]},
            fundamental={"risk": 0.3},
            geo={"score": 3.0},
        )

        assert result is not None
        assert "action" in result
        assert "confidence" in result
        assert result["action"] in ("BUY", "CAUTIOUS_BUY", "HOLD", "SELL", "NEUTRAL")

    def test_signal_fuse_with_high_geo_risk(self, db_session):
        from src.signal.engine import SignalFusionEngine

        engine = SignalFusionEngine()
        result = engine.fuse(
            ticker="SBER",
            technical={"action": "BUY", "confidence": 0.9, "score": 0.8, "reasons": ["strong"]},
            geo={"score": 9.0},
        )

        assert result is not None
        assert result["action"] != "BUY" or result.get("downgraded")


class TestAnalysisServiceIntegration:
    """Integration tests for analysis pipeline."""

    def test_full_analysis_pipeline(self, db_session):
        _clean_tables(db_session)
        from src.analysis.service import analysis_service

        inst = _seed_instrument(db_session, "SBER", "stock", "Банки")
        _seed_prices(db_session, inst.id, days=200)
        _seed_indicator(db_session, inst.id)
        db_session.commit()

        result = analysis_service._analyze_single_sync(db_session, inst, "SBER", with_ml=False)

        assert result is not None
        assert result["ticker"] == "SBER"
        assert "action" in result

    def test_analysis_with_dividend_data(self, db_session):
        _clean_tables(db_session)
        from src.analysis.service import analysis_service

        inst = _seed_instrument(db_session, "LKOH", "stock", "Нефть и газ")
        _seed_prices(db_session, inst.id, days=200)
        _seed_indicator(db_session, inst.id)
        _seed_dividend(db_session, inst.id, amount=15.0, days_ago=350)
        db_session.commit()

        result = analysis_service._analyze_single_sync(db_session, inst, "LKOH", with_ml=False)

        assert result is not None
        assert result["ticker"] == "LKOH"
        assert result["confidence"] > 0
