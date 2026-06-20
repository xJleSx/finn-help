import asyncio
import logging
import re
from functools import wraps
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

logger = logging.getLogger(__name__)


def async_retry(max_attempts: int = 3, base_delay: float = 1.0, backoff: float = 2.0) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception | None = None
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    if attempt < max_attempts - 1:
                        delay = base_delay * (backoff**attempt)
                        logger.warning(
                            "%s attempt %d/%d failed: %s, retry in %.1fs",
                            func.__name__,
                            attempt + 1,
                            max_attempts,
                            e,
                            delay,
                        )
                        await asyncio.sleep(delay)
            raise last_exc  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator


def clean_text(text: str, max_length: int = 2000) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"@\w+", "", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_length]


_KNOWN_TICKERS: set[str] | None = None


def _load_tickers() -> set[str]:
    global _KNOWN_TICKERS
    if _KNOWN_TICKERS is not None:
        return _KNOWN_TICKERS
    try:
        from src.db.connection import get_session
        from src.db.models import Instrument

        db = get_session()
        rows = db.query(Instrument.ticker).all()
        db.close()
        _KNOWN_TICKERS = {r[0].upper() for r in rows if r[0]}
    except Exception:
        _KNOWN_TICKERS = {"SBER", "GAZP", "LKOH", "YNDX", "TATN", "VTBR", "ROSN", "NVTK", "MOEX"}
    return _KNOWN_TICKERS


TICKER_PATTERN = re.compile(r"\b([A-ZА-Я]{2,5})\b")


def extract_tickers(text: str) -> list[str]:
    known = _load_tickers()
    candidates = set(TICKER_PATTERN.findall(text.upper()))
    return sorted(candidates & known)
