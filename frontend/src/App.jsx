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
  getMessageMediaBlob,
  sendMessage,
  takeConversation,
  releaseConversation,
  closeConversation,
  archiveConversation,
  deleteConversation,
  unarchiveConversation,
  markConversationAsRead,
  updateConversationFollowUp,
  getTemplateReportItems,
} from './api';

const AUTO_REFRESH_INTERVAL_MS = 3000;
const ACTIVE_CHAT_REFRESH_INTERVAL_MS = 2000;
const PHONE_NUMBER_REGEX = /^\+[1-9]\d{7,14}$/;
const APP_BROWSER_TITLE = 'Sendro | Sunset Oia';

const CONVERSATION_VIEWS = {
  INBOX: 'inbox',
  MINE: 'mine',
  FOLLOW_UP: 'follow_up',
  ARCHIVED: 'archived',
};

const APP_PAGES = {
  INBOX: 'inbox',
  REPORTS: 'reports',
  SETTINGS: 'settings',
};

function playNotificationSound() {
  try {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;

    if (!AudioContextClass) {
      return;
    }

    const audioContext = new AudioContextClass();

    const playTone = (frequency, startTime, duration) => {
      const oscillator = audioContext.createOscillator();
      const gainNode = audioContext.createGain();

      oscillator.type = 'sine';
      oscillator.frequency.setValueAtTime(frequency, startTime);

      gainNode.gain.setValueAtTime(0.0001, startTime);
      gainNode.gain.exponentialRampToValueAtTime(0.22, startTime + 0.02);
      gainNode.gain.exponentialRampToValueAtTime(0.0001, startTime + duration);

      oscillator.connect(gainNode);
      gainNode.connect(audioContext.destination);

      oscillator.start(startTime);
      oscillator.stop(startTime + duration);
    };

    const startSound = () => {
      const now = audioContext.currentTime;

      playTone(880, now, 0.18);
      playTone(1175, now + 0.16, 0.22);

      window.setTimeout(() => {
        audioContext.close().catch(() => {
          // Ignore audio close errors.
        });
      }, 600);
    };

    if (audioContext.state === 'suspended') {
      audioContext.resume().then(startSound).catch(() => {
        audioContext.close().catch(() => {
          // Ignore audio close errors.
        });
      });
      return;
    }

    startSound();
  } catch {
    // Browsers may block sound until the user interacts with the page.
  }
}

const NEW_CONVERSATION_TEMPLATES = [
  {
    id: 'pickup_reminder_hotel',
    label: 'Pickup reminder - Hotel',
    metaTemplateName: 'pickup_reminder_hotel',
    languageCode: 'en',
    fields: [
      { key: 'guestName', label: 'Guest name', placeholder: 'John Smith' },
      { key: 'tourName', label: 'Tour name', placeholder: 'Diamond Sunset Cruise' },
      { key: 'reservationNumber', label: 'Reservation number', placeholder: '0025257168' },
      { key: 'cruiseDate', label: 'Cruise date', placeholder: '12 May 2026' },
      { key: 'pickupTime', label: 'Pickup time', placeholder: '14:00' },
      { key: 'pickupPoint', label: 'Hotel / pickup point', placeholder: 'Canaves Oia Suites' },
    ],
    buildVariables: (values) => [
      values.guestName,
      values.tourName,
      values.reservationNumber,
      values.cruiseDate,
      values.pickupTime,
      values.pickupPoint,
    ],
    buildPreview: (values) =>
      `Dear ${values.guestName || '{{1}}'},

We are contacting you from Sunset Oia regarding your sailing cruise ${values.tourName || '{{2}}'} with reservation number ${values.reservationNumber || '{{3}}'}.

We would like to remind you that your pick-up time for your cruise on ${values.cruiseDate || '{{4}}'} will be:

Pickup time & point: at ${values.pickupTime || '{{5}}'} from ${values.pickupPoint || '{{6}}'}.

Best regards,
Sunset Oia Sailing Team`,
  },
  {
    id: 'pickup_reminder_hotel_missing_details',
    label: 'Pickup reminder - Hotel + missing details',
    metaTemplateName: 'pickup_reminder_hotel_missing_details',
    languageCode: 'en',
    fields: [
      { key: 'guestName', label: 'Guest name', placeholder: 'John Smith' },
      { key: 'tourName', label: 'Tour name', placeholder: 'Diamond Sunset Cruise' },
      { key: 'reservationNumber', label: 'Reservation number', placeholder: '0025257168' },
      { key: 'cruiseDate', label: 'Cruise date', placeholder: '12 May 2026' },
      { key: 'pickupTime', label: 'Pickup time', placeholder: '14:00' },
      { key: 'pickupPoint', label: 'Hotel / pickup point', placeholder: 'Canaves Oia Suites' },
      { key: 'passengerInfoLink', label: 'Passenger info link', placeholder: 'https://...' },
    ],
    buildVariables: (values) => [
      values.guestName,
      values.tourName,
      values.reservationNumber,
      values.cruiseDate,
      values.pickupTime,
      values.pickupPoint,
      values.passengerInfoLink,
    ],
    buildPreview: (values) =>
      `Dear ${values.guestName || '{{1}}'},

We are contacting you from Sunset Oia regarding your sailing cruise ${values.tourName || '{{2}}'} with reservation number ${values.reservationNumber || '{{3}}'}.

We would like to remind you that your pick-up time for your cruise on ${values.cruiseDate || '{{4}}'} will be:

Pickup time & point: at ${values.pickupTime || '{{5}}'} from ${values.pickupPoint || '{{6}}'}.

Please also complete the missing passenger details using the link below:
${values.passengerInfoLink || '{{7}}'}

Best regards,
Sunset Oia Sailing Team`,
  },
  {
    id: 'pickup_reminder_meeting_point',
    label: 'Pickup reminder - Meeting point',
    metaTemplateName: 'pickup_reminder_meeting_point',
    languageCode: 'en',
    fields: [
      { key: 'guestName', label: 'Guest name', placeholder: 'John Smith' },
      { key: 'tourName', label: 'Tour name', placeholder: 'Diamond Sunset Cruise' },
      { key: 'reservationNumber', label: 'Reservation number', placeholder: '0025257168' },
      { key: 'cruiseDate', label: 'Cruise date', placeholder: '12 May 2026' },
      { key: 'pickupTime', label: 'Pickup time', placeholder: '14:00' },
      { key: 'pickupPoint', label: 'Meeting point', placeholder: 'Aktaion Restaurant, Fira' },
      { key: 'googleMaps', label: 'Google Maps link', placeholder: 'https://maps.google.com/...' },
    ],
    buildVariables: (values) => [
      values.guestName,
      values.tourName,
      values.reservationNumber,
      values.cruiseDate,
      values.pickupTime,
      values.pickupPoint,
      values.googleMaps,
    ],
    buildPreview: (values) =>
      `Dear ${values.guestName || '{{1}}'},

We are contacting you from Sunset Oia regarding your sailing cruise ${values.tourName || '{{2}}'} with reservation number ${values.reservationNumber || '{{3}}'}.

We would like to remind you that your pick-up time for your cruise on ${values.cruiseDate || '{{4}}'} will be:

Pickup time & point: at ${values.pickupTime || '{{5}}'} from ${values.pickupPoint || '{{6}}'}.
Google Maps: ${values.googleMaps || '{{7}}'}

Best regards,
Sunset Oia Sailing Team`,
  },
  {
    id: 'pickup_reminder_meeting_point_missing_details',
    label: 'Pickup reminder - Meeting point + missing details',
    metaTemplateName: 'pickup_reminder_meeting_point_missing_details',
    languageCode: 'en',
    fields: [
      { key: 'guestName', label: 'Guest name', placeholder: 'John Smith' },
      { key: 'tourName', label: 'Tour name', placeholder: 'Diamond Sunset Cruise' },
      { key: 'reservationNumber', label: 'Reservation number', placeholder: '0025257168' },
      { key: 'cruiseDate', label: 'Cruise date', placeholder: '12 May 2026' },
      { key: 'pickupTime', label: 'Pickup time', placeholder: '14:00' },
      { key: 'pickupPoint', label: 'Meeting point', placeholder: 'Aktaion Restaurant, Fira' },
      { key: 'googleMaps', label: 'Google Maps link', placeholder: 'https://maps.google.com/...' },
      { key: 'passengerInfoLink', label: 'Passenger info link', placeholder: 'https://...' },
    ],
    buildVariables: (values) => [
      values.guestName,
      values.tourName,
      values.reservationNumber,
      values.cruiseDate,
      values.pickupTime,
      values.pickupPoint,
      values.googleMaps,
      values.passengerInfoLink,
    ],
    buildPreview: (values) =>
      `Dear ${values.guestName || '{{1}}'},

We are contacting you from Sunset Oia regarding your sailing cruise ${values.tourName || '{{2}}'} with reservation number ${values.reservationNumber || '{{3}}'}.

We would like to remind you that your pick-up time for your cruise on ${values.cruiseDate || '{{4}}'} will be:

Pickup time & point: at ${values.pickupTime || '{{5}}'} from ${values.pickupPoint || '{{6}}'}.
Google Maps: ${values.googleMaps || '{{7}}'}

Please also complete the missing passenger details using the link below:
${values.passengerInfoLink || '{{8}}'}

Best regards,
Sunset Oia Sailing Team`,
  },
  {
    id: 'missing_hotel_details',
    label: 'Missing hotel details',
    metaTemplateName: 'missing_hotel_details',
    languageCode: 'en',
    fields: [
      { key: 'guestName', label: 'Guest name', placeholder: 'John Smith' },
      { key: 'reservationNumber', label: 'Reservation number', placeholder: '0025257168' },
    ],
    buildVariables: (values) => [
      values.guestName,
      values.reservationNumber,
    ],
    buildPreview: (values) =>
      `Dear ${values.guestName || '{{1}}'},

Greetings from the beautiful Santorini and thank you for choosing Sunset Oia for your sailing experience.

Regarding your reservation with reservation number ${values.reservationNumber || '{{2}}'}.

Please send us the name of your hotel so that we may arrange your pick-up time and point. In case you are staying in an Airbnb, please send us the name of your Airbnb and the contact details of your host.

We remain at your disposal for any additional information or clarification.

Best regards,
Sunset Oia Sailing Team`,
  },
  {
    id: 'post_call_followup_request',
    label: 'Post-call follow-up request',
    metaTemplateName: 'post_call_followup_request',
    languageCode: 'en',
    fields: [
      { key: 'guestName', label: 'Guest name', placeholder: 'John Smith' },
    ],
    buildVariables: (values) => [
      values.guestName,
    ],
    buildPreview: (values) =>
      `Dear ${values.guestName || '{{1}}'},

Thank you for contacting Sunset Oia.

As discussed, please send us the requested details here on WhatsApp, and our team will be happy to assist you further.

Best regards,
Sunset Oia Sailing Team`,
  },
  {
    id: 'no_transfer_amoudi',
    label: 'No transfer - Amoudi',
    metaTemplateName: 'no_transfer_amoudi',
    languageCode: 'en',
    fields: [
      { key: 'guestName', label: 'Guest name', placeholder: 'Tom Maguire' },
      { key: 'reservationNumber', label: 'Reservation number', placeholder: '0025255180/GYG2Q9NWF239' },
      { key: 'meetingTime', label: 'Meeting time', placeholder: '09:15' },
      { key: 'cruiseDate', label: 'Cruise date', placeholder: '10/05/2026' },
    ],
    buildVariables: (values) => [
      values.guestName,
      values.reservationNumber,
      values.meetingTime,
      values.cruiseDate,
    ],
    buildPreview: (values) =>
      `Dear ${values.guestName || '{{1}}'},

We are contacting you from Sunset Oia regarding your sailing cruise with reservation number ${values.reservationNumber || '{{2}}'}.

We would like to remind you that you will have to be at Amoudi port at ${values.meetingTime || '{{3}}'} for your sailing cruise on ${values.cruiseDate || '{{4}}'}.

Google Maps: https://goo.gl/maps/jJrjT9rPvnK81xH4A

Should you need any additional information regarding your cruise, please call us at +30 22860 72200 or contact us on WhatsApp.

Best regards,
Sunset Oia Sailing team`,
  },
  {
    id: 'driver_delay_notice',
    label: 'Driver delay - Sailing cruise',
    metaTemplateName: 'driver_delay_notice',
    languageCode: 'en',
    fields: [
      { key: 'guestName', label: 'Guest name', placeholder: 'Tom Maguire' },
      { key: 'delayMinutes', label: 'Delay minutes', placeholder: '10' },
    ],
    buildVariables: (values) => [
      values.guestName,
      values.delayMinutes,
    ],
    buildPreview: (values) =>
      `Dear ${values.guestName || '{{1}}'},

We would like to inform you that the driver for your sailing cruise is expected to be approximately ${values.delayMinutes || '{{2}}'} minutes late.

We sincerely apologize for the inconvenience and thank you for your kind understanding.

Best regards,
Sunset Oia Sailing team`,
  },
];

function getMediaCaption(content) {
  const lines = String(content || '').split('\n');

  const captionLine = lines.find((line) =>
    line.trim().toLowerCase().startsWith('caption:')
  );

  if (!captionLine) {
    return '';
  }

  return captionLine.replace(/^caption:\s*/i, '').trim();
}

const MESSAGE_URL_REGEX = /(https?:\/\/[^\s]+|www\.[^\s]+)/gi;

function renderMessageContentWithLinks(content) {
  const text = String(content || '');

  if (!text) {
    return null;
  }

  const parts = [];
  let lastIndex = 0;

  for (const match of text.matchAll(MESSAGE_URL_REGEX)) {
    const urlText = match[0];
    const matchIndex = match.index ?? 0;

    if (matchIndex > lastIndex) {
      parts.push(text.slice(lastIndex, matchIndex));
    }

    let cleanUrl = urlText;
    let trailingText = '';

    while (/[.,!?;:)]$/.test(cleanUrl)) {
      trailingText = cleanUrl.slice(-1) + trailingText;
      cleanUrl = cleanUrl.slice(0, -1);
    }

    const href = cleanUrl.startsWith('www.') ? `https://${cleanUrl}` : cleanUrl;

    parts.push(
      <a
        key={`message-link-${matchIndex}`}
        href={href}
        target="_blank"
        rel="noopener noreferrer"
      >
        {cleanUrl}
      </a>
    );

    if (trailingText) {
      parts.push(trailingText);
    }

    lastIndex = matchIndex + urlText.length;
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts;
}

function MessageMediaPreview({ message }) {
  const [mediaUrl, setMediaUrl] = useState('');
  const [mediaError, setMediaError] = useState('');

  const messageType = String(message?.message_type || 'text').toLowerCase();
  const caption = getMediaCaption(message?.content);
  const hasMedia = Boolean(message?.id && message?.media_id);

  useEffect(() => {
    let isMounted = true;
    let objectUrl = '';

    async function loadMedia() {
      if (!hasMedia) {
        setMediaUrl('');
        setMediaError('');
        return;
      }

      try {
        setMediaError('');

        const blob = await getMessageMediaBlob(message.id);
        objectUrl = URL.createObjectURL(blob);

        if (isMounted) {
          setMediaUrl(objectUrl);
        }
      } catch {
        if (isMounted) {
          setMediaError('Could not load media.');
        }
      }
    }

    loadMedia();

    return () => {
      isMounted = false;

      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [hasMedia, message?.id]);

  if (messageType === 'image' && hasMedia) {
    return (
      <div className="media-message-body">
        {mediaUrl ? (
          <a href={mediaUrl} target="_blank" rel="noreferrer">
            <img className="message-media-image" src={mediaUrl} alt="WhatsApp media" />
          </a>
        ) : (
          <div className="message-media-loading">Loading photo...</div>
        )}

        {caption && <div className="message-media-caption">{caption}</div>}
        {mediaError && <div className="message-media-error">{mediaError}</div>}
      </div>
    );
  }

  if (messageType === 'document' && hasMedia) {
    const filename = message.media_filename || 'Document';

    return (
      <div className="media-message-body">
        <div className="message-document-card">
          <div>
            <strong>Document</strong>
            <span>{filename}</span>
          </div>

          {mediaUrl ? (
            <a href={mediaUrl} target="_blank" rel="noreferrer">
              Open
            </a>
          ) : (
            <small>Loading...</small>
          )}
        </div>

        {caption && <div className="message-media-caption">{caption}</div>}
        {mediaError && <div className="message-media-error">{mediaError}</div>}
      </div>
    );
  }

  return (
    <div className="message-content">
      {renderMessageContentWithLinks(message.content)}
    </div>
  );
}

function App() {
  const [token, setToken] = useState(getToken());
  const [user, setUser] = useState(null);
  const [users, setUsers] = useState([]);

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  const [conversations, setConversations] = useState([]);
  const [activePage, setActivePage] = useState(APP_PAGES.INBOX);

  const [reportFilters, setReportFilters] = useState({
    operation_date: '',
    date_from: '',
    date_to: '',
    option_code: '',
    status: '',
    whatsapp_status: '',
    q: '',
    problems_only: false,
  });
  const [reportData, setReportData] = useState(null);
  const [isLoadingReports, setIsLoadingReports] = useState(false);
  const [reportsError, setReportsError] = useState('');
  const [activeConversationView, setActiveConversationView] = useState(
    CONVERSATION_VIEWS.INBOX
  );
  const [inboxSearchQuery, setInboxSearchQuery] = useState('');
  const [selectedConversation, setSelectedConversation] = useState(null);
  const [messages, setMessages] = useState([]);

  const messagesEndRef = useRef(null);
  const latestConversationRequestIdRef = useRef(0);
  const previousBrowserUnreadCountRef = useRef(0);
  const hasInitializedUnreadSoundRef = useRef(false);

  const [newMessage, setNewMessage] = useState('');
  const [error, setError] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [isUpdatingFollowUp, setIsUpdatingFollowUp] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const [showNewConversationForm, setShowNewConversationForm] = useState(false);
  const [newContactName, setNewContactName] = useState('');
  const [newContactPhone, setNewContactPhone] = useState('');

  const [selectedNewConversationTemplateId, setSelectedNewConversationTemplateId] =
    useState('pickup_reminder_hotel');

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

  const isCustomerServiceSessionExpired =
    Boolean(selectedConversation) &&
    !selectedConversation.customer_service_window_open;

  const canSendMessage =
    Boolean(selectedConversation) &&
    !isCustomerServiceSessionExpired &&
    !isConversationTakenByAnotherUser &&
    selectedConversation?.status !== 'archived' &&
    !isSending;

  const canCurrentUserViewReports =
    Boolean(user) &&
    (
      user.role === 'admin' ||
      user.role === 'power_user' ||
      Boolean(user.can_view_reports)
    );

  function isDoneConversation(conversation) {
    return conversation.status === 'closed';
  }

  function isArchivedConversation(conversation) {
    return conversation.status === 'archived';
  }

  function isActiveConversation(conversation) {
    return !isArchivedConversation(conversation);
  }

  function isMineConversation(conversation) {
    return (
      isActiveConversation(conversation) &&
      conversation.assigned_to_user_id === user?.id
    );
  }

  function isFollowUpConversation(conversation) {
    return !isArchivedConversation(conversation) && Boolean(conversation.follow_up);
  }

  const inboxUnreadCount = conversations.filter((conversation) => {
    return (
      !isArchivedConversation(conversation) &&
      Number(conversation.unread_count || 0) > 0
    );
  }).length;

  const browserUnreadCount = conversations.reduce((total, conversation) => {
    if (isArchivedConversation(conversation)) {
      return total;
    }

    return total + Number(conversation.unread_count || 0);
  }, 0);

  const mineCount = conversations.filter(isMineConversation).length;

  const normalizedInboxSearchQuery = inboxSearchQuery.trim().toLowerCase();

  const filteredConversations = conversations.filter((conversation) => {
    if (normalizedInboxSearchQuery) {
      return true;
    }

    let matchesActiveView = true;

    if (activeConversationView === CONVERSATION_VIEWS.INBOX) {
      matchesActiveView = !isArchivedConversation(conversation);
    }

    if (activeConversationView === CONVERSATION_VIEWS.MINE) {
      matchesActiveView = isMineConversation(conversation);
    }

    if (activeConversationView === CONVERSATION_VIEWS.FOLLOW_UP) {
      matchesActiveView = isFollowUpConversation(conversation);
    }

    if (activeConversationView === CONVERSATION_VIEWS.ARCHIVED) {
      matchesActiveView = isArchivedConversation(conversation);
    }

    if (!matchesActiveView) {
      return false;
    }

    return true;
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

  function getMessageAuthorLabel(message) {
    if (!message || message.direction !== 'outbound') {
      return '';
    }

    const authorName = String(message.author_name || '').trim();

    if (authorName) {
      return authorName;
    }

    const authorUsername = String(message.author_username || '').trim();

    if (authorUsername) {
      return authorUsername;
    }

    if (message.user_id) {
      return `User #${message.user_id}`;
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

  function getResponseIndicatorLabel(conversation) {
    const lastDirection = String(conversation?.last_message_direction || '').toLowerCase();

    if (lastDirection === 'inbound') {
      return 'Customer replied last';
    }

    if (lastDirection === 'outbound') {
      return 'We replied last';
    }

    return 'No messages yet';
  }

  function getResponseIndicatorClass(conversation) {
    const lastDirection = String(conversation?.last_message_direction || '').toLowerCase();

    if (lastDirection === 'inbound') {
      return 'response-indicator-customer';
    }

    if (lastDirection === 'outbound') {
      return 'response-indicator-team';
    }

    return 'response-indicator-neutral';
  }

  function getConversationResponseDotClass(conversation) {
    const lastDirection = String(conversation?.last_message_direction || '').toLowerCase();

    if (lastDirection === 'inbound') {
      return 'conversation-response-dot-customer';
    }

    if (lastDirection === 'outbound') {
      return 'conversation-response-dot-team';
    }

    return 'conversation-response-dot-neutral';
  }

  function formatReportDate(value) {
    if (!value) return '-';

    const parts = String(value).split('-');

    if (parts.length === 3) {
      return `${parts[2]}/${parts[1]}/${parts[0]}`;
    }

    return value;
  }

  function formatReportDateTime(value) {
    if (!value) return '-';

    const rawValue = String(value);
    const hasTimezone = /[zZ]$|[+-]\d{2}:\d{2}$/.test(rawValue);
    const safeValue = hasTimezone ? rawValue : `${rawValue}Z`;
    const date = new Date(safeValue);

    if (Number.isNaN(date.getTime())) {
      return rawValue;
    }

    return new Intl.DateTimeFormat('el-GR', {
      day: '2-digit',
      month: '2-digit',
      year: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).format(date);
  }

  function getReportResultClass(item) {
    const statusValue = String(item?.status || '').toLowerCase();
    const whatsappStatusValue = String(item?.whatsapp_status || '').toLowerCase();

    if (whatsappStatusValue === 'read') return 'report-badge-read';
    if (whatsappStatusValue === 'delivered') return 'report-badge-delivered';

    if (
      statusValue === 'failed' ||
      statusValue === 'no_number' ||
      statusValue === 'invalid_number' ||
      statusValue === 'validation_failed' ||
      whatsappStatusValue === 'failed'
    ) {
      return 'report-badge-problem';
    }

    if (statusValue === 'duplicate') return 'report-badge-duplicate';
    if (statusValue === 'sent') return 'report-badge-sent';

    return 'report-badge-neutral';
  }

  function updateReportFilter(key, value) {
    setReportFilters((currentFilters) => ({
      ...currentFilters,
      [key]: value,
    }));
  }

  async function loadTemplateReports(filtersOverride = reportFilters) {
    try {
      setIsLoadingReports(true);
      setReportsError('');

      const data = await getTemplateReportItems({
        ...filtersOverride,
        limit: 300,
        offset: 0,
      });

      setReportData(data);
    } catch (err) {
      setReportsError(getErrorMessage(err, 'Could not load reports.'));
    } finally {
      setIsLoadingReports(false);
    }
  }

  async function handleReportsSubmit(event) {
    event.preventDefault();
    await loadTemplateReports(reportFilters);
  }

  async function handleReportsReset() {
    const resetFilters = {
      operation_date: '',
      date_from: '',
      date_to: '',
      option_code: '',
      status: '',
      whatsapp_status: '',
      q: '',
      problems_only: false,
    };

    setReportFilters(resetFilters);
    await loadTemplateReports(resetFilters);
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
    setSelectedNewConversationTemplateId('pickup_reminder_hotel');
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

  async function refreshConversations(
    selectedConversationId = null,
    searchQueryOverride = inboxSearchQuery
  ) {
    const requestId = latestConversationRequestIdRef.current + 1;
    latestConversationRequestIdRef.current = requestId;

    const conversationData = await getConversations(searchQueryOverride);

    if (requestId !== latestConversationRequestIdRef.current) {
      return;
    }

    setConversations(conversationData);

    if (selectedConversationId) {
      const refreshedConversation = conversationData.find(
        (conversation) => conversation.id === selectedConversationId
      );

      if (refreshedConversation) {
        setSelectedConversation(refreshedConversation);
        return;
      }

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
    setActivePage(APP_PAGES.INBOX);
    setActiveConversationView(CONVERSATION_VIEWS.INBOX);
    setInboxSearchQuery('');
    resetNewConversationForm();

    setReportData(null);
    setReportsError('');
    setReportFilters({
      operation_date: '',
      date_from: '',
      date_to: '',
      option_code: '',
      status: '',
      whatsapp_status: '',
      q: '',
      problems_only: false,
    });
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
      const errorMessage = getErrorMessage(err, 'Could not load messages.');
      const normalizedErrorMessage = String(errorMessage).toLowerCase();

      const conversationWasDeleted =
        normalizedErrorMessage.includes('conversation not found') ||
        normalizedErrorMessage.includes('404');

      if (conversationWasDeleted) {
        setSelectedConversation((currentConversation) => {
          if (currentConversation?.id === conversationId) {
            return null;
          }

          return currentConversation;
        });

        setMessages([]);

        refreshConversations(null, inboxSearchQuery).catch(() => {
          // Silent refresh failure after deleted conversation.
        });

        return;
      }

      const sessionProblem =
        normalizedErrorMessage.includes('could not validate credentials') ||
        normalizedErrorMessage.includes('not authenticated') ||
        normalizedErrorMessage.includes('session expired') ||
        normalizedErrorMessage.includes('401');

      if (sessionProblem) {
        handleLogout();
        setError('Session expired. Please login again.');
        return;
      }

      setError(errorMessage);
    }
  }

  async function handleSelectConversation(conversation) {
    setError('');
    setActivePage(APP_PAGES.INBOX);
    setSelectedConversation(conversation);

    const isTakenByAnotherUser =
      conversation.assigned_to_user_id !== null &&
      conversation.assigned_to_user_id !== user?.id &&
      user?.role !== 'admin' &&
      user?.role !== 'power_user';

    if (conversation.unread_count > 0 && !isTakenByAnotherUser) {
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

    const templateVariables = selectedTemplate.buildVariables(
      newConversationTemplateValues
    ).map((value) => String(value || '').trim());

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
        setActiveConversationView(CONVERSATION_VIEWS.INBOX);

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
        setActiveConversationView(CONVERSATION_VIEWS.INBOX);
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

      if (selectedConversation.status === 'archived') {
        await unarchiveConversation(selectedConversation.id);
        setActiveConversationView(CONVERSATION_VIEWS.INBOX);
      } else {
        await archiveConversation(selectedConversation.id);
      }

      await refreshConversations(selectedConversation.id);
    } catch (err) {
      setError(
        getErrorMessage(
          err,
          selectedConversation.status === 'archived'
            ? 'Could not move conversation back to Inbox.'
            : 'Could not archive conversation.'
        )
      );
    }
  }

  async function handleDeleteConversation() {
    if (!selectedConversation) return;

    try {
      setError('');
      await deleteConversation(selectedConversation.id);
      setSelectedConversation(null);
      setMessages([]);
      setError('');
      setShowDeleteConfirm(false);
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
      setActiveConversationView(CONVERSATION_VIEWS.INBOX);
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
    if (!token || activePage !== APP_PAGES.REPORTS) {
      return;
    }

    loadTemplateReports().catch(() => {
      // Report loading errors are handled inside loadTemplateReports.
    });
  }, [token, activePage]);

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
    if (!token || browserUnreadCount <= 0) {
      document.title = APP_BROWSER_TITLE;
      return;
    }

    document.title = `(${browserUnreadCount}) ${APP_BROWSER_TITLE}`;
  }, [token, browserUnreadCount]);

  useEffect(() => {
    if (!token) {
      previousBrowserUnreadCountRef.current = 0;
      hasInitializedUnreadSoundRef.current = false;
      return;
    }

    if (!hasInitializedUnreadSoundRef.current) {
      previousBrowserUnreadCountRef.current = browserUnreadCount;
      hasInitializedUnreadSoundRef.current = true;
      return;
    }

    if (browserUnreadCount > previousBrowserUnreadCountRef.current) {
      playNotificationSound();
    }

    previousBrowserUnreadCountRef.current = browserUnreadCount;
  }, [token, browserUnreadCount]);

  useEffect(() => {
    if (!selectedConversation?.id || !lastMessageId) {
      return;
    }

    scrollMessagesToBottom();
  }, [selectedConversation?.id, lastMessageId]);

  useEffect(() => {
    if (!token || activePage !== APP_PAGES.INBOX) {
      return undefined;
    }

    const timeoutId = window.setTimeout(() => {
      const selectedConversationId = selectedConversation?.id || null;

      refreshConversations(selectedConversationId, inboxSearchQuery).catch(() => {
        // Silent search refresh failure.
      });
    }, 350);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [token, activePage, inboxSearchQuery, selectedConversation?.id]);

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
    selectedConversation?.id,
  ]);

  useEffect(() => {
    if (!token) return undefined;

    const intervalId = window.setInterval(() => {
      const selectedConversationId = selectedConversation?.id || null;

      refreshConversations(selectedConversationId, inboxSearchQuery).catch(() => {
        // Silent conversations auto-refresh failure.
      });
    }, AUTO_REFRESH_INTERVAL_MS);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [token, selectedConversation?.id, inboxSearchQuery]);

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

  function renderReportsPanel() {
    const summary = reportData?.summary || {};
    const reportItems = reportData?.items || [];

    return (
      <div className="reports-panel">
        <div className="reports-header">
          <div>
            <span>Operations reports</span>
            <h2>Template message reports</h2>
            <p>
              View which guests were informed, which messages were read, and which
              reservations need attention.
            </p>
          </div>

          <button
            type="button"
            className="reports-refresh-button"
            onClick={() => loadTemplateReports(reportFilters)}
            disabled={isLoadingReports}
          >
            {isLoadingReports ? 'Loading...' : 'Refresh'}
          </button>
        </div>

        <form className="reports-filters" onSubmit={handleReportsSubmit}>
          <label>
            <span>Tour date</span>
            <input
              type="date"
              value={reportFilters.operation_date}
              onChange={(event) =>
                updateReportFilter('operation_date', event.target.value)
              }
            />
          </label>

          <label>
            <span>Date from</span>
            <input
              type="date"
              value={reportFilters.date_from}
              onChange={(event) => updateReportFilter('date_from', event.target.value)}
            />
          </label>

          <label>
            <span>Date to</span>
            <input
              type="date"
              value={reportFilters.date_to}
              onChange={(event) => updateReportFilter('date_to', event.target.value)}
            />
          </label>

          <label>
            <span>Tour / option</span>
            <input
              value={reportFilters.option_code}
              onChange={(event) => updateReportFilter('option_code', event.target.value)}
              placeholder="DIAMOND_MORNING"
            />
          </label>

          <label>
            <span>Search</span>
            <input
              value={reportFilters.q}
              onChange={(event) => updateReportFilter('q', event.target.value)}
              placeholder="Reservation, name, phone..."
            />
          </label>

          <label>
            <span>Send result</span>
            <select
              value={reportFilters.status}
              onChange={(event) => updateReportFilter('status', event.target.value)}
            >
              <option value="">All</option>
              <option value="sent">Sent</option>
              <option value="no_number">Missing phone</option>
              <option value="invalid_number">Invalid phone</option>
              <option value="validation_failed">Missing details</option>
              <option value="failed">Failed</option>
              <option value="duplicate">Duplicate</option>
            </select>
          </label>

          <label>
            <span>WhatsApp status</span>
            <select
              value={reportFilters.whatsapp_status}
              onChange={(event) =>
                updateReportFilter('whatsapp_status', event.target.value)
              }
            >
              <option value="">All</option>
              <option value="sent">Sent</option>
              <option value="delivered">Delivered</option>
              <option value="read">Read</option>
              <option value="failed">Failed</option>
            </select>
          </label>

          <label className="reports-checkbox">
            <input
              type="checkbox"
              checked={reportFilters.problems_only}
              onChange={(event) =>
                updateReportFilter('problems_only', event.target.checked)
              }
            />
            <span>Problems only</span>
          </label>

          <div className="reports-filter-actions">
            <button type="submit" disabled={isLoadingReports}>
              Apply filters
            </button>

            <button type="button" onClick={handleReportsReset} disabled={isLoadingReports}>
              Reset
            </button>
          </div>
        </form>

        {reportsError && <div className="reports-error">{reportsError}</div>}

        <div className="reports-summary-grid">
          <div className="reports-summary-card">
            <span>Total</span>
            <strong>{summary.total || 0}</strong>
          </div>

          <div className="reports-summary-card">
            <span>Sent</span>
            <strong>{summary.sent || 0}</strong>
          </div>

          <div className="reports-summary-card good">
            <span>Read</span>
            <strong>{summary.read || 0}</strong>
          </div>

          <div className="reports-summary-card warning">
            <span>Waiting</span>
            <strong>{summary.waiting_status || 0}</strong>
          </div>

          <div className="reports-summary-card danger">
            <span>Problems</span>
            <strong>{summary.problems || 0}</strong>
          </div>

          <div className="reports-summary-card muted">
            <span>Duplicates</span>
            <strong>{summary.duplicates || 0}</strong>
          </div>
        </div>

        <div className="reports-table-card">
          <div className="reports-table-header">
            <h3>Report items</h3>
            <span>{reportItems.length} rows shown</span>
          </div>

          {isLoadingReports ? (
            <div className="empty-state">Loading reports...</div>
          ) : reportItems.length === 0 ? (
            <div className="empty-state">No report items found.</div>
          ) : (
            <div className="reports-table-wrap">
              <table className="reports-table">
                <thead>
                  <tr>
                    <th>Tour date</th>
                    <th>Tour / option</th>
                    <th>Reservation</th>
                    <th>Full name</th>
                    <th>Phone</th>
                    <th>Template</th>
                    <th>Result</th>
                    <th>WhatsApp</th>
                    <th>Problem / Reason</th>
                    <th>Sent at</th>
                  </tr>
                </thead>

                <tbody>
                  {reportItems.map((item) => (
                    <tr key={item.id}>
                      <td>{formatReportDate(item.operation_date)}</td>

                      <td>
                        <strong>{item.tour_name || '-'}</strong>
                        {item.option_code && <small>{item.option_code}</small>}
                      </td>

                      <td>
                        <strong>{item.reservation_number || '-'}</strong>
                        {item.batch_label && <small>{item.batch_label}</small>}
                      </td>

                      <td>{item.guest_name || '-'}</td>
                      <td>{item.phone || '-'}</td>
                      <td>{item.template_label || item.template_type}</td>

                      <td>
                        <span className={`report-badge ${getReportResultClass(item)}`}>
                          {item.result_label || item.status_label}
                        </span>
                      </td>

                      <td>{item.whatsapp_status_label || '-'}</td>

                      <td>
                        {item.problem_label ? (
                          <>
                            <strong className="report-problem-label">
                              {item.problem_label}
                            </strong>
                            {item.reason && <small>{item.reason}</small>}
                          </>
                        ) : item.reason ? (
                          <small>{item.reason}</small>
                        ) : (
                          '-'
                        )}
                      </td>

                      <td>{formatReportDateTime(item.sent_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    );
  }

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
    <div
      className={`app sendro-shell ${activePage === APP_PAGES.REPORTS ? 'reports-mode' : ''
        } ${activePage === APP_PAGES.SETTINGS ? 'settings-mode' : ''}`}
    >
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
              className={`blue-filter-button ${activeConversationView === CONVERSATION_VIEWS.INBOX ? 'active' : ''
                }`}
              onClick={() => {
                setActivePage(APP_PAGES.INBOX);
                setActiveConversationView(CONVERSATION_VIEWS.INBOX);
              }}
            >
              <span>Inbox</span>
              {inboxUnreadCount > 0 && <strong>{inboxUnreadCount}</strong>}
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
              {mineCount > 0 && <strong>{mineCount}</strong>}
            </button>

            <button
              type="button"
              className={`blue-filter-button ${activeConversationView === CONVERSATION_VIEWS.FOLLOW_UP ? 'active' : ''
                }`}
              onClick={() => {
                setActivePage(APP_PAGES.INBOX);
                setActiveConversationView(CONVERSATION_VIEWS.FOLLOW_UP);
              }}
            >
              <span>To Follow Up</span>
            </button>

            <button
              type="button"
              className={`blue-filter-button ${activeConversationView === CONVERSATION_VIEWS.ARCHIVED ? 'active' : ''
                }`}
              onClick={() => {
                setActivePage(APP_PAGES.INBOX);
                setActiveConversationView(CONVERSATION_VIEWS.ARCHIVED);
              }}
            >
              <span>Archived</span>
            </button>
          </div>

          {canCurrentUserViewReports && (
            <button
              type="button"
              className={`blue-settings-button ${activePage === APP_PAGES.REPORTS ? 'active' : ''}`}
              onClick={() => {
                setActivePage(APP_PAGES.REPORTS);
                setSelectedConversation(null);
              }}
            >
              Reports
            </button>
          )}

          <button
            type="button"
            className={`blue-settings-button ${activePage === APP_PAGES.SETTINGS ? 'active' : ''}`}
            onClick={() => {
              setActivePage(APP_PAGES.SETTINGS);
              setSelectedConversation(null);
            }}
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
              placeholder="Search name, phone, message..."
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
        </div>

        {showNewConversationForm && (
          <div className="new-conversation-overlay">
            <div className="new-conversation-overlay-header">
              <div>
                <h3>New conversation</h3>
                <p>Choose a template first, then fill in the guest details.</p>
              </div>
            </div>

            <form className="new-conversation-form" onSubmit={handleCreateConversation}>
              <label className="new-template-field new-template-picker-top">
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
                : activeConversationView === CONVERSATION_VIEWS.MINE
                  ? 'No conversations assigned to you.'
                  : activeConversationView === CONVERSATION_VIEWS.FOLLOW_UP
                    ? 'No conversations marked for follow up.'
                    : activeConversationView === CONVERSATION_VIEWS.ARCHIVED
                      ? 'No archived conversations.'
                      : 'No conversations in Inbox.'}
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
                    <div className="conversation-title-main">
                      <span
                        className={`conversation-response-dot ${getConversationResponseDotClass(
                          conversation
                        )}`}
                        title={getResponseIndicatorLabel(conversation)}
                        aria-label={getResponseIndicatorLabel(conversation)}
                      />

                      <strong>{label}</strong>
                    </div>

                    {unreadCount > 0 && (
                      <span className="unread-badge">{unreadCount}</span>
                    )}
                  </div>

                  <span>{conversation.contact_phone}</span>

                  <small className="conversation-meta">

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
        {activePage === APP_PAGES.REPORTS && canCurrentUserViewReports ? (
          renderReportsPanel()
        ) : activePage === APP_PAGES.SETTINGS ? (
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
                  onClick={handleArchiveConversation}
                >
                  {selectedConversation.status === 'archived' ? 'Back to Inbox' : 'Archive'}
                </button>

                <button
                  className="conversation-action-button release-mode"
                  type="button"
                  onClick={() => setShowDeleteConfirm(true)}
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
                  const messageAuthorLabel = getMessageAuthorLabel(message);

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
                        <MessageMediaPreview message={message} />

                        {(messageAuthorLabel || messageTime || getMessageStatusLabel(message)) && (
                          <div className="message-meta">
                            {messageAuthorLabel && (
                              <span className="message-author">{messageAuthorLabel}</span>
                            )}

                            {messageAuthorLabel && messageTime && (
                              <span className="message-author-separator">•</span>
                            )}

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
              <textarea
                value={newMessage}
                onChange={(event) => setNewMessage(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault();
                    handleSendMessage(event);
                  }
                }}
                placeholder={
                  selectedConversation.status === 'archived'
                    ? 'Archived conversation'
                    : isCustomerServiceSessionExpired
                      ? 'Session expired — template required'
                      : isConversationTakenByAnotherUser
                        ? `Taken by ${getAssignedUserLabel(
                          selectedConversation.assigned_to_user_id
                        )}`
                        : 'Type a message...'
                }
                disabled={!canSendMessage}
                rows="2"
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
      {showDeleteConfirm && selectedConversation && (
        <div
          className="delete-confirm-overlay"
          onClick={() => setShowDeleteConfirm(false)}
        >
          <div
            className="delete-confirm-modal"
            onClick={(event) => event.stopPropagation()}
          >
            <p className="delete-confirm-text">
              Are you sure you want to delete this conversation?
            </p>

            <div className="delete-confirm-actions">
              <button
                type="button"
                className="delete-confirm-cancel"
                onClick={() => setShowDeleteConfirm(false)}
              >
                Cancel
              </button>

              <button
                type="button"
                className="delete-confirm-delete"
                onClick={handleDeleteConversation}
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
      <aside className="future-panel" aria-label="Future templates and quick replies panel" />
    </div>
  );
}

export default App;