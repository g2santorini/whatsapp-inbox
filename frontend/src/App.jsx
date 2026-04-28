import { useEffect, useState } from 'react';
import './App.css';
import sendroLogo from './assets/sendro_logo_clean.svg';
import SettingsPanel from './components/SettingsPanel';
import {
  getToken,
  login,
  clearToken,
  getCurrentUser,
  getUsers,
  getConversations,
  createConversation,
  getMessages,
  sendMessage,
  takeConversation,
  releaseConversation,
  closeConversation,
  archiveConversation,
  deleteConversation,
  markConversationAsRead,
} from './api';

const AUTO_REFRESH_INTERVAL_MS = 5000;
const PHONE_NUMBER_REGEX = /^\+[1-9]\d{7,14}$/;

const INBOX_VIEWS = {
  ALL: 'all',
  OPEN: 'open',
  MINE: 'mine',
  CLOSED: 'closed',
  ARCHIVED: 'archived',
};

const APP_PAGES = {
  INBOX: 'inbox',
  SETTINGS: 'settings',
};

function BrandBlock({ subtitle }) {
  return (
    <div className="brand">
      <div className="brand-icon">
        <img src={sendroLogo} alt="Sendro logo" className="brand-logo" />
      </div>
      <div>
        <h1>Sendro</h1>
        <p>{subtitle}</p>
      </div>
    </div>
  );
}

function App() {
  const [token, setToken] = useState(getToken());
  const [user, setUser] = useState(null);
  const [users, setUsers] = useState([]);

  const [username, setUsername] = useState('testuser');
  const [password, setPassword] = useState('testpass');

  const [conversations, setConversations] = useState([]);
  const [activePage, setActivePage] = useState(APP_PAGES.INBOX);
  const [activeInboxView, setActiveInboxView] = useState(INBOX_VIEWS.ALL);
  const [inboxSearchQuery, setInboxSearchQuery] = useState('');
  const [selectedConversation, setSelectedConversation] = useState(null);
  const [messages, setMessages] = useState([]);

  const [newMessage, setNewMessage] = useState('');
  const [error, setError] = useState('');
  const [isSending, setIsSending] = useState(false);

  const [showNewConversationForm, setShowNewConversationForm] = useState(false);
  const [newContactName, setNewContactName] = useState('');
  const [newContactPhone, setNewContactPhone] = useState('');
  const [newConversationMessage, setNewConversationMessage] = useState('');
  const [isCreatingConversation, setIsCreatingConversation] = useState(false);

  const assignedToUserId = selectedConversation?.assigned_to_user_id || null;

  const isConversationTakenByAnotherUser =
    Boolean(assignedToUserId) && assignedToUserId !== user?.id;

  const canTakeConversation =
    Boolean(selectedConversation) && !selectedConversation.assigned_to_user_id;

  const canReleaseConversation =
    Boolean(selectedConversation) && selectedConversation.assigned_to_user_id === user?.id;

  const canUseConversationAction = canTakeConversation || canReleaseConversation;

  const canSendMessage =
    Boolean(selectedConversation) &&
    !isConversationTakenByAnotherUser &&
    selectedConversation?.status !== 'archived' &&
    !isSending;

  const activeConversations = conversations.filter(
    (conversation) => conversation.status !== 'archived'
  );

  const allCount = activeConversations.length;

  const openUnreadCount = conversations.filter((conversation) => {
    return (
      conversation.status !== 'archived' &&
      conversation.status !== 'closed' &&
      !conversation.assigned_to_user_id
    );
  }).length;

  const mineCount = conversations.filter(
    (conversation) =>
      conversation.status !== 'archived' &&
      conversation.status !== 'closed' &&
      conversation.assigned_to_user_id === user?.id
  ).length;

  const closedCount = conversations.filter(
    (conversation) => conversation.status === 'closed'
  ).length;

  const archivedCount = conversations.filter(
    (conversation) => conversation.status === 'archived'
  ).length;

  const normalizedInboxSearchQuery = inboxSearchQuery.trim().toLowerCase();

  const filteredConversations = conversations.filter((conversation) => {
    let matchesActiveInboxView = true;

    if (activeInboxView === INBOX_VIEWS.ALL) {
      matchesActiveInboxView = conversation.status !== 'archived';
    }

    if (activeInboxView === INBOX_VIEWS.OPEN) {
      matchesActiveInboxView =
        conversation.status !== 'archived' &&
        conversation.status !== 'closed' &&
        !conversation.assigned_to_user_id;
    }

    if (activeInboxView === INBOX_VIEWS.MINE) {
      matchesActiveInboxView =
        conversation.status !== 'archived' &&
        conversation.status !== 'closed' &&
        conversation.assigned_to_user_id === user?.id;
    }

    if (activeInboxView === INBOX_VIEWS.CLOSED) {
      matchesActiveInboxView = conversation.status === 'closed';
    }

    if (activeInboxView === INBOX_VIEWS.ARCHIVED) {
      matchesActiveInboxView = conversation.status === 'archived';
    }

    if (!matchesActiveInboxView) {
      return false;
    }

    if (!normalizedInboxSearchQuery) {
      return true;
    }

    const searchableText = [
      conversation.contact_name,
      conversation.contact_phone,
      conversation.status,
      getAssignedUserLabel(conversation.assigned_to_user_id),
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase();

    return searchableText.includes(normalizedInboxSearchQuery);
  });

  function getAssignedUser(userId) {
    if (!userId) return null;
    return users.find((singleUser) => singleUser.id === userId) || null;
  }

  function getAssignedUserLabel(userId) {
    if (!userId) return 'Nobody';

    const assignedUser = getAssignedUser(userId);
    if (!assignedUser) return `User #${userId}`;

    return assignedUser.username || `User #${userId}`;
  }

  function getAssignedUserClass(userId) {
    if (!userId) return 'assigned-nobody';

    const assignedUser = getAssignedUser(userId);
    const usernameValue = assignedUser?.username?.toLowerCase() || '';

    if (usernameValue === 'george') return 'assigned-george';
    if (usernameValue === 'panagiotis') return 'assigned-panagiotis';

    return 'assigned-other';
  }

  function getConversationActionLabel() {
    if (!selectedConversation) return 'Take';
    if (canTakeConversation) return 'Take';
    if (canReleaseConversation) return 'Release';

    return `Taken by ${getAssignedUserLabel(selectedConversation.assigned_to_user_id)}`;
  }

  function getErrorMessage(err, fallbackMessage) {
    let errorMessage = fallbackMessage;

    try {
      const parsedError = JSON.parse(err.message);
      errorMessage = parsedError.detail || errorMessage;
    } catch {
      errorMessage = err.message || errorMessage;
    }

    return errorMessage;
  }

  function resetNewConversationForm() {
    setNewContactName('');
    setNewContactPhone('');
    setNewConversationMessage('');
  }

  function closeNewConversationOverlay() {
    setShowNewConversationForm(false);
    resetNewConversationForm();
    setError('');
  }

  async function refreshConversations(selectedConversationId = null) {
    const conversationData = await getConversations();
    setConversations(conversationData);

    if (selectedConversationId) {
      const refreshedConversation = conversationData.find(
        (conversation) => conversation.id === selectedConversationId
      );

      if (refreshedConversation) {
        setSelectedConversation(refreshedConversation);
        return;
      }

      setSelectedConversation(conversationData[0] || null);
      return;
    }

    setSelectedConversation(conversationData[0] || null);
  }

  async function handleLogin(event) {
    event.preventDefault();
    setError('');

    try {
      const data = await login(username, password);
      setToken(data.access_token);
    } catch (err) {
      setError('Login failed. Check username and password.');
    }
  }

  function handleLogout() {
    clearToken();
    setToken(null);
    setUser(null);
    setUsers([]);
    setConversations([]);
    setSelectedConversation(null);
    setMessages([]);
    setNewMessage('');
    setError('');
    setShowNewConversationForm(false);
    setActivePage(APP_PAGES.INBOX);
    setActiveInboxView(INBOX_VIEWS.ALL);
    setInboxSearchQuery('');
    resetNewConversationForm();
  }

  async function loadInitialData() {
    try {
      const currentUser = await getCurrentUser();
      setUser(currentUser);

      try {
        const usersData = await getUsers();
        setUsers(usersData);
      } catch (err) {
        setUsers([]);
      }

      await refreshConversations();
    } catch (err) {
      clearToken();
      setToken(null);
      setError('Session expired. Please login again.');
    }
  }

  async function loadMessages(conversationId) {
    try {
      const messageData = await getMessages(conversationId);
      setMessages(messageData);
    } catch (err) {
      setError('Could not load messages.');
    }
  }

  async function handleSelectConversation(conversation) {
    setError('');
    setActivePage(APP_PAGES.INBOX);
    setSelectedConversation(conversation);

    if (conversation.unread_count > 0) {
      try {
        await markConversationAsRead(conversation.id);
        await refreshConversations(conversation.id);
      } catch (err) {
        setError(getErrorMessage(err, 'Could not mark conversation as read.'));
      }
    }
  }

  async function handleCreateConversation(event) {
    event.preventDefault();

    const contactPhone = newContactPhone.trim();
    const contactName = newContactName.trim() || contactPhone;
    const firstMessage = newConversationMessage.trim();

    if (!contactPhone || isCreatingConversation) {
      setError('Phone number is required.');
      return;
    }

    if (!PHONE_NUMBER_REGEX.test(contactPhone)) {
      setError('Phone number must start with + and country code, for example +306900000000.');
      return;
    }

    if (!firstMessage) {
      setError('First message is required.');
      return;
    }

    try {
      setIsCreatingConversation(true);
      setError('');

      const createdConversation = await createConversation(contactName, contactPhone);

      if (createdConversation?.id) {
        await sendMessage(createdConversation.id, firstMessage);

        resetNewConversationForm();
        setShowNewConversationForm(false);
        setActivePage(APP_PAGES.INBOX);

        await refreshConversations(createdConversation.id);
        await loadMessages(createdConversation.id);
      } else {
        setError('Conversation was created, but it could not be opened.');
        await refreshConversations();
      }
    } catch (err) {
      setError(getErrorMessage(err, 'Could not create conversation.'));
    } finally {
      setIsCreatingConversation(false);
    }
  }

  async function handleTakeConversation() {
    if (!selectedConversation || !canTakeConversation) return;

    try {
      setError('');
      await takeConversation(selectedConversation.id);
      setActivePage(APP_PAGES.INBOX);
      setActiveInboxView(INBOX_VIEWS.MINE);
      await refreshConversations(selectedConversation.id);
    } catch (err) {
      setError(getErrorMessage(err, 'Could not take conversation.'));
    }
  }

  async function handleReleaseConversation() {
    if (!selectedConversation || !canReleaseConversation) return;

    try {
      setError('');
      await releaseConversation(selectedConversation.id);
      await refreshConversations(selectedConversation.id);
    } catch (err) {
      setError(getErrorMessage(err, 'Could not release conversation.'));
    }
  }

  async function handleConversationAction() {
    if (canTakeConversation) {
      await handleTakeConversation();
      return;
    }

    if (canReleaseConversation) {
      await handleReleaseConversation();
    }
  }

  async function handleCloseConversation() {
    if (!selectedConversation) return;

    try {
      setError('');
      await closeConversation(selectedConversation.id);
      setActiveInboxView(INBOX_VIEWS.CLOSED);
      await refreshConversations(selectedConversation.id);
    } catch (err) {
      setError(getErrorMessage(err, 'Could not close conversation.'));
    }
  }

  async function handleArchiveConversation() {
    if (!selectedConversation) return;

    try {
      setError('');
      await archiveConversation(selectedConversation.id);
      setActiveInboxView(INBOX_VIEWS.ARCHIVED);
      await refreshConversations(selectedConversation.id);
    } catch (err) {
      setError(getErrorMessage(err, 'Could not archive conversation.'));
    }
  }

  async function handleDeleteConversation() {
    if (!selectedConversation) return;

    const confirmed = window.confirm(
      'Are you sure you want to delete this conversation?\n\nThis action cannot be undone.'
    );

    if (!confirmed) return;

    try {
      setError('');
      await deleteConversation(selectedConversation.id);
      setSelectedConversation(null);
      setMessages([]);
      setError('');
      await refreshConversations();
    } catch (err) {
      setError(getErrorMessage(err, 'Could not delete conversation.'));
    }
  }

  async function handleSendMessage(event) {
    event.preventDefault();

    if (!selectedConversation || !newMessage.trim() || isSending) return;

    if (isConversationTakenByAnotherUser) {
      setError(
        `This conversation is taken by ${getAssignedUserLabel(
          selectedConversation.assigned_to_user_id
        )}.`
      );
      return;
    }

    const messageToSend = newMessage.trim();

    setIsSending(true);
    setError('');
    setNewMessage('');

    try {
      await sendMessage(selectedConversation.id, messageToSend);
      await loadMessages(selectedConversation.id);
      await refreshConversations(selectedConversation.id);
    } catch (err) {
      setError(getErrorMessage(err, 'Could not send message.'));
      setNewMessage(messageToSend);
    } finally {
      setIsSending(false);
    }
  }

  useEffect(() => {
    if (token) {
      loadInitialData();
    }
  }, [token]);

  useEffect(() => {
    if (selectedConversation && activePage === APP_PAGES.INBOX) {
      setError('');
      loadMessages(selectedConversation.id);
    } else {
      setMessages([]);
    }
  }, [selectedConversation?.id, activePage]);

  useEffect(() => {
    if (activePage !== APP_PAGES.INBOX) return;

    if (filteredConversations.length === 0) {
      setSelectedConversation(null);
      return;
    }

    if (!selectedConversation) {
      setSelectedConversation(filteredConversations[0]);
      return;
    }

    const selectedStillVisible = filteredConversations.some(
      (conversation) => conversation.id === selectedConversation.id
    );

    if (!selectedStillVisible) {
      setSelectedConversation(filteredConversations[0]);
    }
  }, [
    activeInboxView,
    conversations,
    user?.id,
    activePage,
    inboxSearchQuery,
    selectedConversation?.id,
  ]);

  useEffect(() => {
    if (!token) return undefined;

    const intervalId = window.setInterval(() => {
      const selectedConversationId = selectedConversation?.id || null;

      refreshConversations(selectedConversationId).catch(() => {
        // Silent auto-refresh failure.
      });
    }, AUTO_REFRESH_INTERVAL_MS);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [token, selectedConversation?.id]);

  if (!token) {
    return (
      <div className="login-page">
        <form className="login-card" onSubmit={handleLogin}>
          <div className="login-brand">
            <BrandBlock subtitle="Team WhatsApp Inbox" />
          </div>

          <input
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="Username"
          />

          <input
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="Password"
            type="password"
          />

          <button type="submit">Login</button>

          {error && <p className="error-message">{error}</p>}
        </form>
      </div>
    );
  }

  return (
    <div className="app">
      {error && <div className="app-error">{error}</div>}

      <aside className="sidebar">
        <BrandBlock subtitle={user ? `Logged in as ${user.username}` : 'Team WhatsApp Inbox'} />

        <nav className="sidebar-nav">
          <button
            type="button"
            className={`sidebar-nav-button ${activePage === APP_PAGES.INBOX ? 'active' : ''}`}
            onClick={() => setActivePage(APP_PAGES.INBOX)}
          >
            Inbox
          </button>

          <button
            type="button"
            className={`sidebar-nav-button ${activePage === APP_PAGES.SETTINGS ? 'active' : ''}`}
            onClick={() => setActivePage(APP_PAGES.SETTINGS)}
          >
            Settings
          </button>
        </nav>

        {activePage === APP_PAGES.INBOX && (
          <>
            <div className="inbox-search">
              <input
                value={inboxSearchQuery}
                onChange={(event) => setInboxSearchQuery(event.target.value)}
                placeholder="Search by name, phone, status..."
              />

              {inboxSearchQuery && (
                <button
                  type="button"
                  onClick={() => setInboxSearchQuery('')}
                  aria-label="Clear inbox search"
                >
                  ×
                </button>
              )}
            </div>

            <div className="inbox-tabs">
              <button
                type="button"
                className={`inbox-tab ${activeInboxView === INBOX_VIEWS.ALL ? 'active' : ''}`}
                onClick={() => setActiveInboxView(INBOX_VIEWS.ALL)}
              >
                <span>All</span>
                <strong>{allCount}</strong>
              </button>

              <button
                type="button"
                className={`inbox-tab ${activeInboxView === INBOX_VIEWS.OPEN ? 'active' : ''}`}
                onClick={() => setActiveInboxView(INBOX_VIEWS.OPEN)}
              >
                <span>Open / Unread</span>
                <strong>{openUnreadCount}</strong>
              </button>

              <button
                type="button"
                className={`inbox-tab ${activeInboxView === INBOX_VIEWS.MINE ? 'active' : ''}`}
                onClick={() => setActiveInboxView(INBOX_VIEWS.MINE)}
              >
                <span>Mine</span>
                <strong>{mineCount}</strong>
              </button>

              <button
                type="button"
                className={`inbox-tab ${activeInboxView === INBOX_VIEWS.CLOSED ? 'active' : ''}`}
                onClick={() => setActiveInboxView(INBOX_VIEWS.CLOSED)}
              >
                <span>Closed</span>
                <strong>{closedCount}</strong>
              </button>

              <button
                type="button"
                className={`inbox-tab ${activeInboxView === INBOX_VIEWS.ARCHIVED ? 'active' : ''}`}
                onClick={() => setActiveInboxView(INBOX_VIEWS.ARCHIVED)}
              >
                <span>Archived</span>
                <strong>{archivedCount}</strong>
              </button>
            </div>

            <div className="new-conversation-area">
              <button
                className={`new-conversation-fab ${showNewConversationForm ? 'active' : ''}`}
                onClick={() => {
                  setError('');
                  setShowNewConversationForm((currentValue) => !currentValue);
                }}
                type="button"
                aria-label="Create new conversation"
              >
                <span className="new-conversation-plus">
                  {showNewConversationForm ? '×' : '+'}
                </span>
                <span className="new-conversation-label">
                  {showNewConversationForm ? 'Close' : 'New'}
                </span>
              </button>

              {showNewConversationForm && (
                <div className="new-conversation-overlay">
                  <div className="new-conversation-overlay-header">
                    <div>
                      <h3>New conversation</h3>
                      <p>Create a chat and send the first message.</p>
                    </div>

                    <button
                      className="new-conversation-close"
                      type="button"
                      onClick={closeNewConversationOverlay}
                      aria-label="Close new conversation form"
                    >
                      ×
                    </button>
                  </div>

                  <form className="new-conversation-form" onSubmit={handleCreateConversation}>
                    <input
                      value={newContactName}
                      onChange={(event) => setNewContactName(event.target.value)}
                      placeholder="Contact name"
                      disabled={isCreatingConversation}
                    />

                    <input
                      value={newContactPhone}
                      onChange={(event) => setNewContactPhone(event.target.value)}
                      placeholder="Phone number, e.g. +306900000000"
                      disabled={isCreatingConversation}
                    />

                    <textarea
                      value={newConversationMessage}
                      onChange={(event) => setNewConversationMessage(event.target.value)}
                      placeholder="First message"
                      disabled={isCreatingConversation}
                      rows="3"
                    />

                    <button
                      type="submit"
                      disabled={
                        isCreatingConversation ||
                        !newContactPhone.trim() ||
                        !newConversationMessage.trim()
                      }
                    >
                      {isCreatingConversation ? 'Creating...' : 'Create & Send'}
                    </button>
                  </form>
                </div>
              )}
            </div>

            <div className="conversation-list">
              {filteredConversations.length === 0 ? (
                <div className="empty-state">
                  {inboxSearchQuery
                    ? `No conversations found for "${inboxSearchQuery}".`
                    : 'No conversations in this view.'}
                </div>
              ) : (
                filteredConversations.map((conversation) => {
                  const isActive = selectedConversation?.id === conversation.id;
                  const label = conversation.contact_name || conversation.contact_phone;
                  const unreadCount = Number(conversation.unread_count || 0);

                  return (
                    <button
                      key={conversation.id}
                      className={`conversation ${isActive ? 'active' : ''}`}
                      onClick={() => handleSelectConversation(conversation)}
                    >
                      <div className="conversation-title-row">
                        <strong>{label}</strong>

                        {unreadCount > 0 && (
                          <span className="unread-badge">{unreadCount}</span>
                        )}
                      </div>

                      <span>{conversation.contact_phone}</span>

                      <small className="conversation-meta">
                        <span className="status-pill">{conversation.status || 'open'}</span>
                        <span
                          className={`assigned-badge ${getAssignedUserClass(
                            conversation.assigned_to_user_id
                          )}`}
                        >
                          {getAssignedUserLabel(conversation.assigned_to_user_id)}
                        </span>
                      </small>
                    </button>
                  );
                })
              )}
            </div>
          </>
        )}

        <button className="logout-button" onClick={handleLogout}>
          Logout
        </button>
      </aside>

      <main className="chat-panel">
        {activePage === APP_PAGES.SETTINGS ? (
          user?.role === 'admin' ? (
            <SettingsPanel />
          ) : (
            <div className="settings-access-denied">
              <div>
                <span>Settings locked</span>
                <h2>Admin access required</h2>
                <p>
                  Settings are available only to admins. You can still use the inbox according
                  to your role permissions.
                </p>
                <button type="button" onClick={() => setActivePage(APP_PAGES.INBOX)}>
                  Back to inbox
                </button>
              </div>
            </div>
          )
        ) : selectedConversation ? (
          <>
            <header className="chat-header">
              <div>
                <h2>{selectedConversation.contact_name || 'Unknown contact'}</h2>
                <p>{selectedConversation.contact_phone}</p>

                <p className="conversation-status-row">
                  <span className="status-pill">
                    {selectedConversation.status || 'open'}
                  </span>

                  <span
                    className={`assigned-badge ${getAssignedUserClass(
                      selectedConversation.assigned_to_user_id
                    )}`}
                  >
                    Assigned to: {getAssignedUserLabel(selectedConversation.assigned_to_user_id)}
                  </span>
                </p>

                {isConversationTakenByAnotherUser && (
                  <p className="conversation-locked-message">
                    This conversation is taken by{' '}
                    {getAssignedUserLabel(selectedConversation.assigned_to_user_id)}.
                  </p>
                )}
              </div>

              <div className="chat-actions">
                <button
                  className={`conversation-action-button ${canReleaseConversation ? 'release-mode' : ''}`}
                  onClick={handleConversationAction}
                  disabled={!canUseConversationAction}
                >
                  {getConversationActionLabel()}
                </button>

                <button
                  className="conversation-action-button"
                  type="button"
                  onClick={handleCloseConversation}
                  disabled={selectedConversation.status === 'closed'}
                >
                  Close
                </button>

                <button
                  className="conversation-action-button release-mode"
                  type="button"
                  onClick={handleArchiveConversation}
                  disabled={selectedConversation.status === 'archived'}
                >
                  Archive
                </button>

                <button
                  className="conversation-action-button release-mode"
                  type="button"
                  onClick={handleDeleteConversation}
                >
                  Delete
                </button>
              </div>
            </header>

            <section className="messages">
              {messages.length === 0 ? (
                <div className="empty-state">No messages yet.</div>
              ) : (
                messages.map((message) => (
                  <div
                    key={message.id}
                    className={`message ${
                      message.direction === 'outbound' ? 'outgoing' : 'incoming'
                    }`}
                  >
                    {message.content}
                  </div>
                ))
              )}
            </section>

            <form className="composer" onSubmit={handleSendMessage}>
              <input
                value={newMessage}
                onChange={(event) => setNewMessage(event.target.value)}
                placeholder={
                  selectedConversation.status === 'archived'
                    ? 'Archived conversation'
                    : isConversationTakenByAnotherUser
                      ? `Taken by ${getAssignedUserLabel(
                          selectedConversation.assigned_to_user_id
                        )}`
                      : 'Type a message...'
                }
                disabled={!canSendMessage}
              />

              <button type="submit" disabled={!canSendMessage || !newMessage.trim()}>
                {isSending ? 'Sending...' : 'Send'}
              </button>
            </form>
          </>
        ) : (
          <div className="no-chat-selected">Select a conversation to start.</div>
        )}
      </main>
    </div>
  );
}

export default App;