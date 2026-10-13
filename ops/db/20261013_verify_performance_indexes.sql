-- Sendro 2026-10-13 — read-only PostgreSQL index and query-plan checks.
-- Safe to run before and after the manual index rollout.
-- EXPLAIN (without ANALYZE) does NOT execute the workload.
-- The example conversation id is arbitrary; no message content is returned.

-- Inventory including whether an index is valid/ready.
SELECT
    t.relname AS table_name,
    i.relname AS index_name,
    ix.indisvalid AS is_valid,
    ix.indisready AS is_ready,
    pg_size_pretty(pg_relation_size(i.oid)) AS index_size
FROM pg_class t
JOIN pg_index ix ON ix.indrelid = t.oid
JOIN pg_class i ON i.oid = ix.indexrelid
WHERE t.relname IN ('messages', 'conversations')
  AND t.relnamespace = 'public'::regnamespace
ORDER BY t.relname, i.relname;

-- Count only: no guest message bodies or phone numbers.
SELECT
    (SELECT COUNT(*) FROM public.messages) AS messages,
    (SELECT COUNT(*) FROM public.conversations) AS conversations,
    (SELECT COUNT(*) FROM public.conversations WHERE status <> 'archived') AS active_conversations;

EXPLAIN
SELECT id, content, direction
FROM public.messages
WHERE conversation_id = 3724
ORDER BY id DESC
LIMIT 30;

EXPLAIN
SELECT id, content
FROM public.messages
WHERE conversation_id = 3724
  AND id > 50000
ORDER BY id
LIMIT 30;

EXPLAIN
SELECT id
FROM public.messages
WHERE whatsapp_message_id = 'wamid.synthetic-check-does-not-exist'
LIMIT 1;

EXPLAIN
SELECT id, updated_at
FROM public.conversations
WHERE status <> 'archived'
ORDER BY updated_at DESC, id DESC
LIMIT 61;

EXPLAIN
SELECT id, last_message_at
FROM public.conversations
WHERE status <> 'archived'
ORDER BY last_message_at DESC, id DESC
LIMIT 6;
