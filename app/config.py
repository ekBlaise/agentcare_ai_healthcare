"""
Environment-based configuration for AgentCare.
All settings load from environment variables / .env — no hardcoded secrets.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # LLM
    groq_api_key: str = "not_set"
    llm_model: str = "llama-3.3-70b-versatile"

    # Database
    database_url: str = "sqlite:///./data/agentcare.db"

    # Auth
    jwt_secret_key: str = "dev_secret_change_me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 120

    # App
    app_env: str = "development"
    upload_dir: str = "./app/uploads"
    log_level: str = "INFO"

    # Safety
    emergency_keywords: str = (
        "chest pain,stroke,bleeding,unconscious,suicide,"
        "overdose,can't breathe,heart attack"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def emergency_keyword_list(self) -> list[str]:
        return [k.strip().lower() for k in self.emergency_keywords.split(",") if k.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
