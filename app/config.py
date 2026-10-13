from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: Literal["development", "production", "test"] = "development"
    database_url: str = "sqlite:///./data/workflows.db"
    ai_provider: Literal["mock", "openai"] = "mock"
    openai_api_key: SecretStr = SecretStr("")
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    api_key: SecretStr = SecretStr("")
    llm_timeout_seconds: float = Field(default=15, gt=0, le=120)
    llm_max_attempts: int = Field(default=3, ge=1, le=5)
    llm_backoff_seconds: float = Field(default=0.5, ge=0, le=10)

    @model_validator(mode="after")
    def validate_configuration(self) -> "Settings":
        if not self.database_url.startswith("sqlite:"):
            raise ValueError("This MVP supports SQLite databases only")
        if self.app_env == "production" and len(self.api_key.get_secret_value()) < 32:
            raise ValueError("Production requires an API_KEY of at least 32 characters")
        if self.ai_provider == "openai" and not self.openai_api_key.get_secret_value():
            raise ValueError("OPENAI_API_KEY is required for the openai provider")
        url = urlsplit(self.openai_base_url)
        local = url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}
        if (url.scheme != "https" and not local) or not url.hostname or url.username:
            raise ValueError("Provider URL must use HTTPS or a local development endpoint")
        return self
