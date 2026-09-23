from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "LaSaTrading Backend"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8000

    DATABASE_URL: str = "postgresql://lasa:lasa@localhost:5432/lasa"
    POSTGRES_USER: str = "lasa"
    POSTGRES_PASSWORD: str = "lasa"
    POSTGRES_DB: str = "lasa"

    REDIS_URL: str = "redis://localhost:6379/0"

    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    BINANCE_API_BASE_URL: str = "https://api.binance.com"
    BINANCE_SYMBOLS_CACHE_TTL: int = 86400
    BINANCE_THROTTLE_MS: int = 100
    BINANCE_MAX_RETRIES: int = 3
    BINANCE_RETRY_BACKOFF_BASE: float = 1.0
    BINANCE_429_RETRY_WAIT_SECONDS: int = 60
    BINANCE_REQUEST_TIMEOUT: float = 30.0
    BINANCE_KLINES_LIMIT: int = 1000

    CORS_ORIGINS: list[str] = ["http://localhost:5173"]


def get_settings() -> Settings:
    return Settings()
