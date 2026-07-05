from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Any, Callable

logger = logging.getLogger(__name__)

_shutdown_tasks: list[Callable[[], Any]] = []


def register_shutdown_hook(fn: Callable[[], Any]) -> None:
    _shutdown_tasks.append(fn)


def _run_hooks() -> None:
    for fn in _shutdown_tasks:
        try:
            fn()
        except Exception as e:
            logger.warning("Shutdown hook %s failed: %s", fn.__name__, e)


def _signal_handler(sig: int, _frame: Any) -> None:
    sig_name = signal.Signals(sig).name
    logger.info("Received %s, shutting down...", sig_name)
    _run_hooks()
    logger.info("Shutdown complete")
    sys.exit(0)


def setup_signal_handlers() -> None:
    if sys.platform == "win32":
        return
    loop = asyncio.get_running_loop()
    for s in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(s, lambda s=s: _signal_handler(s, None))
        except NotImplementedError:
            signal.signal(s, _signal_handler)
