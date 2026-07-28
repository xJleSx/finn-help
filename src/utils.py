from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


def _safe_int(val: object) -> int | None:
    if val is None:
        return None
    try:
        return int(val)  # type: ignore[call-overload]
    except (ValueError, TypeError):
        return None


def _safe_float(val: object) -> float | None:
    if val is None:
        return None
    try:
        return float(val)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None


def clean_text(text: str, max_length: int = 2000) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"@\w+", "", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_length]
