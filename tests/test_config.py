"""Unit tests for application configuration."""
from __future__ import annotations

import os

from app.core.config import Settings, get_settings


def test_settings_defaults_are_safe() -> None:
    s = Settings(_env_file=None)
    assert s.ai_provider_api_key == "public"
    assert s.app_env == "development"
    assert s.displayed_provider_name == "Slide AI"
    assert s.ai_provider_default_model == "deepseek-v4-flash-free"


def test_sqlalchemy_uri_assembles_from_components() -> None:
    s = Settings(
        _env_file=None,
        db_user="u",
        db_password="p",
        db_host="h",
        db_port=5433,
        db_name="n",
    )
    uri = s.sqlalchemy_database_uri
    assert uri.startswith("postgresql+asyncpg://u:p@h:5433/n")


def test_sqlalchemy_uri_uses_explicit_database_url() -> None:
    s = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://explicit/db",
        db_user="ignored",
    )
    assert s.sqlalchemy_database_uri == "postgresql+asyncpg://explicit/db"


def test_is_production_flag() -> None:
    assert Settings(_env_file=None, app_env="production").is_production is True
    assert Settings(_env_file=None, app_env="development").is_production is False


def test_get_settings_is_cached(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    a = get_settings()
    b = get_settings()
    assert a is b
    # clear cache so other tests are unaffected
    get_settings.cache_clear()
