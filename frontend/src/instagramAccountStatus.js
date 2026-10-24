/** Pure, fail-closed mapping for read-only Instagram registry credentials. */

import { isInstagramStagingHost } from './instagramConnectFlow.js';

const SAFE_STATUSES = Object.freeze({
  not_linked: {
    label: 'Not connected',
    description: 'No Instagram credential is stored for this account.',
  },
  stored_unverified: {
    label: 'Credential stored · Meta not checked',
    description: 'A credential exists, but current Meta permission and messaging are unverified.',
  },
  expired: {
    label: 'Credential expired',
    description: 'A new authorization is required before using this account.',
  },
});

export function canLoadInstagramAccountStatus({
  enabled = false, hostname = '', tenantId, currentUser,
  hasStatusLoader = false,
} = {}) {
  return enabled === true
    && isInstagramStagingHost(hostname)
    && Number.isSafeInteger(tenantId) && tenantId > 0
    && Number.isSafeInteger(currentUser?.id) && currentUser.id > 0
    && currentUser.mfa_enabled === true
    && (currentUser.role === 'owner' || currentUser.role === 'admin')
    && hasStatusLoader === true;
}

/** Do not infer healthy messaging or Meta authorization from a saved token. */
export function parseInstagramAccountStatus(response, expectedTenant) {
  if (!response || typeof response !== 'object' || Array.isArray(response)
    || !Number.isSafeInteger(expectedTenant) || expectedTenant <= 0
    || response.tenant_id !== expectedTenant
    || response.messaging_enabled !== false
    || response.meta_authorization_verified_now !== false
    || !Array.isArray(response.accounts) || response.accounts.length > 50) {
    throw new Error('Instagram account status unavailable');
  }
  const seen = new Set();
  const accounts = response.accounts.map((row) => {
    if (!row || typeof row !== 'object' || Array.isArray(row)
      || !Number.isSafeInteger(row.channel_account_id) || row.channel_account_id <= 0
      || seen.has(row.channel_account_id)
      || typeof row.display_name !== 'string'
      || row.display_name.length > 160
      || !['testing', 'active'].includes(row.registration_status)
      || !Object.hasOwn(SAFE_STATUSES, row.credential_status)
      || !(row.expires_at_epoch === null
        || (Number.isSafeInteger(row.expires_at_epoch) && row.expires_at_epoch > 0))
      || (row.credential_status === 'not_linked') !== (row.expires_at_epoch === null)) {
      throw new Error('Invalid Instagram account status response');
    }
    seen.add(row.channel_account_id);
    return {
      accountId: row.channel_account_id,
      registryLabel: row.display_name || 'Instagram account',
      registrationStatus: row.registration_status,
      credentialStatus: row.credential_status,
      statusLabel: SAFE_STATUSES[row.credential_status].label,
      statusDescription: SAFE_STATUSES[row.credential_status].description,
      expiresAtEpoch: row.expires_at_epoch,
    };
  });
  return { tenantId: expectedTenant, accounts, messagingEnabled: false };
}
