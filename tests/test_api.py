"""Tests for API endpoints"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def mock_client(mock_db):
    from src.interfaces.api.server import app, get_db

    def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestHealth:
    def test_health_returns_ok(self, mock_client, mock_db):
        resp = mock_client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestInstruments:
    def test_instruments_list(self, mock_client, mock_db):
        mock_db.query.return_value.order_by.return_value.all.return_value = []
        resp = mock_client.get("/api/instruments")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_instrument_by_ticker_not_found(self, mock_client, mock_db):
        mock_db.query.return_value.filter_by.return_value.first.return_value = None
        resp = mock_client.get("/api/instruments/FAKE")
        assert resp.status_code == 404


class TestNews:
    def test_news_empty(self, mock_client, mock_db):
        mock_db.query.return_value.order_by.return_value.limit.return_value.all.return_value = []
        resp = mock_client.get("/api/news")
        assert resp.status_code == 200
        assert resp.json() == []


class TestPortfolio:
    def test_portfolio_empty(self, mock_client, mock_db):
        mock_db.query.return_value.all.return_value = []
        resp = mock_client.get("/api/portfolio")
        assert resp.status_code == 200
        assert resp.json() == []


class TestGeoRisk:
    def test_geo_risk_empty(self, mock_client, mock_db):
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        resp = mock_client.get("/api/geo-risk")
        assert resp.status_code == 200
        assert resp.json() == []


class TestAllocate:
    def test_allocate_returns_dict(self, client):
        resp = client.post("/api/portfolio/allocate", json={"capital": 50000})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
