import { useEffect, useState } from 'react';
import {
  canLoadInstagramAccountStatus,
  parseInstagramAccountStatus,
} from './instagramAccountStatus.js';
import { isInstagramStagingHost } from './instagramConnectFlow.js';
import './InstagramAccountStatusPreview.css';

/**
 * Metadata-only staging UI. Deliberately no fetch unless an independently
 * reviewed statusLoader and enabled=true are BOTH supplied. No UI tokens,
 * auto-refresh, connections, credential access or real Meta calls.
 */
export default function InstagramAccountStatusPreview({
  tenantId = null, currentUser = null, companyName = '',
  enabled = false, statusLoader,
}) {
  const hostname = typeof window === 'undefined' ? '' : window.location.hostname;
  const staging = isInstagramStagingHost(hostname);
  const canRead = canLoadInstagramAccountStatus({
    enabled, hostname, tenantId, currentUser,
    hasStatusLoader: typeof statusLoader === 'function',
  });
  const [state, setState] = useState({ phase: 'disabled', accounts: [] });

  useEffect(() => {
    if (!canRead) {
      setState({ phase: 'disabled', accounts: [] });
      return undefined;
    }
    const controller = new AbortController();
    let active = true;
    setState({ phase: 'loading', accounts: [] });
    Promise.resolve()
      .then(() => statusLoader(tenantId, { signal: controller.signal }))
      .then((payload) => {
        if (active) {
          const parsed = parseInstagramAccountStatus(payload, tenantId);
          setState({ phase: 'ready', accounts: parsed.accounts });
        }
      })
      .catch(() => {
        if (active) setState({ phase: 'error', accounts: [] });
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [tenantId, currentUser?.id, canRead, statusLoader]);

  if (!staging) return null;

  return (
    <section className="ig-account-status-preview" aria-label="Instagram account status">
      <div className="ig-account-status-heading">
        <strong>Instagram account status</strong>
        <span>READ ONLY</span>
      </div>
      <p className="ig-account-status-company">{companyName || 'Selected company'}</p>
      {state.phase === 'disabled' && (
        <p className="ig-account-status-info">
          Secure account verification has not been activated. Existing Instagram
          registrations are not confirmed as connected.
        </p>
      )}
      {state.phase === 'loading' && (
        <p className="ig-account-status-info" role="status">Checking account registry…</p>
      )}
      {state.phase === 'error' && (
        <p className="ig-account-status-info" role="alert">
          Account status could not be verified. No connection has been confirmed.
        </p>
      )}
      {state.phase === 'ready' && state.accounts.length === 0 && (
        <p className="ig-account-status-info">No Instagram accounts are registered for this business.</p>
      )}
      {state.phase === 'ready' && state.accounts.map((account) => (
        <div className="ig-account-status-row" key={account.accountId}>
          <strong>{account.registryLabel}</strong>
          <small>Account #{account.accountId} · Registry: {account.registrationStatus}</small>
          <span>{account.statusLabel}</span>
          <p>{account.statusDescription}</p>
          {account.expiresAtEpoch !== null && (
            <small>Token expiry: {new Date(account.expiresAtEpoch * 1000).toLocaleDateString()}</small>
          )}
        </div>
      ))}
      <p className="ig-account-status-footnote">
        Token status is not proof of live Meta access. Instagram messaging remains OFF.
      </p>
    </section>
  );
}
