import { Fragment, useEffect, useRef, useState } from 'react';
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
  createTemplateConversation,
  getMessages,
  sendMessage,
  takeConversation,
  releaseConversation,
  closeConversation,
  archiveConversation,
  deleteConversation,
  markConversationAsRead,
  updateConversationFollowUp,
} from './api';

const AUTO_REFRESH_INTERVAL_MS = 5000;
const ACTIVE_CHAT_REFRESH_INTERVAL_MS = 2000;
const PHONE_NUMBER_REGEX = /^\+[1-9]\d{7,14}$/;

const CONVERSATION_VIEWS = {
  ALL: 'all',
  NEEDS_ACTION: 'needs_action',
  MINE: 'mine',
  FOLLOW_UP: 'follow_up',
  DONE: 'done',
};

const APP_PAGES = {
  INBOX: 'inbox',
  SETTINGS: 'settings',
};

const NEW_CONVERSATION_TEMPLATES = [
  {
    id: 'cruise_pickup_reminder',
    label: 'Cruise pickup reminder',
    metaTemplateName: 'cruise_pickup_reminder',
    languageCode: 'en',
    fields: [
      { key: 'guestName', label: 'Guest name', placeholder: 'John Smith' },
      { key: 'cruiseName', label: 'Cruise', placeholder: 'Diamond Sunset Cruise' },
      { key: 'reservationNumber', label: 'Reservation number', placeholder: 'ABC123' },
      { key: 'cruiseDate', label: 'Cruise date', placeholder: '12 May 2026' },
      { key: 'pickupTime', label: 'Pickup time', placeholder: '14:00' },
      { key: 'pickupPoint', label: 'Pickup point', placeholder: 'Canaves Oia' },
      { key: 'googleMapsLink', label: 'Google Maps link', placeholder: 'https://maps.google.com/...' },
    ],
    buildPreview: (values) =>
      `Dear ${values.guestName || '{{1}}'},

We are contacting you from Sunset Oia regarding your sailing cruise ${values.cruiseName || '{{2}}'} with reservation number ${values.reservationNumber || '{{3}}'}.

We would like to remind you that your pick-up time for your cruise on ${values.cruiseDate || '{{4}}'} will be:

Pickup time & point: at ${values.pickupTime || '{{5}}'} from ${values.pickupPoint || '{{6}}'}
Google Maps: ${values.googleMapsLink || '{{7}}'}

Should you need any additional information, feel free to contact us on WhatsApp.

Best regards,  
Sunset Oia Sailing Team`,
  },
];

function App() {
  const [token, setToken] = useState(getToken());
  const [user, setUser] = useState(null);
  const [users, setUsers] = useState([]);

  const [username, setUsername] = useState('testuser');
  const [password, setPassword] = useState('testpass');

  const [conversations, setConversations] = useState([]);
  const [activePage, setActivePage] = useState(APP_PAGES.INBOX);
  const [activeConversationView, setActiveConversationView] = useState(
    CONVERSATION_VIEWS.ALL
  );
  const [showDoneInAll, setShowDoneInAll] = useState(false);
  const [inboxSearchQuery, setInboxSearchQuery] = useState('');
  const [selectedConversation, setSelectedConversation] = useState(null);
  const [messages, setMessages] = useState([]);

  const messagesEndRef = useRef(null);

  const [newMessage, setNewMessage] = useState('');
  const [error, setError] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [isUpdatingFollowUp, setIsUpdatingFollowUp] = useState(false);

  const [showNewConversationForm, setShowNewConversationForm] = useState(false);
  const [newContactName, setNewContactName] = useState('');
  const [newContactPhone, setNewContactPhone] = useState('');

  const [selectedNewConversationTemplateId, setSelectedNewConversationTemplateId] =
    useState('cruise_pickup_reminder');

  const [newConversationTemplateValues, setNewConversationTemplateValues] =
    useState({});

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

  function isDoneConversation(conversation) {
    return conversation.status === 'closed';
  }

  function isArchivedConversation(conversation) {
    return conversation.status === 'archived';
  }

  function isActiveConversation(conversation) {
    return !isDoneConversation(conversation) && !isArchivedConversation(conversation);
  }

  function isNeedsActionConversation(conversation) {
    return (
      isActiveConversation(conversation) &&
      (conversation.status === 'open' || conversation.status === 'taken')
    );
  }

  function isMineConversation(conversation) {
    return (
      isNeedsActionConversation(conversation) &&
      conversation.assigned_to_user_id === user?.id
    );
  }

  function isFollowUpConversation(conversation) {
    return !isArchivedConversation(conversation) && Boolean(conversation.follow_up);
  }

  const allCount = conversations.filter((conversation) => {
    if (isArchivedConversation(conversation)) return false;
    if (!showDoneInAll && isDoneConversation(conversation)) return false;
    return true;
  }).length;

  const needsActionCount = conversations.filter(isNeedsActionConversation).length;
  const mineCount = conversations.filter(isMineConversation).length;
  const followUpCount = conversations.filter(isFollowUpConversation).length;
  const doneCount = conversations.filter(isDoneConversation).length;

  const normalizedInboxSearchQuery = inboxSearchQuery.trim().toLowerCase();

  const filteredConversations = conversations.filter((conversation) => {
    let matchesActiveView = true;

    if (activeConversationView === CONVERSATION_VIEWS.ALL) {
      matchesActiveView = !isArchivedConversation(conversation);

      if (!showDoneInAll && isDoneConversation(conversation)) {
        matchesActiveView = false;
      }
    }

    if (activeConversationView === CONVERSATION_VIEWS.NEEDS_ACTION) {
      matchesActiveView = isNeedsActionConversation(conversation);
    }

    if (activeConversationView === CONVERSATION_VIEWS.MINE) {
      matchesActiveView = isMineConversation(conversation);
    }

    if (activeConversationView === CONVERSATION_VIEWS.FOLLOW_UP) {
      matchesActiveView = isFollowUpConversation(conversation);
    }

    if (activeConversationView === CONVERSATION_VIEWS.DONE) {
      matchesActiveView = isDoneConversation(conversation);
    }

    if (!matchesActiveView) {
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

    return 'Taken';
  }

  function scrollMessagesToBottom() {
    window.setTimeout(() => {
      messagesEndRef.current?.scrollIntoView({
        behavior: 'auto',
        block: 'end',
      });
    }, 100);
  }

  function getMessageDate(createdAt) {
    if (!createdAt) return null;

    const rawValue = String(createdAt);
    const hasTimezone = /[zZ]$|[+-]\d{2}:\d{2}$/.test(rawValue);
    const safeValue = hasTimezone ? rawValue : `${rawValue}Z`;
    const date = new Date(safeValue);

    if (Number.isNaN(date.getTime())) {
      return null;
    }

    return date;
  }

  function formatMessageTime(createdAt) {
    const date = getMessageDate(createdAt);

    if (!date) {
      return '';
    }

    return new Intl.DateTimeFormat('el-GR', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).format(date);
  }

  function isSameMessageDay(dateA, dateB) {
    if (!dateA || !dateB) return false;

    return (
      dateA.getFullYear() === dateB.getFullYear() &&
      dateA.getMonth() === dateB.getMonth() &&
      dateA.getDate() === dateB.getDate()
    );
  }

  function formatMessageDayLabel(createdAt) {
    const date = getMessageDate(createdAt);

    if (!date) {
      return '';
    }

    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);

    const messageDay = new Date(
      date.getFullYear(),
      date.getMonth(),
      date.getDate()
    );

    if (messageDay.getTime() === today.getTime()) {
      return 'Σήμερα';
    }

    if (messageDay.getTime() === yesterday.getTime()) {
      return 'Χθες';
    }

    return new Intl.DateTimeFormat('el-GR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    }).format(date);
  }

  function getMessageStatusLabel(message) {
    if (!message || message.direction !== 'outbound') {
      return '';
    }

    const statusValue = String(message.whatsapp_status || '').toLowerCase();

    if (statusValue === 'sent') {
      return '✓';
    }

    if (statusValue === 'delivered') {
      return '✓✓';
    }

    if (statusValue === 'read') {
      return '✓✓';
    }

    if (statusValue === 'failed') {
      return 'failed';
    }

    return '';
  }

  function getMessageStatusClass(message) {
    if (!message || message.direction !== 'outbound') {
      return '';
    }

    const statusValue = String(message.whatsapp_status || '').toLowerCase();

    if (statusValue === 'sent') {
      return 'message-status-sent';
    }

    if (statusValue === 'delivered') {
      return 'message-status-delivered';
    }

    if (statusValue === 'read') {
      return 'message-status-read';
    }

    if (statusValue === 'failed') {
      return 'message-status-failed';
    }

    return '';
  }

  function formatCustomerServiceWindow(conversation) {
    if (!conversation?.customer_service_window_open) {
      return 'Session expired — template required';
    }

    const secondsLeft = Number(
      conversation.customer_service_time_left_seconds || 0
    );

    if (secondsLeft <= 0) {
      return 'Session expired — template required';
    }

    const hours = Math.floor(secondsLeft / 3600);
    const minutes = Math.floor((secondsLeft % 3600) / 60);

    return `${hours}h ${minutes}m left`;
  }

  function getCustomerServiceWindowClass(conversation) {
    if (!conversation?.customer_service_window_open) {
      return 'customer-service-expired';
    }

    const secondsLeft = Number(
      conversation.customer_service_time_left_seconds || 0
    );

    if (secondsLeft <= 0) {
      return 'customer-service-expired';
    }

    if (secondsLeft <= 2 * 60 * 60) {
      return 'customer-service-warning';
    }

    return 'customer-service-open';
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
    setSelectedNewConversationTemplateId('cruise_pickup_reminder');
    setNewConversationTemplateValues({});
  }

  function getSelectedNewConversationTemplate() {
    return NEW_CONVERSATION_TEMPLATES.find(
      (template) => template.id === selectedNewConversationTemplateId
    );
  }

  function updateNewConversationTemplateValue(fieldKey, value) {
    setNewConversationTemplateValues((currentValues) => ({
      ...currentValues,
      [fieldKey]: value,
    }));
  }

  function getNewConversationTemplatePreview() {
    const selectedTemplate = getSelectedNewConversationTemplate();

    if (!selectedTemplate) {
      return '';
    }

    return selectedTemplate.buildPreview(newConversationTemplateValues);
  }

  function getNewConversationTemplateMissingFields() {
    const selectedTemplate = getSelectedNewConversationTemplate();

    if (!selectedTemplate) {
      return [];
    }

    return selectedTemplate.fields.filter((field) => {
      const value = newConversationTemplateValues[field.key];
      return !String(value || '').trim();
    });
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
    setActiveConversationView(CONVERSATION_VIEWS.ALL);
    setShowDoneInAll(false);
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

    const selectedTemplate = getSelectedNewConversationTemplate();
    const missingTemplateFields = getNewConversationTemplateMissingFields();

    const contactPhone = newContactPhone.trim();
    const guestName = String(newConversationTemplateValues.guestName || '').trim();
    const contactName = newContactName.trim() || guestName || contactPhone;
    const firstMessage = getNewConversationTemplatePreview().trim();

    if (!contactPhone || isCreatingConversation) {
      setError('Phone number is required.');
      return;
    }

    if (!PHONE_NUMBER_REGEX.test(contactPhone)) {
      setError('Phone number must start with + and country code, for example +306900000000.');
      return;
    }

    if (!selectedTemplate) {
      setError('Please select a template.');
      return;
    }

    if (missingTemplateFields.length > 0) {
      setError(
        `Please fill in: ${missingTemplateFields
          .map((field) => field.label)
          .join(', ')}.`
      );
      return;
    }

    if (!firstMessage) {
      setError('Template preview is required.');
      return;
    }

    const templateVariables = selectedTemplate.fields.map((field) =>
      String(newConversationTemplateValues[field.key] || '').trim()
    );

    try {
      setIsCreatingConversation(true);
      setError('');

      const createdConversation = await createTemplateConversation({
        contactName,
        contactPhone,
        templateName: selectedTemplate.metaTemplateName,
        languageCode: selectedTemplate.languageCode,
        variables: templateVariables,
        previewContent: firstMessage,
      });

      if (createdConversation?.id) {
        resetNewConversationForm();
        setShowNewConversationForm(false);
        setActivePage(APP_PAGES.INBOX);
        setActiveConversationView(CONVERSATION_VIEWS.DONE);

        await refreshConversations(createdConversation.id);
        await loadMessages(createdConversation.id);
      } else {
        setError('Template was sent, but the conversation could not be opened.');
        await refreshConversations();
      }
    } catch (err) {
      setError(getErrorMessage(err, 'Could not send template conversation.'));
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

  async function handleDoneConversation() {
    if (!selectedConversation) return;

    try {
      setError('');
      await closeConversation(selectedConversation.id);
      await refreshConversations(selectedConversation.id);
    } catch (err) {
      setError(getErrorMessage(err, 'Could not mark conversation as done.'));
    }
  }

  async function handleToggleFollowUp(checked) {
    if (!selectedConversation || isUpdatingFollowUp) return;

    try {
      setIsUpdatingFollowUp(true);
      setError('');

      await updateConversationFollowUp(selectedConversation.id, checked);

      if (checked) {
        setActiveConversationView(CONVERSATION_VIEWS.FOLLOW_UP);
      } else {
        setActiveConversationView(CONVERSATION_VIEWS.DONE);
      }

      await refreshConversations(selectedConversation.id);
    } catch (err) {
      setError(getErrorMessage(err, 'Could not update follow up.'));
    } finally {
      setIsUpdatingFollowUp(false);
    }
  }

  async function handleArchiveConversation() {
    if (!selectedConversation) return;

    try {
      setError('');
      await archiveConversation(selectedConversation.id);
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
      await closeConversation(selectedConversation.id);
      setActiveConversationView(CONVERSATION_VIEWS.DONE);
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

  const lastMessageId =
    messages.length > 0 ? messages[messages.length - 1]?.id : null;

  useEffect(() => {
    if (!selectedConversation?.id || !lastMessageId) {
      return;
    }

    scrollMessagesToBottom();
  }, [selectedConversation?.id, lastMessageId]);

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
    activeConversationView,
    conversations,
    user?.id,
    activePage,
    inboxSearchQuery,
    showDoneInAll,
    selectedConversation?.id,
  ]);

  useEffect(() => {
    if (!token) return undefined;

    const intervalId = window.setInterval(() => {
      const selectedConversationId = selectedConversation?.id || null;

      refreshConversations(selectedConversationId).catch(() => {
        // Silent conversations auto-refresh failure.
      });
    }, AUTO_REFRESH_INTERVAL_MS);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [token, selectedConversation?.id]);

  useEffect(() => {
    if (!token || !selectedConversation?.id) {
      return undefined;
    }

    const selectedConversationId = selectedConversation.id;

    const intervalId = window.setInterval(() => {
      loadMessages(selectedConversationId).catch(() => {
        // Silent active chat refresh failure.
      });
    }, ACTIVE_CHAT_REFRESH_INTERVAL_MS);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [token, selectedConversation?.id]);

  useEffect(() => {
    if (!token || activePage !== APP_PAGES.INBOX || !selectedConversation?.id) {
      return undefined;
    }

    const selectedConversationId = selectedConversation.id;

    const intervalId = window.setInterval(() => {
      loadMessages(selectedConversationId).catch(() => {
        // Silent messages auto-refresh failure.
      });
    }, AUTO_REFRESH_INTERVAL_MS);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [token, activePage, selectedConversation?.id]);

  if (!token) {
    return (
      <div className="login-page">
        <form className="login-card" onSubmit={handleLogin}>
          <div className="login-brand">
            <div className="brand">
              <div className="brand-icon">
                <img src={sendroLogo} alt="Sendro logo" className="brand-logo" />
              </div>
              <div>
                <h1>Sendro</h1>
                <p>Team WhatsApp Inbox</p>
              </div>
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
    <div className="app sendro-shell">
      {error && <div className="app-error">{error}</div>}

      <aside className="blue-sidebar">
        <div className="blue-sidebar-top">
          <div className="blue-brand">
            <div className="blue-brand-icon">
              <img src={sendroLogo} alt="Sendro logo" className="blue-brand-logo" />
            </div>
            <span>Sendro</span>
          </div>

          <div className="blue-section-title">Conversations</div>

          <div className="blue-filter-list">
            <button
              type="button"
              className={`blue-filter-button ${activeConversationView === CONVERSATION_VIEWS.ALL ? 'active' : ''
                }`}
              onClick={() => {
                setActivePage(APP_PAGES.INBOX);
                setActiveConversationView(CONVERSATION_VIEWS.ALL);
              }}
            >
              <span>All</span>
              <strong>{allCount}</strong>
            </button>

            <button
              type="button"
              className={`blue-filter-button ${activeConversationView === CONVERSATION_VIEWS.NEEDS_ACTION
                ? 'active'
                : ''
                }`}
              onClick={() => {
                setActivePage(APP_PAGES.INBOX);
                setActiveConversationView(CONVERSATION_VIEWS.NEEDS_ACTION);
              }}
            >
              <span>Needs Action</span>
              <strong>{needsActionCount}</strong>
            </button>

            <button
              type="button"
              className={`blue-filter-button ${activeConversationView === CONVERSATION_VIEWS.MINE ? 'active' : ''
                }`}
              onClick={() => {
                setActivePage(APP_PAGES.INBOX);
                setActiveConversationView(CONVERSATION_VIEWS.MINE);
              }}
            >
              <span>Mine</span>
              <strong>{mineCount}</strong>
            </button>

            <button
              type="button"
              className={`blue-filter-button ${activeConversationView === CONVERSATION_VIEWS.FOLLOW_UP
                ? 'active'
                : ''
                }`}
              onClick={() => {
                setActivePage(APP_PAGES.INBOX);
                setActiveConversationView(CONVERSATION_VIEWS.FOLLOW_UP);
              }}
            >
              <span>To Follow Up</span>
              <strong>{followUpCount}</strong>
            </button>

            <button
              type="button"
              className={`blue-filter-button ${activeConversationView === CONVERSATION_VIEWS.DONE ? 'active' : ''
                }`}
              onClick={() => {
                setActivePage(APP_PAGES.INBOX);
                setActiveConversationView(CONVERSATION_VIEWS.DONE);
              }}
            >
              <span>Done</span>
              <strong>{doneCount}</strong>
            </button>
          </div>

          <button
            type="button"
            className={`blue-settings-button ${activePage === APP_PAGES.SETTINGS ? 'active' : ''}`}
            onClick={() => setActivePage(APP_PAGES.SETTINGS)}
          >
            Settings
          </button>
        </div>

        <div className="blue-sidebar-bottom">
          <div className="blue-user-box">
            <span>Logged in as</span>
            <strong>{user?.username || 'User'}</strong>
            <small>{user?.role || 'user'}</small>
          </div>

          <button className="blue-logout-button" onClick={handleLogout}>
            Logout
          </button>
        </div>
      </aside>

      <section className="conversation-column">
        <div className="conversation-column-header">
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

          {activeConversationView === CONVERSATION_VIEWS.ALL && (
            <label className="show-done-toggle">
              <input
                type="checkbox"
                checked={showDoneInAll}
                onChange={(event) => setShowDoneInAll(event.target.checked)}
              />
              <span>Show Done</span>
            </label>
          )}
        </div>

        {showNewConversationForm && (
          <div className="new-conversation-overlay">
            <div className="new-conversation-overlay-header">
              <div>
                <h3>New conversation</h3>
                <p>Create a chat and send an approved template preview.</p>
              </div>
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

              <div className="new-template-box">
                <label className="new-template-field">
                  <span>Choose template</span>

                  <select
                    value={selectedNewConversationTemplateId}
                    onChange={(event) => {
                      setSelectedNewConversationTemplateId(event.target.value);
                      setNewConversationTemplateValues({});
                    }}
                    disabled={isCreatingConversation}
                  >
                    {NEW_CONVERSATION_TEMPLATES.map((template) => (
                      <option key={template.id} value={template.id}>
                        {template.label}
                      </option>
                    ))}
                  </select>
                </label>

                {getSelectedNewConversationTemplate()?.fields.map((field) => (
                  <label className="new-template-field" key={field.key}>
                    <span>{field.label}</span>

                    <input
                      value={newConversationTemplateValues[field.key] || ''}
                      onChange={(event) =>
                        updateNewConversationTemplateValue(field.key, event.target.value)
                      }
                      placeholder={field.placeholder}
                      disabled={isCreatingConversation}
                    />
                  </label>
                ))}

                <label className="new-template-field">
                  <span>Preview</span>
                  <textarea value={getNewConversationTemplatePreview()} readOnly rows="10" />
                </label>
              </div>

              <button
                type="submit"
                disabled={
                  isCreatingConversation ||
                  !newContactPhone.trim() ||
                  getNewConversationTemplateMissingFields().length > 0
                }
              >
                {isCreatingConversation ? 'Creating...' : 'Create & Send Template'}
              </button>
            </form>
          </div>
        )}

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
                    {isDoneConversation(conversation) && (
                      <span className="status-pill">Done</span>
                    )}

                    {isArchivedConversation(conversation) && (
                      <span className="status-pill">Archived</span>
                    )}

                    {conversation.assigned_to_user_id && (
                      <span
                        className={`assigned-badge ${getAssignedUserClass(
                          conversation.assigned_to_user_id
                        )}`}
                      >
                        Taken by {getAssignedUserLabel(conversation.assigned_to_user_id)}
                      </span>
                    )}
                  </small>
                </button>
              );
            })
          )}
        </div>
      </section>

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
                  Back to conversations
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

                <div className="conversation-status-area">
                  <p className="conversation-status-row">
                    {isDoneConversation(selectedConversation) && (
                      <span className="status-pill">Done</span>
                    )}

                    {isArchivedConversation(selectedConversation) && (
                      <span className="status-pill">Archived</span>
                    )}

                    {selectedConversation.assigned_to_user_id ? (
                      <span
                        className={`assigned-badge ${getAssignedUserClass(
                          selectedConversation.assigned_to_user_id
                        )}`}
                      >
                        Taken by {getAssignedUserLabel(selectedConversation.assigned_to_user_id)}
                      </span>
                    ) : (
                      <span className="assigned-badge assigned-nobody">Available</span>
                    )}

                    <span
                      className={`customer-service-badge ${getCustomerServiceWindowClass(
                        selectedConversation
                      )}`}
                    >
                      {formatCustomerServiceWindow(selectedConversation)}
                    </span>
                  </p>

                  {isDoneConversation(selectedConversation) && (
                    <label className="follow-up-checkbox">
                      <input
                        type="checkbox"
                        checked={Boolean(selectedConversation.follow_up)}
                        onChange={(event) => handleToggleFollowUp(event.target.checked)}
                        disabled={isUpdatingFollowUp}
                      />
                      <span>To Follow Up</span>
                    </label>
                  )}
                </div>
              </div>

              <div className="chat-actions">
                <button
                  className={`conversation-action-button ${canReleaseConversation ? 'release-mode' : ''
                    }`}
                  onClick={handleConversationAction}
                  disabled={!canUseConversationAction}
                >
                  {getConversationActionLabel()}
                </button>

                <button
                  className="conversation-action-button"
                  type="button"
                  onClick={handleDoneConversation}
                  disabled={selectedConversation.status === 'closed'}
                >
                  Done
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
                messages.map((message, index) => {
                  const previousMessage = messages[index - 1];
                  const currentMessageDate = getMessageDate(message.created_at);
                  const previousMessageDate = getMessageDate(previousMessage?.created_at);
                  const shouldShowDaySeparator =
                    currentMessageDate &&
                    !isSameMessageDay(currentMessageDate, previousMessageDate);
                  const messageTime = formatMessageTime(message.created_at);

                  return (
                    <Fragment key={message.id}>
                      {shouldShowDaySeparator && (
                        <div className="message-day-separator">
                          <span>{formatMessageDayLabel(message.created_at)}</span>
                        </div>
                      )}

                      <div
                        className={`message ${message.direction === 'outbound' ? 'outgoing' : 'incoming'
                          }`}
                      >
                        <div className="message-content">{message.content}</div>

                        {(messageTime || getMessageStatusLabel(message)) && (
                          <div className="message-meta">
                            {messageTime && <span>{messageTime}</span>}

                            {getMessageStatusLabel(message) && (
                              <span
                                className={`message-status ${getMessageStatusClass(
                                  message
                                )}`}
                              >
                                {getMessageStatusLabel(message)}
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    </Fragment>
                  );
                })
              )}

              <div ref={messagesEndRef} />
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

      <aside className="future-panel" aria-label="Future templates and quick replies panel" />
    </div>
  );
}

export default App;