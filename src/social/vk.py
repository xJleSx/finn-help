from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from src.config import settings
from src.social.base import RawPost, SocialDataSource
from src.social.utils import clean_text, extract_tickers

logger = logging.getLogger(__name__)

VK_API_BASE = "https://api.vk.com/method/"


class VKAdapter(SocialDataSource):
    source_name = "vk"

    def __init__(self, group_ids: Optional[list[str]] = None, api_token: Optional[str] = None) -> None:
        self._api_token = api_token or settings.vk_api_token
        self._group_ids = group_ids or [g.strip() for g in settings.vk_group_ids.split(",") if g.strip()]
        self._api_version = settings.vk_api_version
        self._http = httpx.AsyncClient(timeout=30.0)

    async def fetch_posts(self, since: Optional[datetime] = None) -> list[RawPost]:
        if not self._api_token:
            logger.warning("VK API token not configured")
            return []
        posts: list[RawPost] = []
        for group_id in self._group_ids:
            try:
                batch = await self._fetch_group_posts(group_id, since)
                posts.extend(batch)
            except Exception as e:
                logger.warning("VK fetch failed for group %s: %s", group_id, e)
        return posts

    async def _fetch_group_posts(self, group_id: str, since: Optional[datetime] = None) -> list[RawPost]:
        params: dict[str, Any] = {
            "owner_id": f"-{group_id}" if group_id.isdigit() else group_id,
            "count": 100,
            "v": self._api_version,
            "access_token": self._api_token,
        }
        if since:
            params["start_time"] = int(since.timestamp())
        resp = await self._http.get(f"{VK_API_BASE}wall.get", params=params)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            logger.warning("VK API error for %s: %s", group_id, data["error"])
            return []
        items = data.get("response", {}).get("items", [])
        results = []
        for item in items:
            raw_dt = item.get("date")
            dt = datetime.fromtimestamp(raw_dt, tz=timezone.utc) if raw_dt else None
            text = clean_text(item.get("text", ""))
            if not text:
                continue
            post_id = item.get("id", 0)
            from_id = item.get("from_id", 0)
            owner_id = item.get("owner_id", 0)
            results.append(
                RawPost(
                    source=self.source_name,
                    external_id=f"vk_{owner_id}_{post_id}",
                    author_nick=str(from_id),
                    author_id=str(from_id),
                    text=text,
                    published_at=dt,
                    url=f"https://vk.com/wall{owner_id}_{post_id}",
                    tickers=extract_tickers(text),
                    raw=item,
                )
            )
        return results

    async def fetch_author_stats(self, author_nick: str) -> Optional[dict[str, Any]]:
        params: dict[str, Any] = {
            "user_ids": author_nick,
            "fields": "followers_count,counters",
            "v": self._api_version,
            "access_token": self._api_token,
        }
        try:
            resp = await self._http.get(f"{VK_API_BASE}users.get", params=params)
            resp.raise_for_status()
            data = resp.json()
            users = data.get("response", [])
            if users:
                user = users[0]
                return {
                    "followers_count": user.get("followers_count", 0),
                    "author_nick": author_nick,
                }
        except Exception as e:
            logger.debug("VK author stats failed for %s: %s", author_nick, e)
        return None

    async def close(self) -> None:
        await self._http.aclose()
