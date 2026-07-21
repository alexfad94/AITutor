from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str = Field(..., alias="BOT_TOKEN")
    database_url: str = Field(..., alias="DATABASE_URL")
    openai_api_key: str = Field(..., alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_MODEL")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    training_topic: str = Field(default="Корпоративный онбординг", alias="TRAINING_TOPIC")
    training_material: str = Field(
        default=(
            "Компания использует асинхронную коммуникацию по умолчанию. "
            "Все задачи ведутся через трекер, важные решения фиксируются письменно, "
            "а эскалации блокеров ожидаются в течение 30 минут. "
            "Перед релизом нужны code review, зеленые тесты и короткая запись в changelog."
        ),
        alias="TRAINING_MATERIAL",
    )
    training_material_file: str | None = Field(default=None, alias="TRAINING_MATERIAL_FILE")
    quiz_question_count: int = Field(default=5, alias="QUIZ_QUESTION_COUNT", ge=1, le=20)
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    def get_training_material(self) -> str:
        if self.training_material_file:
            return Path(self.training_material_file).read_text(encoding="utf-8").strip()
        return self.training_material.strip()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
