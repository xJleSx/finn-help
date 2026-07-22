from __future__ import annotations

import asyncio
from typing import Any


def run_async(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
