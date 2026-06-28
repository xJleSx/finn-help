"""Add exchange column to instruments table.

Run: uv run python scripts/migrate_exchange.py
"""

import sqlite3
import sys
from pathlib import Path


def migrate(db_path: str) -> None:
    p = Path(db_path)
    if not p.exists():
        print(f"Database not found: {db_path}")
        return
    conn = sqlite3.connect(str(p))
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(instruments)")
    cols = {row[1] for row in cursor.fetchall()}
    if "exchange" in cols:
        print("OK: column exchange already exists")
    else:
        cursor.execute("ALTER TABLE instruments ADD COLUMN exchange VARCHAR(20) DEFAULT 'MOEX'")
        conn.commit()
        print("OK: column exchange added")
    conn.close()


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "data/finn.db"
    migrate(path)
