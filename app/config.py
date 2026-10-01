import os
from typing import List, Dict, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # App Metadata
    APP_NAME: str = "HubSpot Master Service"
    APP_ENV: str = Field(default="development", description="Environment: development, staging, production")
    LOG_LEVEL: str = "INFO"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = Field(
        default="sqlite:///./hubspot_master_service.db",
        description="Database connection URL (PostgreSQL or SQLite fallback)"
    )
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # HubSpot API Settings
    HUBSPOT_API_BASE_URL: str = "https://api.hubapi.com"
    HUBSPOT_CLIENT_ID: Optional[str] = None
    HUBSPOT_CLIENT_SECRET: Optional[str] = None
    HUBSPOT_TOKEN_URL: str = "https://api.hubapi.com/oauth/v1/token"
    HTTP_TIMEOUT_SECONDS: float = 30.0

    # Rate Limiting & Pagination
    HUBSPOT_BURST_LIMIT: int = 100
    HUBSPOT_RATE_LIMIT_WINDOW_SECONDS: int = 10
    HUBSPOT_DAILY_LIMIT: int = 50000
    HUBSPOT_DEFAULT_RETRY_AFTER: float = 10.0
    HUBSPOT_DEFAULT_PAGE_SIZE: int = 100
    HUBSPOT_MAX_PAGE_SIZE: int = 100

    # MinIO / Object Storage
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadminpassword"
    MINIO_SECURE: bool = False
    MINIO_BUCKET: str = "hubspot-master-data"

    # Resilience & Retries
    EXTERNAL_CALL_MAX_RETRIES: int = 3
    EXTERNAL_CALL_RETRY_DELAYS: List[float] = [1.0, 2.0, 4.0]
    EXTERNAL_CALL_JITTER: bool = True
    DLQ_PAYLOAD_MAX_BYTES: int = 65536  # 64 KB

    # HMAC Security
    HMAC_ENABLED: bool = True
    HMAC_SECRET_KEY_CORE: str = "super-secret-coordinator-key-32-chars-long"
    HMAC_SECRET_KEY_ENGINEER: str = "super-secret-engineer-key-32-chars-long"
    HMAC_SIGNATURE_MAX_AGE: int = 300  # 5 minutes window

    # Heartbeat & Maintenance
    HEARTBEAT_INTERVAL_SECONDS: int = 15
    CRASH_TIMEOUT_MINUTES: int = 5

    # Storage Paths
    LOCAL_STORAGE_DIR: str = Field(default="./data/scans")


settings = Settings()
