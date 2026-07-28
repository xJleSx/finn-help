import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


PERSONAL_CONFIG_PATH = Path(__file__).resolve().parents[1] / "data" / "personal_settings.yaml"


def load_personal_settings() -> dict[str, object]:
    path = PERSONAL_CONFIG_PATH
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning("Failed to load %s: %s", path, e)
    return {}


def get_personal_settings() -> dict[str, object]:
    return personal


class Settings(BaseSettings):
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    social_groq_model: str = "llama-3.1-8b-instant"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    jwt_secret: str = ""
    jwt_refresh_secret: str = ""
    jwt_expire_minutes: int = 15
    password_min_length: int = 8
    tinkoff_token: str = ""
    tinkoff_sandbox: bool = True
    database_url: str = "postgresql://finn@localhost:5432/finn"
    telegram_bot_token: str = ""
    telegram_proxy_url: str = ""
    telegram_allowed_ids: str = ""
    telegram_rate_limit_messages: int = 20
    telegram_rate_limit_period: int = 60
    telegram_anti_flood_cooldown: int = 5
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"
    cors_credentials: bool = True
    rate_limit_per_minute: int = 60
    ssl_tbank_verify: bool = True
    enable_trading: bool = False
    max_trades_per_day: int = 5
    metrics_token: str = ""
    vk_api_token: str = ""
    vk_api_version: str = "5.199"
    vk_group_ids: str = "26196417,2676,30574849"
    llm_social_enabled: bool = False
    newsapi_api_key: str = "demo"

    mlflow_tracking_uri: str = ""
    use_mock_data: bool = False

    tax_capital_gains_rate: float = 0.13
    tax_dividend_rate: float = 0.13
    tax_long_term_rate: float = 0.0
    tax_long_term_years: int = 3
    tax_free_threshold: float = 0.0

    margin_initial_pct: float = 0.25
    margin_maintenance_pct: float = 0.15
    margin_call_pct: float = 0.20
    margin_liquidation_pct: float = 0.10
    short_initial_margin_pct: float = 0.50
    short_maintenance_margin_pct: float = 0.30
    max_leverage: float = 3.0
    broker_interest_rate: float = 0.18

    aml_high_volume_rub: float = 1_000_000
    aml_structuring_threshold_rub: float = 600_000
    aml_max_daily_volume_rub: float = 10_000_000
    aml_pep_threshold_rub: float = 5_000_000

    compliance_position_limit_pct: float = 0.25
    compliance_sector_limit_pct: float = 0.40
    compliance_max_short_pct: float = 0.20
    compliance_min_capital_short: float = 500_000

    default_broker: str = "tbank"
    enable_short_selling: bool = False

    wolfram_app_id: str = ""
    wolfram_enabled: bool = True

    fm_api_token: str = ""
    moex_iss_url: str = "https://iss.moex.com/iss"
    cbr_url: str = "https://www.cbr.ru/scripts/XML_daily.asp"

    ml_n_estimators: int = 50
    ml_max_depth: int = 3
    ml_learning_rate: float = 0.1
    ml_lookahead: int = 5
    ml_threshold: float = 0.03
    ml_action_threshold: float = 0.55
    ml_min_train_rows: int = 30
    ml_min_predict_rows: int = 60
    ml_oos_acc_min: float = 0.52
    ml_gap_size: int = 20

    ml_impact_n_estimators: int = 100
    ml_impact_max_depth: int = 4
    ml_impact_learning_rate: float = 0.05
    ml_impact_min_train_samples: int = 50
    ml_impact_horizons: str = "1,3,5"
    ml_impact_days_back: int = 365

    ml_sentiment_n_estimators: int = 100
    ml_sentiment_max_depth: int = 4
    ml_sentiment_learning_rate: float = 0.05
    ml_sentiment_min_train_samples: int = 30
    ml_sentiment_horizons: str = "3,7"
    ml_sentiment_days_back: int = 365

    ml_hpo_enabled: bool = False
    ml_hpo_trials: int = 20
    ml_bootstrap_samples: int = 0

    ml_anomaly_volume_contamination: float = 0.1
    ml_anomaly_sentiment_contamination: float = 0.1
    ml_anomaly_autoencoder_contamination: float = 0.1
    ml_anomaly_window_sizes: str = "3,7,14,30"
    ml_anomaly_days_back: int = 365
    ml_anomaly_autoencoder_hidden_dim: int = 8
    ml_anomaly_autoencoder_epochs: int = 50
    ml_anomaly_autoencoder_lr: float = 0.001
    ml_anomaly_weight_volume: float = 0.25
    ml_anomaly_weight_sentiment: float = 0.25
    ml_anomaly_weight_source: float = 0.2
    ml_anomaly_weight_topic: float = 0.15
    ml_anomaly_weight_autoencoder: float = 0.15
    ml_anomaly_min_samples: int = 10
    ml_anomaly_source_min_freq: int = 3

    alert_critical_threshold: float = 0.8
    alert_high_threshold: float = 0.6
    alert_medium_threshold: float = 0.4
    alert_weight_anomaly: float = 0.35
    alert_weight_impact: float = 0.35
    alert_weight_portfolio: float = 0.2
    alert_weight_recency: float = 0.1
    alert_dedup_hours: int = 24
    alert_cooldown_minutes: int = 60
    alert_min_impact_abs: float = 0.005
    alert_max_alerts_per_run: int = 20

    redis_url: str = "redis://localhost:6379/0"
    redis_password: str = ""
    redis_socket_timeout: int = 2
    redis_socket_connect_timeout: int = 2
    redis_max_connections: int = 20

    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    db_pool_recycle: int = 3600
    db_pool_pre_ping: bool = True
    db_read_replica_url: str = ""

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_use_tls: bool = True

    encryption_key: str = ""
    sentry_dsn: str = ""
    sentry_environment: str = "production"
    lock_file_path: str = ""
    ml_prometheus_enabled: bool = True
    executor_max_workers: int = 4
    otlp_endpoint: str = "http://localhost:4317"

    oauth_google_client_id: str = ""
    oauth_google_client_secret: str = ""
    oauth_github_client_id: str = ""
    oauth_github_client_secret: str = ""
    oauth_yandex_client_id: str = ""
    oauth_yandex_client_secret: str = ""
    oauth_redirect_uri: str = "http://localhost:3000/auth/callback"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "forbid"}


settings = Settings()
personal = load_personal_settings()

if not os.environ.get("JWT_SECRET"):
    import logging as _logging
    _logging.warning(
        "JWT_SECRET is not set in environment. Authentication will use an empty secret — "
        "this is a SECURITY RISK. Set JWT_SECRET in .env. "
        "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(48))'"
    )

if not settings.encryption_key:
    import logging as _logging
    _logging.warning(
        "encryption_key is empty. Data at rest is NOT encrypted. "
        "Set a strong encryption_key (32+ chars) in .env."
    )
elif len(settings.encryption_key) < 16:
    import logging as _logging
    _logging.error(
        "encryption_key is too short (%d chars < 16). "
        "Data at rest is NOT encrypted securely. "
        "Set a strong encryption_key (32+ chars) in .env.",
        len(settings.encryption_key),
    )


# ── Static constants (merged from constants.py) ───────────────────────

MIN_PRICE_ROWS = 50
MIN_INDICATOR_ROWS = 2
MIN_TRAIN_PRICES = 60
MIN_PLAN_ROWS = 20
ANALYSIS_CONCURRENCY = 10
TRADE_PLAN_ATR_MULTIPLIER = 0.02

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

CACHE_TTL: int = 300
MAX_CACHE_SIZE: int = 100
COOLDOWN_SECONDS: int = 5

MACRO_THRESHOLDS: dict[str, dict[str, Any]] = {
    "brent": {"high": 80, "high_adj": 0.03, "low": 50, "low_adj": -0.05},
    "key_rate": {"high": 15, "high_adj": -0.05, "low": 7, "low_adj": 0.03},
    "cpi": {"high": 8, "high_adj": -0.04, "low": 4, "low_adj": 0.02},
    "ofz_10y": {"high": 12, "high_adj": -0.03, "low": 6, "low_adj": 0.02},
    "m2": {"high": 70000, "high_adj": 0.02, "low": 50000, "low_adj": -0.02},
    "imoex": {"high": 3500, "high_adj": 0.02, "low": 2500, "low_adj": -0.03},
}

MACRO_MAX_ADJUSTMENT: float = 0.10

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

NEWS_SENTIMENT_DAYS: int = 3
SOCIAL_SENTIMENT_WEIGHT: float = 0.6
NEWS_SENTIMENT_WEIGHT: float = 0.4

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

BROKER_NAMES: dict[str, str] = {
    "tbank": "Т-Банк (Тинькофф)",
    "openapi": "OpenAPI",
}

DEFAULT_HISTORY_DAYS: int = 365
DIVIDEND_CHECK_DAYS: int = 365
NEWS_MAX_PER_FEED: int = 5
NEWS_STALE_HOURS: int = 24

BOND_PORTFOLIO_RULES: dict[str, Any] = {
    "max_speculative_pct": 0.10,
    "min_gov_quasi_pct": 0.50,
    "default_recovery_months_limit": 6,
    "max_single_issuer_pct": 0.25,
    "small_portfolio_threshold": 50000,
    "small_portfolio_min_gov_pct": 0.70,
}

BOND_RATING_CATEGORIES: dict[str, list[str]] = {
    "investment_grade": ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-"],
    "speculative": ["BB+", "BB", "BB-", "B+", "B", "B-"],
    "default_risk": ["CCC+", "CCC", "CCC-", "CC", "C", "D"],
}

GOV_BOND_PREFIXES: list[str] = ["SU", "ОФЗ"]
QUASI_GOV_KEYWORDS: list[str] = [
    "рос", "ростех", "росатом", "ржд", "русгидро", "аэрофлот",
    "вэб", "дом.рф", "почта", "транснефть", "газпром",
]

LIQUIDITY_THRESHOLDS: dict[str, dict[str, float]] = {
    "ofz": {
        "value_min_high": 100_000_000,
        "value_min_medium": 20_000_000,
        "value_max_low": 500_000,
        "spread_max": 0.3,
        "trades_min": 20,
        "depth_min": 50,
        "amihud_max": 0.01,
    },
    "corporate_aaa": {
        "value_min_high": 50_000_000,
        "value_min_medium": 10_000_000,
        "value_max_low": 500_000,
        "spread_max": 0.5,
        "trades_min": 15,
        "depth_min": 30,
        "amihud_max": 0.05,
    },
    "corporate": {
        "value_min": 1_000_000,
        "spread_max": 1.0,
        "trades_min": 10,
        "depth_min": 10,
        "amihud_max": 0.1,
    },
}

SPREAD_REJECT_THRESHOLDS: dict[str, float] = {
    "ofz": 0.3,
    "aaa": 0.5,
    "a": 1.0,
    "speculative": 2.0,
}

BROKER_COMMISSION_CONFIG: dict[str, dict[str, Any]] = {
    "tbank": {"commission_pct": 0.025, "min_rub": 0, "monthly_fee": 0},
}
MOEX_EXCHANGE_FEE_PCT: float = 0.01

TAX_RATES: dict[str, float] = {
    "coupon_ndfl": settings.tax_dividend_rate,
    "capital_gains_ndfl": settings.tax_capital_gains_rate,
    "ldv_years": settings.tax_long_term_years,
}
TAX_ACCOUNT_TYPES: dict[str, dict[str, Any]] = {
    "broker": {"coupon_tax": settings.tax_dividend_rate, "capital_gains_tax": settings.tax_capital_gains_rate, "ldv_exempt": True},
    "iis3": {"coupon_tax": settings.tax_dividend_rate, "capital_gains_tax": settings.tax_capital_gains_rate, "ldv_exempt": True, "contribution_deduction_max": 52000},
}

MOEX_BOND_BOARDS: dict[str, str] = {
    "main": "TQOB",
    "corporate": "TQCB",
}

DEFAULT_PROBABILITY_BY_RATING: dict[str, float] = {
    "AAA": 0.999,
    "AA+": 0.997,
    "AA": 0.995,
    "AA-": 0.990,
    "A+": 0.985,
    "A": 0.975,
    "A-": 0.960,
    "BBB+": 0.930,
    "BBB": 0.900,
    "BBB-": 0.870,
    "BB+": 0.830,
    "BB": 0.800,
    "B+": 0.750,
    "B": 0.700,
    "B-": 0.650,
}

RECOVERY_RATE_DEFAULTS: dict[str, float] = {
    "with_state_support": 0.667,
    "without_state_support": 0.40,
    "secured": 0.65,
    "unsecured_2025": 0.35,
}

KELLY_SIZER_LIMITS: dict[str, Any] = {
    "small_portfolio_max_pct": 0.10,
    "large_portfolio_max_pct": 0.20,
    "kelly_cap_pct": 0.30,
    "max_speculative_positions_small": 1,
    "max_speculative_positions_large": 3,
}

REBALANCING_TRIGGERS: dict[str, Any] = {
    "key_rate_change_bps": 150,
    "price_change_pct": 15.0,
    "rating_notch_change": 1,
    "allocation_deviation_pct": 5.0,
    "quarterly_days": 90,
}

MACRO_SCENARIO_RULES: dict[str, Any] = {
    "default_surge_threshold": 5,
    "rate_cut_consecutive": 2,
    "rate_cut_min_bps": 100,
    "rate_hold_consecutive_for_stagnation": 2,
    "inflation_stagnation_threshold": 8.0,
}
