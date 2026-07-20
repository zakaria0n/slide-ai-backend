"""ORM model package.

Importing this package registers all models on :class:`app.db.base.Base`
so Alembic (``app.models`` side-effect import) and the app can discover
every table via ``Base.metadata``.
"""
from __future__ import annotations

from app.models.file_asset import FileAsset
from app.models.presentation import Presentation  # noqa: F401

__all__ = ["Presentation", "FileAsset"]
