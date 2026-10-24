from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "高中题目 AI 学习本地端"
    app_env: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = Path("./data")
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    deepseek_vision_model: str = "deepseek-flash"
    ai_timeout_seconds: float = 120
    max_upload_bytes: int = 10 * 1024 * 1024
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def database_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'db' / 'subjects-learning.sqlite3').resolve()}"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    def ensure_data_dirs(self) -> None:
        for name in ("db", "objects", "tmp", "logs", "backups"):
            (self.data_dir / name).mkdir(parents=True, exist_ok=True)
        for name in ("original-images", "thumbnails", "structured-content", "generated-pdfs", "raw-ai"):
            (self.data_dir / "objects" / name).mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_data_dirs()
    return settings
