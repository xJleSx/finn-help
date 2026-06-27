from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class RawPost:
    source: str
    external_id: str
    author_nick: str
    author_id: str | None = None
    text: str = ""
    published_at: datetime | None = None
    url: str | None = None
    tickers: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class SocialDataSource(ABC):
    source_name: str = ""

    @abstractmethod
    async def fetch_posts(self, since: datetime | None = None) -> list[RawPost]: ...

    @abstractmethod
    async def fetch_author_stats(self, author_nick: str) -> dict[str, Any] | None: ...

    def normalize(self, raw: dict[str, Any]) -> RawPost:
        return RawPost(
            source=self.source_name,
            external_id=str(raw.get("id", "")),
            author_nick=str(raw.get("author", {}).get("nick", "")),
            author_id=str(raw.get("author", {}).get("id")),
            text=str(raw.get("text", "")),
            published_at=raw.get("published_at"),
            url=raw.get("url"),
            tickers=[],
            raw=raw,
        )
