"""Tests for API endpoints"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


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


class TestHealth:
    def test_health_returns_ok(self, mock_client, mock_db):
        resp = mock_client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestInstruments:
    def test_instruments_list(self, mock_client, mock_db):
        mock_db.execute.return_value.scalars.return_value.all.return_value = []
        resp = mock_client.get("/api/instruments")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_instrument_by_ticker_not_found(self, mock_client, mock_db):
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        resp = mock_client.get("/api/instruments/FAKE")
        assert resp.status_code == 404


class TestNews:
    def test_news_empty(self, mock_client, mock_db):
        mock_db.execute.return_value.scalars.return_value.all.return_value = []
        resp = mock_client.get("/api/news")
        assert resp.status_code == 200
        assert resp.json() == []


class TestPortfolio:
    def test_portfolio_empty(self, mock_client, mock_db):
        mock_db.execute.return_value.scalars.return_value.all.return_value = []
        resp = mock_client.get("/api/portfolio")
        assert resp.status_code == 200
        assert resp.json() == []


class TestGeoRisk:
    def test_geo_risk_empty(self, mock_client, mock_db):
        mock_db.execute.return_value.scalars.return_value.all.return_value = []
        resp = mock_client.get("/api/geo-risk")
        assert resp.status_code == 200
        assert resp.json() == []


class TestAllocate:
    def test_allocate_returns_dict(self, mock_client, mock_db):
        mock_db.execute.return_value.scalars.return_value.all.return_value = []
        resp = mock_client.post("/api/portfolio/allocate", json={"capital": 50000})
        assert resp.status_code == 200
