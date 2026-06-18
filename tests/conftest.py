"""Test configuration: in-memory SQLite for sync, async for API tests"""

from __future__ import annotations

import os
import tempfile
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base

# ── Sync fixtures (for unit tests) ──────────────────────────────────────────


@pytest.fixture(scope="session")
def in_memory_db():
    db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = db_file.name
    db_file.close()
    engine = create_engine(f"sqlite:///{db_path}", echo=False, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()
    try:
        os.unlink(db_path)
    except PermissionError:
        pass


@pytest.fixture
def db_session(in_memory_db):
    session_class = sessionmaker(bind=in_memory_db)
    session = session_class()
    try:
        yield session
    finally:
        session.close()


# ── Async fixtures (for API tests) ──────────────────────────────────────────


@pytest.fixture(scope="session")
def async_in_memory_db():
    db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = db_file.name
    db_file.close()
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
    )
    import asyncio

    loop = asyncio.new_event_loop()
    loop.run_until_complete(engine.run_sync(Base.metadata.create_all))
    yield engine
    loop.run_until_complete(engine.dispose())
    loop.close()
    try:
        os.unlink(db_path)
    except PermissionError:
        pass


@pytest.fixture
async def async_db_session(async_in_memory_db) -> AsyncGenerator[AsyncSession, None]:
    session_class = async_sessionmaker(bind=async_in_memory_db, class_=AsyncSession, expire_on_commit=False)
    async with session_class() as session:
        try:
            yield session
        finally:
            await session.close()


@pytest.fixture
async def async_client(async_in_memory_db) -> AsyncGenerator[AsyncClient, None]:
    """Create fresh async session per request (no commit/rollback at generator level)."""
    from src.interfaces.api.auth import get_db
    from src.interfaces.api.server import app

    session_class = async_sessionmaker(bind=async_in_memory_db, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_class() as session:
            yield session

    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


# ── Mock fixtures for edge-case tests ───────────────────────────────────────


class AsyncMagicMock(MagicMock):
    """MagicMock that supports async/await like AsyncMock."""

    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)

    def __await__(self):
        async def _():
            return self

        return _().__await__()


@pytest.fixture
def mock_db():
    m = AsyncMagicMock()
    m.execute = AsyncMock()
    m.execute.return_value = AsyncMagicMock()
    m.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)
    m.execute.return_value.scalars = MagicMock()
    m.execute.return_value.scalars.return_value.all = MagicMock(return_value=[])
    return m


@pytest.fixture
def mock_client(mock_db):
    from src.db.models import User
    from src.interfaces.api.auth import get_current_user, get_db, require_user
    from src.interfaces.api.server import app

    def override_get_db():
        yield mock_db

    mock_user = User(id=1, username="test", hashed_password="x", role="user", is_active=True, risk_profile="balanced")

    async def override_user():
        return mock_user

    async def override_anon():
        return None

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_anon
    app.dependency_overrides[require_user] = override_user

    from fastapi.testclient import TestClient

    yield TestClient(app)
    app.dependency_overrides.clear()


# ── Legacy sync client fixture ──────────────────────────────────────────────


@pytest.fixture
def client(db_session):
    from src.interfaces.api.server import app

    def override_get_db_sync():
        yield db_session

    app.dependency_overrides.clear()
    from src.interfaces.api.auth import get_db

    app.dependency_overrides[get_db] = override_get_db_sync

    from fastapi.testclient import TestClient

    yield TestClient(app)
    app.dependency_overrides.clear()
