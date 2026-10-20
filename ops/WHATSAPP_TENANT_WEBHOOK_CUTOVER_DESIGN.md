# WhatsApp webhook → tenant-account cutover (DESIGN ONLY, 2026-10-20)

**NO-GO for live activation.** This is an implementation and operational review plan, not permission to change the production/shared database, the Sendro WhatsApp endpoint, Meta callbacks, signature settings, or privacy features. The current single-business Sendro messaging must stay operational until a separately authorized, verified cutover.

## Existing, reviewed behaviour

| Path | Current implementation | Tenant/provenance risk |
|---|---|---|
| Incoming message | `backend/app/main.py::receive_whatsapp_message` reads `entry[0].changes[0].value.messages[0]`; legacy conversation found by customer number globally | Neither WABA nor destination Phone Number ID is checked or persisted as trusted company provenance |
| Delivery/status | Looks up `Message` and `TemplateBatchItem` by `whatsapp_message_id` | Lookup is not joined to an independently verified destination account |
| Reaction | Finds original message by `whatsapp_message_id` | No tenant-account-scoped match |
| Outgoing text/template | Uses process-wide `WHATSAPP_PHONE_NUMBER_ID` and one `WHATSAPP_ACCESS_TOKEN` | Cannot route safely for multiple tenants |
| Template imports/batches | `find_conversation_by_whatsapp_phone` finds legacy rows by customer number | Would associate unrelated businesses' guests if reused as multi-tenant path |
| Signature verification | Existing `WHATSAPP_WEBHOOK_SIGNATURE_REQUIRED` is optional and defaults false | Required to trust any Meta `entry.id` / `value.metadata.phone_number_id`; live flag state not independently confirmed |
| Payload iterations | Legacy handler takes only first entry/change/message | Multi-account or multi-message delivery could be silently ignored; statuses/reactions need testing too |
| Logging | Legacy handler prints guest names, numbers, message text and, for some no-message events, the full `value` | Logs should stop containing customer content/PII before SaaS rollout |
| Existing account registry | `sendro_channel_accounts` supports WhatsApp `platform` but no WhatsApp rows in earlier read-only snapshot | A runtime-approved **pair** (WABA + Phone Number ID) must have uniquely evidenced tenant ownership before any lookup |

## Tested in PR #55 and subsequent integration rehearsal

- `backend/app/whatsapp_account_routing_preflight.py` is **pure and unused** by the real webhook; requires previously verified signature and independently reviewed server-side mapping `(waba_id, phone_number_id) -> tenant_id`. This Boolean is merely a contract; the handler must cryptographically verify raw request bytes first.
- Synthetic unit tests prove distinct companies can be differentiated even with the same customer phone and that unknown/mixed destinations fail closed.
- New integration-contract tests use the **actual FastAPI webhook route** and **in-memory SQLite**, sending realistic, signed Meta-format synthetic envelopes for inbound, status, reaction and tampered signature. Neither the Meta API nor Render's DB is called.
- These tests prove backward compatibility in a safe, fabricated environment, **not** live SaaS tenant routing.

## Proposed separately approved implementation order

### Phase A — authority and storage (not applied)
1. Verify and retain external evidence for legal/controller ownership of the real WABA ID and Phone Number ID; record reviewer, date, and evidence reference *outside* GitHub.
2. Decide a tenant-scoped, uniquely indexed server-side account-to-phone registry. A WABA can have multiple Phone Number IDs; never route by business display name or only the customer's number. Prefer a separately reviewed registry with uniqueness, revocation and evidence. Do not insert in the shared DB without fresh backup and explicit approval.
3. Independently verify Meta app secret availability and inbound signature enforcement in each environment **without displaying the secret**. Fail closed on bad/unsigned input before extracting or trusting destination IDs.
4. Audit verified ownership access/permissions for all existing staff using SaaS roles, not a generic webhook admin.

### Phase B — isolated synthetic implementation
5. Build an independent **tenant-keyed conversation store** (e.g., `UNIQUE(channel_account_id, external_customer_id)` for WhatsApp, analogous to Instagram). Never reuse legacy global customer-phone lookup across tenants.
6. Parse every expected `entry`, `change`, `messages` and `statuses` item. Require atomic or durable per-delivery processing to avoid silent partial successes. Bound input size and implement idempotent Meta message ID uniqueness *within the verified account*, with controlled retry when storage fails.
7. Resolve outbound account/phone credentials from the tenant-authorized account. Do not expose access tokens to the browser; all templates, batch replies, status callbacks and reactions must check the same account scope.
8. In disposable PostgreSQL, test two businesses sharing the same guest number; forged signatures, unknown/revoked account, replay, concurrency, double delivery, statuses, reactions, media, outbound routing, and partial failure/retry.
9. Refactor request/error logs to redact guests, message text, URLs, phone numbers, tokens and signed payload bodies. Add bounded aggregate-only audit/metrics for mismatched or missing account IDs.

### Phase C — safe operator-approved staging rollout
10. Fresh restorable snapshot of **shared** DB and isolated restoration rehearsal, migration preflight, and written rollback. No schema change until explicit approval.
11. Add an independent `SENDRO_WHATSAPP_TENANT_ROUTING` opt-in, default **OFF**; staging first after isolated tests. Legacy route must not silently accept mixed-business delivery while new routing is active. Avoid a background shadow read of user data or full payload logging.
12. Confirm Meta callback environment wiring and business account origin before a **controlled pilot** using synthetic test sender and an explicitly authorized account; never modify the live Sunset Oia webhook while testing without an approved no-loss procedure.
13. Check application/Meta delivery ACK semantics (5xx on persistence error), duplicates, expected deliveries, outbound receipts and unread counts; monitor with *aggregate* metrics only, then seek separate production promotion approval.
14. Rollback must preserve new-account-associated data without recasting tenant ownership; restoring legacy behavior may not be safe after multi-tenant traffic starts. Roll back to a forward-compatible processing mode rather than global customer-phone matching.

### Phase D — historical GDPR links (separate authorization)
15. Historical ownership evidence is a different problem from new-message routing. The verified link table currently has **0 rows**; do not infer old ownership from current settings, customer phone, or a sole registered tenant.
16. Use the previously tested bounded PostgreSQL rehearsal plus independent evidence/controller sign-off and fresh backup before **any** live link insertion, privacy flag change or deletion action. Partial inventory includes template batches, media, logs, provider data and backups.

## Operational stop conditions

**Do NOT deploy active routing** if signature enforcement cannot be verified, account pair ownership is missing/ambiguous, live delivery behaviour differs from the synthetic contract, inbound/outbound/status/reaction paths are not all tenant-scoped, a rollback cannot preserve messages, or the shared DB backup is not restorable.

**This design does not authorize a production/Meta change or a live GDPR mapping.** The only immediate change is automated safety tests and documentation on `dev`.
