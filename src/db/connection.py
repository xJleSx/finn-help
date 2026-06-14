import logging
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import scoped_session, sessionmaker

from src.config import settings
from src.db.models import Base

logger = logging.getLogger(__name__)

DB_DIR = Path(settings.database_url.replace("sqlite:///", "")).parent
DB_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    if "sqlite" in settings.database_url:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = scoped_session(sessionmaker(bind=engine))


def get_session():
    return SessionLocal()


def _add_missing_columns():
    inspector = inspect(engine)
    model_tables = Base.metadata.tables
    with engine.begin() as conn:
        for table_name, table in model_tables.items():
            if not inspector.has_table(table_name):
                continue
            existing = {c[1] for c in conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()}
            for col in table.columns:
                if col.name not in existing:
                    col_type = col.type
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type}"))
                    logger.info("Added missing column %s.%s (%s)", table_name, col.name, col_type)


def init_db():
    Base.metadata.create_all(bind=engine)
    _add_missing_columns()


init_db()
