-- SENDRO INSTAGRAM LOGIN OAuth/vault draft — REVIEW ONLY, intentionally BLOCKED.
-- NEVER execute against shared Render staging/production PostgreSQL.
-- BEGIN + unconditional RAISE EXCEPTION means the transaction aborts
-- BEFORE the first CREATE TABLE, even if someone runs this file by mistake.
-- The hold may be removed only in a separately owner-approved, reviewed
-- operator-run migration after full offline rehearsal, verified restore,
-- scoped access review and a safe callback-log investigation.
--
-- Prerequisites present in current GitHub migration snapshots:
-- public.sendro_tenant_users PRIMARY KEY (tenant_id, user_id)
-- public.sendro_channel_accounts UNIQUE (id, tenant_id)
--
-- Not attached to FastAPI startup or deploy scripts. No GRANTs or data inserts.

BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

-- CI ONLY: exact release hold sentinel; DO NOT REMOVE IN DEPLOYABLE REPO.
DO $sendro_oauth_hold$ BEGIN
    RAISE EXCEPTION 'RELEASE HOLD: owner approval and Render log review required';
END $sendro_oauth_hold$;

CREATE TABLE public.sendro_instagram_oauth_challenges (
    state_hash CHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    user_id INTEGER NOT NULL,
    created_epoch BIGINT NOT NULL,
    expires_epoch BIGINT NOT NULL,
    encrypted_authorization_code BYTEA NULL,
    received_epoch BIGINT NULL,

    CONSTRAINT fk_ig_oauth_exact_owner
        FOREIGN KEY (tenant_id, user_id)
        REFERENCES public.sendro_tenant_users (tenant_id, user_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_ig_oauth_hash
        CHECK (state_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_ig_oauth_created
        CHECK (created_epoch > 0),
    CONSTRAINT ck_ig_oauth_five_minute_window
        CHECK (expires_epoch > created_epoch
               AND expires_epoch <= created_epoch + 300),
    CONSTRAINT ck_ig_oauth_callback_pair
        CHECK ((encrypted_authorization_code IS NULL)
            = (received_epoch IS NULL)),
    CONSTRAINT ck_ig_oauth_ciphertext
        CHECK (encrypted_authorization_code IS NULL
               OR OCTET_LENGTH(encrypted_authorization_code) > 32),
    CONSTRAINT ck_ig_oauth_received
        CHECK (received_epoch IS NULL OR
               (received_epoch >= created_epoch
                AND received_epoch < expires_epoch))
);

CREATE INDEX idx_ig_oauth_expiry
    ON public.sendro_instagram_oauth_challenges (expires_epoch);

-- Server-side Fernet envelope purpose/binding checks remain mandatory;
-- encryption alone does not replace a separate least-privilege DB role.
CREATE TABLE public.sendro_instagram_token_vault (
    tenant_id BIGINT NOT NULL,
    channel_account_id BIGINT NOT NULL,
    provider_user_id VARCHAR(128) NOT NULL,
    encrypted_token BYTEA NOT NULL,
    issued_epoch BIGINT NOT NULL,
    expires_epoch BIGINT NOT NULL,
    revision BIGINT NOT NULL DEFAULT 1,

    CONSTRAINT pk_ig_token_vault
        PRIMARY KEY (tenant_id, channel_account_id),
    CONSTRAINT fk_ig_vault_exact_account
        FOREIGN KEY (channel_account_id, tenant_id)
        REFERENCES public.sendro_channel_accounts (id, tenant_id)
        ON DELETE RESTRICT,
    CONSTRAINT uq_ig_vault_provider
        UNIQUE (provider_user_id),
    CONSTRAINT ck_ig_vault_provider_numeric
        CHECK (provider_user_id ~ '^[0-9]{1,128}$'),
    CONSTRAINT ck_ig_vault_ciphertext_nonempty
        CHECK (OCTET_LENGTH(encrypted_token) > 32),
    CONSTRAINT ck_ig_vault_lifetime
        CHECK (issued_epoch > 0 AND
               expires_epoch - issued_epoch BETWEEN 86400 AND 5356800),
    CONSTRAINT ck_ig_vault_revision
        CHECK (revision >= 1)
);

-- No GRANT, role creation, token, webhook, Meta call, worker or sample
-- customer/production row here. The actual migration and key management
-- still require a separately approved deployment plan and rollback.
COMMIT;
