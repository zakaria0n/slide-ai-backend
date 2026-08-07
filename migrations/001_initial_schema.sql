-- Initial schema for Slide AI backend.
-- Generated from live Supabase project (maqpnofrjhggebhdqlbu).
-- Apply to a fresh PostgreSQL database to reproduce the schema.

-- =========================================================================
-- presentations
-- =========================================================================

CREATE TABLE IF NOT EXISTS presentations (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id      UUID NOT NULL,
    title         TEXT NOT NULL,
    description   TEXT,
    slide_count   INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'draft',
    theme         TEXT,
    spec          JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_presentations_owner_id ON presentations (owner_id);

ALTER TABLE presentations ENABLE ROW LEVEL SECURITY;

CREATE POLICY presentations_owner_all ON presentations
    FOR ALL USING (owner_id = auth.uid())
    WITH CHECK (owner_id = auth.uid());

-- =========================================================================
-- file_assets
-- =========================================================================

CREATE TABLE IF NOT EXISTS file_assets (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id      UUID NOT NULL,
    filename      TEXT NOT NULL,
    storage_path  TEXT NOT NULL,
    content_type  TEXT,
    size_bytes    BIGINT NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_file_assets_owner_id ON file_assets (owner_id);

ALTER TABLE file_assets ENABLE ROW LEVEL SECURITY;

CREATE POLICY file_assets_owner_all ON file_assets
    FOR ALL USING (owner_id = auth.uid())
    WITH CHECK (owner_id = auth.uid());

-- =========================================================================
-- presentation_versions
-- =========================================================================

CREATE TABLE IF NOT EXISTS presentation_versions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    presentation_id UUID NOT NULL REFERENCES presentations(id) ON DELETE CASCADE,
    owner_id        UUID NOT NULL,
    spec            JSONB NOT NULL DEFAULT '{}',
    version_note    TEXT DEFAULT '',
    slide_count     INTEGER DEFAULT 0,
    chat_snapshot   JSONB DEFAULT '[]',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_presentation_versions_presentation_id
    ON presentation_versions (presentation_id);
CREATE INDEX IF NOT EXISTS idx_presentation_versions_created_at
    ON presentation_versions (created_at DESC);

ALTER TABLE presentation_versions ENABLE ROW LEVEL SECURITY;

CREATE POLICY owners_full_access ON presentation_versions
    FOR ALL USING (owner_id = auth.uid())
    WITH CHECK (owner_id = auth.uid());

-- =========================================================================
-- presentation_shares
-- =========================================================================

CREATE TABLE IF NOT EXISTS presentation_shares (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    presentation_id UUID NOT NULL REFERENCES presentations(id) ON DELETE CASCADE,
    owner_id        UUID NOT NULL,
    token           UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    visibility      TEXT NOT NULL DEFAULT 'public'
        CHECK (visibility IN ('public', 'private', 'password')),
    password_hash   TEXT,
    expires_at      TIMESTAMPTZ,
    permission       TEXT NOT NULL DEFAULT 'view'
        CHECK (permission IN ('view', 'present')),
    embed_allowed   BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_presentation_shares_presentation_id
    ON presentation_shares (presentation_id);
CREATE INDEX IF NOT EXISTS idx_presentation_shares_token
    ON presentation_shares (token);

ALTER TABLE presentation_shares ENABLE ROW LEVEL SECURITY;

CREATE POLICY owners_full_access ON presentation_shares
    FOR ALL USING (owner_id = auth.uid())
    WITH CHECK (owner_id = auth.uid());

CREATE POLICY public_read_shares ON presentation_shares
    FOR SELECT USING (
        visibility = 'public'
        OR (permission = 'view' AND (expires_at IS NULL OR expires_at > now()))
    );

-- =========================================================================
-- workspaces
-- =========================================================================

CREATE TABLE IF NOT EXISTS workspaces (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name       TEXT NOT NULL,
    owner_id   UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;

CREATE POLICY workspace_owners_full ON workspaces
    FOR ALL USING (owner_id = auth.uid())
    WITH CHECK (owner_id = auth.uid());

CREATE POLICY workspace_members_read ON workspaces
    FOR SELECT USING (
        owner_id = auth.uid()
        OR EXISTS (
            SELECT 1 FROM workspace_members
            WHERE workspace_members.workspace_id = workspaces.id
              AND workspace_members.user_id = auth.uid()
        )
    );

-- =========================================================================
-- workspace_members
-- =========================================================================

CREATE TABLE IF NOT EXISTS workspace_members (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id      UUID NOT NULL,
    role         TEXT NOT NULL DEFAULT 'viewer'
        CHECK (role IN ('owner', 'admin', 'editor', 'viewer')),
    invited_by   UUID NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_workspace_members_user_id ON workspace_members (user_id);

ALTER TABLE workspace_members ENABLE ROW LEVEL SECURITY;

CREATE POLICY members_read ON workspace_members
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM workspaces
            WHERE workspaces.id = workspace_members.workspace_id
              AND (
                  workspaces.owner_id = auth.uid()
                  OR EXISTS (
                      SELECT 1 FROM workspace_members wm2
                      WHERE wm2.workspace_id = workspaces.id
                        AND wm2.user_id = auth.uid()
                  )
              )
        )
    );

CREATE POLICY members_full_access ON workspace_members
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM workspaces
            WHERE workspaces.id = workspace_members.workspace_id
              AND (
                  workspaces.owner_id = auth.uid()
                  OR EXISTS (
                      SELECT 1 FROM workspace_members wm2
                      WHERE wm2.workspace_id = workspaces.id
                        AND wm2.user_id = auth.uid()
                        AND wm2.role IN ('owner', 'admin')
                  )
              )
        )
    );

-- =========================================================================
-- workspace_presentations
-- =========================================================================

CREATE TABLE IF NOT EXISTS workspace_presentations (
    workspace_id     UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    presentation_id  UUID NOT NULL REFERENCES presentations(id) ON DELETE CASCADE,
    added_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, presentation_id)
);

CREATE INDEX IF NOT EXISTS idx_workspace_presentations_presentation_id
    ON workspace_presentations (presentation_id);

ALTER TABLE workspace_presentations ENABLE ROW LEVEL SECURITY;

CREATE POLICY wp_read ON workspace_presentations
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM workspaces
            WHERE workspaces.id = workspace_presentations.workspace_id
              AND (
                  workspaces.owner_id = auth.uid()
                  OR EXISTS (
                      SELECT 1 FROM workspace_members
                      WHERE workspace_members.workspace_id = workspaces.id
                        AND workspace_members.user_id = auth.uid()
                  )
              )
        )
    );

CREATE POLICY wp_full ON workspace_presentations
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM workspaces
            WHERE workspaces.id = workspace_presentations.workspace_id
              AND workspaces.owner_id = auth.uid()
        )
    );

-- =========================================================================
-- workspace_audit
-- =========================================================================

CREATE TABLE IF NOT EXISTS workspace_audit (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    actor_id     UUID NOT NULL,
    action       TEXT NOT NULL,
    target       TEXT,
    payload      JSONB DEFAULT '{}',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_workspace_audit_workspace_id
    ON workspace_audit (workspace_id);

ALTER TABLE workspace_audit ENABLE ROW LEVEL SECURITY;

CREATE POLICY audit_read ON workspace_audit
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM workspaces
            WHERE workspaces.id = workspace_audit.workspace_id
              AND (
                  workspaces.owner_id = auth.uid()
                  OR EXISTS (
                      SELECT 1 FROM workspace_members
                      WHERE workspace_members.workspace_id = workspaces.id
                        AND workspace_members.user_id = auth.uid()
                  )
              )
        )
    );

CREATE POLICY audit_full ON workspace_audit
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM workspaces
            WHERE workspaces.id = workspace_audit.workspace_id
              AND workspaces.owner_id = auth.uid()
        )
    );

-- =========================================================================
-- chat_messages
-- =========================================================================

CREATE TABLE IF NOT EXISTS chat_messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    presentation_id UUID NOT NULL REFERENCES presentations(id) ON DELETE CASCADE,
    owner_id        UUID NOT NULL,
    role            TEXT NOT NULL
        CHECK (role IN ('user', 'assistant')),
    content         TEXT NOT NULL DEFAULT '',
    tool_calls      JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_presentation_id
    ON chat_messages (presentation_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_owner_id
    ON chat_messages (owner_id);

ALTER TABLE chat_messages ENABLE ROW LEVEL SECURITY;

CREATE POLICY chat_messages_owner ON chat_messages
    FOR ALL USING (owner_id = auth.uid())
    WITH CHECK (owner_id = auth.uid());
