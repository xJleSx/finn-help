from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

from src.social.vk import VKAdapter


@pytest.fixture
def adapter():
    return VKAdapter(group_ids=["26196417"], api_token="test_token")


@pytest.mark.asyncio
async def test_fetch_posts_no_token():
    a = VKAdapter(group_ids=["1"], api_token="")
    posts = await a.fetch_posts()
    assert posts == []


@pytest.mark.asyncio
async def test_fetch_posts_api_error(adapter):
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.raise_for_status.side_effect = Exception("API error")
    adapter._http.get = AsyncMock(return_value=mock_resp)
    posts = await adapter.fetch_posts()
    assert posts == []


@pytest.mark.asyncio
async def test_fetch_posts_api_response_error(adapter):
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"error": {"error_msg": "access denied"}}
    adapter._http.get = AsyncMock(return_value=mock_resp)
    posts = await adapter.fetch_posts()
    assert posts == []


@pytest.mark.asyncio
async def test_fetch_posts_success(adapter):
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "response": {
            "items": [
                {
                    "id": 101,
                    "from_id": 123,
                    "owner_id": -26196417,
                    "date": 1700000000,
                    "text": "SBER акции растут",
                }
            ]
        }
    }
    adapter._http.get = AsyncMock(return_value=mock_resp)
    posts = await adapter.fetch_posts()
    assert len(posts) == 1
    p = posts[0]
    assert p.source == "vk"
    assert "SBER" in str(p.tickers)
    assert "акции растут" in p.text
    assert p.url == "https://vk.com/wall-26196417_101"


@pytest.mark.asyncio
async def test_fetch_posts_skips_empty_text(adapter):
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "response": {
            "items": [
                {"id": 1, "from_id": 0, "owner_id": -1, "date": 1700000000, "text": ""},
            ]
        }
    }
    adapter._http.get = AsyncMock(return_value=mock_resp)
    posts = await adapter.fetch_posts()
    assert len(posts) == 0


@pytest.mark.asyncio
async def test_fetch_author_stats(adapter):
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "response": [{"id": 123, "followers_count": 500}]
    }
    adapter._http.get = AsyncMock(return_value=mock_resp)
    stats = await adapter.fetch_author_stats("123")
    assert stats is not None
    assert stats["followers_count"] == 500


@pytest.mark.asyncio
async def test_fetch_author_stats_no_response(adapter):
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"response": []}
    adapter._http.get = AsyncMock(return_value=mock_resp)
    stats = await adapter.fetch_author_stats("999")
    assert stats is None


@pytest.mark.asyncio
async def test_close(adapter):
    adapter._http.aclose = AsyncMock()
    await adapter.close()
    adapter._http.aclose.assert_awaited_once()
