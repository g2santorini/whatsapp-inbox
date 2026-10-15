# Sendro Instagram Phase 2L — Ephemeral PostgreSQL Integration Tests

## Goal
Verify Instagram queue behavior under **real PostgreSQL transaction locking**
without provisioning any Render service or connecting to the shared
staging/production PostgreSQL.

## Isolation guarantee
The new GitHub Actions job `instagram-postgres-integration` starts a temporary
PostgreSQL 16 Docker service inside the GitHub runner, published only on
localhost port **55439**, with dedicated database `sendro_ig_ci` and user
`sendro_ci`. Credentials are disposable CI literals and must never be reused.

The integration test fixture REFUSES to connect unless **all** match:
- GitHub Actions environment reports `GITHUB_ACTIONS=true`;
- explicit CI gate `SENDRO_INSTAGRAM_PG_CI_APPROVAL=ephemeral-local-service-only`;
- PostgreSQL driver, localhost/127.0.0.1, port 55439;
- exact database name `sendro_ig_ci` and user `sendro_ci`.

Guard validation happens **before opening any connection**. The fixture
creates a **minimal PostgreSQL test schema** modeled on the columns and
constraints used by the Instagram storage/worker modules; it DOES NOT apply
or modify the production Sendro schema. A future dedicated environment must
validate full migration compatibility separately.

## Covered tests
- Authenticated-only entrypoint contract: real network traffic and Meta
  webhook handlers are NOT invoked; fixtures simulate signed deliveries
  by directly calling the secure persistence function using fake messages.
- PostgreSQL BYTEA encrypted envelope storage, JSONB attachments,
  idempotency of deliveries and provider-message IDs.
- Two tenant accounts can receive the same customer identifier without
  leaking conversation state between them.
- Unsupported/unregistered Instagram account envelopes quarantine without
  partial message writes.
- `FOR UPDATE SKIP LOCKED`: one worker skips a row locked by another
  transaction and processes another eligible delivery without blocking.
- Concurrent workers do not double insert the same delivery or duplicate
  message IDs across two different envelopes.
- Genuine PostgreSQL serialization failure injected **after message
  INSERT**: verify all conversation/message writes roll back; only then
  schedule a compare-and-swap retry, defer it, and recover exactly once.
- A future-dated retry is skipped; WhatsApp provider rows are untouched.

## Not yet proved (next gates)
- These tests use a **minimal fixture schema**, not a production migration
  replay. Review migrations/constraints and compare them in isolated
  infrastructure before enabling customer ingestion.
- Test-only Postgres does **not** turn the supervised runner (Phase 2K-B)
  into a production service. Its guard still rejects PostgreSQL.
- No crash/restart process supervision, operational alert transport,
  long-running load test, secret manager, provider permissions review,
  or quarantine replay policies are established.
- No real Instagram DMs or native Meta webhook payloads are captured or
  verified. Unexpected Meta event kinds still require handling.

## Safety
- Instagram Webhook Subscription: **OFF**.
- `INSTAGRAM_WEBHOOK_INGESTION_ENABLED`: **OFF**.
- `INSTAGRAM_WORKER_MANUAL_ENABLED`: **OFF**.
- No Render database/service changes. No WhatsApp production/main changes.
- This is a draft PR against `dev`, pending GitHub CI review.
