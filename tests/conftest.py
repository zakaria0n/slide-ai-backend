"""Shared pytest fixtures."""
from __future__ import annotations

import os

import copy
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest


class FakeTable:
    """Minimal in-memory stand-in for ``supabase.table()``."""

    def __init__(self, name: str, store: dict[str, list[dict]]) -> None:
        self._name = name
        self._store = store

    def _rows(self) -> list[dict]:
        return self._store.setdefault(self._name, [])

    # -- query builder (synchronous, returns FakeQuery) --

    def select(self, *columns: str, count: str | None = None) -> FakeQuery:
        return FakeQuery(self, columns, count=count)

    def insert(self, data: dict | list[dict]) -> FakeQuery:
        return FakeQuery(self).insert(data)

    def upsert(self, data: dict | list[dict]) -> FakeQuery:
        return FakeQuery(self).upsert(data)

    def update(self, data: dict) -> FakeQuery:
        return FakeQuery(self).update(data)

    def delete(self) -> FakeQuery:
        return FakeQuery(self).delete()


@dataclass
class FakeResult:
    data: list[dict]
    count: int | None = None


class FakeQuery:
    """Chained query builder that executes against in-memory rows."""

    def __init__(
        self,
        table: FakeTable,
        columns: tuple[str, ...] = (),
        *,
        count: str | None = None,
    ) -> None:
        self._table = table
        self._columns = columns
        self._count = count
        self._wheres: list[tuple[str, str, Any]] = []
        self._limit_val: int | None = None
        self._offset_val: int = 0
        self._order_col: str | None = None
        self._order_desc: bool = False
        self._insert_data: dict | list[dict] | None = None
        self._is_upsert = False
        self._update_data: dict | None = None
        self._is_delete = False

    def eq(self, column: str, value: Any) -> FakeQuery:
        q = copy.copy(self)
        q._wheres = list(self._wheres) + [(column, "eq", value)]
        return q

    def in_(self, column: str, values: list[Any]) -> FakeQuery:
        q = copy.copy(self)
        q._wheres = list(self._wheres) + [(column, "in", list(values))]
        return q

    def order(self, column: str, *, desc: bool = False) -> FakeQuery:
        q = copy.copy(self)
        q._order_col = column
        q._order_desc = desc
        return q

    def limit(self, n: int) -> FakeQuery:
        q = copy.copy(self)
        q._limit_val = n
        return q

    def range(self, start: int, end: int) -> FakeQuery:
        q = copy.copy(self)
        q._offset_val = start
        q._limit_val = end - start + 1
        return q

    def insert(self, data: dict | list[dict]) -> FakeQuery:
        q = copy.copy(self)
        q._insert_data = data
        return q

    def upsert(self, data: dict | list[dict]) -> FakeQuery:
        q = copy.copy(self)
        q._insert_data = data
        q._is_upsert = True
        return q

    def update(self, data: dict) -> FakeQuery:
        q = copy.copy(self)
        q._update_data = data
        return q

    def delete(self) -> FakeQuery:
        q = copy.copy(self)
        q._is_delete = True
        return q

    def maybe_single(self) -> FakeQuery:
        # Same as execute but we mark it for single result.
        q = copy.copy(self)
        q._maybe_single = True  # type: ignore[attr-defined]
        return q

    async def execute(self) -> FakeResult:
        rows = self._table._rows()
        filtered = self._apply_filters(rows)

        if self._is_delete:
            for r in filtered:
                rows.remove(r)
            return FakeResult(data=[])

        if self._insert_data is not None:
            from datetime import datetime, timezone

            data = self._insert_data if isinstance(self._insert_data, list) else [self._insert_data]
            for d in data:
                d.setdefault("id", str(uuid4()))
                d.setdefault("created_at", datetime.now(timezone.utc).isoformat())
                d.setdefault("updated_at", datetime.now(timezone.utc).isoformat())
                if self._is_upsert:
                    # Replace any existing row sharing the same natural key.
                    for key in ("user_id", "id"):
                        if key in d:
                            rows[:] = [r for r in rows if r.get(key) != d[key]]
                            break
                rows.append(dict(d))
            return FakeResult(data=[dict(d) for d in data])

        if self._update_data is not None:
            for r in filtered:
                r.update(self._update_data)
            return FakeResult(data=[dict(r) for r in filtered])

        # Select path.
        if self._order_col:
            filtered = sorted(
                filtered,
                key=lambda r: r.get(self._order_col, ""),
                reverse=self._order_desc,
            )
        start = self._offset_val
        if self._limit_val is not None:
            filtered = filtered[start: start + self._limit_val]
        elif start:
            filtered = filtered[start:]

        count_val = len(filtered) if self._count == "exact" else None

        if getattr(self, "_maybe_single", False):
            return FakeResult(data=filtered[0] if filtered else None, count=count_val)

        return FakeResult(data=[dict(r) for r in filtered], count=count_val)

    def _apply_filters(self, rows: list[dict]) -> list[dict]:
        result = list(rows)
        for col, op, val in self._wheres:
            if op == "eq":
                result = [r for r in result if str(r.get(col)) == str(val)]
            elif op == "in":
                vals = {str(v) for v in val}
                result = [r for r in result if str(r.get(col)) in vals]
        return result


class FakeAsyncClient:
    """Drop-in replacement for ``supabase.AsyncClient`` backed by dicts.

    Provides ``.table(name)`` and a ``.rpc()`` stub.
    """

    def __init__(self) -> None:
        self._store: dict[str, list[dict]] = {}

    def table(self, name: str) -> FakeTable:
        return FakeTable(name, self._store)

    def from_(self, name: str) -> FakeTable:
        return FakeTable(name, self._store)

    def schema(self, name: str) -> "FakeAsyncClient":
        return self

    async def rpc(self, fn: str, **params: Any) -> Any:
        return None


@pytest.fixture
def fake_supabase() -> FakeAsyncClient:
    return FakeAsyncClient()


@pytest.fixture
def client(tmp_path, fake_supabase) -> "TestClient":
    """Create a TestClient with a FakeAsyncClient wired up."""
    from unittest.mock import AsyncMock, patch

    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app

    # SLIDE_AI_TESTS_ONLINE=1 switches the AI providers to the REAL one
    # (opencode zen, public key) for online integration tests. Default is
    # the deterministic offline mode: fast and hermetic.
    online = os.environ.get("SLIDE_AI_TESTS_ONLINE") == "1"
    settings = Settings(
        _env_file=None,
        app_env="test",
        cors_allowed_origins=["http://localhost:5173"],
        supabase_jwt_secret="test-secret",
        ai_provider_api_key="" if not online else "public",
    )
    app = create_app(settings)
    with TestClient(app) as c:
        # Override AFTER lifespan startup sets AsyncMock.
        app.state.supabase = fake_supabase
        yield c