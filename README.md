<div align="center">

# Slide AI — Backend

**FastAPI + Supabase backend** for the Slide AI presentation studio.
Generates structured decks via real LLM (DeepSeek via OpenCode Zen), persists
them in Postgres, streams AI chat edits, and exports to HTML / PDF / PPTX.

</div>

---

## ✨ Features

- **AI generation** — single LLM call produces a full structured `PresentationSpec` (meta + N slides). Auto-retries on schema failure.
- **Multi-turn chat agent** — streams tool calls (`update_slide`, `add_slide`, `change_theme`, `reduce_text`…). Tool results are fed back to the LLM until it stops or hits the iteration cap.
- **Topic specificity** — system prompt enforces a `SPECIFICITY MANDATE` (real numbers, named players, no generic filler) and 3 few-shot examples.
- **8 template families** — auto-classified by keywords (`startup_pitch`, `finance`, `education`, `medical`, `marketing`, `product`, `research`, `generic`).
- **Strict schema** — Pydantic v2 with typed `CardItem`, `StatItem`, `TimelineItem`, `ComparisonSide`.
- **Supabase-native** — single AsyncClient for data + Storage + a separate auth client to avoid RLS recursion.
- **Auth** — JWT verifier enforcing `aud="authenticated"` on both ES256 (JWKS) and HS256 paths.
- **Workspaces** — invitations, roles (`owner/admin/editor/viewer`), audit log, member search via GoTrue admin API.
- **Sharing** — public, private, password-protected (salted SHA-256). Tokens are UUIDs.
- **Version history** — every edit snapshots the spec + chat snapshot. Restore reverts both.
- **Export** — HTML (interactive viewer with slide navigation, keyboard, fullscreen, replayed animations), PDF (Playwright/Chromium), PPTX (python-pptx).
- **Rate limiting** — in-memory sliding-window per user (`RateLimitError` 429).

---

## 🏗️ Tech stack

| Layer | Tech |
|-------|------|
| Framework | FastAPI (async) |
| Language | Python ≥ 3.11 |
| Data / Auth / Storage | Supabase Python SDK (`AsyncClient`) |
| Validation | Pydantic v2 / pydantic-settings |
| HTTP (AI provider) | httpx |
| PDF export | Playwright (Chromium headless) |
| PPTX export | python-pptx |
| Auth | PyJWT (HS256 + ES256 via JWKS), `email-validator` |
| Tests | pytest + pytest-asyncio, in-memory `FakeAsyncClient` |

---

## 📐 Architecture

```
                        ┌─────────────────────┐
                        │   OpenCode Zen LLM  │
                        │ (deepseek-v4-flash) │
                        └──────────▲──────────┘
                                   │ httpx (chat/completions)
┌──────────────┐    spec    ┌──────┴────────┐    SQL/JSON    ┌────────────┐
│  React SPA   │◀──────────▶│   FastAPI     │◀──────────────▶│ Supabase   │
│ (this repo's │  REST+SSE  │  (app/main)   │   SDK + JWT    │ PostgreSQL │
│  companion)  │            │               │                │ + Storage  │
└──────────────┘            └───────────────┘                └────────────┘
```

```
app/
├── main.py                # App factory + lifespan (Supabase + auth + storage wiring)
├── api/
│   ├── deps.py            # extract_token, owner_id, user_email, supabase
│   └── routes/            # auth, health
├── auth/                  # AuthService, JWTVerifier, providers (Supabase + Fake)
├── generation/            # GenerationService, PresentationSpec, Online/Offline
│                          #   SpecProvider, SpecEditProvider, schemas
├── chat/                  # ChatService (multi-turn agent), ChatProvider (stream),
│                          #   tools, schemas, context builder
├── presentations/         # CRUD routes, service, versioning, entities, schemas
├── files/                 # Upload + signed-URL service, StorageGateway, schemas
├── sharing/               # Create/list/revoke + public viewer, password hashing
├── workspaces/            # CRUD + members + invitations + audit + user search
├── templates/             # 8 template families + keyword classifier
├── assets/                # AssetRegistry (multi-provider per kind), routes
├── export/                # HtmlExportStrategy (interactive JS), PdfExportStrategy,
│                          #   PptxExportStrategy, theme tokens
├── core/                  # config, logging, exceptions, handlers, ratelimit
└── db.py                  # Thin async Supabase helpers (one module, no ORM)
migrations/
└── 001_initial_schema.sql # Full Postgres schema + RLS policies (chat_snapshot included)
tests/                     # 110+ tests using FakeAsyncClient (no real DB needed)
```

---

## 🚀 Getting started

### Prerequisites

- Python ≥ 3.11
- A Supabase project (URL + service-role key + JWT secret)

### Install

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# or: source .venv/bin/activate  # macOS/Linux
pip install -e ".[dev]"
```

### Environment

Create `.env` (gitignored):

```dotenv
APP_ENV=development
APP_DEBUG=false

# --- Supabase ---
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_ANON_KEY=YOUR_ANON_KEY
SUPABASE_SERVICE_ROLE_KEY=YOUR_SERVICE_ROLE_KEY
SUPABASE_JWT_SECRET=YOUR_JWT_SECRET

# --- AI provider (OpenCode Zen; "public" is a real, free key) ---
AI_PROVIDER_BASE_URL=https://opencode.ai/zen/v1
AI_PROVIDER_API_KEY=public
AI_PROVIDER_DEFAULT_MODEL=deepseek-v4-flash-free
AI_ALLOWED_MODELS=["deepseek-v4-flash-free"]
AI_REQUEST_TIMEOUT_SECONDS=60

# --- Security ---
CORS_ALLOWED_ORIGINS=["http://localhost:5173"]
```

When `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are set, the app boots against the real database. Otherwise it falls back to an in-memory fake (`FakeAuthProvider` + `InMemoryStorageGateway`) — useful for tests.

### Run

```bash
uvicorn app.main:app --reload --port 8000
```

OpenAPI docs: http://localhost:8000/docs

### PDF export

PDF rendering uses Playwright/Chromium. Install the browser once after pip:

```bash
python -m playwright install chromium
```

---

## 🗄️ Database schema

Tables (see [`migrations/001_initial_schema.sql`](migrations/001_initial_schema.sql)):

| Table | Purpose |
|-------|---------|
| `presentations` | Deck metadata + full `spec` JSONB |
| `presentation_versions` | Version snapshots (spec + chat snapshot) |
| `presentation_shares` | Public / password / private share tokens (UUID) |
| `chat_messages` | Conversation history per deck |
| `file_assets` | Uploaded file metadata |
| `workspaces` | Team containers |
| `workspace_members` | Membership with role |
| `workspace_audit` | Append-only audit log |
| `workspace_presentations` | Deck ↔ workspace join |

All tables have **Row Level Security** enabled with `owner_id = auth.uid()` policies. Service-role queries bypass RLS (the backend uses the service-role key for data access; a SEPARATE auth client handles signup/signin so user JWTs never leak into the data path).

---

## 🔌 API surface

All under `/api/v1`.

| Area | Endpoints |
|------|-----------|
| Auth | `POST /auth/signup` · `POST /auth/signin` · `POST /auth/signout` · `GET /auth/me` · `PATCH /auth/me` |
| Presentations | `GET/POST/PATCH/DELETE /presentations` · `POST /presentations/generate` · `GET/PUT /presentations/{id}/spec` |
| AI edit | `POST /presentations/{id}/edit` |
| Chat | `GET /presentations/{id}/chat` · `POST /presentations/{id}/chat/stream` (SSE) · `DELETE` |
| Versions | `GET /presentations/{id}/versions` · `GET /versions/{vid}` · `POST /versions/{vid}/restore` |
| Files | `GET/POST /files` · `DELETE /files/{id}` · `GET /files/{id}/url` (signed URL, 1h) |
| Assets | `GET /assets/search?q=&kind=image|icon&limit=` |
| Templates | `GET /templates` · `GET /templates/suggest?q=` |
| Sharing | `POST /presentations/{id}/shares` · `GET /presentations/{id}/shares` · `DELETE /shares/{token}` · `GET /shared/{token}` |
| Workspaces | `GET/POST/DELETE /workspaces` · `GET/POST/DELETE /workspaces/{id}/members` · `PATCH /workspaces/{id}/members/{uid}` · invitations (create/list/cancel/pending/accept/decline) · audit · presentations · `GET /workspaces/search/users` |
| Export | `GET /presentations/{id}/export?format=html|pdf|pptx` |

---

## 🤖 Generation pipeline

1. **Request** arrives at `POST /presentations/generate` with `{prompt, slide_count, tone, language, theme?, template_name?}`.
2. **`GenerationService.generate`** creates a `presentations` row with `status=generating`.
3. **Template auto-classify** — if `template_name` is missing, `select_template(prompt)` picks one by keyword.
4. **Single LLM call** — `OnlineSpecProvider.generate_spec` POSTs to `{AI_PROVIDER_BASE_URL}/chat/completions` with:
   - A rich system prompt (role + schema + 6 design rules + SPECIFICITY MANDATE + 3 few-shot examples + template hint)
   - `response_format: json_object`, `temperature: 0.6`
5. **Schema validation** — `PresentationSpec.validate_spec` enforces the discriminated-union element types. On failure → auto-retry (max 2) with a "fix the previous output" suffix.
6. **Persist** — `spec` JSONB + `slide_count` saved on the row, `status=ready`.
7. Frontend navigates to `/editor/{id}`.

If the LLM is unreachable or `AI_PROVIDER_API_KEY` is empty, the `OfflineSpecProvider` produces a deterministic spec from the prompt.

---

## 💬 Chat agent loop

`POST /presentations/{id}/chat/stream` opens an SSE stream:

```
event: token       data: {"delta": "..."}        # streamed text
event: tool_call   data: {"name": "...", ...}    # tool announced
event: tool_result data: {"success": ..., ...}   # tool executed
event: spec_update data: {"spec": {...}}         # new spec if changed
event: done        data: {"message_id": "..."}   # turn finished
```

The loop continues feeding `tool` role messages back to the LLM until either no tool calls are emitted, a duplicate-turn guard fires, or `_MAX_AGENT_ITERATIONS` (10) is hit.

---

## 🧪 Tests

```bash
pytest
```

110+ integration tests use `FakeAsyncClient` (an in-memory Supabase stand-in defined in `tests/conftest.py`) so the suite runs with no real database. The fake enforces query filters (`eq`, `in_`) and table semantics, masking test-only behavior from production logic.

Highlights:
- `tests/test_chat_agent_loop.py` — multi-turn agent loop with scripted fake providers
- `tests/test_generation_routes.py` — full generate → spec persist → ownership scoping
- `tests/test_sharing.py` — public / password / private share lifecycle
- `tests/test_workspaces.py` — members, invitations, audit, access role
- `tests/test_export.py` — HTML / PPTX byte output sanity

---

## 🛡️ Security

- **JWT verification** local-first via `PyJWKClient` (ES256) or HS256 secret, both requiring `aud="authenticated"`. Falls back to the provider only for opaque session refresh.
- **RLS** on every table; the data client uses the service-role key (bypasses RLS), the auth client uses the user's session.
- **Owner scoping** in code: every query filters by `owner_id = JWT sub`.
- **Share tokens** are `UUID` (DB column type), generated server-side via `secrets`/`uuid4`. Passwords use salted SHA-256 with `secrets.compare_digest`.
- **Rate limiting** — in-memory sliding window (default 10 req/60s/user) on `/generate` and `/chat/stream`. Surfaces as HTTP 429 `RateLimitError`.
- **CORS** restricted to configured origins.

---

## 🔧 Configuration reference

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `development` | `development`/`staging`/`production`/`test` |
| `APP_DEBUG` | `false` | FastAPI debug flag |
| `SUPABASE_URL` | — | Required for real DB |
| `SUPABASE_ANON_KEY` | — | Optional (not used by server) |
| `SUPABASE_SERVICE_ROLE_KEY` | — | Required for real DB |
| `SUPABASE_JWT_SECRET` | `dev-insecure-secret` | Required in non-dev envs |
| `AI_PROVIDER_BASE_URL` | `https://opencode.ai/zen/v1` | LLM endpoint |
| `AI_PROVIDER_API_KEY` | `public` | Empty → offline mode |
| `AI_PROVIDER_DEFAULT_MODEL` | `deepseek-v4-flash-free` | Model name |
| `AI_ALLOWED_MODELS` | `["deepseek-v4-flash-free"]` | JSON array or comma list |
| `AI_REQUEST_TIMEOUT_SECONDS` | `120` | Per LLM call |
| `CORS_ALLOWED_ORIGINS` | `["http://localhost:5173"]` | JSON array or comma list |

---

## 📦 Scripts

```bash
pytest                            # full suite
uvicorn app.main:app --reload     # dev server
python -m playwright install chromium   # PDF export dependency
```

---

## 📄 License

MIT.
