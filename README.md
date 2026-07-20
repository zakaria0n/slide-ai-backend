# Slide AI Backend

Production-ready backend powering the Slide AI presentation generator.

The AI provider is **exposed only as "Slide AI"** to the frontend, API
responses, logs, and settings. The internal provider implementation is
abstracted behind an adapter and is never surfaced.

## Stack

- FastAPI (async)
- SQLAlchemy 2 (async, `asyncpg`)
- Alembic (migrations)
- Pydantic v2 / pydantic-settings
- httpx
- Supabase (PostgreSQL, Storage, Auth)
- `dependency-injector` (DI / composition root)
- pytest + pytest-asyncio

## Architecture

```
app/
  core/          Config, Logging, Exceptions, Handlers
  db/            Base, Session/Engine, Repositories (generic), Dependencies
  api/routes/    FastAPI routers (health, ...)
  providers/      DI Container (composition root)
  models/        ORM models (added in later features)
alembic/         Migrations
tests/           Unit + integration tests
```

Rules:

- Business logic lives in **services**, never in routes.
- Routes call services; services call **repository interfaces**.
- Providers implement interfaces (adapter pattern) — swappable.
- No placeholders, no fake implementations, no TODO comments.

## Development

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"

# Configure
cp .env.example .env   # fill Supabase + AI provider values

# Run
uvicorn app.main:app --reload --port 8000

# Tests
pytest
```

## Internal AI provider

The default internal provider is **OpenCode Zen** (OpenAI-compatible
Chat Completions). It is wrapped by a `SlideAIProvider` adapter so the
underlying provider can be replaced without touching application code.
Users only ever see the name **"Slide AI"**.
