import { useEffect, useState } from 'react';
import './App.css';
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
} from './api';

const AUTO_REFRESH_INTERVAL_MS = 5000;
const PHONE_NUMBER_REGEX = /^\+[1-9]\d{7,14}$/;

function App() {
  const [token, setToken] = useState(getToken());
  const [user, setUser] = useState(null);
  const [users, setUsers] = useState([]);

  const [username, setUsername] = useState('testuser');
  const [password, setPassword] = useState('testpass');

  const [conversations, setConversations] = useState([]);
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
    Boolean(selectedConversation) && !isConversationTakenByAnotherUser && !isSending;

  function getAssignedUser(userId) {
    if (!userId) {
      return null;
    }

    return users.find((singleUser) => singleUser.id === userId) || null;
  }

  function getAssignedUserLabel(userId) {
    if (!userId) {
      return 'Nobody';
    }

    const assignedUser = getAssignedUser(userId);

    if (!assignedUser) {
      return `User #${userId}`;
    }

    return assignedUser.username || `User #${userId}`;
  }

  function getAssignedUserClass(userId) {
    if (!userId) {
      return 'assigned-nobody';
    }

    const assignedUser = getAssignedUser(userId);
    const usernameValue = assignedUser?.username?.toLowerCase() || '';

    if (usernameValue === 'george') {
      return 'assigned-george';
    }

    if (usernameValue === 'panagiotis') {
      return 'assigned-panagiotis';
    }

    return 'assigned-other';
  }

  function getConversationActionLabel() {
    if (!selectedConversation) {
      return 'Take';
    }

    if (canTakeConversation) {
      return 'Take';
    }

    if (canReleaseConversation) {
      return 'Release';
    }

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

      if (conversationData.length > 0) {
        setSelectedConversation(conversationData[0]);
        return;
      }

      setSelectedConversation(null);
      return;
    }

    if (conversationData.length > 0) {
      setSelectedConversation(conversationData[0]);
    } else {
      setSelectedConversation(null);
    }
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
    setSelectedConversation(conversation);
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
    if (!selectedConversation || !canTakeConversation) {
      return;
    }

    try {
      setError('');

      await takeConversation(selectedConversation.id);
      await refreshConversations(selectedConversation.id);
    } catch (err) {
      setError(getErrorMessage(err, 'Could not take conversation.'));
    }
  }

  async function handleReleaseConversation() {
    if (!selectedConversation || !canReleaseConversation) {
      return;
    }

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

  async function handleSendMessage(event) {
    event.preventDefault();

    if (!selectedConversation || !newMessage.trim() || isSending) {
      return;
    }

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
    if (selectedConversation) {
      loadMessages(selectedConversation.id);
    } else {
      setMessages([]);
    }
  }, [selectedConversation]);

  useEffect(() => {
    if (!token) {
      return undefined;
    }

    const intervalId = window.setInterval(() => {
      const selectedConversationId = selectedConversation?.id || null;

      refreshConversations(selectedConversationId).catch(() => {
        // Silent auto-refresh failure. Manual actions will still show errors.
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
          <div className="brand login-brand">
            <div className="brand-icon">W</div>
            <div>
              <h1>Whinly</h1>
              <p>Team WhatsApp Inbox</p>
            </div>
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
        <div className="brand">
          <div className="brand-icon">W</div>
          <div>
            <h1>Whinly</h1>
            <p>{user ? `Logged in as ${user.username}` : 'Team WhatsApp Inbox'}</p>
          </div>
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
          {conversations.length === 0 ? (
            <div className="empty-state">No conversations yet.</div>
          ) : (
            conversations.map((conversation) => {
              const isActive = selectedConversation?.id === conversation.id;
              const label = conversation.contact_name || conversation.contact_phone;

              return (
                <button
                  key={conversation.id}
                  className={`conversation ${isActive ? 'active' : ''}`}
                  onClick={() => handleSelectConversation(conversation)}
                >
                  <strong>{label}</strong>
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

        <button className="logout-button" onClick={handleLogout}>
          Logout
        </button>
      </aside>

      <main className="chat-panel">
        {selectedConversation ? (
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
                  className={`conversation-action-button ${
                    canReleaseConversation ? 'release-mode' : ''
                  }`}
                  onClick={handleConversationAction}
                  disabled={!canUseConversationAction}
                >
                  {getConversationActionLabel()}
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
                  isConversationTakenByAnotherUser
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