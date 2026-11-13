from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration, read from environment variables or .env (twelve-factor style).

    Nothing else in the app reads os.environ; it asks for a Settings object instead,
    which keeps secrets out of code and lets tests pass their own values.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Model
    model_id: str = "microsoft/Florence-2-base"
    device: str = "cuda"
    max_new_tokens: int = 256

    # Uploads
    max_upload_bytes: int = 5 * 1024 * 1024

    # Database
    database_url: str = "postgresql+asyncpg://visionserve:visionserve@localhost:5432/visionserve"
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # Admin token for POST /v1/users. None means signup is open (dev only).
    admin_token: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
