"""Application configuration — all settings from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # LLM
    llm_provider: Literal["anthropic", "openai", "local"] = "local"
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_model: str = "claude-sonnet-4-6"
    openai_model: str = "gpt-4o-mini"

    # API security
    api_secret_key: str = "dev-insecure-key-change-in-prod"

    # Server
    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = False

    # Logging
    log_level: str = "INFO"
    mask_pii_in_logs: bool = True

    # Storage
    storage_dir: str = "./outputs"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @property
    def storage_path(self) -> Path:
        p = Path(self.storage_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def sessions_path(self) -> Path:
        p = self.storage_path / "sessions"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def effective_provider(self) -> str:
        """Resolve which provider to actually use based on available keys."""
        if self.llm_provider == "anthropic" and self.anthropic_api_key:
            return "anthropic"
        if self.llm_provider == "openai" and self.openai_api_key:
            return "openai"
        if self.anthropic_api_key:
            return "anthropic"
        if self.openai_api_key:
            return "openai"
        return "local"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
