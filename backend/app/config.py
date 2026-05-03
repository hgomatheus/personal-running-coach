from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    gemini_api_key: str = ""
    strava_client_id: str = ""
    strava_client_secret: str = ""
    secret_key: str = "dev-secret-key-change-in-production"
    log_level: str = "INFO"
    app_base_url: str = "http://localhost:3000"
    database_url: str = "sqlite:////data/db/running_coach.db"
    backup_dir: str = "/data/backups"
    logs_dir: str = "/data/logs"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
