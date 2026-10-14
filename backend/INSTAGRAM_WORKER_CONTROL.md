# Instagram worker control — staging operator command

**No service, scheduler or auto-run is created.** The worker remains inert by
default; Meta webhook subscription and `INSTAGRAM_WEBHOOK_INGESTION_ENABLED`
remain OFF. This addition does not alter or write to the production-shared
PostgreSQL database unless the operator deliberately enables manual processing.

## Read-only inspection (safe next operator step)

Open the Render **staging backend Shell** and run from `backend/`:

```bash
python -m app.instagram_worker_control
```

Expected initial output (when the queue is empty):

```text
Instagram worker: STATUS ONLY
pending: 0
processing: 0
processed: 0
quarantined: 0
failed: 0
No deliveries processed
```

This query reads only the existing encrypted delivery queue's status totals,
not message content, user IDs, decrypted payloads, or access tokens. It
does not create or process deliveries. A nonzero count warrants investigation
before continuing.

## Manual one-delivery mode (NOT authorized to use yet)

The implementation supports an operator-only `--run-one` option, protected
by a separate `INSTAGRAM_WORKER_MANUAL_ENABLED=true` gate **and** explicit
CLI confirmation. Keep that environment variable **unset** on staging and
production for now. Never copy an enablement command casually into a shell.
A future approved test plan must verify Meta's real event envelope format,
account access, expected destination tenant, and recovery before processing.

The status command uses an existing database engine with no schema changes.
It never touches the WhatsApp webhook, user messaging permissions, Inbox
polling, or outgoing Meta API.

## Next engineering milestones

1. Verify authorized real Instagram Login webhook example(s) against our
   normalizer; handle additional subscribed event types explicitly.
2. Add a reliable gated scheduler with error metrics, backoff and recovery;
   do not make an HTTP 200 for DMs that won't be processed.
3. Implement tenant-authenticated Inbox listing, role checks, replies, and
   Instagram's customer-service window restrictions.
4. Test on a truly isolated database before enabling ingress in the
   production-shared DB. Keep a recoverable backup.
5. Decide Meta App Publish / App Review / webhook subscription only after
   end-to-end tester validations.

No new Render service or recurring hosting cost was introduced by this step.
