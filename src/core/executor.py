from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from src.config import settings

logger = logging.getLogger(__name__)

_executor: ThreadPoolExecutor | None = None


def get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=settings.executor_max_workers,
            thread_name_prefix="cpuworker",
        )
        logger.info("Created ThreadPoolExecutor with max_workers=%d", settings.executor_max_workers)
    return _executor


async def run_cpu_bound(fn, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(get_executor(), fn, *args)


def shutdown_executor() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=True)
        _executor = None
        logger.info("ThreadPoolExecutor shut down")
