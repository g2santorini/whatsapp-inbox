"""Prove the Instagram OAuth/vault DDL is BLOCKED by default and safe to
rehearse only in the specifically allowlisted ephemeral GitHub PostgreSQL.

Never executes SQL, creates tables or opens a connection to Render or to
a database supplied by a user. CI URL + approval values must pass the
existing strict independent disposable-environment allowlist.
"""
import os
from pathlib import Path

import pytest
from psycopg import ClientCursor
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from backend.tests.test_instagram_postgres_isolation import (
    TEST_URL_ENV, require_ephemeral_ci_postgres,
)

SCHEMA = (Path(__file__).parent / "fixtures" / "instagram_migrations"
          / "step7_oauth_vault_RELEASE_HOLD.sql")
RELEASE_HOLD = """DO $sendro_oauth_hold$ BEGIN
    RAISE EXCEPTION 'RELEASE HOLD: owner approval and Render log review required';
END $sendro_oauth_hold$;"""


def _execute_raw(engine, script):
    raw = engine.raw_connection()
    try:
        raw.rollback()
        with ClientCursor(raw.driver_connection) as cursor:
            cursor.execute(script)
        raw.commit()
    except BaseException:
        raw.rollback()
        raise
    finally:
        raw.close()


def test_fail_stopped_migration_and_exact_tenant_fk_on_ephemeral_pg():
    url = os.getenv(TEST_URL_ENV)
    if not url:
        pytest.skip("Only disposable GitHub PostgreSQL job can execute migration rehearsal")
    approved = require_ephemeral_ci_postgres(url, os.environ)
    script = SCHEMA.read_text(encoding="utf-8")
    assert script.count(RELEASE_HOLD) == 1
    assert script.lstrip().startswith("-- SENDRO INSTAGRAM LOGIN OAuth/vault draft")
    engine = create_engine(approved, connect_args={
        "options": "-c lock_timeout=2500 -c statement_timeout=10000",
    })
    try:
        with engine.connect() as db:
            # Must be a fresh ephemeral copy of the earlier six migration
            # fixtures, not an independently selected live account.
            for name in ("sendro_tenant_users", "sendro_channel_accounts", "users"):
                assert db.execute(text("SELECT to_regclass(:name)"), {
                    "name": f"public.{name}",
                }).scalar_one() is not None
            for name in ("sendro_instagram_oauth_challenges", "sendro_instagram_token_vault"):
                assert db.execute(text("SELECT to_regclass(:name)"), {
                    "name": f"public.{name}",
                }).scalar_one() is None

        # The REAL checked-in script must NEVER be executable without
        # explicit review and manual removal of the unconditional stop.
        with pytest.raises(Exception, match="RELEASE HOLD"):
            _execute_raw(engine, script)
        with engine.connect() as db:
            assert db.execute(text(
                "SELECT to_regclass('public.sendro_instagram_token_vault')"
            )).scalar_one() is None
            assert db.execute(text(
                "SELECT to_regclass('public.sendro_instagram_oauth_challenges')"
            )).scalar_one() is None

        # Only in the allowlisted ephemeral CI DB: remove exactly the
        # sentinel in MEMORY (never mutate or replace the repository file).
        ephemeral_only_sql = script.replace(
            RELEASE_HOLD, "-- CI ONLY: explicit runtime removal of release HOLD",
        )
        _execute_raw(engine, ephemeral_only_sql)

        with engine.begin() as db:
            t1 = db.execute(text("""
                INSERT INTO public.sendro_tenants(slug,display_name)
                VALUES ('ig-oauth-schema-ci-1','CI Only One')
                RETURNING id
            """)).scalar_one()
            t2 = db.execute(text("""
                INSERT INTO public.sendro_tenants(slug,display_name)
                VALUES ('ig-oauth-schema-ci-2','CI Only Two')
                RETURNING id
            """)).scalar_one()
            db.execute(text("INSERT INTO public.users(id) VALUES (912397)"))
            db.execute(text("""
                INSERT INTO public.sendro_tenant_users(tenant_id,user_id,member_role)
                VALUES (:tenant,912397,'owner')
            """), {"tenant": t1})
            account_id = db.execute(text("""
                INSERT INTO public.sendro_channel_accounts (
                    tenant_id, platform, external_account_id, status
                ) VALUES (:tenant,'instagram','17841402019999777','testing')
                RETURNING id
            """), {"tenant": t1}).scalar_one()
        now = 1792800000
        token_blob = b"gAAAA-SYNTHETIC-ENCRYPTED-CREDENTIAL-ONLY-IN-CI"
        code_blob = b"gAAAA-SYNTHETIC-AUTH-CODE-ONLY-IN-CI"
        with engine.begin() as db:
            db.execute(text("""
                INSERT INTO public.sendro_instagram_oauth_challenges (
                    state_hash,tenant_id,user_id,created_epoch,expires_epoch,
                    encrypted_authorization_code,received_epoch
                ) VALUES (:state,:tenant,912397,:now,:expires,:cipher,:received)
            """), dict(state="a"*64,tenant=t1,now=now,
                       expires=now+300,cipher=code_blob,received=now+2))
            db.execute(text("""
                INSERT INTO public.sendro_instagram_token_vault(
                    tenant_id,channel_account_id,provider_user_id,
                    encrypted_token,issued_epoch,expires_epoch,revision
                ) VALUES (:tenant,:account,'17841402019999777',:cipher,
                          :now,:expires,1)
            """), dict(tenant=t1,account=account_id,cipher=token_blob,
                       now=now,expires=now+60*86400))
            count = db.execute(text("""
                SELECT count(*) FROM public.sendro_instagram_token_vault
                WHERE tenant_id=:tenant AND channel_account_id=:account
            """), dict(tenant=t1,account=account_id)).scalar_one()
            assert count == 1

        # The composite tenant+account FK refuses mismatched tenant IDs.
        with pytest.raises(IntegrityError):
            with engine.begin() as db:
                db.execute(text("""
                    INSERT INTO public.sendro_instagram_token_vault(
                        tenant_id,channel_account_id,provider_user_id,
                        encrypted_token,issued_epoch,expires_epoch,revision
                    ) VALUES (:wrong,:account,'17841402019999666',:cipher,
                              :now,:expires,1)
                """),dict(wrong=t2,account=account_id,cipher=token_blob,
                           now=now,expires=now+60*86400))
        # Owner membership FK refuses a state tied to the wrong company.
        with pytest.raises(IntegrityError):
            with engine.begin() as db:
                db.execute(text("""
                    INSERT INTO public.sendro_instagram_oauth_challenges(
                        state_hash,tenant_id,user_id,created_epoch,expires_epoch
                    ) VALUES (:state,:wrong,912397,:now,:expires)
                """),dict(state="b"*64,wrong=t2,now=now,expires=now+300))
        # Broken token lifetime, invalid provider identity also fail.
        with pytest.raises(IntegrityError):
            with engine.begin() as db:
                db.execute(text("""
                    INSERT INTO public.sendro_instagram_token_vault (
                        tenant_id,channel_account_id,provider_user_id,
                        encrypted_token,issued_epoch,expires_epoch,revision
                    ) VALUES (:tenant,:account,'not-numeric',:cipher,:now,:short,1)
                """),dict(tenant=t1,account=account_id,cipher=token_blob,
                           now=now,short=now+50))
    finally:
        # No Render connection exists. Clean only the two transient OAuth
        # tables from the explicitly validated disposable GitHub database.
        with engine.begin() as db:
            db.execute(text(
                "DROP TABLE IF EXISTS public.sendro_instagram_token_vault"
            ))
            db.execute(text(
                "DROP TABLE IF EXISTS public.sendro_instagram_oauth_challenges"
            ))
        engine.dispose()
