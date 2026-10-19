-- MANUAL PROPOSAL ONLY. NOT A RUNTIME MIGRATION.
-- DO NOT APPLY to the production-shared Sendro DB without new explicit
-- owner approval, verified fresh backup, schema preflight and rollback plan.
-- This creates only an EMPTY table. It does NOT assign existing conversations
-- to a tenant, does NOT add phone/customer identifiers, and never deletes data.
--
-- Once independently verified, a separately approved/manual procedure may
-- insert individual conversation links. Never bulk-map by user_id, assigned
-- agent, customer number, tenant count, or "this company is the only tenant".
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

CREATE TABLE public.sendro_privacy_legacy_whatsapp_links (
    conversation_id integer PRIMARY KEY
        REFERENCES public.conversations(id) ON DELETE RESTRICT,
    tenant_id bigint NOT NULL
        REFERENCES public.sendro_tenants(id) ON DELETE RESTRICT,
    verified_by_user_id integer NOT NULL,
    verification_method varchar(32) NOT NULL
        CHECK (verification_method = 'manual-owner-review'),
    evidence_ref uuid NOT NULL,
    verified_at timestamptz NOT NULL,
    revoked_at timestamptz NULL,
    CONSTRAINT fk_privacy_legacy_whatsapp_reviewer
        FOREIGN KEY (tenant_id, verified_by_user_id)
        REFERENCES public.sendro_tenant_users(tenant_id, user_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_privacy_legacy_whatsapp_revocation_time
        CHECK (revoked_at IS NULL OR revoked_at >= verified_at)
);
CREATE INDEX idx_privacy_legacy_whatsapp_tenant
    ON public.sendro_privacy_legacy_whatsapp_links(tenant_id, conversation_id);
COMMIT;
