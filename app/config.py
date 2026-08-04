from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    bot_token: str = Field(alias="BOT_TOKEN")
    # Legacy field from the first admin implementation. It is no longer used,
    # but remains accepted so an old `.env` with ADMIN_TELEGRAM_ID= does not
    # break startup after switching to ADMIN_PASSWORD authentication.
    admin_telegram_id: int | None = Field(default=None, alias="ADMIN_TELEGRAM_ID")
    sonya_telegram_id: int | None = Field(default=None, alias="SONYA_TELEGRAM_ID")
    proxy_url: str | None = Field(default=None, alias="PROXY_URL")
    quest_start_delay_seconds: int = Field(default=300, alias="QUEST_START_DELAY_SECONDS")
    roadmap_path: Path = Field(default=Path("roadmap/quest.json"), alias="ROADMAP_PATH")
    database_path: Path = Field(default=Path("data/bot.db"), alias="DATABASE_PATH")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @field_validator("proxy_url", mode="before")
    @classmethod
    def blank_proxy_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("admin_telegram_id", "sonya_telegram_id", mode="before")
    @classmethod
    def blank_id_to_none(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("quest_start_delay_seconds")
    @classmethod
    def validate_delay(cls, value: int) -> int:
        if value < 0:
            raise ValueError("QUEST_START_DELAY_SECONDS must be >= 0")
        return value


def load_settings() -> Settings:
    return Settings()
