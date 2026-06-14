from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    tinkoff_token: str = ""
    database_url: str = "sqlite:///data/finn.db"
    telegram_bot_token: str = ""
    log_level: str = "INFO"

    moex_iss_url: str = "https://iss.moex.com/iss"
    cbr_url: str = "https://www.cbr.ru/scripts/XML_daily.asp"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
