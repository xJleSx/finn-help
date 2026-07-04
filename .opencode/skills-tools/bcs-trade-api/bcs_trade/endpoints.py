"""BCS backend URL map.

BCS exposes several BFF (Backend-for-Frontend) microservices behind
`be.broker.ru`. The public docs at <https://trade-api.bcs.ru/> list
only relative paths, so the BFF prefix has to be discovered. The
discovered working prefixes live here.

When the BCS team renames or adds a BFF, this is the only file to
update.
"""
from __future__ import annotations

from typing import Final

BASE_URL: Final = "https://be.broker.ru"
TOKEN_URL: Final = (
    "https://be.broker.ru/trade-api-keycloak/realms/tradeapi/protocol/openid-connect/token"
)

# BFF service roots.
PORTFOLIO_BFF: Final = f"{BASE_URL}/trade-api-bff-portfolio"
LIMIT_BFF: Final = f"{BASE_URL}/trade-api-bff-limit"
ORDERS_BFF: Final = f"{BASE_URL}/trade-api-bff-order-details"
OPERATIONS_BFF: Final = f"{BASE_URL}/trade-api-bff-operations"
TRADES_BFF: Final = f"{BASE_URL}/trade-api-bff-trade-details"
INFORMATION_BFF: Final = f"{BASE_URL}/trade-api-information-service"
MARKET_DATA_BFF: Final = f"{BASE_URL}/trade-api-market-data-connector"
MARGINAL_BFF: Final = f"{BASE_URL}/trade-api-bff-marginal-indicators"


# Endpoints we know to exist.
PORTFOLIO_URL: Final = f"{PORTFOLIO_BFF}/api/v1/portfolio"
LIMITS_URL: Final = f"{LIMIT_BFF}/api/v1/limits"
ORDERS_SEARCH_URL: Final = f"{ORDERS_BFF}/api/v1/orders/search"
ORDER_CANCEL_URL_TPL: Final = f"{OPERATIONS_BFF}/api/v1/orders/{{order_id}}/cancel"
ORDER_GET_URL_TPL: Final = f"{OPERATIONS_BFF}/api/v1/orders/{{order_id}}"
TRADES_SEARCH_URL: Final = f"{TRADES_BFF}/api/v1/trades/search"
INSTRUMENTS_BY_TICKERS_URL: Final = f"{INFORMATION_BFF}/api/v1/instruments/by-tickers"
INSTRUMENTS_BY_ISINS_URL: Final = f"{INFORMATION_BFF}/api/v1/instruments/by-isins"
INSTRUMENTS_BY_TYPE_URL: Final = f"{INFORMATION_BFF}/api/v1/instruments/by-type"
TRADING_SCHEDULE_URL: Final = f"{INFORMATION_BFF}/api/v1/trading-schedule/daily-schedule"
TRADING_STATUS_URL: Final = f"{INFORMATION_BFF}/api/v1/trading-schedule/status"
QUOTES_URL: Final = f"{MARKET_DATA_BFF}/api/v1/quotes"
CANDLES_URL: Final = f"{MARKET_DATA_BFF}/api/v1/candles-chart"
ORDER_BOOK_URL: Final = f"{MARKET_DATA_BFF}/api/v1/order-book"
DISCOUNTS_URL: Final = f"{MARGINAL_BFF}/api/v1/instruments-discounts"
