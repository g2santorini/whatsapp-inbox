# Legacy WhatsApp ownership: evidence register and backfill gate

**Status: preliminary evidence gathered; historical ownership mapping NOT approved or executed.** No client data or tokens in this repository. The tenant-link mapping table is already created but was empty at last check. `SENDRO_PRIVACY_WHATSAPP_VERIFIED_LINKS` stays OFF; erasure remains OFF.

## Evidence we have (2026-10-19)

1. The business operator confirmed in this conversation that Sunset Oia Sailing Cruises was the **only business** using Sendro's WhatsApp since its beginning, and that it used **the same WhatsApp Business number throughout**. This is an operator declaration, *not per-row historical proof*.
2. Read-only Meta UI walkthrough showed a WhatsApp Business Account named **Sunset Oia Sailing Cruises Santorini**, and displayed its registered number, WABA ID and Phone Number ID. The Meta Business Portfolio owning that WABA appeared as **George Georgoulas** — distinct from the portfolio labelled Sunset Oia Business which showed no WABA.
3. A no-token staging Render Shell check confirmed that the configured `WHATSAPP_PHONE_NUMBER_ID` exactly matches the Phone Number ID shown in the Meta UI. **Production was NOT independently checked**: the later Shell output was still from staging. Do not claim production validation.
4. The legacy WhatsApp tables lack a trustworthy persisted receiving WABA/Meta Phone Number ID per row. Historical webhook lookup is global by customer phone; current Meta/staging equality alone does not prove every historical conversation was received on that account.
5. Earlier read-only snapshot: 25,511 unmapped conversations, zero mapped, zero duplicate normalized phone groups or orphan messages; 1,528 template batch items without a linked conversation. Counts change as messages arrive.

## Restricted evidence packet to retain outside GitHub and case-event metadata

- An independently retained, dated Meta **WhatsApp Manager** screenshot or official business asset export showing account name, ownership portfolio, WABA ID, Phone Number ID and connection status; redact credentials and customer identifiers. Record file hash, capture timestamp and restricted storage location in a separate evidence registry.
- Responsible controller/operator attestation specifying the exact business legal entity/controller relationship, historical time window, number never changed, no third-party/second business use, and whether any agency or BSP ever controlled/relayed the number. The UI asset ownership portfolio being a person's name does **not** automatically prove the legal controller of customer data.
- Compare expected Meta phone ID with the Render staging and (when possible, separately) production configured phone IDs **without displaying any access token**. Retain only match/mismatch, time and authorized reviewer.
- Independently confirm which Meta business account received historical messages from operational/business records (e.g. Meta activity/archive or prior configuration change history). Record any uncertainty, gaps and exceptions; unresolved cohorts must remain unmapped.
- Create a private evidence reference (UUID) and reviewer attestation with appropriate retention and restricted access. **Do not create fabricated evidence references or publish screenshots in the repo.**

## Technical protocol proposed; NOT authorized to run

1. Take a fresh production-shared DB backup and verify recovery in an isolated PostgreSQL clone.
2. Review current webhook and all outbound code paths: future conversations must be stamped with verified tenant/account provenance from authenticated routing, not inferred from customer phone or user ID. Keep staging/production feature flags OFF.
3. Freeze the proposed historical cohort at an explicit `conversation_id` high-water boundary **only after** independent evidence confirms coverage. Since traffic is live, new conversations after that point need a separate pathway. Do not block real customer messages.
4. Run the no-write `ops/privacy_whatsapp_mapping_dry_run.py` and `ops/privacy_whatsapp_backfill_plan.py`. These return only aggregate counts; `estimated_planning_batches` is *planning*, not permission for inserts.
5. After reviewer/owner sign-off, prepare an idempotent exact-conversation assignment procedure with foreign-key/reviewer/evidence checks and preflight for conflicting, previously verified, revoked, cross-tenant or already mapped rows. It must reject unexpected changes, log the job outside customer-facing logs, and use small bounded transactions with rollback/recovery instructions.
6. Independently test with **synthetic rows on disposable PostgreSQL**: tenant separation, a revoked link, pre-existing conflicts, changes during run, partial failure, idempotency, and no disclosure or erasure.
7. Ask for a **new separate explicit approval** before any manual insert into the live/shared database, or activating `SENDRO_PRIVACY_WHATSAPP_VERIFIED_LINKS`.

No bulk update to `conversations` or `messages`. The map is a separate ownership evidence index, not a customer-identity verification and not a deletion list. The unlinked template batches, media, provider-held copies, audit logs and backups remain **outside** any such partial inventory.

## Read-only planning usage

From Render staging backend Shell (only when asked, not necessary now):

```bash
python ../ops/privacy_whatsapp_backfill_plan.py
```

The command uses `DATABASE_URL`, accesses a read-only PostgreSQL transaction, prints aggregate stats only, and has no write/apply mode. Do not share or print connection URLs or tokens. All repository code changes in this step are operations-only and should not affect the running API.

**Go/no-go: currently NO-GO for live backfill.** A successful dry run only establishes possible candidate counts, not ownership proof or approval.
