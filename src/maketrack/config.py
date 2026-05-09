from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MAKETRACK_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    db_path: Path = Path("/data/maketrack.db")
    uploads_path: Path = Path("/uploads")
    log_level: str = "INFO"
    bind_host: str = "0.0.0.0"
    bind_port: int = 8000
    default_ttl_seconds: int = 86400


def get_settings() -> Settings:
    return Settings()
