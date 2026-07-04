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
        len(ml_coordinator._prophet_cache) > 0 or len(ml_coordinator._ensemble_cache) > 0
        return {"status": "ok", "models_loaded": len(ml_coordinator._prophet_cache) + len(ml_coordinator._ensemble_cache)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_module_health("llm")
async def check_llm_health() -> dict[str, Any]:
    try:
        from src.llm.router import llm
        if llm is None:
            return {"status": "not_configured"}
        # Quick ping via a minimal completion
        result = await llm.ask("respond with just: ok", system_prompt="")
        is_ok = isinstance(result, str) and "ok" in result.lower()
        return {"status": "ok" if is_ok else "degraded"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_module_health("telegram")
async def check_telegram_health() -> dict[str, Any]:
    try:
        from src.config import settings
        if not settings.telegram_bot_token:
            return {"status": "not_configured"}
        import telegram
        bot = telegram.Bot(token=settings.telegram_bot_token)
        me = await bot.get_me()
        return {"status": "ok", "username": me.username if me else "unknown"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_module_health("tbank")
async def check_tbank_health() -> dict[str, Any]:
    try:
        from src.config import settings
        if not settings.tinkoff_token:
            return {"status": "not_configured"}
        from src.trading.brokers.tbank import TBankClient
        client = TBankClient(token=settings.tinkoff_token, sandbox=settings.tinkoff_sandbox)
        accounts = client.get_accounts()
        has_accounts = len(accounts) > 0 if accounts else False
        return {"status": "ok" if has_accounts else "no_accounts"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
