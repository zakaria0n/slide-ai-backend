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

## Database & Supabase

The application is backed by a real **Supabase** project
(PostgreSQL + Auth + Storage):

- **Schema** is managed by Alembic. The `presentations` table is created
  by migration `0001_create_presentations`, and is also provisioned
  directly in the Supabase project (the table already exists in the
  hosted database with Row Level Security enabled).
- **Row Level Security**: `public.presentations` has an `owner_id` column
  and a policy `presentations_owner_all` that restricts every row to
  `owner_id = auth.uid()`. The backend enforces the same ownership in
  application code, so the two layers agree.
- **Auth**: when `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are set the
  app uses the `SupabaseAuthProvider` (real Supabase Auth). Otherwise it
  falls back to an in-memory `FakeAuthProvider` so the app still runs
  offline / in tests. `SUPABASE_JWT_SECRET` is used to verify access
  tokens locally (HS256, no network round-trip).

To create the schema in a fresh Supabase project, run `alembic upgrade
head`, or apply the DDL from the migration by hand.

## Authentication (Feature 2)

Endpoints under ``/api/v1/auth``:

- ``POST /signup``  � create account, returns user + JWT access/refresh tokens
- ``POST /signin``   � authenticate, returns tokens
- ``POST /signout``  � invalidate session (best-effort)
- ``GET  /me``        � current user (Bearer access token)

Design:
- Routes delegate to :class:`AuthService` (business logic lives there only).
- The service depends on an abstract :class:`AuthProvider`; the concrete
  ``SupabaseAuthProvider`` wraps Supabase Auth. A ``FakeAuthProvider``
  (in-memory, JWT-signed) is used for offline/dev/tests.
- ``JWTVerifier`` validates access tokens locally (HS256, Supabase JWT
  secret) — no network round-trip per request.
- The internal auth backend is never exposed in API responses or logs.

## Presentations (Feature 3)

Owner-scoped CRUD for the user's presentations. Every endpoint requires a
Bearer access token; the owner id is taken from the JWT ``sub`` claim, and
operations are scoped so a user can never read or mutate another user's
decks.

Endpoints under ``/api/v1/presentations``:

- ``GET    /``                 list the caller's presentations (newest first)
- ``POST   /``                 create a draft presentation
- ``GET    /{id}``             fetch one (owner only)
- ``PATCH  /{id}``             rename
- ``POST   /{id}/duplicate``   create an owned copy (``"Copy of …"``)
- ``DELETE /{id}``             delete (owner only)

Design:
- Routes delegate to :class:`PresentationService`; the repository layer
  (``PresentationRepository``) handles only persistence.
- The ORM model ``Presentation`` stores owner-scoped metadata
  (``owner_id``, ``title``, ``description``, ``status``, ``theme``,
  ``slide_count``); slide *content* arrives in a later feature.
- ``owner_id`` is indexed but intentionally **not** a foreign key: identity
  lives in the external Supabase auth provider, not in this database.
- The ``presentations`` table is created by the Alembic migration
  ``0001_create_presentations``.

## Internal AI provider

The default internal provider is **OpenCode Zen** (OpenAI-compatible
Chat Completions). It is wrapped by a `SlideAIProvider` adapter so the
underlying provider can be replaced without touching application code.
Users only ever see the name **"Slide AI"**.

## Related repositories

- **Frontend (React + Vite):** https://github.com/HamzaBenChaoui/Ai_Presentation_generated
