-- MANUAL PROPOSAL ONLY. DO NOT APPLY to staging/production-shared
-- Sendro PostgreSQL without separate explicit owner approval and verified
-- backup/restore plan. Required before enabling manual email intake.
-- No runtime migrations. Confirm exact old constraint in pg_constraint first.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
ALTER TABLE public.sendro_privacy_cases
    DROP CONSTRAINT sendro_privacy_cases_channel_check;
ALTER TABLE public.sendro_privacy_cases
    ADD CONSTRAINT sendro_privacy_cases_channel_check
    CHECK (channel IN ('whatsapp','instagram','email'));
COMMIT;
