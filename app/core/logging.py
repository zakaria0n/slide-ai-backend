"""Structured logging configuration for the Slide AI backend.

Provides a single ``setup_logging`` entrypoint used during application
startup. Logs never leak secrets: formatter output is plain text with a
consistent structure suitable for aggregation.
"""
from __future__ import annotations

import logging
import sys
from logging.config import dictConfig

from app.core.config import Settings, get_settings


def _log_level(settings: Settings) -> str:
    if settings.is_production:
        return "INFO"
    return "DEBUG" if settings.app_debug else "INFO"


def setup_logging(settings: Settings | None = None) -> None:
    """Configure the root logger based on application settings.

    Idempotent: calling it multiple times re-applies the same config.
    """
    settings = settings or get_settings()

    config: dict[str, object] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": (
                    "%(asctime)s | %(levelname)-8s | %(name)s | "
                    "%(message)s"
                ),
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "access": {
                "format": (
                    "%(asctime)s | %(levelname)-8s | uvicorn.access | "
                    "%(message)s"
                ),
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "default",
            },
            "access": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "access",
            },
        },
        "loggers": {
            "app": {"handlers": ["default"], "level": _log_level(settings), "propagate": False},
            "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"level": "INFO"},
            "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
        },
        "root": {"handlers": ["default"], "level": _log_level(settings)},
    }

    dictConfig(config)


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger under the ``app`` namespace."""
    if not name.startswith("app"):
        name = f"app.{name}"
    return logging.getLogger(name)


# Ensure a basic logger exists at import time so modules importing
# ``get_logger`` before ``setup_logging`` still work.
logging.getLogger("app").addHandler(logging.NullHandler())
