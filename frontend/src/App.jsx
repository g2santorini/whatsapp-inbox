import { useEffect, useState } from 'react';
import './App.css';
import {
  getToken,
  login,
  clearToken,
  getCurrentUser,
  getConversations,
  getMessages,
  sendMessage,
} from './api';

function App() {
  const [token, setToken] = useState(getToken());
  const [user, setUser] = useState(null);

  const [username, setUsername] = useState('testuser');
  const [password, setPassword] = useState('testpass');

  const [conversations, setConversations] = useState([]);
  const [selectedConversation, setSelectedConversation] = useState(null);
  const [messages, setMessages] = useState([]);

  const [newMessage, setNewMessage] = useState('');
  const [error, setError] = useState('');

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
    setConversations([]);
    setSelectedConversation(null);
    setMessages([]);
  }

  async function loadInitialData() {
    try {
      const currentUser = await getCurrentUser();
      const conversationData = await getConversations();

      setUser(currentUser);
      setConversations(conversationData);

      if (conversationData.length > 0) {
        setSelectedConversation(conversationData[0]);
      }
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
    setSelectedConversation(conversation);
  }

  async function handleSendMessage(event) {
    event.preventDefault();

    if (!selectedConversation || !newMessage.trim()) {
      return;
    }

    try {
      await sendMessage(selectedConversation.id, newMessage.trim());
      setNewMessage('');
      await loadMessages(selectedConversation.id);
    } catch (err) {
      setError('Could not send message.');
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
    }
  }, [selectedConversation]);

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
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-icon">W</div>
          <div>
            <h1>Whinly</h1>
            <p>{user ? `Logged in as ${user.username}` : 'Team WhatsApp Inbox'}</p>
          </div>
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
              </div>

              <button className="take-button">Take</button>
            </header>

            <section className="messages">
              {messages.length === 0 ? (
                <div className="empty-state">No messages yet.</div>
              ) : (
                messages.map((message) => (
                  <div
                    key={message.id}
                    className={`message ${message.direction === 'outbound' ? 'outgoing' : 'incoming'}`}
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
                placeholder="Type a message..."
              />
              <button type="submit">Send</button>
            </form>
          </>
        ) : (
          <div className="no-chat-selected">
            Select a conversation to start.
          </div>
        )}
      </main>
    </div>
  );
}

export default App;