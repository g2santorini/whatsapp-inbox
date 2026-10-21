import { useMemo, useState } from 'react';
import { buildIncidentCenterRows } from './instagramIncidentRows';
import './InstagramIncidentCenterPreview.css';

/**
 * Dormant, presentational prototype. There are deliberately NO API calls,
 * no timers, no live user/tenant reads and no imports from App.jsx.
 * A FUTURE authorized parent must independently enforce recent MFA and
 * global responder privileges on the server and explicitly supply records.
 */
export default function InstagramIncidentCenterPreview({
  incidents = [],
  loading = false,
  error = '',
  onAcknowledge,
}) {
  const rows = useMemo(() => buildIncidentCenterRows(incidents), [incidents]);
  const [busyKey, setBusyKey] = useState('');
  const [message, setMessage] = useState('');

  async function review(item) {
    if (!item.canReview || typeof onAcknowledge !== 'function') return;
    const key = `${item.code}:${item.episode}`;
    setBusyKey(key);
    setMessage('');
    try {
      // The callback does NOT exist in production. It must eventually call
      // an authenticated, step-up MFA backend with fresh exact-version checks.
      await onAcknowledge(item.code, item.episode);
      setMessage('Review request accepted. Refresh the incident list to verify.');
    } catch {
      setMessage('Could not record the review. The incident is still open.');
    } finally {
      setBusyKey('');
    }
  }

  return (
    <section className="ig-incident-center" aria-label="Instagram incident center preview">
      <header className="ig-incident-center-heading">
        <div>
          <h2>Instagram Incident Center</h2>
          <p>Operational alerts only. No guest messages or customer details.</p>
        </div>
        <span className="ig-incident-center-preview-pill">NOT LIVE</span>
      </header>

      {error && <p role="alert" className="ig-incident-center-error">
        Incident status is unavailable. No alerts have been dismissed.
      </p>}
      {loading && <p role="status">Loading incident status…</p>}
      {!loading && !error && rows.length === 0 &&
        <p>No incidents supplied to this preview.</p>}

      {!error && (
        <ul className="ig-incident-center-list">
          {rows.map((item) => (
            <li key={`${item.code}:${item.episode}`}>
              <div className="ig-incident-center-row">
                <div>
                  <strong>{item.label}</strong>
                  <small>Incident {item.episode} · {item.active ? 'Active' : 'Resolved'}</small>
                </div>
                <span className="ig-incident-center-state">{item.status}</span>
                <button type="button"
                  disabled={!item.canReview || busyKey !== '' || typeof onAcknowledge !== 'function'}
                  onClick={() => review(item)}>
                  {item.status === 'acknowledged' ? 'Reviewed' : 'Confirm review'}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {message && <p role="status" className="ig-incident-center-message">{message}</p>}
      <p className="ig-incident-center-note">
        A transport acknowledgment does not prove an operator has reviewed an alert.
        The live Incident Center has not been enabled.
      </p>
    </section>
  );
}
