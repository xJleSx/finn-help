import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class AsyncRateLimiter:
    def __init__(self, calls_per_minute: int = 25) -> None:
        self._min_interval = 60.0 / max(calls_per_minute, 1)
        self._last_call: float = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last_call)
            if wait > 0:
                logger.debug("Rate limiter: waiting %.2fs", wait)
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()


class GroqRetryHandler:
    def __init__(self, max_retries: int = 3, base_delay: float = 2.0) -> None:
        self._max_retries = max_retries
        self._base_delay = base_delay

    async def execute(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                return await fn(*args, **kwargs)
            except Exception as e:
                last_exc = e
                error_str = str(e).lower()
                is_rate_limit = "429" in error_str or "rate_limit" in error_str or "too many" in error_str
                if attempt < self._max_retries and is_rate_limit:
                    delay = self._base_delay * (2**attempt) + (hash(str(time.time())) % 100) / 100.0
                    logger.warning(
                        "Groq rate limited (attempt %d/%d), retrying in %.1fs",
                        attempt + 1,
                        self._max_retries,
                        delay,
                    )
                    await asyncio.sleep(delay)
                elif attempt < self._max_retries:
                    delay = self._base_delay * (1.5**attempt)
                    await asyncio.sleep(delay)
                else:
                    raise
        raise last_exc  # type: ignore[misc]


_rate_limiter = AsyncRateLimiter(calls_per_minute=25)
_retry_handler = GroqRetryHandler()


async def throttled_groq_call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    await _rate_limiter.acquire()
    return await _retry_handler.execute(fn, *args, **kwargs)
