import logging
import re

from src.notifications.retry import retry_async  # noqa: F401
from src.utils import clean_text  # noqa: F401

logger = logging.getLogger(__name__)

_KNOWN_TICKERS: set[str] | None = None
_FALLBACK_TICKERS = {"SBER", "GAZP", "LKOH", "YNDX", "TATN", "VTBR", "ROSN", "NVTK", "MOEX"}


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
        _KNOWN_TICKERS = {r[0].upper() for r in rows if r[0]} | _FALLBACK_TICKERS
    except Exception:
        logger.debug("Could not load tickers from DB, using fallback set")
        _KNOWN_TICKERS = _FALLBACK_TICKERS
    return _KNOWN_TICKERS


TICKER_PATTERN = re.compile(r"\b([A-ZА-Я]{2,5})\b")


def extract_tickers(text: str) -> list[str]:
    known = _load_tickers()
    candidates = set(TICKER_PATTERN.findall(text.upper()))
    return sorted(candidates & known)
