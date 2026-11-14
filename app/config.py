from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration, read from environment variables or .env (twelve-factor style).

    Nothing else in the app reads os.environ; it asks for a Settings object instead,
    which keeps secrets out of code and lets tests pass their own values.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Model
    model_id: str = "microsoft/Florence-2-base"
    # Part of every cache key: bump it when the model or prompts change and old
    # cached results are simply never looked up again.
    model_version: str = "florence-2-base-v1"
    device: str = "cuda"
    max_new_tokens: int = 256

    # Dynamic batching (max_batch_size=1 turns batching off)
    max_batch_size: int = 8
    max_batch_wait_ms: float = 10
    max_queue_size: int = 64
    inference_timeout_s: float = 10

    # Uploads
    max_upload_bytes: int = 5 * 1024 * 1024

    # Database
    database_url: str = "postgresql+asyncpg://visionserve:visionserve@localhost:5432/visionserve"
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # Redis: result cache and rate limits
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_s: int = 24 * 60 * 60
    cache_enabled: bool = True  # turn off for the cache on/off load test
    rate_limit_algorithm: Literal["token_bucket", "fixed_window"] = "token_bucket"
    # Requests per minute by plan. Raise these for load tests.
    rate_limit_free_per_min: int = 60
    rate_limit_pro_per_min: int = 600

    # Object storage (MinIO locally, S3 in the cloud: only these values change)
    s3_endpoint_url: str | None = "http://localhost:9000"
    # Host used inside pre-signed URLs; must be reachable by the client's browser.
    s3_public_endpoint_url: str | None = None
    s3_bucket: str = "visionserve-images"
    s3_region: str = "us-east-1"
    s3_access_key: str | None = "minioadmin"
    s3_secret_key: str | None = "minioadmin"
    presigned_url_ttl_s: int = 15 * 60

    # Admin token for POST /v1/users. None means signup is open (dev only).
    admin_token: str | None = None

    # Logging
    log_level: str = "INFO"
    log_json: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
