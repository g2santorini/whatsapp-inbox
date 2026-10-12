import { useCallback, useEffect, useState } from 'react';
import { getWhatsAppLivePanel } from './api';
import './WhatsAppLivePanel.css';

const REFRESH_MS = 30000;
function displayTime(value) {
  if (!value) return '';
  const date = new Date(value.endsWith('Z') || /[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}
function initials(name) {
  const words = String(name || '?').trim().split(/\s+/);
  return words.length > 1 ? (words[0][0] + words[1][0]).toUpperCase() : words[0].slice(0, 2).toUpperCase();
}

export default function WhatsAppLivePanel({ onOpenInbox, onOpenConversation, onCountChange }) {
  const [data, setData] = useState(null);
  const [tab, setTab] = useState('unread');
  const [error, setError] = useState('');
  const [updatedAt, setUpdatedAt] = useState(null);

  const reload = useCallback(async (signal) => {
    try {
      const result = await getWhatsAppLivePanel({ signal });
      if (signal.aborted) return;
      setData(result);
      setError('');
      setUpdatedAt(new Date());
      onCountChange?.(Number(result?.summary?.inbox_unread_conversations || 0));
    } catch (err) {
      if (!signal.aborted) setError('Δεν ήταν δυνατή η ενημέρωση των συνομιλιών.');
    }
  }, [onCountChange]);

  useEffect(() => {
    const controller = new AbortController();
    const refresh = () => {
      if (document.visibilityState === 'visible') reload(controller.signal);
    };
    refresh();
    const timer = window.setInterval(refresh, REFRESH_MS);
    document.addEventListener('visibilitychange', refresh);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', refresh);
      controller.abort();
    };
  }, [reload]);

  const count = Number(data?.summary?.inbox_unread_conversations ?? 0);
  const messages = Number(data?.summary?.unread_messages ?? 0);
  const mine = Number(data?.summary?.mine ?? 0);
  const followUps = Number(data?.summary?.follow_up ?? 0);
  const rows = tab === 'unread' ? (data?.unread || []) : (data?.recent || []);

  return (
    <aside className="pm-whatsapp-panel" aria-label="WhatsApp activity">
      <section className="pm-wa-card pm-wa-summary-card">
        <div className="pm-wa-heading">
          <div><span className="pm-wa-mark" aria-hidden="true">✆</span><strong>WhatsApp</strong><span className="pm-wa-count">{count}</span></div>
          <span className={`pm-wa-connect ${error ? 'pm-wa-offline' : ''}`}>
            <i />{error ? 'Update failed' : updatedAt ? 'Updated' : 'Loading'}
          </span>
        </div>
        <div className="pm-wa-metrics">
          <div><strong>{count}</strong><span>Unread chats</span></div>
          <div><strong>{messages}</strong><span>Unread messages</span></div>
          <div><strong>{followUps}</strong><span>Follow up</span></div>
          <div><strong>{mine}</strong><span>Assigned to me</span></div>
        </div>
        <button className="pm-wa-open-inbox" type="button" onClick={onOpenInbox}>
          <span aria-hidden="true">✆</span> Open WhatsApp Inbox <span aria-hidden="true">→</span>
        </button>
      </section>
      <section className="pm-wa-card pm-wa-conversations">
        <div className="pm-wa-list-heading"><strong>Conversations</strong><button type="button" onClick={onOpenInbox}>View all →</button></div>
        <div className="pm-wa-list-tabs" role="group" aria-label="Conversation preview filter">
          <button type="button" className={tab === 'unread' ? 'active' : ''} onClick={() => setTab('unread')}>Unread ({count})</button>
          <button type="button" className={tab === 'recent' ? 'active' : ''} onClick={() => setTab('recent')}>Recent</button>
        </div>
        {error && <p className="pm-wa-error" role="status">{error}</p>}
        {!data && !error && <p className="pm-wa-empty">Loading conversations…</p>}
        {data && rows.length === 0 && <p className="pm-wa-empty">{tab === 'unread' ? 'No unread conversations.' : 'No recent conversations.'}</p>}
        <div className="pm-wa-list">
          {rows.map((item) => (
            <button type="button" className="pm-wa-conversation" key={item.id} onClick={() => onOpenConversation(item)}>
              <span className="pm-wa-avatar" aria-hidden="true">{initials(item.contact_name)}</span>
              <span className="pm-wa-conversation-copy">
                <strong>{item.contact_name}</strong>
                <small>{item.last_message_preview || item.contact_phone}</small>
              </span>
              <span className="pm-wa-conversation-meta">
                <small>{displayTime(item.last_message_at)}</small>
                {item.unread_count > 0 && <b>{item.unread_count > 99 ? '99+' : item.unread_count}</b>}
              </span>
            </button>
          ))}
        </div>
        <button type="button" className="pm-wa-view-all" onClick={onOpenInbox}>View all conversations →</button>
      </section>
      {updatedAt && <small className="pm-wa-refresh-note">Auto-refresh every 30 seconds · Last update {updatedAt.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}</small>}
    </aside>
  );
}
