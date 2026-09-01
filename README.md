<div align="center">

# Slide AI — Backend

**FastAPI + Supabase backend** for the Slide AI presentation studio.
Generates structured decks via real LLMs (OpenCode Zen — DeepSeek and other
free models), persists them in Postgres, streams AI chat edits, serves an
**MCP server** for AI coding agents (OAuth2, no manual tokens), and exports
to animated HTML / vector PDF / native PPTX.

</div>

---

## ✨ Features

**Generation**
- **AI generation** — a single LLM call produces a full structured `PresentationSpec` (meta + N slides) with auto-retry on schema failure, a quality-feedback loop, and a 3-model fallback chain.
- **Outline-first** — `POST /presentations/outline` proposes a reviewable slide plan; `GenerationRequest.outline` makes generation follow the approved plan exactly.
- **Custom creative mode** (`theme="custom"`) — forces AI-authored `layout:"custom"` slides (sandboxed HTML/CSS/JS) and custom keyframe animations instead of template structure.
- **Topic specificity** — system prompt enforces a `SPECIFICITY MANDATE` (real numbers, named players, no generic filler) + few-shot examples.
- **Empty-response guard** — free reasoning models sometimes answer `content: null`; treated as a provider error and retried.
- **8 template families** — keyword auto-classification (`startup_pitch`, `finance`, `education`, `medical`, `marketing`, `product`, `research`, `generic`), skipped in custom/outline modes.
- **Deck translation** — `POST /presentations/{id}/translate` rewrites every text (titles, bullets, cards, tables, notes) in ONE model call.
- **PPTX import** — `POST /presentations/import/pptx` converts an existing PowerPoint (text, tables, **native charts**, notes, free positions) into an editable spec — deterministic, no AI rewriting.

**Spec model**
- **Strict schema** — Pydantic v2 discriminated union of 18 element types, including a native **`chart` element** (bar/line/pie/doughnut/radar with multi-series data) and per-element `locked` flag.
- **camelCase aliases** — the API accepts the frontend's `fileId` / `animationDelay` / `chartType` spellings so client-authored specs never silently lose data.
- **User themes** — decks can carry `meta.themeTokens` (full renderer token set) for user-saved themes; `/themes` CRUD stores reusable skins per user.

**MCP server (AI coding agents)**
- **Streamable-HTTP JSON-RPC MCP endpoint** with 28+ toolbox tools: list/read/create/edit decks, per-element read & control, animations without restrictions (security sandbox only), screenshots (headless Chromium), durable `mcp_jobs`, a downloadable **Skill ZIP** (`/skill/slide-ai.zip`) that teaches agents presentation craft.
- **RFC 9728 OAuth2 protected-resource discovery** + dynamic client registration + authorization-code PKCE + **device flow** — CLI agents authenticate in the browser like Claude Code does; 30-day tokens, no manual copy-paste.

**Platform**
- **Multi-turn chat agent** — SSE-streamed tool calls (`update_slide`, `add_slide`, `change_theme`, `reduce_text`…) fed back until done.
- **Workspaces** — invitations, roles (`owner/admin/editor/viewer`), audit log, member search.
- **Sharing** — public / private / password-protected (salted SHA-256), **link expiry** (410 when elapsed), view counts, per-slide viewer timing, reviewer comments.
- **Version history** — every edit snapshots the spec + chat; restore reverts both.
- **Export** — HTML (interactive viewer with replayed animations), PDF (Playwright/Chromium), PPTX (python-pptx with **native editable charts** and rendered images for custom-coded slides).
- **Brand kit & slide library** — per-user logo/colors/fonts applied to generation; reusable saved slides.
- **Rate limiting** — in-memory sliding window per user on generation endpoints.

---

## 🏗️ Tech stack

| Layer | Tech |
|-------|------|
| Framework | FastAPI (async) |
| Language | Python ≥ 3.11 |
| Data / Auth / Storage | Supabase Python SDK (`AsyncClient`) |
| Validation | Pydantic v2 / pydantic-settings |
| HTTP (AI provider) | httpx |
| MCP | JSON-RPC Streamable HTTP + RFC 9728 OAuth2 discovery |
| PDF export | Playwright (Chromium headless) |
| PPTX export / import | python-pptx (native charts both ways) |
| Auth | PyJWT (HS256 + ES256 via JWKS), `email-validator` |
| Tests | pytest + pytest-asyncio, in-memory `FakeAsyncClient` (228 tests) |

---

## 📐 Architecture

```
                         ┌─────────────────────┐
                         │  OpenCode Zen LLMs  │
                         │  (free-tier models) │
                         └──────────▲──────────┘
                                    │ httpx (chat/completions)
┌──────────────┐   spec/REST/SSE ┌──┴─────────────┐   SQL/JSON   ┌────────────┐
│  React SPA   │◀───────────────▶│    FastAPI     │◀────────────▶│  Supabase  │
│ (companion   │                 │   (app/main)   │  SDK + JWT   │ PostgreSQL │
│  frontend)   │◀───────────────▶│  MCP + OAuth2  │              │ + Storage  │
└──────────────┘   JSON-RPC/HTTP └────────────────┘              └────────────┘
        ▲
        │ MCP (tools + OAuth browser flow)          ┌──────────────────┐
└───────┴───────────────────────────────────────────│ AI coding agents │
   ZKR · Claude Code · Cursor · Codex · OpenCode    └──────────────────┘
```

```
app/
├── main.py                # App factory + lifespan (Supabase + auth + storage wiring)
├── api/
│   ├── deps.py            # extract_token, owner_id, user_email, supabase
│   └── routes/            # auth (incl. device flow + mcp-token), health,
│                          #   models, brand_kit, slide_library, themes,
│                          #   oauth (+ /.well-known discovery), skill
├── auth/                  # JWTVerifier, device_flow pairing store, providers
├── generation/            # GenerationService, spec model, Online/Offline
│                          #   SpecProvider, spec_editor, outliner (outline-first),
│                          #   translator (deck i18n), llm (one-shot JSON helper)
├── chat/                  # ChatService (multi-turn agent), ChatProvider, tools
├── presentations/         # CRUD routes, service, versioning, pptx_import
├── files/                 # Upload + signed-URL service, StorageGateway
├── sharing/               # Shares (public/password/private + expiry),
│                          #   viewer analytics, comments
├── workspaces/            # Members, invitations, audit, user search
├── templates/             # 8 template families + keyword classifier
├── assets/                # AssetRegistry (multi-provider), routes
├── export/                # Html/Pdf/Pptx strategies, slide_shot (Chromium
│                          #   renderer used by PPTX + MCP screenshots)
├── mcp/                   # 28+ MCP tools, JSON-RPC routes, server instructions
├── core/                  # config, logging, exceptions, handlers, ratelimit,
│                          #   model_catalog (free-model policy)
└── db.py                  # Thin async Supabase helpers (one module, no ORM)
migrations/                # Applied via Supabase (see 🗄️ below)
tests/                     # 228 tests on FakeAsyncClient (no real DB needed)
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

# --- Frontend origin (used for OAuth resource indicators) ---
FRONTEND_ORIGIN=http://localhost:5173

# --- AI provider (OpenCode Zen; "public" is a real, free key) ---
AI_PROVIDER_BASE_URL=https://opencode.ai/zen/v1
AI_PROVIDER_API_KEY=public
AI_PROVIDER_DEFAULT_MODEL=nemotron-3-ultra-free
ALLOW_PAID_MODELS=false
AI_REQUEST_TIMEOUT_SECONDS=120

# --- Security ---
CORS_ALLOWED_ORIGINS=["http://localhost:5173"]
```

Free-tier policy: only `big-pickle` and models ending in `-free` are exposed by default; set `ALLOW_PAID_MODELS=true` when you have a paid key.

### Run

```bash
uvicorn app.main:app --reload --port 8000
```

OpenAPI docs: http://localhost:8000/docs

### PDF export & MCP screenshots

Playwright/Chromium renders PDFs and MCP slide screenshots. Install once:

```bash
python -m playwright install chromium
```

---

## 🗄️ Database schema

Key tables (migrations applied via Supabase):

| Table | Purpose |
|-------|---------|
| `presentations` | Deck metadata + full `spec` JSONB |
| `presentation_versions` | Version snapshots (spec + chat snapshot) |
| `presentation_shares` | Public / password / private tokens, `expires_at`, `view_count`, `slide_time_json` |
| `share_comments` | Reviewer comments on shared decks |
| `chat_messages` | Conversation history per deck |
| `file_assets` | Uploaded file metadata |
| `user_brand_kits` | Per-user logo/colors/fonts |
| `user_themes` | User-saved theme skins (tokens + ambient JSON) |
| `slide_library` | Reusable saved slides |
| `mcp_jobs` | Durable async jobs for MCP clients |
| `workspaces` / `workspace_members` / `workspace_audit` / `workspace_presentations` | Teams, roles, audit, deck sharing |

All tables have **Row Level Security** enabled with owner policies. Service-role queries bypass RLS (the backend uses the service-role key for data access; a SEPARATE auth client handles signup/signin so user JWTs never leak into the data path).

---

## 🔌 API surface

All under `/api/v1`.

| Area | Endpoints |
|------|-----------|
| Auth | `POST /auth/signup` · `POST /auth/signin` · `POST /auth/signout` · `GET/PATCH /auth/me` · `POST /auth/refresh` · `POST /auth/mcp-token` (30-day) · `POST /auth/device/start\|authorize\|poll` |
| Presentations | `GET/POST/PATCH/DELETE /presentations` · `POST /presentations/generate` · `POST /presentations/outline` · `GET/PUT /presentations/{id}/spec` (optimistic locking, 409 + `X-Updated-At`) · `POST /presentations/{id}/duplicate` · `GET /presentations/search` |
| Import | `POST /presentations/import` (markdown/url) · `POST /presentations/import/pptx` |
| AI edit & i18n | `POST /presentations/{id}/edit` · `POST /presentations/{id}/translate` |
| Chat | `GET /presentations/{id}/chat` · `POST /presentations/{id}/chat/stream` (SSE) · `DELETE` |
| Versions | `GET /presentations/{id}/versions[/{vid}]` · `POST /versions/{vid}/restore` |
| Files | `GET/POST /files` · `DELETE /files/{id}` · `GET /files/{id}/url` (signed, 1h) |
| Assets | `GET /assets/search?q=&kind=image\|icon\|svg` |
| Templates | `GET /templates` · `GET /templates/suggest?q=` |
| Themes | `GET/POST /themes` · `DELETE /themes/{id}` |
| Brand kit | `GET/PUT /brand-kit` |
| Slide library | `GET/POST /slide-library` · `DELETE /slide-library/{id}` |
| Sharing | `POST/GET /presentations/{id}/shares` · `DELETE /shares/{token}` · `GET /shared/{token}` · `POST /shared/{token}/analytics` · `POST /shared/{token}/comments` |
| Workspaces | CRUD + members + role changes + invitations + audit + presentations + `GET /workspaces/search/users` |
| Export | `GET /presentations/{id}/export?format=html\|pdf\|pptx` |
| Models | `GET /models` (policy-filtered catalog) |
| MCP | `POST /mcp` (JSON-RPC: `initialize`, `tools/list`, `tools/call`) + `/.well-known/oauth-protected-resource` (+ path-inserted variants) + `/.well-known/oauth-authorization-server` · `/oauth/*` (register/authorize/token) · `GET /skill/slide-ai.zip` |
| Health | `GET /health` |

---

## 🤖 Generation pipeline

1. **Request** arrives at `POST /presentations/generate` with `{prompt, slide_count, tone, language, theme?, template_name?, model?, outline?, theme_tokens?}`.
2. **`GenerationService.generate`** creates a `presentations` row with `status=generating`.
3. **Template auto-classify** — skipped when the theme is `custom` or an approved `outline` is provided.
4. **LLM call** — `OnlineSpecProvider.generate_spec` POSTs to `{AI_PROVIDER_BASE_URL}/chat/completions` with the rich system prompt (schema + design rules + SPECIFICITY MANDATE + few-shots), `response_format: json_object`, and per-generation creative direction.
5. **Validation & retries** — schema failures and deterministic quality checks (under-filled layouts, generic titles) are fed back to the model (max 2 retries); empty `content` answers raise and trigger the next model in the fallback chain (up to 3 candidates).
6. **Persist** — `spec` JSONB + `slide_count`, `status=ready`; user-theme tokens are stamped onto `meta.themeTokens`.
7. Frontend navigates to `/editor/{id}`.

If no API key is configured, the `OfflineSpecProvider` produces a deterministic topic-aware spec.

---

## 🧩 MCP toolbox

`POST /mcp` is a stateless JSON-RPC endpoint. Highlights of `tools/list`:

- **Read**: `list_presentations`, `get_presentation`, `get_slide_elements`, `get_slide_screenshot` (returns a real PNG via headless Chromium), `search_presentations`
- **Create/edit**: `create_presentation`, `generate_presentation` (opt-in only — agents are instructed to build decks with the toolbox first), `ai_edit_presentation`, `update_slide`, `add_slide`, `delete_slide`, `update_element`, `add_element`, `remove_element`, `move_element`, `set_element_animation`, `define_custom_animation`, `update_custom_slide`, `change_theme`, `rewrite_title`, `duplicate_presentation`, `delete_presentation`…

Agents authenticate via the **browser** (OAuth2 PKCE or device flow — same UX as Claude Code): the CLI opens `http://localhost:5173/oauth/...`, the user clicks *Approve*, done. `SERVER_INSTRUCTIONS` tell client LLMs to compose decks from the toolbox and use `generate_presentation` only when the user explicitly asks.

The **Skill ZIP** (`GET /skill/slide-ai.zip`) is a real craft guide (not an install guide): slide anatomy, layout picking, animation craft, animated SVG diagrams, step-by-step algorithm explainers, verification checklists.

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

The loop keeps feeding `tool` role messages back to the LLM until no tool calls are emitted, a duplicate-turn guard fires, or `_MAX_AGENT_ITERATIONS` (10) is hit.

---

## 🧪 Tests

```bash
pytest                                             # 228 offline tests (default)
SLIDE_AI_TESTS_ONLINE=1 pytest tests/test_online_provider.py -v   # real provider
```

The offline suite runs against `FakeAsyncClient` (an in-memory Supabase stand-in in `tests/conftest.py`) — no real database needed. Online tests are opt-in via `SLIDE_AI_TESTS_ONLINE=1` and hit the real free provider.

Highlights:
- `tests/test_feature_round_3.py` — chart element + native PPTX chart, PPTX import round-trip, outline endpoint, deck translation, user themes
- `tests/test_custom_mode.py` — custom creative mode enforcement
- `tests/test_chat_agent_loop.py` — multi-turn agent loop with scripted fake providers
- `tests/test_generation_routes.py` — generate → spec persist → ownership scoping
- `tests/test_sharing.py` — public / password / private / expired share lifecycle
- `tests/test_mcp*.py` — MCP tools, auth, screenshots
- `tests/test_export.py` — HTML / PDF / PPTX byte output sanity

---

## 🛡️ Security

- **JWT verification** local-first via `PyJWKClient` (ES256) or HS256 secret, both requiring `aud="authenticated"`. Falls back to the provider only for opaque session refresh.
- **RLS** on every table; the data client uses the service-role key (bypasses RLS), the auth client uses the user's session.
- **Owner scoping** in code: every query filters by `owner_id = JWT sub`.
- **Share tokens** are UUIDs generated server-side. Passwords use salted SHA-256 + `secrets.compare_digest`. Expired links return 410 (fail-closed on malformed expiry).
- **MCP/OAuth** — PKCE S256, dynamic client registration, consent screen in the frontend, 30-day tokens, `WWW-Authenticate: resource_metadata` on 401s.
- **Custom slide sandbox** — AI-authored slides run in a sandboxed iframe (`allow-scripts` only, CSP blocking external loads); custom keyframes are CSS-parsed with a property whitelist (no `url(...)`, `expression(...)`, `javascript:`, `@import`).
- **Rate limiting** — in-memory sliding window on generation endpoints → HTTP 429.
- **CORS** restricted to configured origins; URL import is SSRF-guarded (private hosts blocked).

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
| `FRONTEND_ORIGIN` | `http://localhost:5173` | Used for OAuth resource indicators / consent links |
| `AI_PROVIDER_BASE_URL` | `https://opencode.ai/zen/v1` | LLM endpoint |
| `AI_PROVIDER_API_KEY` | `public` | Empty → offline mode |
| `AI_PROVIDER_DEFAULT_MODEL` | `nemotron-3-ultra-free` | Model name |
| `ALLOW_PAID_MODELS` | `false` | Expose non-free models too |
| `AI_REQUEST_TIMEOUT_SECONDS` | `120` | Per LLM call |
| `CORS_ALLOWED_ORIGINS` | `["http://localhost:5173"]` | JSON array or comma list |

---

## 📦 Scripts

```bash
pytest                                  # full offline suite
SLIDE_AI_TESTS_ONLINE=1 pytest tests/test_online_provider.py -v   # real provider
uvicorn app.main:app --reload           # dev server
python -m playwright install chromium   # PDF/MCP-screenshot dependency
```

---

## 📄 License

MIT.
