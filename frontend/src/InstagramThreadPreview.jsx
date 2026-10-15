import { useEffect, useState } from 'react';
import { getInstagramMessages } from './api';

// A separate channel-specific reader, deliberately never accepting
// onSend/onAssign/onArchive props. WhatsApp actions cannot run from here.
export default function InstagramThreadPreview({
  conversation,
  onBack,
}) {
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refreshVersion, setRefreshVersion] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let alive = true;
    setMessages([]);
    setLoading(true);
    setError('');

    getInstagramMessages(conversation.tenant_id, conversation.id, {
      signal: controller.signal,
    })
      .then((rows) => {
        if (alive) setMessages([...rows].reverse());
      })
      .catch((cause) => {
        if (alive && cause?.name !== 'AbortError') {
          setError(cause?.status === 403
            ? 'Your account is not allowed to view this conversation.'
            : 'Could not load Instagram messages. Try Refresh.');
        }
      })
      .finally(() => {
        if (alive) setLoading(false);
      });

    return () => {
      alive = false;
      controller.abort();
    };
  }, [conversation.tenant_id, conversation.id, refreshVersion]);

  const displayName = conversation.contact_name || 'Instagram guest';

  return (
    <div className="unified-ig-thread">
      <header className="unified-ig-thread-header">
        <button type="button" className="unified-ig-back" onClick={onBack}>
          ← Back
        </button>
        <span className="unified-ig-header-icon" aria-hidden="true">◎</span>
        <div className="unified-ig-thread-contact">
          <h2>{displayName}</h2>
          <small>{conversation.account_name || 'Instagram'} · Instagram DM</small>
        </div>
        <span className="unified-ig-read-only">READ ONLY</span>
        <button
          type="button"
          className="unified-ig-reload"
          disabled={loading}
          onClick={() => setRefreshVersion((version) => version + 1)}
          title="Refresh Instagram messages"
        >↻ Refresh</button>
      </header>

      <section className="unified-ig-history" aria-label="Instagram messages">
        {loading && <div className="unified-ig-muted">Loading messages…</div>}
        {error && <p className="unified-ig-error" role="alert">{error}</p>}
        {!loading && !error && !messages.length && (
          <p className="unified-ig-muted">No Instagram messages stored for this guest yet.</p>
        )}
        {!loading && messages.map((message) => (
          <article
            key={message.id}
            className={`unified-ig-bubble ${message.direction === 'outbound' ? 'outgoing' : 'incoming'}`}
          >
            {message.content && <p>{message.content}</p>}
            {message.has_media && <p className="unified-ig-media-note">Instagram media · preview coming later</p>}
            <time>
              {message.provider_timestamp || message.created_at
                ? new Date(message.provider_timestamp || message.created_at).toLocaleString()
                : ''}
            </time>
          </article>
        ))}
      </section>

      <footer className="unified-ig-reply-disabled">
        <span>Instagram replies are disabled during testing.</span>
        <small>We will enable sending only after safe Meta API and messaging-window checks.</small>
      </footer>
    </div>
  );
}
