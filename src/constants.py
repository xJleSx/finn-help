from typing import Any

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

CACHE_TTL: int = 300
MAX_CACHE_SIZE: int = 100
COOLDOWN_SECONDS: int = 5

# ── Macro thresholds (signal/engine.py) ──────────────────────────────

MACRO_THRESHOLDS: dict[str, dict[str, Any]] = {
    "brent": {"high": 80, "high_adj": 0.03, "low": 50, "low_adj": -0.05},
    "key_rate": {"high": 15, "high_adj": -0.05, "low": 7, "low_adj": 0.03},
    "cpi": {"high": 8, "high_adj": -0.04, "low": 4, "low_adj": 0.02},
    "ofz_10y": {"high": 12, "high_adj": -0.03, "low": 6, "low_adj": 0.02},
    "m2": {"high": 70000, "high_adj": 0.02, "low": 50000, "low_adj": -0.02},
    "imoex": {"high": 3500, "high_adj": 0.02, "low": 2500, "low_adj": -0.03},
}

MACRO_MAX_ADJUSTMENT: float = 0.10

# ── Signal / position limits (signal/engine.py) ──────────────────────

BASE_POSITION_PCT: dict[str, int] = {
    "BUY": 50,
    "CAUTIOUS_BUY": 25,
    "HOLD": 10,
    "SELL": 5,
    "NEUTRAL": 10,
}

GEO_RISK_HIGH: float = 7.0
GEO_RISK_ELEVATED: float = 5.0
FUND_RISK_HIGH: float = 0.6

# ── Allocator thresholds (portfolio/allocator.py) ────────────────────

ALLOCATOR_CAPITAL_TIERS: list[dict[str, Any]] = [
    {"max_capital": 1000, "min_budget": 500, "max_positions": 1},
    {"max_capital": 3000, "min_budget": 1000, "max_positions": 2},
]

ALLOCATOR_SECTOR_LIMIT_MIN_CAPITAL: float = 10000

ALLOCATOR_LEFTOVER_THRESHOLD: float = 0.10
ALLOCATOR_LEFTOVER_MIN_ABS: float = 500
ALLOCATOR_RECOMMEND_MAX_PICKS: int = 15
ALLOCATOR_RECOMMEND_TIER_PICKS: list[dict[str, Any]] = [
    {"max_capital": 1000, "max_picks": 4},
    {"max_capital": 5000, "max_picks": 8},
]

# ── Sentiment / news thresholds (analysis/service.py, tasks.py) ──────

NEWS_SENTIMENT_DAYS: int = 3
SOCIAL_SENTIMENT_WEIGHT: float = 0.6
NEWS_SENTIMENT_WEIGHT: float = 0.4

# ── Default days for data collection ─────────────────────────────────

DEFAULT_HISTORY_DAYS: int = 365
DIVIDEND_CHECK_DAYS: int = 365
NEWS_MAX_PER_FEED: int = 5
NEWS_STALE_HOURS: int = 24
