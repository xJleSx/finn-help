"""FinanceMarker API endpoint map.

Single source of truth for paths used by the CLI. Update here when
the API evolves.
"""
from __future__ import annotations

from typing import Final

# Token / quota
TOKEN_INFO: Final = "/token_info"

# Reference data
EXCHANGES: Final = "/exchanges"
OPERATION_METRICS: Final = "/operation_metrics"

# Stocks
STOCKS: Final = "/stocks"
STOCK: Final = "/stocks/{exchange}:{code}"  # .format(exchange=..., code=...)

# Events & ideas
DIVIDENDS: Final = "/dividends"
CALENDAR: Final = "/calendar"
IDEAS: Final = "/ideas"
IDEA_DETAIL: Final = "/ideas/{id}"  # .format(id=...)
INSIDERS: Final = "/insider_transactions"
EXPERTS: Final = "/experts"
DISCLOSURE: Final = "/disclosure"
