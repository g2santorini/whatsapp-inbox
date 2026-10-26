/** Pure guardrails for the not-yet-activated Instagram Business Login UI. */

export const SENDRO_IG_STAGING_FRONTEND_HOST = 'sendro-frontend-staging.onrender.com';
export const SENDRO_IG_STAGING_BACKEND_ORIGIN = 'https://sendro-backend-staging.onrender.com';
export const SENDRO_IG_CALLBACK = SENDRO_IG_STAGING_BACKEND_ORIGIN
  + '/channels/instagram/oauth/callback';
const INSTAGRAM_AUTHORIZE_URL = 'https://www.instagram.com/oauth/authorize';

export function isInstagramStagingHost(hostname) {
  return hostname === SENDRO_IG_STAGING_FRONTEND_HOST;
}

export function canStartInstagramConnection({
  enabled = false, hostname, tenantId, channelAccountId, currentUser,
  hasStartHandler = false, hasFinishHandler = false,
} = {}) {
  return enabled === true
    && isInstagramStagingHost(hostname)
    && Number.isSafeInteger(tenantId) && tenantId > 0
    && Number.isSafeInteger(channelAccountId) && channelAccountId > 0
    && Number.isSafeInteger(currentUser?.id) && currentUser.id > 0
    && currentUser?.mfa_enabled === true
    && (currentUser.role === 'admin' || currentUser.role === 'owner')
    && hasStartHandler === true && hasFinishHandler === true;
}

function uniqueParam(url, name) {
  const values = url.searchParams.getAll(name);
  if (values.length !== 1) throw new Error('Invalid Instagram authorization response');
  return values[0];
}

/** Validate the exact provider navigation target from the authenticated backend. */
export function parseInstagramAuthorizationStart(response, nowMs = Date.now()) {
  if (!response || typeof response !== 'object'
    || typeof response.authorization_url !== 'string'
    || !Number.isInteger(response.expires_at_epoch)
    || !Number.isFinite(nowMs)) {
    throw new Error('Invalid Instagram authorization response');
  }
  const expiresAtMs = response.expires_at_epoch * 1000;
  if (expiresAtMs <= nowMs || expiresAtMs > nowMs + 360000) {
    throw new Error('Invalid Instagram authorization expiry');
  }

  let parsed;
  try { parsed = new URL(response.authorization_url); }
  catch { throw new Error('Invalid Instagram authorization URL'); }
  if (parsed.protocol !== 'https:' || parsed.username || parsed.password
    || parsed.origin + parsed.pathname !== INSTAGRAM_AUTHORIZE_URL
    || parsed.hash) {
    throw new Error('Untrusted Instagram authorization destination');
  }

  const state = uniqueParam(parsed, 'state');
  const clientId = uniqueParam(parsed, 'client_id');
  const redirectUri = uniqueParam(parsed, 'redirect_uri');
  const responseType = uniqueParam(parsed, 'response_type');
  const scope = uniqueParam(parsed, 'scope');
  if (!/^[A-Za-z0-9_-]{32,128}$/.test(state)
    || !/^\d{5,30}$/.test(clientId)
    || redirectUri !== SENDRO_IG_CALLBACK
    || responseType !== 'code'
    || scope !== 'instagram_business_basic,instagram_business_manage_messages'
    || [...parsed.searchParams.keys()].some((key) => ![
      'state', 'client_id', 'redirect_uri', 'response_type', 'scope',
    ].includes(key))) {
    throw new Error('Invalid Instagram authorization parameters');
  }

  return {
    authorizationUrl: parsed.href,
    state,
    expiresAtEpoch: response.expires_at_epoch,
  };
}

/** Never include the provider code or access token in the browser request. */
export function makeInstagramCompletionPayload(pending, {
  tenantId, channelAccountId, userId, nowMs = Date.now(),
} = {}) {
  if (!pending || !/^[A-Za-z0-9_-]{32,128}$/.test(pending.state)
    || !Number.isInteger(pending.expiresAtEpoch)
    || pending.expiresAtEpoch * 1000 <= nowMs
    || !Number.isSafeInteger(tenantId) || tenantId <= 0
    || !Number.isSafeInteger(channelAccountId) || channelAccountId <= 0
    || !Number.isSafeInteger(userId) || userId <= 0
    || pending.tenantId !== tenantId
    || pending.channelAccountId !== channelAccountId
    || pending.userId !== userId) {
    throw new Error('Instagram authorization has expired or the session changed');
  }
  return { tenant_id: tenantId, channel_account_id: channelAccountId, state: pending.state };
}
