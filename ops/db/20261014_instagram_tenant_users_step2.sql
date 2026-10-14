-- Sendro Instagram/SaaS foundation: Step 2 — empty tenant-user membership.
-- MANUAL EXECUTION ONLY. Staging and production share one PostgreSQL DB.
-- No changes to legacy users, messages, conversations, or WhatsApp hooks.
-- Do not execute until the owner has approved and a backup exists.
--
-- Prerequisite: public.sendro_tenants must exist.
-- This SQL is intended to be executed once; stop if the table already exists.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

CREATE TABLE public.sendro_tenant_users (
    tenant_id BIGINT NOT NULL
        REFERENCES public.sendro_tenants(id) ON DELETE RESTRICT,
    user_id INTEGER NOT NULL
        REFERENCES public.users(id) ON DELETE RESTRICT,
    member_role VARCHAR(20) NOT NULL DEFAULT 'operator',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_sendro_tenant_users PRIMARY KEY (tenant_id, user_id),
    CONSTRAINT ck_sendro_tenant_users_role
        CHECK (member_role IN ('owner','admin','operator','viewer'))
);

-- Primary-key index serves tenant lookups; this supports querying
-- tenant memberships when only the user ID is known.
CREATE INDEX idx_sendro_tenant_users_user
    ON public.sendro_tenant_users (user_id);

COMMIT;

-- Expected verification: 5 columns; 0 rows until explicitly assigned.
-- No users are granted any membership during this step.
