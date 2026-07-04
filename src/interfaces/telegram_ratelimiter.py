from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict

from src.config import settings

logger = logging.getLogger(__name__)


class TokenBucket:
    """Token bucket rate limiter for per-user or per-chat rate limiting."""

    def __init__(self, rate: int = 20, period: float = 60.0, burst: int | None = None) -> None:
        self.rate = rate
        self.period = period
        self.tokens_per_sec = rate / period if period > 0 else 1.0
        self.burst = burst or rate
        self._tokens: dict[int | str, float] = defaultdict(lambda: float(self.burst))
        self._last_refill: dict[int | str, float] = defaultdict(time.monotonic)
        self._lock = asyncio.Lock()

    async def acquire(self, key: int | str, tokens: float = 1.0) -> float:
        """Acquire tokens, returning the wait time in seconds (0 if immediate)."""
        async with self._lock:
            now = time.monotonic()
            last = self._last_refill.get(key, now)
            elapsed = now - last
            self._tokens[key] = min(self.burst, self._tokens.get(key, float(self.burst)) + elapsed * self.tokens_per_sec)
            self._last_refill[key] = now

            if self._tokens[key] >= tokens:
                self._tokens[key] -= tokens
                return 0.0

            deficit = tokens - self._tokens[key]
            wait = deficit / self.tokens_per_sec if self.tokens_per_sec > 0 else self.period
            return wait

    async def wait_and_acquire(self, key: int | str, tokens: float = 1.0) -> None:
        wait = await self.acquire(key, tokens)
        if wait > 0:
            logger.debug("Rate limit hit for %s, waiting %.2fs", key, wait)
            await asyncio.sleep(wait)
            async with self._lock:
                self._tokens[key] -= tokens

    @property
    def is_limited(self) -> bool:
        return self.rate > 0


# Global rate limiter instances
user_limiter = TokenBucket(
    rate=settings.telegram_rate_limit_messages,
    period=float(settings.telegram_rate_limit_period),
)
chat_limiter = TokenBucket(
    rate=settings.telegram_rate_limit_messages * 2,
    period=float(settings.telegram_rate_limit_period),
)
