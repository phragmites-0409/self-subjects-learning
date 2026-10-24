from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_name: str = "高中题目 AI 学习本地端"
    app_env: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = PROJECT_ROOT / "data"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    deepseek_vision_model: str = "deepseek-flash"
    ai_timeout_seconds: float = 120
    max_upload_bytes: int = 10 * 1024 * 1024
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    supabase_url: str = ""
    supabase_publishable_key: str = ""

    @property
    def auth_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_publishable_key)

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    @field_validator("data_dir")
    @classmethod
    def resolve_data_dir(cls, value: Path) -> Path:
        return (value if value.is_absolute() else PROJECT_ROOT / value).resolve()

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
