# Slide AI Backend

AI-powered presentation generator. The AI provider is exposed only as **"Slide AI"** to the frontend, API responses, logs, and settings.

## Stack

- **FastAPI** (async)
- **Supabase Python SDK** (data, auth, storage — single `AsyncClient`)
- **Pydantic v2** / pydantic-settings
- **httpx** (AI provider HTTP calls)
- **pytest** + pytest-asyncio

## Architecture

```
app/
  core/          Config, Logging, Exceptions, Handlers
  db.py          Supabase query helpers (one module, no ORM)
  api/routes/    FastAPI routers (health, auth, ...)
  generation/     AI spec provider, spec editor, generation service
  presentations/  Presentation CRUD service, versioning, entities, schemas
  files/         File upload service, storage gateway, schemas
  sharing/       Share links (public, private, password-protected)
  workspaces/    Workspace CRUD, members, audit
  auth/          JWT verifier, auth providers (Supabase + fake)
  assets/        Asset search (icons, placeholder images)
  templates/     Smart template selector
  export/        HTML / PDF / PPTX export
  main.py        App factory, lifespan, Supabase client init
tests/             Unit + integration tests (FakeAsyncClient in conftest)
```

All database access goes through `app/db.py` — thin async functions that call `supabase.AsyncClient.table()`. No ORM, no repositories, no migration framework.

## Environment Variables

Only two are required for production:

| Variable | Description |
|---|---|
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service-role key (server-only) |

Optional:

| Variable | Default | Description |
|---|---|---|
| `SUPABASE_JWT_SECRET` | `dev-insecure-secret` | Secret for verifying Supabase JWTs locally |
| `AI_PROVIDER_BASE_URL` | `https://opencode.ai/zen/v1` | AI provider endpoint |
| `AI_PROVIDER_API_KEY` | `public` | AI provider API key (empty = offline mode) |
| `AI_PROVIDER_DEFAULT_MODEL` | `deepseek-v4-flash-free` | Default model for generation |
| `AI_REQUEST_TIMEOUT_SECONDS` | `120` | Timeout for AI provider HTTP calls |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5173` | Allowed CORS origins (JSON array or comma-separated) |

## Development

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"

# Run (falls back to fake auth/storage if no Supabase)
uvicorn app.main:app --reload --port 8000

# Tests (uses in-memory FakeAsyncClient, no real DB needed)
pytest
```

## Database (Supabase)

Tables are managed directly in the Supabase dashboard (no Alembic). The backend reads/writes through the Supabase SDK:

- `presentations` — deck metadata + full spec JSON
- `file_assets` — uploaded file metadata
- `presentation_shares` — share links
- `presentation_versions` — version snapshots
- `workspaces` / `workspace_members` / `workspace_presentations` / `workspace_audit`

Row Level Security (RLS) on `owner_id` is enforced both by Supabase policies and in application code.

## API

- `POST /api/v1/auth/signup` — create account
- `POST /api/v1/auth/signin` — authenticate
- `GET  /api/v1/auth/me` — current user
- `POST /api/v1/presentations/generate` — AI generation
- `GET/POST/PATCH/DELETE /api/v1/presentations` — CRUD
- `PUT /api/v1/presentations/{id}/spec` — live editing
- `POST /api/v1/presentations/{id}/edit` — AI-driven editing
- `GET /api/v1/presentations/{id}/export` — HTML/PDF/PPTX export
- `POST /api/v1/presentations/{id}/shares` — sharing
- `GET/POST/PATCH/DELETE /api/v1/workspaces` — workspaces
- `POST /api/v1/files` — file upload
