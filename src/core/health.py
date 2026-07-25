"""Central health check registry for all FinAdvisor modules."""

from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

health_registry: dict[str, Callable[[], Coroutine[Any, Any, Any]]] = {}


def register_module_health(name: str) -> Callable:
    """Decorator to register an async health check function."""

    def decorator(fn: Callable[[], Coroutine[Any, Any, Any]]) -> Callable:
        health_registry[name] = fn
        return fn

    return decorator


@register_module_health("ml")
async def check_ml_health() -> dict[str, Any]:
    from src.analysis.ml_coordinator import ml_coordinator

    try:
        return {"status": "ok", "models_loaded": len(ml_coordinator._prophet_cache) + len(ml_coordinator._ensemble_cache)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_module_health("llm")
async def check_llm_health() -> dict[str, Any]:
    try:
        from src.config import settings
        from src.llm.router import llm

        if llm is None:
            return {"status": "not_configured"}
        has_key = bool(settings.groq_api_key)
        return {"status": "ok" if has_key else "not_configured", "configured": has_key}
    except Exception as e:
        return {"status": "error", "message": str(e)}


_telegram_bot: Any = None


@register_module_health("telegram")
async def check_telegram_health() -> dict[str, Any]:
    global _telegram_bot
    try:
        from src.config import settings

        if not settings.telegram_bot_token:
            return {"status": "not_configured"}
        import telegram

        if _telegram_bot is None:
            _telegram_bot = telegram.Bot(token=settings.telegram_bot_token)
        me = await _telegram_bot.get_me()
        return {"status": "ok", "username": me.username if me else "unknown"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_module_health("tbank")
async def check_tbank_health() -> dict[str, Any]:
    try:
        from src.config import settings

        if not settings.tinkoff_token:
            return {"status": "not_configured"}
        import asyncio

        from src.trading.brokers.tbank import TBankClient

        client = TBankClient(token=settings.tinkoff_token, sandbox=settings.tinkoff_sandbox)
        accounts = await asyncio.wait_for(
            asyncio.to_thread(client.get_accounts),
            timeout=5.0,
        )
        has_accounts = len(accounts) > 0 if accounts else False
        return {"status": "ok" if has_accounts else "no_accounts"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
