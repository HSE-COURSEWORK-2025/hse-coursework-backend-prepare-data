"""Общие настройки для приложения."""

import time
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Конфиг с переменными окружения."""

    CHUNK_DURATION_MS: int | None = 30 * 24 * 60 * 60 * 1000

    REDIS_HOST: str | None = "redis"
    REDIS_PORT: str | None = "6379"
    REDIS_DATA_COLLECTION_GOOGLE_FITNESS_API_PROGRESS_BAR_NAMESPACE: str | None = (
        "REDIS_DATA_COLLECTION_GOOGLE_FITNESS_API_PROGRESS_BAR_NAMESPACE-"
    )

    START_MS: int | None = int((time.time() - 360 * 24 * 60 * 60) * 1000)
    START_MS: int | None = 0
    END_MS: int | None = int(time.time() * 1000)

    DOMAIN_NAME: str | None = "http://hse-coursework-health.ru"
    AUTH_API_BASE_URL: str | None = f"{DOMAIN_NAME}:8081"
    DATA_COLLECTION_API_BASE_URL: str | None = f"{DOMAIN_NAME}:8082"

    NOTIFICATIONS_API_BASE_URL: str = (
        "http://notifications-api:8083/notifications-api/api/v1/notifications"
    )

    model_config = SettingsConfigDict(
        env_file=".env.prod",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_nested_delimiter="__",
        extra="ignore",
    )


settings = Settings()
