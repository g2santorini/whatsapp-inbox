-- MANUAL PROPOSAL ONLY — INACTIVE Sendro WhatsApp registry in a DEDICATED schema.
-- DO NOT EXECUTE ON RENDER/shared DB without a fresh verified backup,
-- PostgreSQL role/ACL review, tested rollback and NEW explicit permission.
-- NEVER run on application startup. DOES NOT seed destinations, change legacy
-- WhatsApp tables, route events, contact Meta, or grant write rights to apps.
--
-- PRECONDITIONS (separately approved/provisioned by a trusted migration admin):
-- * NOLOGIN owner: sendro_whatsapp_registry_owner (NOT the legacy sendro_user)
-- * restricted LOGIN reader: sendro_whatsapp_registry_reader
-- * migration session authorized to SET ROLE to registry owner.
-- * registry owner has REFERENCES on public.sendro_tenants and
--   public.sendro_tenant_users, without changing existing application grants.
-- * role / schema name conflicts and dependencies preflighted read-only.
-- * This SQL is a competing replacement proposal for the older public.*
--   registry migration. NEVER run both versions.
--
-- Column-level SELECT only is granted to the reader. No INSERT/UPDATE/DELETE
-- or TRUNCATE, not even for a future attestor/revoker, in this initial phase.
-- Separate evidence-based account registration and revocation need later,
-- separately approved, independently audited privileges / workflows.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SET LOCAL ROLE sendro_whatsapp_registry_owner;

CREATE SCHEMA sendro_whatsapp AUTHORIZATION sendro_whatsapp_registry_owner;
REVOKE ALL ON SCHEMA sendro_whatsapp FROM PUBLIC;

CREATE TABLE sendro_whatsapp.verified_destinations (
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
    CONSTRAINT fk_whatsapp_registry_reviewer
        FOREIGN KEY (tenant_id, verified_by_user_id)
        REFERENCES public.sendro_tenant_users(tenant_id, user_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_whatsapp_registry_revocation
        CHECK (revoked_at IS NULL OR revoked_at >= verified_at),
    CONSTRAINT uq_whatsapp_registry_waba_phone
        UNIQUE(waba_id, phone_number_id)
);

CREATE FUNCTION sendro_whatsapp.validate_reviewer()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER AS $$
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
        RAISE EXCEPTION 'Reviewer must be an enabled active owner/admin';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE EXECUTE ON FUNCTION sendro_whatsapp.validate_reviewer() FROM PUBLIC;

CREATE TRIGGER trg_whatsapp_registry_reviewer
BEFORE INSERT ON sendro_whatsapp.verified_destinations
FOR EACH ROW EXECUTE FUNCTION sendro_whatsapp.validate_reviewer();

CREATE FUNCTION sendro_whatsapp.immutable_revocation()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'WhatsApp registry rows cannot be deleted';
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
        RAISE EXCEPTION 'Registry immutable except one-time revocation';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE EXECUTE ON FUNCTION sendro_whatsapp.immutable_revocation() FROM PUBLIC;

CREATE TRIGGER trg_whatsapp_registry_immutable
BEFORE UPDATE OR DELETE ON sendro_whatsapp.verified_destinations
FOR EACH ROW EXECUTE FUNCTION sendro_whatsapp.immutable_revocation();

CREATE INDEX idx_whatsapp_registry_active_waba
    ON sendro_whatsapp.verified_destinations(waba_id, tenant_id)
    WHERE revoked_at IS NULL;

GRANT USAGE ON SCHEMA sendro_whatsapp TO sendro_whatsapp_registry_reader;
GRANT SELECT (waba_id, phone_number_id, tenant_id, revoked_at)
    ON sendro_whatsapp.verified_destinations TO sendro_whatsapp_registry_reader;
COMMIT;
