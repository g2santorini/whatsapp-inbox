import { useEffect, useState } from 'react';
import WorkspaceTabs from './WorkspaceTabs';
import sendroLogo from './assets/sendro_logo_reversed.png';
import {
  getInstagramTenants,
  getInstagramConversations,
  getInstagramMessages,
} from './api';
import './InstagramInboxPage.css';

const formatDate = (value) => {
  if (!value) return '';
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? '' : parsed.toLocaleString();
};

function humanError(error) {
  if (error?.status === 403) return 'Your account is not authorized for this company.';
  if (error?.status === 401) return 'Your session has expired. Sign in again.';
  return 'Could not load Instagram conversations. Please try again.';
}

export default function InstagramInboxPage({
  currentUser,
  onWhatsApp,
  onProjects,
  onLogout,
}) {
  const [tenants, setTenants] = useState([]);
  const [tenantId, setTenantId] = useState(null);
  const [conversations, setConversations] = useState([]);
  const [selected, setSelected] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loadingTenants, setLoadingTenants] = useState(true);
  const [loadingConversations, setLoadingConversations] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [error, setError] = useState('');
  const [messagesError, setMessagesError] = useState('');
  const [refreshId, setRefreshId] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let live = true;
    setLoadingTenants(true);
    getInstagramTenants({ signal: controller.signal })
      .then((items) => {
        if (!live) return;
        setTenants(items);
        setTenantId((old) => (
          items.some((tenant) => tenant.id === old) ? old : items[0]?.id ?? null
        ));
        setError('');
      })
      .catch((cause) => {
        if (live && cause?.name !== 'AbortError') setError(humanError(cause));
      })
      .finally(() => {
        if (live) setLoadingTenants(false);
      });
    return () => {
      live = false;
      controller.abort();
    };
  }, []);

  useEffect(() => {
    if (!tenantId) {
      setConversations([]);
      setSelected(null);
      return undefined;
    }

    const controller = new AbortController();
    let live = true;
    setLoadingConversations(true);
    getInstagramConversations(tenantId, { signal: controller.signal })
      .then((items) => {
        if (!live) return;
        setConversations(items);
        setSelected((old) => items.find((item) => item.id === old?.id) || null);
        setError('');
      })
      .catch((cause) => {
        if (live && cause?.name !== 'AbortError') setError(humanError(cause));
      })
      .finally(() => {
        if (live) setLoadingConversations(false);
      });
    return () => {
      live = false;
      controller.abort();
    };
  }, [tenantId, refreshId]);

  useEffect(() => {
    if (!selected || !tenantId) {
      setMessages([]);
      setMessagesError('');
      return undefined;
    }

    const controller = new AbortController();
    let live = true;
    setLoadingMessages(true);
    setMessagesError('');
    getInstagramMessages(tenantId, selected.id, { signal: controller.signal })
      .then((items) => {
        if (live) setMessages([...items].reverse());
      })
      .catch((cause) => {
        if (live && cause?.name !== 'AbortError') {
          setMessages([]);
          setMessagesError(humanError(cause));
        }
      })
      .finally(() => {
        if (live) setLoadingMessages(false);
      });

    return () => {
      live = false;
      controller.abort();
    };
  }, [tenantId, selected?.id, refreshId]);

  const company = tenants.find((tenant) => tenant.id === tenantId);
  const totalUnread = conversations.reduce(
    (count, conversation) => count + Number(conversation.unread_count || 0), 0
  );

  return (
    <div className="ig-inbox-page">
      <header className="ig-topbar">
        <div className="ig-topbar-brand">
          <img src={sendroLogo} alt="Sendro" />
          <span>Sendro</span>
        </div>
        <WorkspaceTabs
          active="instagram"
          showInbox
          showInstagram
          showProjects
          onInbox={onWhatsApp}
          onInstagram={() => setRefreshId((value) => value + 1)}
          onProjects={onProjects}
        />
        <div className="ig-user-controls">
          <span>{currentUser?.username}</span>
          <button type="button" onClick={onLogout}>Logout</button>
        </div>
      </header>

      <div className="ig-content">
        <aside className="ig-conversation-pane">
          <div className="ig-pane-heading">
            <span className="ig-channel-icon" aria-hidden="true">◎</span>
            <div>
              <strong>Instagram</strong>
              <small>Direct messages · Read-only preview</small>
            </div>
            <span className="ig-test-pill">TESTING</span>
          </div>

          <label className="ig-tenant-label" htmlFor="ig-tenant-select">Company</label>
          <select
            id="ig-tenant-select"
            value={tenantId ?? ''}
            disabled={loadingTenants || tenants.length < 2}
            onChange={(event) => {
              setTenantId(Number(event.target.value));
              setSelected(null);
              setMessages([]);
              setError('');
            }}
          >
            {tenants.length === 0
              ? <option value="">No Instagram accounts</option>
              : tenants.map((tenant) => (
                <option value={tenant.id} key={tenant.id}>{tenant.display_name}</option>
              ))}
          </select>

          <div className="ig-conversation-summary">
            <span><strong>{conversations.length}</strong> conversations</span>
            <span><strong>{totalUnread}</strong> unread</span>
          </div>

          <div className="ig-list-heading">
            <span>Conversations</span>
            <button
              type="button"
              disabled={!tenantId || loadingConversations}
              onClick={() => setRefreshId((value) => value + 1)}
              title="Refresh Instagram conversations"
            >{loadingConversations ? 'Loading…' : '↻ Refresh'}</button>
          </div>

          {error && (
            <div className="ig-error" role="alert">
              {error}
              <button type="button" onClick={() => setRefreshId((value) => value + 1)}>
                Retry
              </button>
            </div>
          )}

          <div className="ig-conversation-list">
            {loadingTenants || loadingConversations ? (
              <p className="ig-list-empty">Loading Instagram conversations…</p>
            ) : !tenants.length ? (
              <p className="ig-list-empty">
                No Instagram account is available for your Sendro login.
              </p>
            ) : conversations.length === 0 && !error ? (
              <div className="ig-list-empty">
                <span className="ig-empty-icon" aria-hidden="true">✉</span>
                <strong>No Instagram conversations yet</strong>
                <small>
                  {company?.display_name || 'This account'} is in testing.
                  Real Instagram DMs have not been enabled.
                </small>
              </div>
            ) : (
              conversations.map((conversation) => (
                <button
                  type="button"
                  key={conversation.id}
                  className={selected?.id === conversation.id ? 'ig-chat-item selected' : 'ig-chat-item'}
                  onClick={() => setSelected(conversation)}
                >
                  <span className="ig-avatar">IG</span>
                  <span className="ig-chat-info">
                    <strong>{conversation.contact_name || 'Instagram guest'}</strong>
                    <small>{conversation.account_name || 'Instagram'} · {formatDate(conversation.last_message_at)}</small>
                  </span>
                  {conversation.unread_count > 0 &&
                    <span className="ig-unread-pill">{conversation.unread_count}</span>}
                </button>
              ))
            )}
          </div>

          <div className="ig-pane-footer">
            <span className="ig-online-dot" />
            Instagram account registered · Webhook OFF
          </div>
        </aside>

        <main className="ig-message-pane">
          {selected ? (
            <>
              <header className="ig-chat-heading">
                <button type="button" className="ig-back-list" onClick={() => setSelected(null)}>
                  ← Back
                </button>
                <span className="ig-avatar">IG</span>
                <div>
                  <strong>{selected.contact_name || 'Instagram guest'}</strong>
                  <small>{selected.account_name} · {selected.status}</small>
                </div>
                <span className="ig-read-only">READ ONLY</span>
              </header>
              <div className="ig-messages" aria-label="Instagram message history">
                {loadingMessages && <p className="ig-muted">Loading messages…</p>}
                {messagesError && <p className="ig-error" role="alert">{messagesError}</p>}
                {!loadingMessages && !messagesError && messages.length === 0 &&
                  <p className="ig-muted">No messages recorded yet.</p>}
                {!loadingMessages && messages.map((message) => (
                  <div key={message.id} className={message.direction === 'outbound' ? 'ig-bubble mine' : 'ig-bubble'}>
                    {message.content && <p>{message.content}</p>}
                    {message.has_media && <p className="ig-muted">Media attachment (preview not available yet)</p>}
                    <small>{formatDate(message.provider_timestamp || message.created_at)}</small>
                  </div>
                ))}
              </div>
              <footer className="ig-composer-off">
                Replies will be enabled after Instagram API and Meta permissions are verified.
              </footer>
            </>
          ) : (
            <div className="ig-welcome">
              <span className="ig-welcome-icon" aria-hidden="true">◎</span>
              <h1>Instagram Inbox</h1>
              <p>
                A separate, secure inbox for {company?.display_name || 'your company'}.
                Conversations will appear here once test messaging is safely enabled.
              </p>
              <span className="ig-read-only">Preview · No messages sent or received</span>
              <button type="button" onClick={onWhatsApp}>← Back to WhatsApp Inbox</button>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
