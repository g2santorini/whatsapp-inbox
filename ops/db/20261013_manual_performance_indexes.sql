-- Sendro 2026-10-13 — manual performance index rollout (Phase 2A).
--
-- IMPORTANT: Staging and production share the same PostgreSQL database.
-- This file is intentionally NOT invoked from any app startup, CI deploy,
-- migration hook, or Render deployment.
-- Run only after explicit owner approval and a fresh database backup.
--
-- Use psql with autocommit ON (the default), and ON_ERROR_STOP=1.
-- CREATE INDEX CONCURRENTLY cannot run inside a BEGIN/COMMIT transaction.
-- Creation is designed not to block ordinary INSERT/UPDATE/DELETE traffic,
-- but may consume CPU/IO and can still wait for transactions.
-- Run at a low-traffic time. Stop on errors; see RUNBOOK.md.

SET lock_timeout = '5s';
SET statement_timeout = '10min';

-- Frequent: GET /conversations/{id}/messages?limit=30; incremental after_id
-- and pagination before_id; latest inbound/message per conversation.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sendro_messages_conv_id_desc
    ON public.messages (conversation_id, id DESC);

-- WhatsApp incoming replay checks and delivery-status lookups.
-- A NON-UNIQUE index by design: the existing DB contains historical
-- duplicate inbound whatsapp_message_id values. Cleanup and a unique
-- constraint are separate, reviewed changes.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sendro_messages_wa_id
    ON public.messages (whatsapp_message_id)
    WHERE whatsapp_message_id IS NOT NULL;

-- Most conversations are archived. Index only the actively browsed Inbox.
-- Predicate is identical to the application's status != 'archived' filter.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sendro_conversations_inbox_updated
    ON public.conversations (updated_at DESC, id DESC)
    WHERE status <> 'archived';

-- The Projects companion live-panel sorts current chats by last_message_at.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sendro_conversations_active_recent
    ON public.conversations (last_message_at DESC, id DESC)
    WHERE status <> 'archived';

RESET lock_timeout;
RESET statement_timeout;
