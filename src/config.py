from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings
import yaml

load_dotenv()


PERSONAL_CONFIG_PATH = Path(__file__).resolve().parents[1] / "data" / "personal_settings.yaml"


def load_personal_settings() -> dict:
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
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    jwt_secret: str = ""
    tinkoff_token: str = ""
    tinkoff_sandbox: bool = True
    database_url: str = "postgresql://finn:finn@localhost:5432/finn"
    telegram_bot_token: str = ""
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"
    cors_credentials: bool = True
    rate_limit_per_minute: int = 0

    moex_iss_url: str = "https://iss.moex.com/iss"
    cbr_url: str = "https://www.cbr.ru/scripts/XML_daily.asp"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
personal = load_personal_settings()
