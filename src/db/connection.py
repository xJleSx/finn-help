from __future__ import annotations

import logging
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, scoped_session, sessionmaker

from src.config import settings

logger = logging.getLogger(__name__)


def _is_postgres(url: str) -> bool:
    return "postgresql" in url


def _is_sqlite(url: str) -> bool:
    return "sqlite" in url


# ── Async engine (PostgreSQL primary) ────────────────────────────────────


def _build_async_url(url: str) -> str:
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


_ASYNC_DB_URL: str = _build_async_url(settings.database_url)
_is_pg = _is_postgres(_ASYNC_DB_URL)

async_engine = create_async_engine(
    _ASYNC_DB_URL,
    echo=False,
    pool_size=settings.db_pool_size if _is_pg else 1,
    max_overflow=settings.db_max_overflow if _is_pg else 0,
    pool_pre_ping=settings.db_pool_pre_ping,
    pool_recycle=settings.db_pool_recycle if _is_pg else -1,
    pool_timeout=settings.db_pool_timeout if _is_pg else 30,
    connect_args={"check_same_thread": False} if _is_sqlite(_ASYNC_DB_URL) else {},
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def get_async_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            logger.exception("Unhandled exception")
            await session.rollback()
            raise
        finally:
            await session.close()


# ── Read replica async engine (optional) ─────────────────────────────────

_read_replica_engine: Any = None
_ReadReplicaSessionLocal: Any = None


def _init_read_replica() -> bool:
    global _read_replica_engine, _ReadReplicaSessionLocal
    if _read_replica_engine is not None:
        return True
    replica_url = settings.db_read_replica_url
    if not replica_url:
        return False
    try:
        url = _build_async_url(replica_url)
        _read_replica_engine = create_async_engine(
            url,
            echo=False,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_pre_ping=True,
            pool_recycle=settings.db_pool_recycle,
        )
        _ReadReplicaSessionLocal = async_sessionmaker(
            bind=_read_replica_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        logger.info("Read replica engine initialized: %s", replica_url)
        return True
    except Exception as e:
        logger.warning("Failed to init read replica: %s", e)
        return False


@asynccontextmanager
async def get_read_replica_session() -> AsyncIterator[AsyncSession]:
    if _ReadReplicaSessionLocal is None and not _init_read_replica():
        async with get_async_session() as s:
            yield s
        return
    async with _ReadReplicaSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            logger.exception("Unhandled exception")
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
    pool_size=settings.db_pool_size if _is_postgres(settings.database_url) else 1,
    max_overflow=settings.db_max_overflow if _is_postgres(settings.database_url) else 0,
    pool_pre_ping=settings.db_pool_pre_ping,
    pool_recycle=settings.db_pool_recycle if _is_postgres(settings.database_url) else -1,
    pool_timeout=settings.db_pool_timeout if _is_postgres(settings.database_url) else 30,
    connect_args={"check_same_thread": False} if _is_sqlite(settings.database_url) else {},
)


@event.listens_for(sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
    if _is_sqlite(settings.database_url):
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
def session_scope() -> Any:
    """Provide a transactional scope around a series of operations."""
    session = get_session()
    try:
        yield session
    except Exception:
        logger.exception("Unhandled exception")
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


def close_db() -> None:
    """Close all database connections during shutdown."""
    try:
        from sqlalchemy.orm import close_all_sessions

        close_all_sessions()
        logger.info("All database sessions closed")
    except Exception as e:
        logger.warning("Failed to close database sessions: %s", e)
