import logging
from contextlib import contextmanager
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, scoped_session, sessionmaker

from src.config import settings

logger = logging.getLogger(__name__)

# ── Async engine (PostgreSQL primary, SQLite fallback) ──────────────────────
_ASYNC_DB_URL: str = settings.database_url
if _ASYNC_DB_URL.startswith("sqlite:///"):
    _ASYNC_DB_URL = _ASYNC_DB_URL.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
elif _ASYNC_DB_URL.startswith("postgresql+asyncpg://"):
    pass
elif _ASYNC_DB_URL.startswith("postgresql://"):
    _ASYNC_DB_URL = _ASYNC_DB_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

async_engine = create_async_engine(
    _ASYNC_DB_URL,
    echo=False,
    pool_size=5 if "postgresql" in _ASYNC_DB_URL else 1,
    max_overflow=10 if "postgresql" in _ASYNC_DB_URL else 0,
    connect_args={"check_same_thread": False} if "sqlite" in _ASYNC_DB_URL else {},
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ── Sync engine (for CLI, scripts, tests) ───────────────────────────────────
DB_DIR = Path("data")
DB_DIR.mkdir(parents=True, exist_ok=True)

sync_engine = create_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
)


@event.listens_for(sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    if "sqlite" in settings.database_url:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SyncSessionLocal = scoped_session(sessionmaker(bind=sync_engine, expire_on_commit=False))


def get_session() -> Session:
    return SyncSessionLocal()


def close_session() -> None:
    SyncSessionLocal.remove()


@contextmanager
def session_scope():
    """Provide a transactional scope around a series of operations."""
    session = get_session()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    from alembic.config import Config

    from alembic import command

    alembic_cfg = Config(Path(__file__).resolve().parents[2] / "alembic.ini")
    command.upgrade(alembic_cfg, "head")
    logger.info("Database migrated to latest revision")
