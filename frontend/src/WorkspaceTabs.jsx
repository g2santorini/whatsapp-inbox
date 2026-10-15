import './WorkspaceNavigation.css';

export default function WorkspaceTabs({
  active = 'inbox',
  showInbox = true,
  showInstagram = false,
  showProjects = true,
  unreadCount = 0,
  onInbox,
  onInstagram,
  onProjects,
}) {
  return (
    <nav className={`sendro-global-tabs ${showInstagram ? 'has-instagram' : '' }`} aria-label="Sendro applications">
      {showInbox && (
        <button
          type="button"
          className={`sendro-global-tab ${active === 'inbox' ? 'is-active' : ''}`}
          aria-current={active === 'inbox' ? 'page' : undefined}
          onClick={onInbox}
        >
          <span className="sendro-global-tab-symbol whatsapp" aria-hidden="true">✆</span>
          <span>{showInstagram ? 'Unified Inbox' : 'WhatsApp Inbox'}</span>
          {unreadCount > 0 && (
            <span className="sendro-global-unread" aria-label={`${unreadCount} unread conversations`}>
              {unreadCount > 99 ? '99+' : unreadCount}
            </span>
          )}
        </button>
      )}
      {showInstagram && (
        <button
          type="button"
          className={`sendro-global-tab ${active === 'instagram' ? 'is-active' : ''}`}
          aria-current={active === 'instagram' ? 'page' : undefined}
          onClick={onInstagram}
        >
          <span className="sendro-global-tab-symbol instagram" aria-hidden="true">◎</span>
          <span>Instagram</span>
        </button>
      )}
      {showProjects && (
        <button
          type="button"
          className={`sendro-global-tab ${active === 'projects' ? 'is-active' : ''}`}
          aria-current={active === 'projects' ? 'page' : undefined}
          onClick={onProjects}
        >
          <span className="sendro-global-tab-symbol projects" aria-hidden="true">▦</span>
          <span>Projects &amp; Tasks</span>
        </button>
      )}
    </nav>
  );
}
