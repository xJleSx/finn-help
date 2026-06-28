from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class KASECollector:
    BASE = "https://kase.kz/api"

    def __init__(self) -> None:
        self._base_url = self.BASE

    async def get_securities(self) -> list[dict[str, Any]]:
        raise NotImplementedError(
            "KASE API integration - implement when API access is available"
        )

    async def get_prices(self, ticker: str) -> list[dict[str, Any]]:
        raise NotImplementedError(
            "KASE API integration - implement when API access is available"
        )

    async def update_instruments(self, db: Any) -> None:
        raise NotImplementedError(
            "KASE API integration - implement when API access is available"
        )
