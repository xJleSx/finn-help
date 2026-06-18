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

RISK_PROFILES: dict[str, dict] = {
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
