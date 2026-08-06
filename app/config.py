from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    xai_api_key: str | None = None
    xai_model: str = "grok-4.3"
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    app_api_key: str | None = None
    telegram_bot_token: str | None = None
    telegram_webhook_secret: str | None = None
    youtube_api_key: str | None = None
    # Optional credentials for a licensed China catalogue-data provider.
    china_provider_api_key: str | None = None
    china_provider_base_url: str | None = None
    min_kaspi_price_kzt: int = 4000
    min_reviews: int = 15
    max_sellers: int = 8

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)

    @property
    def xai_configured(self) -> bool:
        return bool(self.xai_api_key)

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token)

    @property
    def china_provider_configured(self) -> bool:
        return bool(self.china_provider_api_key and self.china_provider_base_url)

    @property
    def youtube_configured(self) -> bool:
        return bool(self.youtube_api_key)

    @property
    def china_live_data_configured(self) -> bool:
        """Whether a dependable catalogue-data provider is configured.

        Generated marketplace links are useful, but they are not a reliable
        live supplier feed. Keep the health check honest about that distinction.
        """
        return self.china_provider_configured



@lru_cache
def get_settings() -> Settings:
    return Settings()
