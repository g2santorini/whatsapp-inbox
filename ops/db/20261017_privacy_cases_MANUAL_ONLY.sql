-- MANUAL PROPOSAL ONLY — not installed on Sendro or Render.
-- Staging and production SHARE a PostgreSQL database. NEVER automatically
-- execute from application startup. Require separate owner approval and a
-- verified backup/restore rehearsal before deployment.
-- These tables do not store names, phone numbers, customer IDs or message text.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

CREATE TABLE public.sendro_privacy_cases (
    case_ref VARCHAR(36) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES public.sendro_tenants(id) ON DELETE RESTRICT,
    channel VARCHAR(20) NOT NULL CHECK (channel IN ('whatsapp','instagram')),
    status VARCHAR(40) NOT NULL CHECK (
        status IN ('received','identity_checked','needs_evidence',
                   'on_hold','ready_for_manual_decision')
    ),
    scope_blockers TEXT NOT NULL DEFAULT '[]',
    response_recorded BOOLEAN NOT NULL DEFAULT FALSE,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    received_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_sendro_privacy_case_tenant_ref UNIQUE (tenant_id, case_ref),
    CONSTRAINT ck_sendro_privacy_case_timestamps CHECK (updated_at >= received_at)
);
CREATE INDEX idx_sendro_privacy_case_recent
    ON public.sendro_privacy_cases(tenant_id, received_at DESC, case_ref DESC);

CREATE TABLE public.sendro_privacy_case_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    case_ref VARCHAR(36) NOT NULL,
    seq INTEGER NOT NULL CHECK (seq >= 1),
    actor_user_id INTEGER NOT NULL,
    action VARCHAR(24) NOT NULL CHECK (
        action IN ('received','identity_checked','scope_reviewed','response_recorded')
    ),
    recorded_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_sendro_privacy_event_seq UNIQUE (case_ref, seq),
    CONSTRAINT fk_sendro_privacy_event_tenant
        FOREIGN KEY (tenant_id, case_ref)
        REFERENCES public.sendro_privacy_cases(tenant_id, case_ref) ON DELETE RESTRICT,
    CONSTRAINT fk_sendro_privacy_event_actor
        FOREIGN KEY (tenant_id, actor_user_id)
        REFERENCES public.sendro_tenant_users(tenant_id, user_id) ON DELETE RESTRICT
);

-- Protect audit log immutability at PostgreSQL level, not only in Python.
CREATE FUNCTION public.sendro_privacy_event_no_mutation() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Privacy audit events are append-only';
END;
$$;
CREATE TRIGGER trg_sendro_privacy_event_no_mutation
    BEFORE UPDATE OR DELETE ON public.sendro_privacy_case_events
    FOR EACH ROW EXECUTE FUNCTION public.sendro_privacy_event_no_mutation();
COMMIT;

-- Production rollback requires separate approval and verified no real cases.
-- No automatic rollback or DROP is authorized.
