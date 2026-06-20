import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, cast

import httpx

from src.social.base import RawPost, SocialDataSource
from src.social.utils import async_retry, clean_text, extract_tickers

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
PROFILE_URL = "https://www.tbank.ru/invest/social/profile/{}/"


def _parse_dt(iso_str: str | None) -> datetime | None:
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _extract_tramvai_state(html: str) -> dict[str, Any] | None:
    idx = html.find("__TRAMVAI_CHILD_STATE__")
    if idx == -1:
        return None
    start = html.find("{", idx)
    if start == -1:
        return None
    depth = 0
    end = start
    for i in range(start, min(start + 2_000_000, len(html))):
        if html[i] == "{":
            depth += 1
        elif html[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    try:
        result: Any = json.loads(html[start:end])
        return cast("dict[str, Any] | None", result)
    except json.JSONDecodeError:
        return None


def _find_social_store(state: dict[str, Any]) -> dict[str, Any] | None:
    for key, val in state.items():
        if "social" in key.lower():
            stores: Any = val.get("stores", {})
            return cast("dict[str, Any] | None", stores)
    return None


class PulseAdapter(SocialDataSource):
    source_name = "pulse"

    def __init__(self, authors: list[str]) -> None:
        self._authors = authors
        self._http = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=30,
        )

    @async_retry(max_attempts=3, base_delay=2.0)
    async def fetch_posts(self, since: datetime | None = None) -> list[RawPost]:
        all_posts: list[RawPost] = []
        for nick in self._authors:
            try:
                html = await self._fetch_profile_page(nick)
                if not html:
                    continue
                posts = self._parse_posts_from_html(nick, html)
                for post in posts:
                    post.text = clean_text(post.text)
                    post.tickers = extract_tickers(post.text)
                    all_posts.append(post)
                logger.info("Pulse: collected %d posts from @%s", len(posts), nick)
            except Exception as e:
                logger.error("Pulse: failed to fetch @%s: %s", nick, e)
        return all_posts

    async def _fetch_profile_page(self, nick: str) -> str | None:
        loop = asyncio.get_event_loop()
        url = PROFILE_URL.format(nick)
        try:
            resp = await loop.run_in_executor(None, lambda: self._http.get(url, follow_redirects=True))
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning("Pulse: profile @%s not found (404)", nick)
            else:
                logger.warning("Pulse: HTTP %d for @%s", e.response.status_code, nick)
            return None

    @async_retry(max_attempts=3, base_delay=2.0)
    async def fetch_author_stats(self, author_nick: str) -> dict[str, Any] | None:
        try:
            html = await self._fetch_profile_page(author_nick)
            if not html:
                return None
            state = _extract_tramvai_state(html)
            if not state:
                return None
            stores = _find_social_store(state)
            if not stores:
                return None
            raw_profiles: Any = stores.get("investSocialProfiles", {})
            return cast("dict[str, Any] | None", raw_profiles.get(author_nick))
        except Exception as e:
            logger.warning("Pulse: failed to fetch stats @%s: %s", author_nick, e)
            return None

    def _parse_posts_from_html(self, author_nick: str, html: str) -> list[RawPost]:
        state = _extract_tramvai_state(html)
        if not state:
            return []
        stores = _find_social_store(state)
        if not stores:
            return []
        posts_by_user = stores.get("investSocialPostsByProfile", {})
        raw_posts: list[RawPost] = []
        for key, val in posts_by_user.items():
            items = val.get("items", [])
            for item in items:
                post = self.normalize(item)
                post.author_nick = item.get("nickname") or author_nick
                raw_posts.append(post)
        return raw_posts

    def normalize(self, raw: dict[str, Any]) -> RawPost:
        content = raw.get("content", {}) or {}
        text = content.get("text") if isinstance(content, dict) else ""
        instruments = raw.get("instruments", []) or []
        tickers_from_instruments = [
            inst.get("ticker", "").upper()
            for inst in instruments
            if isinstance(inst, dict) and inst.get("ticker")
        ]
        return RawPost(
            source=self.source_name,
            external_id=str(raw.get("id", "")),
            author_nick=str(raw.get("nickname", "")),
            author_id=str(raw.get("profileId")),
            text=str(text or ""),
            published_at=_parse_dt(raw.get("inserted")),
            tickers=tickers_from_instruments,
            raw=raw,
        )

    async def close(self) -> None:
        self._http.close()
