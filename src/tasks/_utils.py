from __future__ import annotations

import asyncio
from typing import Any


def run_async(coro: Any) -> Any:
    return asyncio.run(coro)
