"""Single shared logger configuration."""
from __future__ import annotations

import logging
import sys
from typing import Final

_NAME: Final = "financemarker"


def setup(level: str | None = None) -> logging.Logger:
    logger = logging.getLogger(_NAME)
    if not logger.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-5s %(name)s: %(message)s")
        )
        logger.addHandler(h)
    logger.setLevel((level or "INFO").upper())
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(_NAME)
