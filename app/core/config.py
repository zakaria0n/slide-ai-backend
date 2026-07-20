"""Application configuration loaded from environment variables.

All secrets (Supabase keys, AI provider key, DB password) are read from the
environment via pydantic-settings. A `.env` file is supported for local dev.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the Slide AI backend.

    Values are resolved in this order (last wins): defaults below, then
    variables from a local `.env` file, then real process environment.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Environment ---
    app_env: Literal["development", "staging", "production", "test"] = "development"
    app_debug: bool = False

    # --- API ---
    api_v1_prefix: str = "/api/v1"
    project_name: str = "Slide AI"
    api_title: str = "Slide AI API"
    api_version: str = "1.0.0"

    # --- Database (Supabase PostgreSQL) ---
    # Full SQLAlchemy URL takes precedence when provided.
    database_url: str | None = Field(
        default=None,
        description="Full PostgreSQL/SQLAlchemy connection URL (overrides the pieces below).",
    )
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "postgres"
    db_user: str = "postgres"
    db_password: str = ""
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    db_echo: bool = False

    # --- Supabase ---
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""

    # --- AI provider (internal: OpenCode Zen, exposed to users as "Slide AI") ---
    ai_provider_base_url: str = "https://opencode.ai/zen/v1"
    ai_provider_api_key: str = "public"
    ai_provider_default_model: str = "deepseek-v4-flash-free"
    # Models that may be selected by the application. The real model name is
    # shown to users; only the *provider name* is hidden ("Slide AI").
    ai_allowed_models: list[str] = Field(
        default_factory=lambda: ["deepseek-v4-flash-free"]
    )
    ai_request_timeout_seconds: float = 60.0

    @field_validator("ai_allowed_models", mode="before")
    @classmethod
    def _parse_allowed_models(cls, value: object) -> object:
        """Accept a JSON array or a comma-separated string from the env."""
        if isinstance(value, str):
            import json

            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                pass
            return [m.strip() for m in value.split(",") if m.strip()]
        return value

    # --- Security ---
    # Supabase uses JWTs signed with the JWT secret for auth. The anon key
    # is safe to expose to the browser; the service-role key is server-only.
    cors_allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def sqlalchemy_database_uri(self) -> str:
        """Return the SQLAlchemy database URL.

        Uses the explicit ``database_url`` when set, otherwise assembles a
        Supabase-style ``postgresql+psycopg://`` URL from its components.
        """
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def displayed_provider_name(self) -> str:
        """The provider name shown to users. Always 'Slide AI'."""
        return "Slide AI"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
