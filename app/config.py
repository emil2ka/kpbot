from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    xai_api_key: str | None = None
    xai_model: str = "grok-4.3"
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    app_api_key: str | None = None
    min_kaspi_price_kzt: int = 4000
    min_reviews: int = 15
    max_sellers: int = 8


@lru_cache
def get_settings() -> Settings:
    return Settings()

