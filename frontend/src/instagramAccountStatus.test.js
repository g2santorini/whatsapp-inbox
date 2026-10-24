import test from 'node:test';
import assert from 'node:assert/strict';
import {
  canLoadInstagramAccountStatus, parseInstagramAccountStatus,
} from './instagramAccountStatus.js';

const USER = { id: 7, role: 'admin', mfa_enabled: true };
const STAGING = 'sendro-frontend-staging.onrender.com';

const permission = (override = {}) => ({
  enabled: true, hostname: STAGING, tenantId: 10,
  currentUser: USER, hasStatusLoader: true, ...override,
});

const account = (override = {}) => ({
  channel_account_id: 31, display_name: '@sunsetoiasailing',
  registration_status: 'testing', credential_status: 'stored_unverified',
  expires_at_epoch: 1824800000, ...override,
});

const envelope = (override = {}) => ({
  tenant_id: 10, accounts: [account()],
  messaging_enabled: false, meta_authorization_verified_now: false,
  ...override,
});

test('connection status is disabled by default, even for staging admin', () => {
  assert.equal(canLoadInstagramAccountStatus(permission({ enabled: false })), false);
  assert.equal(canLoadInstagramAccountStatus(permission({ hasStatusLoader: false })), false);
  assert.equal(canLoadInstagramAccountStatus(permission()), true);
});

test('status can never load from production or the wrong account', () => {
  for (const hostname of ['inbox.sendro-app.com','sendro-app.com','localhost','',
                          'sendro-frontend-staging.onrender.com.evil.example']) {
    assert.equal(canLoadInstagramAccountStatus(permission({ hostname })), false);
  }
  for (const currentUser of [
    null, { ...USER, role: 'operator' }, { ...USER, role: 'viewer' },
    { ...USER, mfa_enabled: false }, { ...USER, id: '7' },
  ]) {
    assert.equal(canLoadInstagramAccountStatus(permission({ currentUser })), false);
  }
  for (const tenantId of [0, -1, '10', true, 1.5]) {
    assert.equal(canLoadInstagramAccountStatus(permission({ tenantId })), false);
  }
});

test('stored token is explicitly unverified, never called an active connection', () => {
  const result = parseInstagramAccountStatus(envelope(), 10);
  assert.equal(result.accounts[0].statusLabel,
    'Credential stored · Meta not checked');
  assert.equal(result.messagingEnabled, false);
  assert.equal(result.accounts[0].accountId, 31);
  assert.equal(result.accounts[0].expiresAtEpoch, 1824800000);
});

test('registered and expired credentials stay distinguishable', () => {
  const result = parseInstagramAccountStatus(envelope({ accounts: [
    account({ credential_status: 'not_linked', expires_at_epoch: null }),
    account({ channel_account_id: 32, credential_status: 'expired',
      expires_at_epoch: 1792400000 }),
  ] }), 10);
  assert.deepEqual(result.accounts.map(x=>x.statusLabel),
    ['Not connected', 'Credential expired']);
});

test('extra fields and tokens never leak into UI mapping', () => {
  const sentinel = 'SYNTHETIC_SUPER_SECRET_NOT_FOR_UI';
  const result = parseInstagramAccountStatus(envelope({
    access_token: sentinel,
    accounts: [account({ encrypted_token: sentinel, provider_user_id: sentinel })],
  }), 10);
  assert.ok(!JSON.stringify(result).includes(sentinel));
  assert.ok(!Object.hasOwn(result.accounts[0], 'encrypted_token'));
  assert.ok(!Object.hasOwn(result.accounts[0], 'provider_user_id'));
});

test('cross-tenant response fails closed and never shows foreign accounts', () => {
  assert.throws(() => parseInstagramAccountStatus(envelope({ tenant_id: 20 }), 10));
  assert.throws(() => parseInstagramAccountStatus(envelope(), 20));
});

test('reject claims that messaging is enabled or Meta authorization was checked', () => {
  assert.throws(() => parseInstagramAccountStatus(
    envelope({ messaging_enabled: true }), 10));
  assert.throws(() => parseInstagramAccountStatus(
    envelope({ meta_authorization_verified_now: true }), 10));
});

test('invalid registry accounts and duplicates fail the whole response', () => {
  const invalidRows = [
    account({ registration_status: 'disabled' }),
    account({ credential_status: 'connected' }),
    account({ credential_status: '__proto__' }),
    account({ channel_account_id: -1 }),
    account({ display_name: null }),
    account({ expires_at_epoch: '1824800000' }),
    account({ credential_status: 'not_linked', expires_at_epoch: 1824800000 }),
    account({ credential_status: 'stored_unverified', expires_at_epoch: null }),
  ];
  for (const entry of invalidRows) {
    assert.throws(() => parseInstagramAccountStatus(envelope({ accounts:[entry] }), 10));
  }
  assert.throws(() => parseInstagramAccountStatus(envelope({
    accounts: [account(), account()],
  }), 10));
});

test('missing, malformed and oversized payloads are rejected', () => {
  for (const value of [null, undefined, {}, [],
    { ...envelope(), accounts: 'secret' },
    envelope({ accounts: Array.from({ length: 51 }, (_, i) =>
      account({ channel_account_id: i + 1 })) }),
  ]) {
    assert.throws(() => parseInstagramAccountStatus(value, 10));
  }
});
