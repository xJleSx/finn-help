from __future__ import annotations

import asyncio
import logging
import signal
import sys
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)

_shutdown_tasks: list[Callable[[], Any]] = []
_hooks_lock = threading.Lock()


def register_shutdown_hook(fn: Callable[[], Any]) -> None:
    with _hooks_lock:
        _shutdown_tasks.append(fn)


def _run_hooks() -> None:
    with _hooks_lock:
        hooks = list(_shutdown_tasks)
    async_hooks: list[Any] = []
    for fn in hooks:
        try:
            if asyncio.iscoroutinefunction(fn):
                async_hooks.append(fn())
            else:
                fn()
        except Exception as e:
            logger.warning("Shutdown hook %s failed: %s", fn.__name__, e)
    if async_hooks:
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.run_until_complete(asyncio.gather(*async_hooks, return_exceptions=True))
        except RuntimeError:
            logger.warning("No running loop for async shutdown hooks")


def _signal_handler(sig: int, _frame: Any) -> None:
    sig_name = signal.Signals(sig).name
    logger.info("Received %s, shutting down...", sig_name)
    _run_hooks()
    logger.info("Shutdown complete")
    try:
        loop = asyncio.get_running_loop()
        loop.call_soon_threadsafe(loop.stop)
    except RuntimeError:
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
