# Instagram / SaaS tenant foundation — Manual DB step 1

**Status: prepared, not executed by application or CI.**

Both Sendro backends (staging `dev` and production `main`) use the same
PostgreSQL database. The DB operator must execute each change manually,
only after a fresh verified backup and owner approval.

## Phase 2B — Step 1: tenant catalog

Script: `ops/db/20261014_instagram_tenants_step1.sql`.

Creates **one new empty table**, `public.sendro_tenants`.
Its `slug` uniquely identifies a company (e.g. `sunset-oia` in a later
step), and `display_name` is its human-readable title.

It does not modify or query WhatsApp data, create users, grant anyone access,
activate Instagram message ingestion, or create test data.

### Preflight

Check this statement returns **no rows**:

```sql
SELECT tablename
FROM pg_catalog.pg_tables
WHERE schemaname = 'public' AND tablename = 'sendro_tenants';
```

### Manual execution

Use a direct database SQL session (or a backend staging shell through
SQLAlchemy) and run the migration **once** inside its explicit transaction.
A 5-second lock timeout and 30-second statement timeout prevent extended
waiting on other operations. Never copy production credentials into chat.

Do not automatically execute it during GitHub CI or backend startup.

### Verification

```sql
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'sendro_tenants'
ORDER BY ordinal_position;
```

Should contain `id`, `slug`, `display_name`, `created_at` (4 rows).
The table should have no rows yet.

### If migration fails

The explicit transaction rolls back, including the attempted CREATE TABLE.
Stop and inspect the exact error before retrying. Never use `IF NOT EXISTS`
to conceal an unexpectedly different existing table.

### Next phase (not authorized by this step)

Create tenant membership and channel-scoped account/message/webhook tables
using separately prepared, tested migrations. No roles or tenant membership
are inserted at this stage. Do not activate the Instagram webhook subscription.

### Rollback warning

Do not drop the table unless the owner separately approves. Once dependent
tenant/channel data exists, dropping it could cause data loss.
