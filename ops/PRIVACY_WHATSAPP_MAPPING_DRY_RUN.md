# WhatsApp GDPR ownership — read-only dry run

This procedure is a **non-mutating investigation**, not a bulk verification, import, erasure or migration. The historical owner stated that Sunset Oia Sailing Cruises was always the sole WhatsApp operator and used the same WhatsApp Business number since the beginning; that statement is helpful but **does not replace independently retained proof of which Meta account received each historical record**.

## Script and access

File: `ops/privacy_whatsapp_mapping_dry_run.py` (in the repository root).

If the Render staging backend shell starts inside `~/project/src/backend`, run:

```bash
python ../ops/privacy_whatsapp_mapping_dry_run.py
```

The environment must already have the `DATABASE_URL` configured. Do **not** paste connection strings, access tokens, customer names/numbers, or raw messages into the chat or build logs. The script uses the deployed `psycopg` dependency and opens `REPEATABLE READ, READ ONLY` with short statement and lock timeouts. It does not accept any `--apply`, `--write` or `--commit` option.

The resulting JSON contains only aggregate counts, company label, high-water conversation ID, a non-PII partial inventory and **0** ready-to-backfill, **0** writes. Exact totals may change as the live system receives traffic. Do not mistake `unverified_candidate_conversations` for verified ownership or permission to delete.

## Checks included

- Exact DB name and expected Sunset Oia tenant.
- Existing verified-link table and number of unmapped/linked/revoked/conflicting entries.
- Current conversation high-water mark, message counts and message orphan checks.
- Duplicate normalized WhatsApp phone groups and invalid E.164 phone-format counts (counts only, no values).
- Template batch entries not linked to a conversation.
- Registered tenant count and whether a WhatsApp `sendro_channel_accounts` record exists.

Even a clean result **does not authorize a backfill**. The legacy webhook did not store an independently verified inbound Meta WhatsApp business-account ID per historical conversation, and unlinked template batches exist outside the conversation link structure.

## Next stage (separate explicit approval)

1. Document the owner/controller declaration and obtain independently verifiable Meta business account/number ownership evidence; store outside the GDPR case audit and reference it safely.
2. Investigate possible business-account mixing and verify migration coverage for the historical creation interval.
3. Prepare exact-conversation staging-safe backfill with separate written approval, fresh backup, isolated PostgreSQL restore rehearsal and rollback/compensation plan.
4. Confirm behavior for new inbound/outbound WhatsApp records before enabling any multi-tenant feature.
5. Require a fresh database preflight before any manual write; never infer ownership from phone, agent/user ID, or the presence of one tenant.

**No deletion action is part of this plan.** `SENDRO_PRIVACY_WHATSAPP_VERIFIED_LINKS` remains disabled. The previously created empty mapping table remains unchanged.
