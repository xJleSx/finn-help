import logging
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import scoped_session, sessionmaker

from src.config import settings

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


def close_session():
    SessionLocal.remove()


def init_db():
    from pathlib import Path

    from alembic.config import Config

    from alembic import command

    alembic_cfg = Config(Path(__file__).resolve().parents[2] / "alembic.ini")
    command.upgrade(alembic_cfg, "head")
    logger.info("Database migrated to latest revision")
