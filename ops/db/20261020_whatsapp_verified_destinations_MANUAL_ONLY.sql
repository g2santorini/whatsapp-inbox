-- Sendro WhatsApp destination ownership registry — MANUAL PROPOSAL ONLY.
--
-- NEVER execute on Render/shared staging+production DB without a NEW, specific
-- owner approval, current backup/verified restore, preflight and rollback.
-- This migration creates an EMPTY registry, DOES NOT seed business phone IDs,
-- map any legacy conversations, accept or send WhatsApp events, or enable flags.
-- CI tests replay it only in a disposable local GitHub PostgreSQL container.
--
-- Exact routing identity is the verified (WABA ID, Phone Number ID) pair.
-- Primary key on Phone Number ID prevents the same number serving two tenants.
-- Revocation is append-preserving; no silent reassignment or overwrite.
-- Store restricted source evidence OUTSIDE this database/repository, referenced
-- only by UUID. Do NOT store credentials, customer numbers or message content.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

CREATE TABLE public.sendro_whatsapp_verified_destinations (
    phone_number_id VARCHAR(32) PRIMARY KEY
        CHECK (phone_number_id ~ '^[0-9]{5,32}$'),
    waba_id VARCHAR(32) NOT NULL
        CHECK (waba_id ~ '^[0-9]{5,32}$'),
    tenant_id BIGINT NOT NULL
        REFERENCES public.sendro_tenants(id) ON DELETE RESTRICT,
    verified_by_user_id INTEGER NOT NULL,
    verification_method VARCHAR(32) NOT NULL
        CHECK (verification_method = 'manual-owner-review'),
    evidence_ref UUID NOT NULL,
    verified_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ NULL,
    CONSTRAINT fk_sendro_whatsapp_destination_reviewer
        FOREIGN KEY (tenant_id, verified_by_user_id)
        REFERENCES public.sendro_tenant_users(tenant_id, user_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_sendro_whatsapp_destination_revocation
        CHECK (revoked_at IS NULL OR revoked_at >= verified_at),
    CONSTRAINT uq_sendro_whatsapp_destination_waba_phone
        UNIQUE(waba_id, phone_number_id)
);

-- Fail closed unless the reviewer has active owner/admin membership AND an enabled user login.
CREATE FUNCTION public.sendro_whatsapp_destination_validate_reviewer()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM public.sendro_tenant_users m
        JOIN public.users u ON u.id = m.user_id
        WHERE m.tenant_id = NEW.tenant_id
          AND m.user_id = NEW.verified_by_user_id
          AND m.is_active IS TRUE
          AND m.member_role IN ('owner', 'admin')
          AND u.disabled IS FALSE
    ) THEN
        RAISE EXCEPTION 'WhatsApp destination reviewer must be an enabled active owner/admin';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_sendro_whatsapp_destination_reviewer
BEFORE INSERT ON public.sendro_whatsapp_verified_destinations
FOR EACH ROW EXECUTE FUNCTION
    public.sendro_whatsapp_destination_validate_reviewer();

-- Preserve original attestations; only a one-time valid revocation is allowed.
CREATE FUNCTION public.sendro_whatsapp_destination_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Verified WhatsApp destinations cannot be deleted';
    END IF;
    IF OLD.phone_number_id IS DISTINCT FROM NEW.phone_number_id
       OR OLD.waba_id IS DISTINCT FROM NEW.waba_id
       OR OLD.tenant_id IS DISTINCT FROM NEW.tenant_id
       OR OLD.verified_by_user_id IS DISTINCT FROM NEW.verified_by_user_id
       OR OLD.verification_method IS DISTINCT FROM NEW.verification_method
       OR OLD.evidence_ref IS DISTINCT FROM NEW.evidence_ref
       OR OLD.verified_at IS DISTINCT FROM NEW.verified_at
       OR OLD.revoked_at IS NOT NULL
       OR NEW.revoked_at IS NULL
    THEN
        RAISE EXCEPTION 'Verified WhatsApp destination is immutable except one-time revocation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_sendro_whatsapp_destination_immutable
BEFORE UPDATE OR DELETE ON public.sendro_whatsapp_verified_destinations
FOR EACH ROW EXECUTE FUNCTION
    public.sendro_whatsapp_destination_immutable();

CREATE INDEX idx_sendro_whatsapp_destination_active_waba
    ON public.sendro_whatsapp_verified_destinations(waba_id, tenant_id)
    WHERE revoked_at IS NULL;
COMMIT;
