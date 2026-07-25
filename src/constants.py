from typing import Any

MIN_PRICE_ROWS = 50  # min rows for price analysis
MIN_INDICATOR_ROWS = 2  # min rows for indicator calculation
MIN_TRAIN_PRICES = 60  # min price points for ML training
MIN_PLAN_ROWS = 20  # min rows for trade plan generation
ANALYSIS_CONCURRENCY = 10  # parallel analysis tasks
TRADE_PLAN_ATR_MULTIPLIER = 0.02  # ATR multiplier for stop-loss in trade plans

# WARNING: Hardcoded list — will go stale. Update periodically from MOEX data source.
# See collectors/dividend.py for the refresh mechanism.
KNOWN_DIVIDEND_STOCKS: dict[str, str] = {
    "SBER": "dividend",
    "GAZP": "dividend",
    "LKOH": "dividend",
    "VTBR": "dividend",
    "MOEX": "growth",
    "NLMK": "dividend",
    "MGNT": "dividend",
    "MTSS": "dividend",
    "SNGS": "dividend",
    "SNGSP": "dividend",
    "TATN": "dividend",
    "RTKM": "dividend",
    "PHOR": "dividend",
    "AFKS": "growth",
}

# TODO: i18n — Russian sector/risk labels below need translation
SECTOR_NAME_MAP: dict[str, str] = {
    "Банки": "banking",
    "Нефть": "energy",
    "Нефть и газ": "energy",
    "IT": "tech",
    "Металлы": "metals",
    "Телеком": "telecom",
    "Энергетика": "utilities",
    "Транспорт": "transport",
    "Потребтовары": "retail",
    "Потреб": "retail",
    "Строительство": "construction",
    "Химия": "chemicals",
    "Машиностроение": "manufacturing",
    "Медицина": "healthcare",
    "Финансы": "banking",
    "Оборона": "defense",
    "Сельское хозяйство": "agriculture",
    "Недвижимость": "real_estate",
}

SECTOR_NAMES: dict[str, str] = {
    "SBER": "Банки",
    "GAZP": "Нефть и газ",
    "LKOH": "Нефть и газ",
    "VTBR": "Банки",
    "MOEX": "Финансы",
}

SAFE_ETFS: list[str] = [
    "FXRL",
    "SBMX",
    "TMOS",
    "AKIM",
    "RUSB",
    "TRUR",
]

SAFE_BONDS: list[str] = [
    "SU26238RMFS5",
    "SU26243RMFS2",
    "SU26248RMFS1",
]

# Source of truth: compliance_sector_limit_pct in settings (config.py:89)
# This dict maps sector → override limits; leave empty to rely on settings only
SECTOR_LIMITS: dict[str, float] = {
    "Нефть и газ": 0.35,
    "Банки": 0.25,
    "Финансы": 0.20,
    "Металлы": 0.20,
    "Телеком": 0.15,
    "IT": 0.15,
    "Потреб": 0.20,
}

RISK_PROFILES: dict[str, dict[str, Any]] = {
    "conservative": {
        "label": "Консервативный",
        "weights": {"technical": 0.30, "fundamental": 0.25, "geo": 0.20, "ml": 0.08, "sentiment": 0.07, "mtf": 0.10},
        "max_position_pct": 10,
        "min_confidence": 0.4,
        "geo_threshold": 6.0,
        "description": "Низкий риск, приоритет фундаментального анализа и геополитики",
    },
    "balanced": {
        "label": "Умеренный",
        "weights": {"technical": 0.35, "fundamental": 0.18, "geo": 0.17, "ml": 0.13, "sentiment": 0.12, "mtf": 0.05},
        "max_position_pct": 20,
        "min_confidence": 0.3,
        "geo_threshold": 7.0,
        "description": "Сбалансированный риск, стандартные веса",
    },
    "aggressive": {
        "label": "Агрессивный",
        "weights": {"technical": 0.40, "fundamental": 0.10, "geo": 0.10, "ml": 0.20, "sentiment": 0.15, "mtf": 0.05},
        "max_position_pct": 35,
        "min_confidence": 0.2,
        "geo_threshold": 8.0,
        "description": "Высокий риск, упор на технический и ML анализ",
    },
}

ACTION_EMOJI: dict[str, str] = {
    "BUY": "\U0001f7e2",
    "CAUTIOUS_BUY": "\U0001f7e1",
    "HOLD": "\u26aa",
    "SELL": "\U0001f534",
    "NEUTRAL": "\u26aa",
}

CACHE_TTL: int = 300  # default cache TTL in seconds
MAX_CACHE_SIZE: int = 100  # max entries in memory cache
COOLDOWN_SECONDS: int = 5  # cooldown between repeated operations

# ── Macro thresholds (signal/engine.py) ──────────────────────────────

MACRO_THRESHOLDS: dict[str, dict[str, Any]] = {
    "brent": {"high": 80, "high_adj": 0.03, "low": 50, "low_adj": -0.05},
    "key_rate": {"high": 15, "high_adj": -0.05, "low": 7, "low_adj": 0.03},
    "cpi": {"high": 8, "high_adj": -0.04, "low": 4, "low_adj": 0.02},
    "ofz_10y": {"high": 12, "high_adj": -0.03, "low": 6, "low_adj": 0.02},
    "m2": {"high": 70000, "high_adj": 0.02, "low": 50000, "low_adj": -0.02},
    "imoex": {"high": 3500, "high_adj": 0.02, "low": 2500, "low_adj": -0.03},
}

MACRO_MAX_ADJUSTMENT: float = 0.10  # cap on macro-driven signal adjustment

# ── Signal / position limits (signal/engine.py) ──────────────────────

BASE_POSITION_PCT: dict[str, int] = {
    "BUY": 50,
    "CAUTIOUS_BUY": 25,
    "HOLD": 10,
    "SELL": 5,
    "NEUTRAL": 10,
}

GEO_RISK_HIGH: float = 7.0  # threshold for high geopolitical risk score
GEO_RISK_ELEVATED: float = 5.0  # threshold for elevated geopolitical risk
FUND_RISK_HIGH: float = 0.6  # threshold for high fundamental risk

# ── Allocator thresholds (portfolio/allocator.py) ────────────────────

ALLOCATOR_CAPITAL_TIERS: list[dict[str, Any]] = [
    {"max_capital": 1000, "min_budget": 500, "max_positions": 1},
    {"max_capital": 3000, "min_budget": 1000, "max_positions": 2},
]

ALLOCATOR_SECTOR_LIMIT_MIN_CAPITAL: float = 10000  # min capital to enforce sector limits

ALLOCATOR_LEFTOVER_THRESHOLD: float = 0.10  # max fraction of capital left unallocated
ALLOCATOR_LEFTOVER_MIN_ABS: float = 500  # min leftover in RUB before forcing allocation
ALLOCATOR_RECOMMEND_MAX_PICKS: int = 15  # max tickers in recommendation output
ALLOCATOR_RECOMMEND_TIER_PICKS: list[dict[str, Any]] = [
    {"max_capital": 1000, "max_picks": 4},
    {"max_capital": 5000, "max_picks": 8},
]

# ── Sentiment / news thresholds (analysis/service.py, tasks.py) ──────

NEWS_SENTIMENT_DAYS: int = 3  # lookback window for news sentiment
SOCIAL_SENTIMENT_WEIGHT: float = 0.6  # weight of social sentiment in composite
NEWS_SENTIMENT_WEIGHT: float = 0.4  # weight of news sentiment in composite

# ── Phase 10: Advanced Trading & Compliance ──────────────────────────

ORDER_TYPE_LABELS: dict[str, str] = {
    "market": "Рыночная",
    "limit": "Лимитная",
    "ioc": "IOC (Immediate-or-Cancel)",
    "fok": "FOK (Fill-or-Kill)",
}

TIME_IN_FORCE_LABELS: dict[str, str] = {
    "day": "Дневная",
    "gtc": "GTC (до отмены)",
    "ioc": "IOC",
    "fok": "FOK",
}

MARGIN_STATUS_LABELS: dict[str, str] = {
    "safe": "Безопасно",
    "warning": "Внимание",
    "margin_call": "Margin Call",
    "liquidation": "Принудительное закрытие",
}

SHORT_BORROW_RATES: dict[str, float] = {
    "SBER": 0.15,
    "GAZP": 0.20,
    "LKOH": 0.12,
    "VTBR": 0.25,
}

SHORT_RESTRICTED_TICKERS: list[str] = []

AML_SUSPICIOUS_PATTERNS: list[str] = [
    "round_trip",
    "structuring",
    "velocity_anomaly",
    "high_volume",
    "pep_volume",
]

TAX_RUB_DIVIDEND_RATE: float = 0.13
TAX_RUB_CAPITAL_GAINS_RATE: float = 0.13
TAX_RUB_LONG_TERM_RATE: float = 0.0
TAX_RUB_LONG_TERM_DAYS: int = 1095
TAX_RUB_BROKER_COMMISSION_PCT: float = 0.0004

BROKER_NAMES: dict[str, str] = {
    "tbank": "Т-Банк (Тинькофф)",
    "alor": "Алор",
    "finam": "Финам",
    "openapi": "OpenAPI",
}

# ── Default days for data collection ─────────────────────────────────

DEFAULT_HISTORY_DAYS: int = 365  # default price history lookback
DIVIDEND_CHECK_DAYS: int = 365  # lookback for dividend data collection
NEWS_MAX_PER_FEED: int = 5  # max news articles per feed source
NEWS_STALE_HOURS: int = 24  # hours after which news is considered stale
