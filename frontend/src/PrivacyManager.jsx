import { useEffect, useState } from 'react';
import sendroLogo from './assets/sendro_logo_reversed.png';
import WorkspaceTabs from './WorkspaceTabs';
import {
  getPrivacyCases, getPrivacyCase, getPrivacyWorkflowStatus,
  createPrivacyRequest, verifyPrivacyIdentity, reviewPrivacyScope,
  recordPrivacyResponse,
} from './api';
import './PrivacyManager.css';

const REVIEW_FIELDS = [
  ['controller_authority_confirmed', 'Company authority confirmed'],
  ['identity_authority_verified', 'Identity or authority independently checked'],
  ['tenant_scope_checked', 'Correct company and request scope'],
  ['whatsapp_records_checked', 'WhatsApp conversations reviewed'],
  ['instagram_records_checked', 'Instagram conversations reviewed'],
  ['template_batches_checked', 'Outbound templates and batches reviewed'],
  ['unlinked_batch_items_checked', 'Unlinked booking/template items reviewed'],
  ['media_checked', 'Attachments and media reviewed'],
  ['provider_copies_checked', 'Meta / provider copies reviewed'],
  ['application_logs_checked', 'Application logs reviewed'],
  ['backup_restore_plan_checked', 'Backup and restore plan reviewed'],
  ['retention_exceptions_checked', 'Legal retention exceptions reviewed'],
];

function oneMonthTarget(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  const y = date.getUTCFullYear();
  const m = date.getUTCMonth();
  const day = date.getUTCDate();
  const maxDay = new Date(Date.UTC(y, m + 2, 0)).getUTCDate();
  const next = new Date(Date.UTC(y, m + 1, Math.min(day, maxDay)));
  return next.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC' });
}

function privacyError(error) {
  if (error?.status === 403) {
    return 'Your GDPR access requires a fresh Authenticator sign-in (within 10 minutes) and an active owner/admin company membership. Sign out, sign back in with Authenticator, and try again.';
  }
  if (error?.status === 401) return 'Your sign-in has expired. Please sign in again.';
  if (error?.status === 429) return 'Too many GDPR requests. Wait one minute before refreshing.';
  if (error?.status === 404) return 'This GDPR request is no longer available to your company.';
  return 'Could not load GDPR preview. Please try again.';
}

function formatCaseRef(value) {
  return typeof value === 'string' ? value.slice(0, 8).toUpperCase() : '—';
}

export default function PrivacyManager({
  currentUser, tenants, onWhatsApp, onInstagram, onProjects, onLogout,
}) {
  const [tenantId, setTenantId] = useState(() => tenants[0]?.id ?? null);
  const [cases, setCases] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [refreshId, setRefreshId] = useState(0);
  const [selectedRef, setSelectedRef] = useState(null);
  const [details, setDetails] = useState(null);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [detailsError, setDetailsError] = useState('');
  const [workflowEnabled, setWorkflowEnabled] = useState(false);
  const [creating, setCreating] = useState(false);
  const [requestSource, setRequestSource] = useState('email');
  const [working, setWorking] = useState(false);
  const [notice, setNotice] = useState('');
  const [scopeChecks, setScopeChecks] = useState({});
  const [legalHold, setLegalHold] = useState('unknown');
  const [scopeOpen, setScopeOpen] = useState(false);

  const allowedTenant = tenants.some((tenant) => tenant.id === tenantId);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    getPrivacyWorkflowStatus({ signal: controller.signal })
      .then((status) => {
        if (active) setWorkflowEnabled(status?.manual_workflow_enabled === true &&
          status?.erasure_enabled === false);
      })
      .catch(() => {
        if (active) setWorkflowEnabled(false);
      });
    return () => { active = false; controller.abort(); };
  }, []);

  useEffect(() => {
    if (!allowedTenant) return undefined;
    const controller = new AbortController();
    let active = true;
    getPrivacyCases(tenantId, { signal: controller.signal })
      .then((items) => {
        if (active) {
          setCases(items);
          setError('');
        }
      })
      .catch((cause) => {
        if (active && cause?.name !== 'AbortError') {
          setCases([]);
          setError(privacyError(cause));
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [tenantId, allowedTenant, refreshId]);

  useEffect(() => {
    if (!allowedTenant || !selectedRef) return undefined;
    const controller = new AbortController();
    let active = true;
    getPrivacyCase(tenantId, selectedRef, { signal: controller.signal })
      .then((item) => {
        if (active) {
          setDetails(item);
          setDetailsError('');
        }
      })
      .catch((cause) => {
        if (active && cause?.name !== 'AbortError') {
          setDetails(null);
          setDetailsError(privacyError(cause));
        }
      })
      .finally(() => {
        if (active) setDetailsLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [tenantId, allowedTenant, selectedRef]);

  function chooseTenant(event) {
    const id = Number(event.target.value);
    if (!tenants.some((tenant) => tenant.id === id)) return;
    setTenantId(id);
    setCases([]);
    setSelectedRef(null);
    setDetails(null);
    setError('');
    setDetailsError('');
    setNotice('');
    setCreating(false);
    setScopeChecks({});
    setLegalHold('unknown');
    setScopeOpen(false);
    setLoading(true);
  }

  function selectCase(caseRef) {
    setSelectedRef(caseRef);
    setDetails(null);
    setDetailsError('');
    setDetailsLoading(true);
    setNotice('');
    setScopeChecks({});
    setLegalHold('unknown');
    setScopeOpen(false);
  }

  function refresh() {
    setSelectedRef(null);
    setDetails(null);
    setDetailsError('');
    setLoading(true);
    setRefreshId((value) => value + 1);
  }

  async function runCaseAction(action) {
    if (!workflowEnabled || !allowedTenant || working) return;
    setWorking(true);
    setError('');
    setDetailsError('');
    setNotice('');
    try {
      const updated = await action();
      setSelectedRef(updated.case_ref);
      setDetails(updated);
      setRefreshId((value) => value + 1);
      setNotice('Saved with an audit event. No customer data was deleted or sent.');
      setScopeOpen(false);
    } catch (cause) {
      setDetailsError(privacyError(cause));
    } finally {
      setWorking(false);
    }
  }

  async function submitNewRequest(event) {
    event.preventDefault();
    if (!workflowEnabled || !allowedTenant || working) return;
    setWorking(true);
    setError('');
    setNotice('');
    try {
      const created = await createPrivacyRequest(tenantId, requestSource);
      setCreating(false);
      setSelectedRef(created.case_ref);
      setDetails(created);
      setRefreshId((value) => value + 1);
      setNotice('Case created. Keep the customer request in the company’s restricted inbox, using this reference to link it.');
    } catch (cause) {
      setError(privacyError(cause));
    } finally {
      setWorking(false);
    }
  }

  return (
    <div className="gdpr-page">
      <header className="gdpr-topbar">
        <div className="gdpr-brand">
          <img src={sendroLogo} alt="Sendro" />
          <span>Sendro</span>
        </div>
        <WorkspaceTabs
          active="privacy"
          showInbox
          showInstagram
          showProjects
          showPrivacy
          onInbox={onWhatsApp}
          onInstagram={onInstagram}
          onProjects={onProjects}
        />
        <div className="gdpr-account">
          <span>{currentUser.username}</span>
          <button type="button" onClick={onLogout}>Sign out</button>
        </div>
      </header>

      <main className="gdpr-main">
        <div className="gdpr-page-heading">
          <div>
            <span className="gdpr-eyebrow">Governance / Privacy requests</span>
            <h1>GDPR Manager</h1>
            <p>Track customer privacy requests from your company’s email or messaging channels.</p>
          </div>
          <span className="gdpr-preview-pill">STAGING · GDPR PILOT</span>
        </div>
        <div className="gdpr-warning" role="note">
          <strong>Privacy-first mode.</strong> Customers contact their business directly.
          Staff register the request here, not the customer's name or message.
          No automatic customer lookup, outbound reply, export or deletion.
          Access requires recent Authenticator verification and company owner/admin membership.
        </div>

        <div className="gdpr-toolbar">
          <label htmlFor="gdpr-tenant">Company</label>
          <select id="gdpr-tenant" value={allowedTenant ? tenantId : ''} onChange={chooseTenant}>
            {tenants.map((tenant) => (
              <option key={tenant.id} value={tenant.id}>{tenant.display_name}</option>
            ))}
          </select>
          <button type="button" onClick={refresh} disabled={!allowedTenant || loading}>
            {loading ? 'Loading…' : 'Refresh'}
          </button>
          {workflowEnabled && (
            <button type="button" className="gdpr-primary-btn" onClick={() => setCreating((old) => !old)}
              disabled={!allowedTenant || working}>
              {creating ? 'Cancel' : '+ New request'}
            </button>
          )}
          <span className="gdpr-pagination-note">First 50 requests · manual refresh only</span>
        </div>

        {workflowEnabled && creating && (
          <form className="gdpr-intake-form" onSubmit={submitNewRequest}>
            <div>
              <strong>Register a customer request</strong>
              <p>Use the company’s existing email or WhatsApp to communicate with the person. Do not enter any personal details in this register.</p>
            </div>
            <label htmlFor="gdpr-source">How did the customer contact the business?</label>
            <select id="gdpr-source" value={requestSource} onChange={(event) => setRequestSource(event.target.value)}>
              <option value="email">Email</option>
              <option value="whatsapp">WhatsApp</option>
              <option value="instagram">Instagram</option>
            </select>
            <button type="submit" disabled={working || !allowedTenant}>
              {working ? 'Saving…' : 'Create case'}
            </button>
          </form>
        )}
        {notice && <div className="gdpr-notice" role="status">{notice}</div>}
        {error && <div className="gdpr-alert" role="alert">{error}</div>}
        <div className="gdpr-cards">
          <article>
            <span>Requests shown</span>
            <strong>{cases.length}</strong>
            <small>{loading ? 'Refreshing…' : 'Tenant scoped'}</small>
          </article>
          <article>
            <span>Responses recorded</span>
            <strong>{cases.filter((item) => item.response_recorded).length}</strong>
            <small>Within this page</small>
          </article>
          <article>
            <span>Erasure actions</span>
            <strong>Disabled</strong>
            <small>No destructive operations mounted</small>
          </article>
        </div>

        <div className="gdpr-content">
          <section className="gdpr-list" aria-label="GDPR requests">
            <div className="gdpr-panel-heading">
              <h2>Request register</h2>
              <span>{loading ? 'Loading' : workflowEnabled ? 'Manual workflow' : 'Read-only'}</span>
            </div>
            {loading ? (
              <div className="gdpr-empty">Loading authorized request summaries…</div>
            ) : !allowedTenant ? (
              <div className="gdpr-empty">You have no authorized GDPR company.</div>
            ) : cases.length === 0 ? (
              <div className="gdpr-empty">
                <strong>No GDPR requests recorded</strong>
                <p>The register is empty for this company. This is expected during the pilot.</p>
              </div>
            ) : (
              <div className="gdpr-records">
                {cases.map((item) => (
                  <button
                    key={item.case_ref}
                    type="button"
                    className={`gdpr-record ${selectedRef === item.case_ref ? 'selected' : ''}`}
                    onClick={() => selectCase(item.case_ref)}
                    aria-pressed={selectedRef === item.case_ref}
                  >
                    <span className="gdpr-record-head">
                      <strong>Case {formatCaseRef(item.case_ref)}</strong>
                      <span className="gdpr-status">{item.status}</span>
                    </span>
                    <span>Channel: {item.channel}</span>
                    <span>Blockers: {item.blockers?.length ?? 0} · Events: {item.audit_events}</span>
                  </button>
                ))}
              </div>
            )}
          </section>

          <section className="gdpr-detail" aria-label="GDPR request detail">
            <div className="gdpr-panel-heading">
              <h2>Case details</h2>
              <span>Non-identifying</span>
            </div>
            {detailsError && <div className="gdpr-alert" role="alert">{detailsError}</div>}
            {detailsLoading ? (
              <div className="gdpr-empty">Verifying access and loading details…</div>
            ) : !details ? (
              <div className="gdpr-empty gdpr-detail-intro">
                <span className="gdpr-detail-symbol" aria-hidden="true">◇</span>
                <strong>Secure case review</strong>
                <p>Select a request from the register to inspect its status, audit count and scope blockers.</p>
                <small>No customer names, messages or contact information are returned.</small>
              </div>
            ) : (
              <div className="gdpr-detail-fields">
                <div><span>Case reference</span><strong>{formatCaseRef(details.case_ref)}</strong></div>
                <div><span>Received (UTC)</span><strong>{details.received_at ? new Date(details.received_at).toLocaleString('en-GB') : '—'}</strong></div>
                <div><span>One-month response target*</span><strong>{oneMonthTarget(details.received_at)}</strong></div>
                <div><span>Status</span><strong>{details.status.replaceAll('_', ' ')}</strong></div>
                <div><span>Channel</span><strong>{details.channel}</strong></div>
                <div><span>Audit events</span><strong>{details.audit_events}</strong></div>
                <div><span>Response recorded</span><strong>{details.response_recorded ? 'Yes' : 'No'}</strong></div>
                <div><span>Identity verified by system</span><strong>{details.identity_verified_by_system ? 'Yes' : 'No'}</strong></div>
                <div><span>Erasure enabled</span><strong>No</strong></div>
                <div><span>Source request</span><strong>{details.channel}</strong></div>
                <section className="gdpr-blockers">
                  <h3>Scope blockers</h3>
                  {details.blockers?.length
                    ? <ul>{details.blockers.map((entry, index) => <li key={index}>{entry}</li>)}</ul>
                    : <p>None recorded</p>}
                </section>
                {workflowEnabled && (
                  <section className="gdpr-workflow-actions" aria-label="Manual case workflow">
                    <h3>Manual review steps</h3>
                    {details.status === 'received' && (
                      <div className="gdpr-step">
                        <strong>1. Verify identity / authority</strong>
                        <p>Check the requester's identity outside Sendro only when needed. This button records your own confirmation; Sendro cannot verify identity automatically.</p>
                        <button type="button" disabled={working} onClick={() => {
                          if (window.confirm('Have you independently verified the requester or their authority, where appropriate?')) {
                            runCaseAction(() => verifyPrivacyIdentity(tenantId, details.case_ref));
                          }
                        }}>{working ? 'Saving…' : 'Mark independently verified'}</button>
                      </div>
                    )}
                    {details.status !== 'received' && (
                      <div className="gdpr-step">
                        <strong>2. Review applicable data and any legal holds</strong>
                        <p>Keep unchecked items as pending. This review does not approve or perform erasure.</p>
                        <button type="button" className="gdpr-secondary-btn" onClick={() => setScopeOpen((old) => !old)}>
                          {scopeOpen ? 'Hide checklist' : 'Open review checklist'}
                        </button>
                        {scopeOpen && (
                          <div className="gdpr-checklist">
                            {REVIEW_FIELDS.map(([field, label]) => (
                              <label key={field}>
                                <input type="checkbox" checked={scopeChecks[field] === true}
                                  onChange={(event) => setScopeChecks((old) => ({ ...old, [field]: event.target.checked }))}/>
                                <span>{label}</span>
                              </label>
                            ))}
                            <label className="gdpr-hold-label" htmlFor="gdpr-legal-hold">Legal hold or retention exception assessed</label>
                            <select id="gdpr-legal-hold" value={legalHold} onChange={(event) => setLegalHold(event.target.value)}>
                              <option value="unknown">Not assessed yet</option>
                              <option value="yes">Yes — legal hold exists</option>
                              <option value="no">No legal hold identified</option>
                            </select>
                            <button type="button" disabled={working} onClick={() => runCaseAction(() =>
                              reviewPrivacyScope(tenantId, details.case_ref, {
                                ...Object.fromEntries(REVIEW_FIELDS.map(([field]) => [field, scopeChecks[field] === true])),
                                legal_hold: legalHold === 'unknown' ? null : legalHold === 'yes',
                              })
                            )}>{working ? 'Saving…' : 'Save reviewed scope'}</button>
                          </div>
                        )}
                      </div>
                    )}
                    {details.status !== 'received' && !details.response_recorded && (
                      <div className="gdpr-step">
                        <strong>3. Record the reply after sending it</strong>
                        <p>Reply directly through the company’s email/WhatsApp first. This records the reply only; it does not send anything or erase any data.</p>
                        <button type="button" disabled={working} onClick={() => {
                          if (window.confirm('Have you ALREADY sent the response to the customer outside Sendro?')) {
                            runCaseAction(() => recordPrivacyResponse(tenantId, details.case_ref));
                          }
                        }}>{working ? 'Saving…' : 'I sent the response — record it'}</button>
                      </div>
                    )}
                    {details.response_recorded && (
                      <p className="gdpr-complete">Response recorded. Retention and erasure, if applicable, require independent handling.</p>
                    )}
                  </section>
                )}
              </div>
            )}
          </section>
        </div>
        <p className="gdpr-footnote">
          *Guidance only: the ordinary GDPR response timeframe is generally one calendar month, with exceptions.
          This internal pilot never automatically emails, retrieves or deletes customer data.
          Server-side MFA and tenant authorization apply to every action.
        </p>
      </main>
    </div>
  );
}
