import { useEffect, useRef, useState } from 'react';
import {
  canStartInstagramConnection, isInstagramStagingHost,
  parseInstagramAuthorizationStart, makeInstagramCompletionPayload,
} from './instagramConnectFlow.js';
import './InstagramConnectPreview.css';

/**
 * Staging-only onboarding surface. DISABLED BY DEFAULT.
 * The containing Sendro Instagram Inbox passes enabled={false} and no API
 * callbacks until a separately reviewed activation. No polling, storage,
 * Meta calls, or background work on render.
 */
export default function InstagramConnectPreview({
  tenantId = null,
  companyName = '',
  channelAccountId = null,
  currentUser = null,
  enabled = false,
  startConnection,
  finishConnection,
}) {
  const [phase, setPhase] = useState('idle');
  const [notice, setNotice] = useState('');
  const pendingRef = useRef(null);
  const popupRef = useRef(null);
  const busyRef = useRef(false);
  const hostname = typeof window === 'undefined' ? '' : window.location.hostname;

  const allowed = canStartInstagramConnection({
    enabled, hostname, tenantId, channelAccountId, currentUser,
    hasStartHandler: typeof startConnection === 'function',
    hasFinishHandler: typeof finishConnection === 'function',
  });
  const staging = isInstagramStagingHost(hostname);
  const waiting = phase === 'awaiting';
  const busy = phase === 'requesting' || phase === 'completing';

  useEffect(() => {
    pendingRef.current = null;
    busyRef.current = false;
    try { popupRef.current?.close(); } catch { /* already closed */ }
    popupRef.current = null;
    setPhase('idle');
    setNotice('');
  }, [tenantId, channelAccountId, currentUser?.id]);

  useEffect(() => () => {
    pendingRef.current = null;
    try { popupRef.current?.close(); } catch { /* no popup */ }
  }, []);

  if (!staging) return null;

  function cancel() {
    pendingRef.current = null;
    busyRef.current = false;
    try { popupRef.current?.close(); } catch { /* user already closed it */ }
    popupRef.current = null;
    setPhase('idle');
    setNotice('Connection cancelled. No Instagram account was connected.');
  }

  async function connect() {
    if (!allowed || busyRef.current || pendingRef.current) return;
    // Popup must be created during a real click, before awaiting network.
    // Do not place Meta's OAuth URL in the original Sendro tab/history.
    const popup = window.open('about:blank', '_blank', 'popup,width=540,height=740');
    if (!popup) {
      setNotice('Allow the Instagram sign-in window and try again.');
      return;
    }
    popup.opener = null;
    popupRef.current = popup;
    busyRef.current = true;
    setPhase('requesting');
    setNotice('');
    try {
      const result = await startConnection({ tenant_id: tenantId });
      const parsed = parseInstagramAuthorizationStart(result);
      if (!allowed || popupRef.current !== popup || popup.closed) {
        throw new Error('Instagram sign-in window was closed');
      }
      pendingRef.current = {
        state: parsed.state, expiresAtEpoch: parsed.expiresAtEpoch,
        tenantId, channelAccountId, userId: currentUser.id,
      };
      // Only a pinned instagram.com authorization URL is navigable here.
      popup.location.replace(parsed.authorizationUrl);
      setPhase('awaiting');
      setNotice('After approving access on Instagram, return here and choose Complete connection.');
    } catch {
      pendingRef.current = null;
      try { popup.close(); } catch { /* no popup */ }
      popupRef.current = null;
      setPhase('idle');
      setNotice('Instagram connection could not be started. Please try again.');
    } finally {
      busyRef.current = false;
    }
  }

  async function complete() {
    if (!allowed || !waiting || !pendingRef.current || busyRef.current) return;
    busyRef.current = true;
    setPhase('completing');
    setNotice('');
    try {
      const body = makeInstagramCompletionPayload(pendingRef.current, {
        tenantId, channelAccountId, userId: currentUser.id,
      });
      // This calls an authenticated Sendro API only. No provider token/code
      // is sent to or handled by React. The backend verifies the real profile.
      const result = await finishConnection(body);
      if (result?.connected !== true
        || !Number.isInteger(result.expires_at_epoch)
        || result.expires_at_epoch * 1000 <= Date.now()) {
        throw new Error('Instagram connection has not been confirmed');
      }
      pendingRef.current = null;
      try { popupRef.current?.close(); } catch { /* user may have closed popup */ }
      popupRef.current = null;
      setPhase('connected');
      setNotice('Instagram authorization confirmed for this session. Messaging remains disabled.');
    } catch {
      // The backend may have consumed the OAuth state; never retry it.
      pendingRef.current = null;
      try { popupRef.current?.close(); } catch { /* no popup */ }
      popupRef.current = null;
      setPhase('idle');
      setNotice('The connection was not confirmed. Start a new Instagram authorization.');
    } finally {
      busyRef.current = false;
    }
  }

  return (
    <section className="ig-connect-preview" aria-label="Instagram account connection">
      <div className="ig-connect-header">
        <div>
          <strong>Instagram account connection</strong>
          <p>{companyName || 'Selected company'}</p>
        </div>
        <span className="ig-connect-status">{phase === 'connected'
          ? 'SESSION CONFIRMED' : 'SETUP PREVIEW'}</span>
      </div>

      {!allowed && (
        <p className="ig-connect-explanation">
          The Instagram connection is not active yet. We are preparing secure
          authorization and account verification. No messages will be sent or received.
        </p>
      )}
      {allowed && !waiting && phase !== 'connected' && (
        <p className="ig-connect-explanation">
          Connect your Instagram Professional account in a separate window.
          Only authorized company administrators can complete this step.
        </p>
      )}
      {waiting && (
        <p className="ig-connect-explanation">
          Finish authorization on Instagram, then return to this Sendro tab.
          If you refreshed or switched accounts, start again.
        </p>
      )}
      {phase === 'connected' && (
        <p className="ig-connect-explanation">
          This session was confirmed by Sendro. A permanent account-status
          screen will be available after the final onboarding review.
        </p>
      )}

      <div className="ig-connect-actions">
        {!waiting && phase !== 'connected' && (
          <button type="button" onClick={connect} disabled={!allowed || busy}>
            {phase === 'requesting' ? 'Opening Instagram…' : 'Connect Instagram'}
          </button>
        )}
        {waiting && (
          <>
            <button type="button" onClick={complete} disabled={!allowed || busy}>
              Complete connection
            </button>
            <button className="ig-connect-secondary" type="button"
              onClick={cancel} disabled={busy}>Cancel</button>
          </>
        )}
        {phase === 'completing' && <span>Verifying account…</span>}
      </div>
      {notice && <p className="ig-connect-notice" role="status">{notice}</p>}
      <p className="ig-connect-footnote">
        Staging only · Instagram Direct Messages remain OFF · No Meta App Review submission
      </p>
    </section>
  );
}
