import secrets
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()

_DEFAULT_JWT = secrets.token_urlsafe(48)


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


class Settings(BaseSettings):
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    social_groq_model: str = "llama-3.1-8b-instant"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    jwt_secret: str = _DEFAULT_JWT
    jwt_expire_minutes: int = 15
    password_min_length: int = 8
    tinkoff_token: str = ""
    tinkoff_sandbox: bool = True
    database_url: str = "postgresql://finn:finn@localhost:5432/finn"
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

    wolfram_app_id: str = ""
    wolfram_enabled: bool = True

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

    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    celery_task_always_eager: bool = False
    celery_worker_concurrency: int = 2
    celery_task_soft_time_limit: int = 300
    celery_task_hard_time_limit: int = 600

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_use_tls: bool = True

    sentry_dsn: str = ""
    sentry_environment: str = "production"
    lock_file_path: str = ""
    ml_prometheus_enabled: bool = True

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
personal = load_personal_settings()
