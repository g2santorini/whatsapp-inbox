import './WorkspaceNavigation.css';

export default function WorkspaceTabs({
  active = 'inbox',
  showInbox = true,
  showProjects = true,
  unreadCount = 0,
  onInbox,
  onProjects,
}) {
  return (
    <nav className="sendro-global-tabs" aria-label="Sendro applications">
      {showInbox && (
        <button
          type="button"
          className={`sendro-global-tab ${active === 'inbox' ? 'is-active' : ''}`}
          aria-current={active === 'inbox' ? 'page' : undefined}
          onClick={onInbox}
        >
          <span className="sendro-global-tab-symbol whatsapp" aria-hidden="true">✆</span>
          <span>WhatsApp Inbox</span>
          {unreadCount > 0 && (
            <span className="sendro-global-unread" aria-label={`${unreadCount} unread conversations`}>
              {unreadCount > 99 ? '99+' : unreadCount}
            </span>
          )}
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
