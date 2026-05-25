from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "development"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000

    database_url: str = "sqlite+aiosqlite:///./stock_picker.db"
    redis_url: str = "redis://localhost:6379/0"

    data_refresh_hours: str = "13,15"
    data_refresh_minutes: str = "5,5"

    cache_ttl: int = 3600

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    wechat_webhook_url: str = ""
    notification_top_n: int = 10

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    wechat_corp_id: str = ""
    wechat_app_agent_id: int = 0
    wechat_app_secret: str = ""
    wechat_token: str = ""
    wechat_encoding_aes_key: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug(cls, value: Any) -> Any:
        if isinstance(value, str) and value.lower() in {"release", "prod", "production"}:
            return False
        return value


settings = Settings()
