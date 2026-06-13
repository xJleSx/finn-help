from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, scoped_session

from src.config import settings
from src.db.models import Base

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


def init_db():
    Base.metadata.create_all(bind=engine)
