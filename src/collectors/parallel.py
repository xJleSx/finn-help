from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

from src.cache import get_redis

logger = logging.getLogger(__name__)

REDIS_QUEUE_KEY = "collector:queue"
REDIS_RESULT_KEY = "collector:result:{}"
TASK_TTL = 3600
POLL_INTERVAL = 0.5


@dataclass
class CollectorTask:
    ticker: str
    source: str
    task_type: str = "collect"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    retries: int = 0
    max_retries: int = 3


async def enqueue_collector_tasks(
    tickers: list[str],
    source: str,
    executor: Callable[[str], Coroutine[Any, Any, Any]],
) -> list[dict[str, Any]]:
    r = await get_redis()
    tasks = [CollectorTask(ticker=t, source=source) for t in tickers]
    for t in tasks:
        await r.lpush(REDIS_QUEUE_KEY, t.ticker)
    logger.info("Enqueued %d collector tasks for source=%s", len(tasks), source)

    workers = [asyncio.create_task(_worker(r, executor)) for _ in range(min(5, len(tasks)))]
    results: list[dict[str, Any]] = []
    for t in tasks:
        result = await _poll_result(r, t.ticker)
        results.append({"ticker": t.ticker, "source": source, **result})
    for _ in workers:
        await r.lpush(REDIS_QUEUE_KEY, b"")
    for w in workers:
        w.cancel()
        try:
            await w
        except asyncio.CancelledError:
            pass
    logger.info("Shut down %d collector workers", len(workers))
    return results


async def _worker(r: Any, executor: Callable[[str], Coroutine[Any, Any, Any]]) -> None:
    while True:
        ticker_bytes = await r.brpop(REDIS_QUEUE_KEY, timeout=5)
        if ticker_bytes is None:
            break
        _key, ticker = ticker_bytes
        ticker = ticker.decode()
        if not ticker:
            break
        try:
            data = await executor(ticker)
            await r.setex(
                REDIS_RESULT_KEY.format(f"{ticker}:done"),
                TASK_TTL,
                json.dumps(data, default=str),
            )
        except Exception as exc:
            logger.error("Worker failed for %s: %s", ticker, exc)
            await r.setex(
                REDIS_RESULT_KEY.format(f"{ticker}:error"),
                TASK_TTL,
                str(exc),
            )


async def _poll_result(r: Any, ticker: str, timeout: float = 120.0) -> dict[str, Any]:
    elapsed = 0.0
    while elapsed < timeout:
        done = await r.get(REDIS_RESULT_KEY.format(f"{ticker}:done"))
        if done:
            return {"status": "ok", "data": json.loads(done)}
        err = await r.get(REDIS_RESULT_KEY.format(f"{ticker}:error"))
        if err:
            return {"status": "error", "error": err.decode()}
        await asyncio.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
    return {"status": "timeout", "error": "No result within timeout"}
