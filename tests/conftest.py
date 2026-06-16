"""Test configuration: in-memory SQLite for sync, async for API tests"""

from __future__ import annotations

import os
import tempfile
from typing import AsyncGenerator

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
    from src.interfaces.api.server import app
    from src.interfaces.api.auth import get_db

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


# ── Legacy sync client fixture ──────────────────────────────────────────────

@pytest.fixture
def client(db_session):
    from src.interfaces.api.server import app

    def override_get_db_sync():
        from sqlalchemy.orm import Session
        yield db_session

    app.dependency_overrides.clear()
    from src.interfaces.api.auth import get_db
    app.dependency_overrides[get_db] = override_get_db_sync

    from fastapi.testclient import TestClient
    yield TestClient(app)
    app.dependency_overrides.clear()
