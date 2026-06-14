import sys

sys.path.insert(0, ".")

from datetime import datetime, timedelta

from src.db.connection import get_session
from src.db.models import Instrument, Portfolio, Transaction


def seed_portfolio():
    db = get_session()
    try:
        existing = db.query(Portfolio).count()
        if existing > 0:
            print(f"Portfolio already has {existing} positions, skipping seed")
            return

        positions = [
            ("SBER", 100, 287.50),
            ("GAZP", 50, 165.30),
            ("LKOH", 10, 7100.00),
        ]

        for ticker, qty, price in positions:
            inst = db.query(Instrument).filter_by(ticker=ticker).first()
            if not inst:
                print(f"  {ticker} not in DB, skipping")
                continue

            existing_pos = db.query(Portfolio).filter_by(instrument_id=inst.id).first()
            if existing_pos:
                print(f"  {ticker} already in portfolio")
                continue

            pos = Portfolio(
                instrument_id=inst.id,
                quantity=qty,
                avg_price=price,
            )
            db.add(pos)

            tx = Transaction(
                instrument_id=inst.id,
                type="buy",
                quantity=qty,
                price=price,
                date=datetime.now() - timedelta(days=30),
            )
            db.add(tx)
            print(f"  Added {ticker}: {qty} шт. × {price} ₽")

        db.commit()
        print("Portfolio seeded successfully")

        pos_count = db.query(Portfolio).count()
        total_value = 0
        for p in db.query(Portfolio).all():
            total_value += p.quantity * (p.avg_price or 0)
        print(f"Total: {pos_count} positions, ~{total_value:,.0f} ₽")

    finally:
        db.close()


if __name__ == "__main__":
    seed_portfolio()
