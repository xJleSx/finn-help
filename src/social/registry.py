import logging
from typing import Any

from src.config import personal
from src.social.base import SocialDataSource

logger = logging.getLogger(__name__)


class SocialRegistry:
    def __init__(self) -> None:
        self._sources: dict[str, SocialDataSource] = {}

    def register(self, source: SocialDataSource) -> None:
        self._sources[source.source_name] = source
        logger.info("Social source registered: %s", source.source_name)

    def get(self, name: str) -> SocialDataSource | None:
        return self._sources.get(name)

    def get_active(self) -> list[SocialDataSource]:
        cfg: dict[str, Any] = personal.get("social_sources", {})  # type: ignore[assignment]
        return [s for name, s in self._sources.items() if cfg.get(name, {}).get("enabled", False)]

    def build_from_config(self) -> None:
        cfg: dict[str, Any] = personal.get("social_sources", {})  # type: ignore[assignment]
        pulse_cfg = cfg.get("pulse", {})
        if pulse_cfg.get("enabled") and pulse_cfg.get("authors"):
            from src.social.pulse import PulseAdapter

            self.register(PulseAdapter(authors=pulse_cfg["authors"]))


registry = SocialRegistry()
