import { Fragment, useEffect, useRef, useState } from 'react';
import './App.css';
import sendroLogo from './assets/sendro_logo_reversed.png';
import SettingsPanel from './components/SettingsPanel';
import {
  getToken,
  login,
  clearToken,
  getCurrentUser,
  getUsers,
  getQuickReplies,
  getQuickReplyCategories,
  updateQuickReply,
  getConversations,
  getConversationSummary,
  createTemplateConversation,
  getMessages,
  getMessageMediaBlob,
  sendMessage,
  sendMessageReaction,
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

const AUTO_REFRESH_INTERVAL_MS = 15000;
const SUMMARY_REFRESH_INTERVAL_MS = 15000;
const ACTIVE_CHAT_REFRESH_INTERVAL_MS = 5000;
const FULL_MESSAGE_SYNC_EVERY_POLLS = 12;
const MAX_POLL_BACKOFF_MS = 60000;
const CONVERSATION_PAGE_SIZE = 60;
const MAX_LOADED_CONVERSATIONS = 200;
const MESSAGE_PAGE_SIZE = 30;
const LOAD_OLDER_SCROLL_THRESHOLD_PX = 80;
const PHONE_NUMBER_REGEX = /^\+[1-9]\d{7,14}$/;
const APP_BROWSER_TITLE = 'Sendro | Sunset Oia';
const BASIC_REACTION_EMOJIS = ['👍', '❤️', '😂', '🙏', '👌'];
const MOBILE_LAYOUT_QUERY = '(max-width: 820px)';
const MOBILE_HISTORY_STATE_KEY = '__sendroMobileNavigation';
const MOBILE_HISTORY_LAYERS = {
  EXIT_BOUNDARY: 'exit-boundary',
  LIST: 'list',
  CONVERSATION: 'conversation',
  PAGE: 'page',
  DRAWER: 'drawer',
  SEARCH: 'search',
  NEW_CONVERSATION: 'new-conversation',
  QUICK_REPLIES: 'quick-replies',
  REACTION: 'reaction',
  DELETE_CONFIRM: 'delete-confirm',
};
const ASSIGNMENT_COLOR_PALETTE = [
  '#1d4ed8',
  '#c026d3',
  '#6d28d9',
  '#087f5b',
  '#c2410c',
  '#be123c',
  '#047857',
  '#4338ca',
  '#a21caf',
  '#9a3412',
];
const AUTOMATIC_DARK_TEXT_COLOR = '#10213f';
const AUTOMATIC_LIGHT_TEXT_COLOR = '#ffffff';
const HEX_COLOR_REGEX = /^#[0-9a-f]{6}$/i;

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

function getRelativeLuminance(hexColor) {
  const normalized = String(hexColor || '').trim().replace('#', '');

  if (!/^[0-9a-f]{6}$/i.test(normalized)) {
    return 0;
  }

  const channels = [0, 2, 4].map((offset) => {
    const channel = Number.parseInt(normalized.slice(offset, offset + 2), 16) / 255;
    return channel <= 0.04045
      ? channel / 12.92
      : ((channel + 0.055) / 1.055) ** 2.4;
  });

  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

function getAutomaticTextColor(backgroundColor) {
  const backgroundLuminance = getRelativeLuminance(backgroundColor);
  const darkLuminance = getRelativeLuminance(AUTOMATIC_DARK_TEXT_COLOR);
  const lightContrast = 1.05 / (backgroundLuminance + 0.05);
  const darkContrast =
    (Math.max(backgroundLuminance, darkLuminance) + 0.05) /
    (Math.min(backgroundLuminance, darkLuminance) + 0.05);

  return lightContrast >= darkContrast
    ? AUTOMATIC_LIGHT_TEXT_COLOR
    : AUTOMATIC_DARK_TEXT_COLOR;
}

function isMobileLayout() {
  return window.matchMedia(MOBILE_LAYOUT_QUERY).matches;
}

function Icon({ name, size = 20, strokeWidth = 1.8 }) {
  const commonProps = {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth,
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
    'aria-hidden': 'true',
  };

  const paths = {
    inbox: <><path d="M4 4h16v13H4z" /><path d="M4 13h4l2 3h4l2-3h4" /></>,
    chat: <><path d="M5 5h14v11H9l-4 3z" /></>,
    user: <><circle cx="12" cy="8" r="3" /><path d="M5 20c.8-4 3.1-6 7-6s6.2 2 7 6" /></>,
    users: <><circle cx="9" cy="8" r="3" /><path d="M3 20c.7-4 2.8-6 6-6s5.3 2 6 6" /><path d="M16 5c2.4.3 3.7 3.1 2.1 5" /><path d="M17 14c2.1.7 3.4 2.6 4 5" /></>,
    follow: <><path d="M4 18V6" /><path d="M4 7h10l-1 4 1 4H4" /></>,
    archive: <><path d="M4 7h16v13H4z" /><path d="M3 4h18v3H3z" /><path d="M9 11h6" /></>,
    reports: <><path d="M5 20V10" /><path d="M12 20V4" /><path d="M19 20v-7" /></>,
    settings: <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4v-.2a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H3v-4h.1a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1A1.7 1.7 0 0 0 9 4.6 1.7 1.7 0 0 0 10 3V3h4v.1a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1z" /></>,
    search: <><circle cx="11" cy="11" r="7" /><path d="m16.5 16.5 4 4" /></>,
    filter: <><path d="M4 5h16l-6 7v6l-4 2v-8z" /></>,
    plus: <><path d="M12 5v14M5 12h14" /></>,
    clock: <><circle cx="12" cy="12" r="8.5" /><path d="M12 7v5l3.5 2" /></>,
    info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v6" /><path d="M12 7h.01" /></>,
    more: <><circle cx="5" cy="12" r="1" fill="currentColor" stroke="none" /><circle cx="12" cy="12" r="1" fill="currentColor" stroke="none" /><circle cx="19" cy="12" r="1" fill="currentColor" stroke="none" /></>,
    back: <><path d="m15 18-6-6 6-6" /></>,
    send: <><path d="m22 2-7 20-4-9-9-4z" /><path d="M22 2 11 13" /></>,
    take: <><circle cx="9" cy="8" r="3" /><path d="M3 20c.7-4 2.8-6 6-6 1.5 0 2.8.4 3.8 1.1" /><path d="M18 12v6M15 15h6" /></>,
    release: <><circle cx="9" cy="8" r="3" /><path d="M3 20c.7-4 2.8-6 6-6 1.5 0 2.8.4 3.8 1.1" /><path d="m16 13 4 4m0-4-4 4" /></>,
    delete: <><path d="M4 7h16" /><path d="M9 7V4h6v3" /><path d="m6 7 1 13h10l1-13" /><path d="M10 11v5M14 11v5" /></>,
    folder: <><path d="M3 6h6l2 2h10v11H3z" /></>,
    quick: <><path d="m12 3 1.2 3.8L17 8l-3.8 1.2L12 13l-1.2-3.8L7 8l3.8-1.2z" /><path d="m18.5 14 .7 2.3 2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7z" /></>,
    menu: <><path d="M4 7h16M4 12h16M4 17h16" /></>,
    chevron: <><path d="m8 10 4 4 4-4" /></>,
    sidebarCollapse: <><path d="M4 5h16v14H4z" /><path d="M9 5v14" /><path d="m15 9-3 3 3 3" /></>,
    sidebarExpand: <><path d="M4 5h16v14H4z" /><path d="M9 5v14" /><path d="m12 9 3 3-3 3" /></>,
    responseInbound: <><path d="m16.5 7.5-9 9" /><path d="M14 16.5H7.5V10" /></>,
    responseOutbound: <><path d="m7.5 16.5 9-9" /><path d="M10 7.5h6.5V14" /></>,
    responseNeutral: <circle cx="12" cy="12" r="2.2" fill="currentColor" stroke="none" />,
    logout: <><path d="M10 4H5v16h5" /><path d="m14 8 4 4-4 4" /><path d="M8 12h10" /></>,
  };

  return <svg {...commonProps}>{paths[name] || paths.chat}</svg>;
}

function getInitials(value) {
  const words = String(value || '').trim().split(/\s+/).filter(Boolean);

  if (words.length === 0) return '?';
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();

  return `${words[0][0]}${words[words.length - 1][0]}`.toUpperCase();
}

function getQuickReplySlashMatch(value, cursorPosition) {
  const draft = String(value || '');
  const safeCursorPosition = Number.isInteger(cursorPosition)
    ? cursorPosition
    : draft.length;
  const beforeCursor = draft.slice(0, safeCursorPosition);
  const match = beforeCursor.match(/(^|\s)\/([a-zA-Z0-9_-]*)$/);

  if (!match) return null;

  return {
    query: match[2] || '',
    start: safeCursorPosition - (match[2]?.length || 0) - 1,
    end: safeCursorPosition,
  };
}

function attachCustomerServiceExpiry(conversations) {
  const receivedAtMs = Date.now();

  return conversations.map((conversation) => {
    const secondsLeft = Math.max(
      0,
      Number(conversation.customer_service_time_left_seconds || 0)
    );

    return {
      ...conversation,
      customer_service_expires_at_ms:
        conversation.customer_service_window_open && secondsLeft > 0
          ? receivedAtMs + (secondsLeft * 1000)
          : null,
    };
  });
}

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

function getLocationContentValue(content, label) {
  const lines = String(content || '').split('\n');
  const targetPrefix = `${label}:`;

  const matchingLine = lines.find((line) =>
    line.trim().toLowerCase().startsWith(targetPrefix.toLowerCase())
  );

  if (!matchingLine) {
    return '';
  }

  return matchingLine.slice(targetPrefix.length).trim();
}

function getLocationGoogleMapsUrl(content) {
  const directUrl = getLocationContentValue(content, 'Google Maps');

  if (directUrl) {
    return directUrl;
  }

  const latitude = getLocationContentValue(content, 'Latitude');
  const longitude = getLocationContentValue(content, 'Longitude');

  if (!latitude || !longitude) {
    return '';
  }

  return `https://www.google.com/maps?q=${latitude},${longitude}`;
}

function MessageMediaPreview({ message }) {
  const [mediaUrl, setMediaUrl] = useState('');
  const [mediaError, setMediaError] = useState('');

  const messageType = String(message?.message_type || 'text').toLowerCase();
  const caption = getMediaCaption(message?.content);
  const hasMedia = Boolean(message?.id && message?.media_id);

  const locationName = getLocationContentValue(message?.content, 'Name');
  const locationAddress = getLocationContentValue(message?.content, 'Address');
  const locationLatitude = getLocationContentValue(message?.content, 'Latitude');
  const locationLongitude = getLocationContentValue(message?.content, 'Longitude');
  const locationUrl = getLocationGoogleMapsUrl(message?.content);

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

  if (messageType === 'location') {
    return (
      <div className="message-location-card">
        <div className="message-location-title">
          {locationName || 'Location shared'}
        </div>

        {locationAddress && (
          <div className="message-location-address">{locationAddress}</div>
        )}

        {(locationLatitude || locationLongitude) && (
          <div className="message-location-coordinates">
            {locationLatitude}
            {locationLatitude && locationLongitude ? ', ' : ''}
            {locationLongitude}
          </div>
        )}

        {locationUrl && (
          <a
            className="message-location-link"
            href={locationUrl}
            target="_blank"
            rel="noreferrer"
          >
            Open in Google Maps
          </a>
        )}
      </div>
    );
  }

  if (messageType === 'image' && hasMedia) {
    return (
      <div className="message-media-card message-image-card">
        {mediaUrl ? (
          <a href={mediaUrl} target="_blank" rel="noreferrer">
            <img
              className="message-image-preview"
              src={mediaUrl}
              alt={caption || 'WhatsApp photo'}
            />
          </a>
        ) : (
          <div className="message-media-loading">Loading photo...</div>
        )}

        {caption && <div className="message-media-caption">{caption}</div>}

        {mediaError && (
          <div className="message-media-error">{mediaError}</div>
        )}
      </div>
    );
  }

  if (messageType === 'video' && hasMedia) {
    return (
      <div className="message-media-card message-video-card">
        {mediaUrl ? (
          <video
            className="message-video-preview"
            src={mediaUrl}
            controls
          />
        ) : (
          <div className="message-media-loading">Loading video...</div>
        )}

        {caption && <div className="message-media-caption">{caption}</div>}

        {mediaError && (
          <div className="message-media-error">{mediaError}</div>
        )}
      </div>
    );
  }

  if (messageType === 'audio' && hasMedia) {
    return (
      <div className="message-media-card message-audio-card">
        <div className="message-media-title">Audio message</div>

        {mediaUrl ? (
          <audio src={mediaUrl} controls />
        ) : (
          <div className="message-media-loading">Loading audio...</div>
        )}

        {mediaError && (
          <div className="message-media-error">{mediaError}</div>
        )}
      </div>
    );
  }

  if (messageType === 'sticker' && hasMedia) {
    return (
      <div className="message-media-card message-sticker-card">
        {mediaUrl ? (
          <img
            className="message-sticker-preview"
            src={mediaUrl}
            alt="WhatsApp sticker"
          />
        ) : (
          <div className="message-media-loading">Loading sticker...</div>
        )}

        {mediaError && (
          <div className="message-media-error">{mediaError}</div>
        )}
      </div>
    );
  }

  if (messageType === 'document' && hasMedia) {
    const filename = message.media_filename || 'Document';

    return (
      <div className="message-media-card message-document-card">
        <div className="message-media-title">Document</div>
        <div className="message-media-filename">{filename}</div>

        {mediaUrl ? (
          <a href={mediaUrl} target="_blank" rel="noreferrer">
            Open
          </a>
        ) : (
          <div className="message-media-loading">Loading document...</div>
        )}

        {caption && <div className="message-media-caption">{caption}</div>}

        {mediaError && (
          <div className="message-media-error">{mediaError}</div>
        )}
      </div>
    );
  }

  return (
    <div className="message-text-content">
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
  const [conversationSummary, setConversationSummary] = useState(null);
  const [hasMoreConversations, setHasMoreConversations] = useState(false);
  const [isLoadingMoreConversations, setIsLoadingMoreConversations] = useState(false);
  const [activePage, setActivePage] = useState(APP_PAGES.INBOX);
  const [isPageVisible, setIsPageVisible] = useState(
    () => document.visibilityState !== 'hidden'
  );

  const [reportFilters, setReportFilters] = useState({
    operation_date: '',
    date_from: '',
    date_to: '',
    option_code: '',
    time_slot: '',
    result_status: '',
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
  const [hasMoreOlderMessages, setHasMoreOlderMessages] = useState(true);
  const [isLoadingOlderMessages, setIsLoadingOlderMessages] = useState(false);

  const messagesEndRef = useRef(null);
  const messagesContainerRef = useRef(null);
  const messageInputRef = useRef(null);
  const messagesRef = useRef([]);
  const selectedConversationIdRef = useRef(null);
  const latestConversationRequestIdRef = useRef(0);
  const conversationAbortControllerRef = useRef(null);
  const conversationSummaryAbortControllerRef = useRef(null);
  const loadMoreConversationsAbortControllerRef = useRef(null);
  const loadedConversationLimitRef = useRef(CONVERSATION_PAGE_SIZE);
  const messagesRequestInProgressRef = useRef(null);
  const messagePollStateRef = useRef({ conversationId: null, incrementalPolls: 0 });
  const olderMessagesRequestInProgressRef = useRef(false);
  const olderMessagesAbortControllerRef = useRef(null);
  const apiFailureCountRef = useRef(0);
  const previousBrowserUnreadCountRef = useRef(0);
  const hasInitializedUnreadSoundRef = useRef(false);

  const [messageDrafts, setMessageDrafts] = useState({});

  const selectedConversationId = selectedConversation?.id || null;

  const newMessage = selectedConversationId
    ? messageDrafts[selectedConversationId] || ''
    : '';

  function setConversationDraft(conversationId, value) {
    if (!conversationId) return;

    setMessageDrafts((currentDrafts) => {
      const nextDrafts = { ...currentDrafts };

      if (value) {
        nextDrafts[conversationId] = value;
      } else {
        delete nextDrafts[conversationId];
      }

      return nextDrafts;
    });
  }

  const [reactingMessageIds, setReactingMessageIds] = useState([]);
  const [openReactionPickerMessageId, setOpenReactionPickerMessageId] = useState(null);
  const [error, setError] = useState('');
  const [systemStatus, setSystemStatus] = useState('live');
  const [isSending, setIsSending] = useState(false);
  const [isUpdatingFollowUp, setIsUpdatingFollowUp] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [showExitConfirm, setShowExitConfirm] = useState(false);
  const [isMobileChatOpen, setIsMobileChatOpen] = useState(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [isMobileSearchOpen, setIsMobileSearchOpen] = useState(false);
  const [mobileDrawerMode, setMobileDrawerMode] = useState(null);
  const [quickReplies, setQuickReplies] = useState([]);
  const [quickReplyCategories, setQuickReplyCategories] = useState([]);
  const [quickReplySearch, setQuickReplySearch] = useState('');
  const [quickReplyCategoryFilter, setQuickReplyCategoryFilter] = useState('all');
  const [isLoadingQuickReplies, setIsLoadingQuickReplies] = useState(false);
  const [quickRepliesError, setQuickRepliesError] = useState('');
  const [copiedQuickReplyId, setCopiedQuickReplyId] = useState(null);
  const [favoritingQuickReplyIds, setFavoritingQuickReplyIds] = useState([]);
  const [slashQuickReplyMatch, setSlashQuickReplyMatch] = useState(null);
  const [activeSlashReplyIndex, setActiveSlashReplyIndex] = useState(0);
  const [customerServiceNowMs, setCustomerServiceNowMs] = useState(() => Date.now());
  const inboxSearchInputRef = useRef(null);
  const mobileHistorySessionIdRef = useRef(null);
  const skipNextMobilePopRef = useRef(false);
  const allowMobileExitRef = useRef(false);
  const mobileNavigationSnapshotRef = useRef({});

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

  const selectedCustomerServiceSecondsLeft = getCustomerServiceSecondsLeft(
    selectedConversation,
    customerServiceNowMs
  );

  const isCustomerServiceSessionExpired =
    Boolean(selectedConversation) &&
    (
      !selectedConversation.customer_service_window_open ||
      selectedCustomerServiceSecondsLeft <= 0
    );

  const canTypeMessage =
    Boolean(selectedConversation) &&
    !isCustomerServiceSessionExpired &&
    !isConversationTakenByAnotherUser &&
    selectedConversation?.status !== 'archived';

  const canSendMessage = canTypeMessage && !isSending;

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

  const loadedInboxUnreadCount = conversations.filter((conversation) => {
    return (
      !isArchivedConversation(conversation) &&
      Number(conversation.unread_count || 0) > 0
    );
  }).length;

  const loadedBrowserUnreadCount = conversations.reduce((total, conversation) => {
    if (isArchivedConversation(conversation)) {
      return total;
    }

    return total + Number(conversation.unread_count || 0);
  }, 0);

  const loadedMineCount = conversations.filter(isMineConversation).length;

  const inboxUnreadCount =
    conversationSummary?.inbox_unread_conversations ?? loadedInboxUnreadCount;
  const browserUnreadCount =
    conversationSummary?.unread_messages ?? loadedBrowserUnreadCount;
  const mineCount = conversationSummary?.mine ?? loadedMineCount;

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

  const normalizedQuickReplySearch = quickReplySearch.trim().toLowerCase();
  const filteredQuickReplies = quickReplies.filter((reply) => {
    let matchesCategory = true;

    if (quickReplyCategoryFilter === 'favorites') {
      matchesCategory = Boolean(reply.is_favorite);
    } else if (quickReplyCategoryFilter === 'team') {
      matchesCategory = reply.scope === 'team';
    } else if (quickReplyCategoryFilter === 'mine') {
      matchesCategory = reply.scope === 'personal';
    } else if (quickReplyCategoryFilter !== 'all') {
      const selectedCategoryId = Number(quickReplyCategoryFilter);
      matchesCategory =
        reply.category_id === selectedCategoryId ||
        reply.parent_category_id === selectedCategoryId;
    }

    if (!matchesCategory) return false;
    if (!normalizedQuickReplySearch) return true;

    return [
      reply.title,
      reply.shortcut,
      reply.category_name,
      reply.parent_category_name,
      reply.content,
    ]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(normalizedQuickReplySearch));
  });
  const normalizedSlashQuickReplyQuery = String(
    slashQuickReplyMatch?.query || ''
  ).toLowerCase();
  const slashQuickReplies = quickReplies
    .filter((reply) => {
      if (!normalizedSlashQuickReplyQuery) return true;

      return [
        reply.shortcut,
        reply.title,
        reply.category_name,
        reply.parent_category_name,
        reply.content,
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(normalizedSlashQuickReplyQuery));
    })
    .slice(0, 7);

  function getCurrentMobileHistoryMarker() {
    return window.history.state?.[MOBILE_HISTORY_STATE_KEY] || null;
  }

  function createMobileHistoryState(layer) {
    return {
      ...(window.history.state || {}),
      [MOBILE_HISTORY_STATE_KEY]: {
        sessionId: mobileHistorySessionIdRef.current,
        layer,
      },
    };
  }

  function pushMobileHistoryLayer(layer) {
    if (!token || !isMobileLayout() || !mobileHistorySessionIdRef.current) {
      return;
    }

    const currentMarker = getCurrentMobileHistoryMarker();

    if (
      currentMarker?.sessionId === mobileHistorySessionIdRef.current &&
      currentMarker.layer === layer
    ) {
      return;
    }

    window.history.pushState(createMobileHistoryState(layer), '', window.location.href);
  }

  function replaceMobileHistoryLayer(layer) {
    if (!token || !isMobileLayout() || !mobileHistorySessionIdRef.current) {
      return;
    }

    window.history.replaceState(
      createMobileHistoryState(layer),
      '',
      window.location.href
    );
  }

  function dismissMobileHistoryLayer(
    closeLayer,
    historySteps = 1,
    expectedLayer = null
  ) {
    const currentMarker = getCurrentMobileHistoryMarker();
    const ownsCurrentEntry =
      token &&
      isMobileLayout() &&
      mobileHistorySessionIdRef.current &&
      currentMarker?.sessionId === mobileHistorySessionIdRef.current &&
      ![
        MOBILE_HISTORY_LAYERS.EXIT_BOUNDARY,
        MOBILE_HISTORY_LAYERS.LIST,
      ].includes(currentMarker.layer) &&
      (!expectedLayer || currentMarker.layer === expectedLayer);

    closeLayer();

    if (ownsCurrentEntry) {
      skipNextMobilePopRef.current = true;
      window.history.go(-Math.max(1, historySteps));
    }
  }

  function openMobileDrawer(mode) {
    if (mobileDrawerMode || showNewConversationForm || isMobileSearchOpen) {
      setShowNewConversationForm(false);
      setIsMobileSearchOpen(false);
      setMobileDrawerMode(mode);
      replaceMobileHistoryLayer(MOBILE_HISTORY_LAYERS.DRAWER);
      return;
    }

    setMobileDrawerMode(mode);
    pushMobileHistoryLayer(MOBILE_HISTORY_LAYERS.DRAWER);
  }

  function closeMobileDrawer() {
    dismissMobileHistoryLayer(
      () => setMobileDrawerMode(null),
      1,
      MOBILE_HISTORY_LAYERS.DRAWER
    );
  }

  function toggleNewConversationPanel() {
    if (showNewConversationForm) {
      dismissMobileHistoryLayer(
        () => setShowNewConversationForm(false),
        1,
        MOBILE_HISTORY_LAYERS.NEW_CONVERSATION
      );
      return;
    }

    if (isMobileSearchOpen || activePage !== APP_PAGES.INBOX) {
      setIsMobileSearchOpen(false);
      setShowNewConversationForm(true);
      replaceMobileHistoryLayer(MOBILE_HISTORY_LAYERS.NEW_CONVERSATION);
      return;
    }

    setShowNewConversationForm(true);
    pushMobileHistoryLayer(MOBILE_HISTORY_LAYERS.NEW_CONVERSATION);
  }

  function closeSlashQuickReplies() {
    dismissMobileHistoryLayer(() => {
      setSlashQuickReplyMatch(null);
      setActiveSlashReplyIndex(0);
    }, 1, MOBILE_HISTORY_LAYERS.QUICK_REPLIES);
  }

  function toggleReactionPicker(messageId) {
    if (openReactionPickerMessageId === messageId) {
      dismissMobileHistoryLayer(
        () => setOpenReactionPickerMessageId(null),
        1,
        MOBILE_HISTORY_LAYERS.REACTION
      );
      return;
    }

    if (openReactionPickerMessageId) {
      setOpenReactionPickerMessageId(messageId);
      replaceMobileHistoryLayer(MOBILE_HISTORY_LAYERS.REACTION);
      return;
    }

    setOpenReactionPickerMessageId(messageId);
    pushMobileHistoryLayer(MOBILE_HISTORY_LAYERS.REACTION);
  }

  function closeMobileConversation() {
    dismissMobileHistoryLayer(() => {
      setOpenReactionPickerMessageId(null);
      setSlashQuickReplyMatch(null);
      setIsMobileChatOpen(false);
    }, 1, MOBILE_HISTORY_LAYERS.CONVERSATION);
  }

  function handleMobileChatBack() {
    if (openReactionPickerMessageId) {
      dismissMobileHistoryLayer(
        () => setOpenReactionPickerMessageId(null),
        1,
        MOBILE_HISTORY_LAYERS.REACTION
      );
      return;
    }

    if (slashQuickReplyMatch) {
      closeSlashQuickReplies();
      return;
    }

    closeMobileConversation();
  }

  function openDeleteConfirmation() {
    setShowDeleteConfirm(true);
    pushMobileHistoryLayer(MOBILE_HISTORY_LAYERS.DELETE_CONFIRM);
  }

  function closeDeleteConfirmation() {
    dismissMobileHistoryLayer(
      () => setShowDeleteConfirm(false),
      1,
      MOBILE_HISTORY_LAYERS.DELETE_CONFIRM
    );
  }

  function handleStayInSendro() {
    setShowExitConfirm(false);
  }

  function handleExitSendro() {
    const currentMarker = getCurrentMobileHistoryMarker();

    setShowExitConfirm(false);

    if (
      isMobileLayout() &&
      currentMarker?.sessionId === mobileHistorySessionIdRef.current
    ) {
      allowMobileExitRef.current = true;
      window.history.back();
      return;
    }

    window.history.back();
  }

  function openConversationView(view) {
    const showConversationList = () => {
      setActivePage(APP_PAGES.INBOX);
      setActiveConversationView(view);
      setIsMobileChatOpen(false);
      setIsMobileSearchOpen(false);
      setMobileDrawerMode(null);
    };

    if (
      mobileDrawerMode ||
      isMobileChatOpen ||
      activePage !== APP_PAGES.INBOX
    ) {
      dismissMobileHistoryLayer(
        showConversationList,
        mobileDrawerMode && activePage !== APP_PAGES.INBOX ? 2 : 1,
        mobileDrawerMode
          ? MOBILE_HISTORY_LAYERS.DRAWER
          : isMobileChatOpen
            ? MOBILE_HISTORY_LAYERS.CONVERSATION
            : MOBILE_HISTORY_LAYERS.PAGE
      );
      return;
    }

    showConversationList();
  }

  async function loadQuickReplyData() {
    try {
      setIsLoadingQuickReplies(true);
      setQuickRepliesError('');

      const [categoryData, replyData] = await Promise.all([
        getQuickReplyCategories(),
        getQuickReplies(),
      ]);

      setQuickReplyCategories(categoryData);
      setQuickReplies(replyData);
    } catch (err) {
      setQuickRepliesError(getErrorMessage(err, 'Could not load quick replies.'));
    } finally {
      setIsLoadingQuickReplies(false);
    }
  }

  function handleSettingsQuickRepliesChanged(updatedReplies, updatedCategories) {
    setQuickReplies(updatedReplies);
    setQuickReplyCategories(updatedCategories);
    setQuickRepliesError('');
    setQuickReplyCategoryFilter((currentFilter) => {
      if (['all', 'team', 'mine', 'favorites'].includes(currentFilter)) {
        return currentFilter;
      }

      return updatedCategories.some(
        (category) => String(category.id) === currentFilter
      )
        ? currentFilter
        : 'all';
    });
  }

  function getQuickReplyCategoryLabel(reply) {
    return [reply.parent_category_name, reply.category_name]
      .filter(Boolean)
      .join(' / ') || 'General';
  }

  async function handleToggleQuickReplyFavorite(reply) {
    if (favoritingQuickReplyIds.includes(reply.id)) return;

    const nextFavoriteValue = !reply.is_favorite;
    setFavoritingQuickReplyIds((currentIds) => [...currentIds, reply.id]);
    setQuickReplies((currentReplies) =>
      currentReplies.map((currentReply) =>
        currentReply.id === reply.id
          ? { ...currentReply, is_favorite: nextFavoriteValue }
          : currentReply
      )
    );

    try {
      const updatedReply = await updateQuickReply(reply.id, {
        is_favorite: nextFavoriteValue,
      });
      setQuickReplies((currentReplies) =>
        currentReplies.map((currentReply) =>
          currentReply.id === updatedReply.id ? updatedReply : currentReply
        )
      );
    } catch (err) {
      setQuickReplies((currentReplies) =>
        currentReplies.map((currentReply) =>
          currentReply.id === reply.id ? reply : currentReply
        )
      );
      setQuickRepliesError(
        getErrorMessage(err, 'Could not update your Favorites.')
      );
    } finally {
      setFavoritingQuickReplyIds((currentIds) =>
        currentIds.filter((replyId) => replyId !== reply.id)
      );
    }
  }

  function insertQuickReplyIntoComposer(reply, options = {}) {
    if (!selectedConversationId || !canTypeMessage) return;

    const currentDraft = newMessage;
    const textarea = messageInputRef.current;
    const slashMatch = options.slashMatch || null;
    const selectionStart = slashMatch?.start ?? textarea?.selectionStart ?? currentDraft.length;
    const selectionEnd = slashMatch?.end ?? textarea?.selectionEnd ?? selectionStart;
    const beforeSelection = currentDraft.slice(0, selectionStart);
    const afterSelection = currentDraft.slice(selectionEnd);
    const leadingSeparator =
      !slashMatch && beforeSelection && !/\s$/.test(beforeSelection) ? '\n' : '';
    const trailingSeparator =
      afterSelection && !/^\s/.test(afterSelection) ? '\n' : '';
    const insertedContent = `${leadingSeparator}${reply.content}${trailingSeparator}`;
    const nextDraft = `${beforeSelection}${insertedContent}${afterSelection}`;
    const nextCursorPosition = beforeSelection.length + insertedContent.length;

    if (mobileDrawerMode) {
      replaceMobileHistoryLayer(MOBILE_HISTORY_LAYERS.CONVERSATION);
    } else if (slashQuickReplyMatch && isMobileLayout()) {
      const currentMarker = getCurrentMobileHistoryMarker();

      if (
        currentMarker?.sessionId === mobileHistorySessionIdRef.current &&
        currentMarker.layer === MOBILE_HISTORY_LAYERS.QUICK_REPLIES
      ) {
        skipNextMobilePopRef.current = true;
        window.history.back();
      }
    }

    setConversationDraft(selectedConversationId, nextDraft);
    setIsMobileChatOpen(true);
    setMobileDrawerMode(null);
    setSlashQuickReplyMatch(null);
    setActiveSlashReplyIndex(0);

    window.setTimeout(() => {
      messageInputRef.current?.focus();
      messageInputRef.current?.setSelectionRange(
        nextCursorPosition,
        nextCursorPosition
      );
    }, 0);
  }

  function handleQuickReplyDragStart(event, reply) {
    event.dataTransfer.effectAllowed = 'copy';
    event.dataTransfer.setData('application/x-sendro-quick-reply', reply.content);
    event.dataTransfer.setData('text/plain', reply.content);
  }

  async function handleCopyQuickReply(reply) {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(reply.content);
      } else {
        const temporaryTextarea = document.createElement('textarea');
        temporaryTextarea.value = reply.content;
        temporaryTextarea.style.position = 'fixed';
        temporaryTextarea.style.opacity = '0';
        document.body.appendChild(temporaryTextarea);
        temporaryTextarea.select();
        const copied = document.execCommand('copy');
        temporaryTextarea.remove();

        if (!copied) {
          throw new Error('Copy failed');
        }
      }
      setCopiedQuickReplyId(reply.id);
      window.setTimeout(() => {
        setCopiedQuickReplyId((currentId) =>
          currentId === reply.id ? null : currentId
        );
      }, 1600);
    } catch {
      setError('Could not copy quick reply.');
    }
  }

  function handleQuickReplyDrop(event) {
    event.preventDefault();
    const content = event.dataTransfer.getData('application/x-sendro-quick-reply');
    if (!content || !canTypeMessage) return;
    insertQuickReplyIntoComposer({ content });
  }

  function handleComposerDraftChange(event) {
    const nextDraft = event.target.value;
    const slashMatch = getQuickReplySlashMatch(
      nextDraft,
      event.target.selectionStart
    );

    setConversationDraft(selectedConversationId, nextDraft);

    if (slashMatch && !slashQuickReplyMatch) {
      pushMobileHistoryLayer(MOBILE_HISTORY_LAYERS.QUICK_REPLIES);
    } else if (!slashMatch && slashQuickReplyMatch) {
      closeSlashQuickReplies();
      return;
    }

    setSlashQuickReplyMatch(slashMatch);
    setActiveSlashReplyIndex(0);
  }

  function openSlashQuickReplyPicker() {
    if (!selectedConversationId || !canTypeMessage) return;

    const textarea = messageInputRef.current;
    const cursorPosition = textarea?.selectionStart ?? newMessage.length;
    const beforeCursor = newMessage.slice(0, cursorPosition);
    const afterCursor = newMessage.slice(cursorPosition);
    const prefix = beforeCursor && !/\s$/.test(beforeCursor) ? ' /' : '/';
    const nextDraft = `${beforeCursor}${prefix}${afterCursor}`;
    const nextCursorPosition = beforeCursor.length + prefix.length;

    setConversationDraft(selectedConversationId, nextDraft);
    if (!slashQuickReplyMatch) {
      pushMobileHistoryLayer(MOBILE_HISTORY_LAYERS.QUICK_REPLIES);
    }
    setSlashQuickReplyMatch({
      query: '',
      start: nextCursorPosition - 1,
      end: nextCursorPosition,
    });
    setActiveSlashReplyIndex(0);

    window.setTimeout(() => {
      messageInputRef.current?.focus();
      messageInputRef.current?.setSelectionRange(nextCursorPosition, nextCursorPosition);
    }, 0);
  }

  function handleComposerKeyDown(event) {
    if (slashQuickReplyMatch) {
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        setActiveSlashReplyIndex((currentIndex) =>
          slashQuickReplies.length
            ? (currentIndex + 1) % slashQuickReplies.length
            : 0
        );
        return;
      }

      if (event.key === 'ArrowUp') {
        event.preventDefault();
        setActiveSlashReplyIndex((currentIndex) =>
          slashQuickReplies.length
            ? (currentIndex - 1 + slashQuickReplies.length) % slashQuickReplies.length
            : 0
        );
        return;
      }

      if (event.key === 'Escape') {
        event.preventDefault();
        closeSlashQuickReplies();
        return;
      }

      if (event.key === 'Enter' && !event.shiftKey && slashQuickReplies.length > 0) {
        event.preventDefault();
        insertQuickReplyIntoComposer(
          slashQuickReplies[activeSlashReplyIndex] || slashQuickReplies[0],
          { slashMatch: slashQuickReplyMatch }
        );
        return;
      }
    }

    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      handleSendMessage(event);
    }
  }

  function focusMobileInboxSearch() {
    if (isMobileSearchOpen) {
      dismissMobileHistoryLayer(
        () => setIsMobileSearchOpen(false),
        1,
        MOBILE_HISTORY_LAYERS.SEARCH
      );
      return;
    }

    setActivePage(APP_PAGES.INBOX);
    setIsMobileChatOpen(false);
    setMobileDrawerMode(null);

    if (showNewConversationForm || activePage !== APP_PAGES.INBOX) {
      setShowNewConversationForm(false);
      setIsMobileSearchOpen(true);
      replaceMobileHistoryLayer(MOBILE_HISTORY_LAYERS.SEARCH);
    } else {
      setIsMobileSearchOpen(true);
      pushMobileHistoryLayer(MOBILE_HISTORY_LAYERS.SEARCH);
    }

    window.setTimeout(() => {
      inboxSearchInputRef.current?.focus();
    }, 0);
  }

  function renderQuickReplyList() {
    if (isLoadingQuickReplies) {
      return <div className="quick-reply-empty">Loading quick replies...</div>;
    }

    if (quickRepliesError) {
      return (
        <div className="quick-reply-empty quick-reply-load-error">
          <span>{quickRepliesError}</span>
          <button type="button" onClick={loadQuickReplyData}>Try again</button>
        </div>
      );
    }

    if (filteredQuickReplies.length === 0) {
      return <div className="quick-reply-empty">No quick replies found.</div>;
    }

    return filteredQuickReplies.map((reply) => (
      <article
        className="quick-reply-card"
        key={reply.id}
        draggable={canTypeMessage}
        onDragStart={(event) => handleQuickReplyDragStart(event, reply)}
      >
        <div className="quick-reply-card-heading">
          <button
            type="button"
            className={reply.is_favorite ? 'quick-reply-star active' : 'quick-reply-star'}
            onClick={() => handleToggleQuickReplyFavorite(reply)}
            disabled={favoritingQuickReplyIds.includes(reply.id)}
            aria-label={reply.is_favorite ? 'Remove from my Favorites' : 'Add to my Favorites'}
            aria-pressed={Boolean(reply.is_favorite)}
            title={reply.is_favorite ? 'Remove from my Favorites' : 'Add to my Favorites'}
          >
            ★
          </button>
          <div>
            <strong>{reply.title}</strong>
            <small>
              {reply.scope === 'personal' ? 'My reply' : 'Team'} · {getQuickReplyCategoryLabel(reply)}
              {reply.shortcut ? ` · /${reply.shortcut}` : ''}
            </small>
          </div>
        </div>
        <p>{reply.content}</p>
        <div className="quick-reply-card-actions">
          <button type="button" onClick={() => handleCopyQuickReply(reply)}>
            {copiedQuickReplyId === reply.id ? 'Copied' : 'Copy'}
          </button>
          <button
            type="button"
            onClick={() => insertQuickReplyIntoComposer(reply)}
            disabled={!selectedConversationId || !canTypeMessage}
          >
            Insert
          </button>
        </div>
      </article>
    ));
  }

  function getAssignedUser(userId) {
    if (!userId) return null;
    return users.find((singleUser) => singleUser.id === userId) || null;
  }

  function getAssignedUserLabel(userId) {
    if (!userId) return 'Nobody';

    const assignedUser = getAssignedUser(userId);
    if (!assignedUser) return `User #${userId}`;

    const customDisplayName = String(assignedUser.display_name || '').trim();

    if (customDisplayName) {
      return customDisplayName;
    }

    const rawName = String(
      assignedUser.first_name ||
      assignedUser.full_name ||
      assignedUser.username ||
      ''
    ).trim();

    if (!rawName) return `User #${userId}`;

    const firstName = rawName.split(/[\s._-]+/).filter(Boolean)[0] || rawName;

    return `${firstName.charAt(0).toUpperCase()}${firstName.slice(1).toLowerCase()}`;
  }

  function getAssignedUserClass(userId) {
    if (!userId) return 'assigned-nobody';

    const assignedUser = getAssignedUser(userId);
    const stableValue = String(
      assignedUser?.username ||
      assignedUser?.id ||
      userId
    ).toLowerCase();
    const fallbackColorIndex = Array.from(stableValue).reduce(
      (total, character) =>
        (total + character.charCodeAt(0)) % ASSIGNMENT_COLOR_PALETTE.length,
      0
    );

    return `assigned-color-${fallbackColorIndex + 1}`;
  }

  function getAssignedUserColor(userId) {
    const assignedUser = getAssignedUser(userId);
    const savedColor = String(assignedUser?.assignment_color || '').trim();

    if (/^#[0-9a-f]{6}$/i.test(savedColor)) {
      return savedColor;
    }

    const className = getAssignedUserClass(userId);
    const colorIndex = Number(className.replace('assigned-color-', '')) - 1;
    return ASSIGNMENT_COLOR_PALETTE[colorIndex] || ASSIGNMENT_COLOR_PALETTE[0];
  }

  function getAssignedUserTextColor(userId) {
    const assignedUser = getAssignedUser(userId);
    const savedTextColor = String(
      assignedUser?.assignment_text_color || ''
    ).trim();

    if (HEX_COLOR_REGEX.test(savedTextColor)) {
      return savedTextColor;
    }

    return getAutomaticTextColor(getAssignedUserColor(userId));
  }

  function handleSettingsUsersChanged(updatedUsers) {
    setUsers(updatedUsers);
    setUser((currentUser) => {
      if (!currentUser?.id) return currentUser;
      return updatedUsers.find((singleUser) => singleUser.id === currentUser.id) || currentUser;
    });
  }

  function scrollMessagesToBottom() {
    window.setTimeout(() => {
      messagesEndRef.current?.scrollIntoView({
        behavior: 'auto',
        block: 'end',
      });
    }, 100);
  }


  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  function mergeMessagesById(...messageGroups) {
    const messagesById = new Map();

    messageGroups.flat().forEach((message) => {
      if (message?.id !== undefined && message?.id !== null) {
        messagesById.set(message.id, message);
      }
    });

    return Array.from(messagesById.values()).sort((a, b) => a.id - b.id);
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

  function getMessageStatusTitle(message) {
    if (!message || message.direction !== 'outbound') {
      return '';
    }

    const statusValue = String(message.whatsapp_status || '').toLowerCase();

    if (statusValue === 'sent') return 'Sent';
    if (statusValue === 'delivered') return 'Delivered';
    if (statusValue === 'read') return 'Read';
    if (statusValue === 'failed') return 'Failed';

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

  function getCustomerServiceSecondsLeft(conversation, nowMs) {
    if (!conversation?.customer_service_window_open) {
      return 0;
    }

    const expiresAtMs = Number(conversation.customer_service_expires_at_ms || 0);

    if (!expiresAtMs) {
      return Math.max(
        0,
        Number(conversation.customer_service_time_left_seconds || 0)
      );
    }

    return Math.max(0, Math.ceil((expiresAtMs - nowMs) / 1000));
  }

  function formatCustomerServiceWindow(conversation) {
    const secondsLeft = getCustomerServiceSecondsLeft(
      conversation,
      customerServiceNowMs
    );

    if (secondsLeft <= 0) {
      return 'Expired';
    }

    const hours = Math.floor(secondsLeft / 3600);
    const minutes = Math.floor((secondsLeft % 3600) / 60);
    const seconds = secondsLeft % 60;

    return [hours, minutes, seconds]
      .map((value) => String(value).padStart(2, '0'))
      .join(':');
  }

  function getCustomerServiceWindowClass(conversation) {
    const secondsLeft = getCustomerServiceSecondsLeft(
      conversation,
      customerServiceNowMs
    );

    if (!conversation?.customer_service_window_open || secondsLeft <= 0) {
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

  function getConversationResponseIconName(conversation) {
    const lastDirection = String(conversation?.last_message_direction || '').toLowerCase();

    if (lastDirection === 'inbound') return 'responseInbound';
    if (lastDirection === 'outbound') return 'responseOutbound';

    return 'responseNeutral';
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
      time_slot: '',
      result_status: '',
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

  function markApiSuccess() {
    apiFailureCountRef.current = 0;
    setSystemStatus('live');
  }

  function markApiFailure() {
    apiFailureCountRef.current += 1;

    if (apiFailureCountRef.current >= 2) {
      setSystemStatus('issue');
    }
  }

  function isAbortError(err) {
    return err?.name === 'AbortError';
  }

  async function refreshConversations(
    selectedConversationId = null,
    searchQueryOverride = inboxSearchQuery,
    conversationViewOverride = activeConversationView,
    options = {}
  ) {
    if (options.resetPagination === true) {
      loadMoreConversationsAbortControllerRef.current?.abort();
      loadedConversationLimitRef.current = CONVERSATION_PAGE_SIZE;
    }

    conversationAbortControllerRef.current?.abort();

    const abortController = new AbortController();
    conversationAbortControllerRef.current = abortController;

    const requestId = latestConversationRequestIdRef.current + 1;
    latestConversationRequestIdRef.current = requestId;

    const requestedLimit = Math.min(
      MAX_LOADED_CONVERSATIONS,
      Math.max(CONVERSATION_PAGE_SIZE, loadedConversationLimitRef.current)
    );

    try {
      const rawConversationData = await getConversations({
        searchQuery: searchQueryOverride,
        view: conversationViewOverride,
        limit: requestedLimit + 1,
        offset: 0,
        signal: abortController.signal,
      });

      markApiSuccess();

      if (requestId !== latestConversationRequestIdRef.current) {
        return;
      }

      const conversationData = attachCustomerServiceExpiry(
        rawConversationData.slice(0, requestedLimit)
      );

      loadedConversationLimitRef.current = Math.max(
        CONVERSATION_PAGE_SIZE,
        conversationData.length
      );
      setHasMoreConversations(
        requestedLimit < MAX_LOADED_CONVERSATIONS &&
          rawConversationData.length > requestedLimit
      );
      setConversations(conversationData);

      if (selectedConversationId) {
        const refreshedConversation = conversationData.find(
          (conversation) => conversation.id === selectedConversationId
        );

        if (refreshedConversation) {
          selectedConversationIdRef.current = refreshedConversation.id;
          setSelectedConversation(refreshedConversation);
          return;
        }

        selectedConversationIdRef.current = null;
        setSelectedConversation(null);
      }
    } catch (err) {
      if (isAbortError(err)) {
        return;
      }

      markApiFailure();
      throw err;
    } finally {
      if (conversationAbortControllerRef.current === abortController) {
        conversationAbortControllerRef.current = null;
      }
    }
  }

  async function refreshConversationSummary() {
    conversationSummaryAbortControllerRef.current?.abort();

    const abortController = new AbortController();
    conversationSummaryAbortControllerRef.current = abortController;

    try {
      const summaryData = await getConversationSummary({
        signal: abortController.signal,
      });

      setConversationSummary(summaryData);
    } catch (err) {
      if (!isAbortError(err)) {
        markApiFailure();
      }
    } finally {
      if (conversationSummaryAbortControllerRef.current === abortController) {
        conversationSummaryAbortControllerRef.current = null;
      }
    }
  }

  async function loadMoreConversations() {
    if (isLoadingMoreConversations || !hasMoreConversations) {
      return;
    }

    const offset = conversations.length;
    const remainingLimit = MAX_LOADED_CONVERSATIONS - offset;
    const pageSize = Math.min(CONVERSATION_PAGE_SIZE, remainingLimit);

    if (pageSize <= 0) {
      setHasMoreConversations(false);
      return;
    }

    loadMoreConversationsAbortControllerRef.current?.abort();

    const abortController = new AbortController();
    loadMoreConversationsAbortControllerRef.current = abortController;

    try {
      setIsLoadingMoreConversations(true);

      const rawConversationData = await getConversations({
        searchQuery: inboxSearchQuery,
        view: activeConversationView,
        limit: pageSize + 1,
        offset,
        signal: abortController.signal,
      });

      const nextPage = attachCustomerServiceExpiry(
        rawConversationData.slice(0, pageSize)
      );

      setConversations((currentConversations) => {
        const conversationsById = new Map(
          currentConversations.map((conversation) => [conversation.id, conversation])
        );

        nextPage.forEach((conversation) => {
          conversationsById.set(conversation.id, conversation);
        });

        const mergedConversations = Array.from(conversationsById.values());
        loadedConversationLimitRef.current = Math.min(
          MAX_LOADED_CONVERSATIONS,
          mergedConversations.length
        );

        return mergedConversations;
      });

      setHasMoreConversations(
        offset + pageSize < MAX_LOADED_CONVERSATIONS &&
          rawConversationData.length > pageSize
      );
      markApiSuccess();
    } catch (err) {
      if (!isAbortError(err)) {
        markApiFailure();
        setError(getErrorMessage(err, 'Could not load more conversations.'));
      }
    } finally {
      if (loadMoreConversationsAbortControllerRef.current === abortController) {
        loadMoreConversationsAbortControllerRef.current = null;
      }

      setIsLoadingMoreConversations(false);
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
    conversationAbortControllerRef.current?.abort();
    conversationSummaryAbortControllerRef.current?.abort();
    loadMoreConversationsAbortControllerRef.current?.abort();
    messagesRequestInProgressRef.current?.controller?.abort();
    olderMessagesAbortControllerRef.current?.abort();

    clearToken();
    setToken(null);
    setUser(null);
    setUsers([]);
    setConversations([]);
    setConversationSummary(null);
    setHasMoreConversations(false);
    setIsLoadingMoreConversations(false);
    loadedConversationLimitRef.current = CONVERSATION_PAGE_SIZE;
    selectedConversationIdRef.current = null;
    setSelectedConversation(null);
    setMessages([]);
    messagesRef.current = [];
    setHasMoreOlderMessages(true);
    setIsLoadingOlderMessages(false);
    setMessageDrafts({});
    setError('');
    setShowNewConversationForm(false);
    setActivePage(APP_PAGES.INBOX);
    setActiveConversationView(CONVERSATION_VIEWS.INBOX);
    setInboxSearchQuery('');
    resetNewConversationForm();

    setReportData(null);
    setReportsError('');
    setQuickReplies([]);
    setQuickReplyCategories([]);
    setQuickReplySearch('');
    setQuickReplyCategoryFilter('all');
    setQuickRepliesError('');
    setCopiedQuickReplyId(null);
    setFavoritingQuickReplyIds([]);
    setSlashQuickReplyMatch(null);
    setActiveSlashReplyIndex(0);
    setReportFilters({
      operation_date: '',
      date_from: '',
      date_to: '',
      option_code: '',
      time_slot: '',
      result_status: '',
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

      await Promise.all([
        refreshConversations(),
        refreshConversationSummary(),
        loadQuickReplyData(),
      ]);
    } catch (err) {
      clearToken();
      setToken(null);
      setError('Session expired. Please login again.');
    }
  }

  async function loadMessages(conversationId, options = {}) {
    if (!conversationId) {
      return;
    }

    const shouldReplaceMessages = options.replace === true;
    const shouldRefreshExistingMessages = options.refreshExisting === true;
    const requestKey = `${conversationId}:latest`;

    if (messagesRequestInProgressRef.current?.key === requestKey) {
      if (!shouldReplaceMessages) {
        return;
      }

      messagesRequestInProgressRef.current.controller.abort();
    }

    const abortController = new AbortController();
    const requestState = {
      key: requestKey,
      controller: abortController,
    };

    messagesRequestInProgressRef.current = requestState;

    const currentMessages = messagesRef.current;
    const newestMessage = currentMessages[currentMessages.length - 1];
    const shouldUseIncrementalFetch =
      !shouldReplaceMessages &&
      !shouldRefreshExistingMessages &&
      Boolean(newestMessage?.id);

    try {
      const messageData = await getMessages(conversationId, {
        limit: MESSAGE_PAGE_SIZE,
        afterId: shouldUseIncrementalFetch ? newestMessage.id : undefined,
        signal: abortController.signal,
      });

      markApiSuccess();

      if (selectedConversationIdRef.current !== conversationId) {
        return;
      }

      setMessages((currentMessages) => {
        if (shouldReplaceMessages || currentMessages.length === 0) {
          return messageData;
        }

        return mergeMessagesById(currentMessages, messageData);
      });

      if (shouldReplaceMessages || messagesRef.current.length === 0) {
        setHasMoreOlderMessages(messageData.length >= MESSAGE_PAGE_SIZE);
      }

      const currentPollState = messagePollStateRef.current;

      messagePollStateRef.current = {
        conversationId,
        incrementalPolls: shouldUseIncrementalFetch
          ? (currentPollState.conversationId === conversationId
              ? currentPollState.incrementalPolls
              : 0) + 1
          : 0,
      };
    } catch (err) {
      if (isAbortError(err)) {
        return;
      }

      const errorMessage = getErrorMessage(err, 'Could not load messages.');
      const normalizedErrorMessage = String(errorMessage).toLowerCase();

      const conversationWasDeleted =
        normalizedErrorMessage.includes('conversation not found') ||
        normalizedErrorMessage.includes('404');

      if (conversationWasDeleted) {
        selectedConversationIdRef.current = null;
        setSelectedConversation(null);
        setMessages([]);
        messagesRef.current = [];
        setHasMoreOlderMessages(true);
        await refreshConversations();
        return;
      }

      markApiFailure();
      throw err;
    } finally {
      if (messagesRequestInProgressRef.current === requestState) {
        messagesRequestInProgressRef.current = null;
      }
    }
  }

  async function loadOlderMessages() {
    if (!selectedConversation || activePage !== APP_PAGES.INBOX) {
      return;
    }

    if (!hasMoreOlderMessages || olderMessagesRequestInProgressRef.current) {
      return;
    }

    const conversationId = selectedConversation.id;
    const currentMessages = messagesRef.current;
    const oldestMessage = currentMessages[0];

    if (!oldestMessage) {
      return;
    }

    olderMessagesRequestInProgressRef.current = true;
    setIsLoadingOlderMessages(true);

    olderMessagesAbortControllerRef.current?.abort();

    const abortController = new AbortController();
    olderMessagesAbortControllerRef.current = abortController;

    const messagesContainer = messagesContainerRef.current;
    const previousScrollHeight = messagesContainer?.scrollHeight ?? 0;
    const previousScrollTop = messagesContainer?.scrollTop ?? 0;

    try {
      const olderMessages = await getMessages(conversationId, {
        limit: MESSAGE_PAGE_SIZE,
        beforeId: oldestMessage.id,
        signal: abortController.signal,
      });

      markApiSuccess();

      if (selectedConversationIdRef.current !== conversationId) {
        return;
      }

      if (olderMessages.length === 0) {
        setHasMoreOlderMessages(false);
        return;
      }

      setMessages((currentMessages) =>
        mergeMessagesById(olderMessages, currentMessages)
      );

      setHasMoreOlderMessages(olderMessages.length >= MESSAGE_PAGE_SIZE);

      window.setTimeout(() => {
        const currentContainer = messagesContainerRef.current;

        if (!currentContainer) {
          return;
        }

        const newScrollHeight = currentContainer.scrollHeight;
        currentContainer.scrollTop =
          newScrollHeight - previousScrollHeight + previousScrollTop;
      }, 0);
    } catch (err) {
      if (isAbortError(err)) {
        return;
      }

      markApiFailure();
      setError(getErrorMessage(err, 'Could not load older messages.'));
    } finally {
      olderMessagesRequestInProgressRef.current = false;
      if (olderMessagesAbortControllerRef.current === abortController) {
        olderMessagesAbortControllerRef.current = null;
      }
      setIsLoadingOlderMessages(false);
    }
  }

  function handleMessagesScroll(event) {
    if (event.currentTarget.scrollTop <= LOAD_OLDER_SCROLL_THRESHOLD_PX) {
      loadOlderMessages();
    }
  }

  async function handleSelectConversation(conversation) {
    setError('');
    setActivePage(APP_PAGES.INBOX);

    if (!isMobileChatOpen) {
      pushMobileHistoryLayer(MOBILE_HISTORY_LAYERS.CONVERSATION);
    }

    setIsMobileChatOpen(true);
    setIsMobileSearchOpen(false);
    setMobileDrawerMode(null);

    messagesRequestInProgressRef.current?.controller?.abort();
    olderMessagesAbortControllerRef.current?.abort();
    latestConversationRequestIdRef.current += 1;
    selectedConversationIdRef.current = conversation.id;
    messagePollStateRef.current = {
      conversationId: conversation.id,
      incrementalPolls: 0,
    };

    setSelectedConversation(conversation);

    const isTakenByAnotherUser =
      conversation.assigned_to_user_id !== null &&
      conversation.assigned_to_user_id !== user?.id &&
      user?.role !== 'admin' &&
      user?.role !== 'power_user';

    if (conversation.unread_count > 0 && !isTakenByAnotherUser) {
      try {
        await markConversationAsRead(conversation.id);
        await Promise.all([
          refreshConversations(conversation.id),
          refreshConversationSummary(),
        ]);
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
        replaceMobileHistoryLayer(MOBILE_HISTORY_LAYERS.CONVERSATION);
        setShowNewConversationForm(false);
        setActivePage(APP_PAGES.INBOX);
        setActiveConversationView(CONVERSATION_VIEWS.INBOX);
        setIsMobileChatOpen(true);

        await Promise.all([
          refreshConversations(
            createdConversation.id,
            inboxSearchQuery,
            CONVERSATION_VIEWS.INBOX,
            { resetPagination: true }
          ),
          refreshConversationSummary(),
        ]);
        await loadMessages(createdConversation.id, { replace: true });
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
      await Promise.all([
        refreshConversations(selectedConversation.id),
        refreshConversationSummary(),
      ]);
    } catch (err) {
      setError(getErrorMessage(err, 'Could not take conversation.'));
    }
  }

  async function handleReleaseConversation() {
    if (!selectedConversation || !canReleaseConversation) return;

    try {
      setError('');
      await releaseConversation(selectedConversation.id);
      await Promise.all([
        refreshConversations(selectedConversation.id),
        refreshConversationSummary(),
      ]);
    } catch (err) {
      setError(getErrorMessage(err, 'Could not release conversation.'));
    }
  }

  async function handleDoneConversation() {
    if (!selectedConversation) return;

    try {
      setError('');
      await closeConversation(selectedConversation.id);
      await Promise.all([
        refreshConversations(selectedConversation.id),
        refreshConversationSummary(),
      ]);
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

      const nextConversationView = checked
        ? CONVERSATION_VIEWS.FOLLOW_UP
        : CONVERSATION_VIEWS.INBOX;

      setActiveConversationView(nextConversationView);

      await Promise.all([
        refreshConversations(
          selectedConversation.id,
          inboxSearchQuery,
          nextConversationView,
          { resetPagination: true }
        ),
        refreshConversationSummary(),
      ]);
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

      let nextConversationView = activeConversationView;

      if (selectedConversation.status === 'archived') {
        await unarchiveConversation(selectedConversation.id);
        nextConversationView = CONVERSATION_VIEWS.INBOX;
        setActiveConversationView(nextConversationView);
      } else {
        await archiveConversation(selectedConversation.id);
      }

      await Promise.all([
        refreshConversations(
          selectedConversation.id,
          inboxSearchQuery,
          nextConversationView,
          { resetPagination: true }
        ),
        refreshConversationSummary(),
      ]);
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
      selectedConversationIdRef.current = null;
      setSelectedConversation(null);
      setMessages([]);
      messagesRef.current = [];
      setHasMoreOlderMessages(true);
      setIsLoadingOlderMessages(false);
      setError('');
      dismissMobileHistoryLayer(() => {
        setShowDeleteConfirm(false);
        setIsMobileChatOpen(false);
      }, 2, MOBILE_HISTORY_LAYERS.DELETE_CONFIRM);
      await Promise.all([
        refreshConversations(),
        refreshConversationSummary(),
      ]);
    } catch (err) {
      setError(getErrorMessage(err, 'Could not delete conversation.'));
    }
  }


  async function handleSendReaction(messageId, emoji) {
    if (!messageId) {
      return;
    }

    if (reactingMessageIds.includes(messageId)) {
      return;
    }

    setError('');
    setReactingMessageIds((currentIds) => [...currentIds, messageId]);

    try {
      const updatedMessage = await sendMessageReaction(messageId, emoji);

      setMessages((currentMessages) =>
        currentMessages.map((message) =>
          message.id === updatedMessage.id ? updatedMessage : message
        )
      );

      dismissMobileHistoryLayer(
        () => setOpenReactionPickerMessageId(null),
        1,
        MOBILE_HISTORY_LAYERS.REACTION
      );

      await Promise.all([
        refreshConversations(selectedConversation?.id || null),
        refreshConversationSummary(),
      ]);
    } catch (err) {
      setError(err.message || 'Failed to send reaction');
    } finally {
      setReactingMessageIds((currentIds) =>
        currentIds.filter((currentId) => currentId !== messageId)
      );
    }
  }

  async function handleSendMessage(event) {
  event.preventDefault();

  const conversationId = selectedConversation?.id;

  if (!conversationId || !newMessage.trim() || isSending) return;

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
  setConversationDraft(conversationId, '');
  closeSlashQuickReplies();

  try {
    const sentMessage = await sendMessage(conversationId, messageToSend);

    setMessages((currentMessages) =>
      mergeMessagesById(currentMessages, sentMessage)
    );

    setActiveConversationView(CONVERSATION_VIEWS.INBOX);
    await Promise.all([
      refreshConversations(
        conversationId,
        inboxSearchQuery,
        CONVERSATION_VIEWS.INBOX,
        { resetPagination: true }
      ),
      refreshConversationSummary(),
    ]);

    window.setTimeout(() => {
      messageInputRef.current?.focus();
    }, 0);
  } catch (err) {
    setError(getErrorMessage(err, 'Could not send message.'));
    setConversationDraft(conversationId, messageToSend);
  } finally {
    setIsSending(false);

    window.setTimeout(() => {
      messageInputRef.current?.focus();
    }, 0);
  }
}

  useEffect(() => {
    if (!selectedConversation?.customer_service_window_open) {
      return undefined;
    }

    const intervalId = window.setInterval(() => {
      setCustomerServiceNowMs(Date.now());
    }, 1000);

    return () => window.clearInterval(intervalId);
  }, [
    selectedConversation?.id,
    selectedConversation?.customer_service_window_open,
  ]);

  useEffect(() => {
    function handleVisibilityChange() {
      setIsPageVisible(document.visibilityState !== 'hidden');
    }

    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      conversationAbortControllerRef.current?.abort();
      conversationSummaryAbortControllerRef.current?.abort();
      loadMoreConversationsAbortControllerRef.current?.abort();
      messagesRequestInProgressRef.current?.controller?.abort();
      olderMessagesAbortControllerRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    mobileNavigationSnapshotRef.current = {
      showDeleteConfirm,
      showExitConfirm,
      openReactionPickerMessageId,
      slashQuickReplyMatch,
      mobileDrawerMode,
      showNewConversationForm,
      isMobileSearchOpen,
      isMobileChatOpen,
      activePage,
    };
  }, [
    showDeleteConfirm,
    showExitConfirm,
    openReactionPickerMessageId,
    slashQuickReplyMatch,
    mobileDrawerMode,
    showNewConversationForm,
    isMobileSearchOpen,
    isMobileChatOpen,
    activePage,
  ]);

  useEffect(() => {
    if (!token) {
      return undefined;
    }

    const mobileMediaQuery = window.matchMedia(MOBILE_LAYOUT_QUERY);

    function initializeMobileHistory() {
      if (!mobileMediaQuery.matches) {
        return;
      }

      const existingMarker = getCurrentMobileHistoryMarker();

      if (!mobileHistorySessionIdRef.current) {
        mobileHistorySessionIdRef.current =
          existingMarker?.sessionId ||
          `sendro-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      }

      if (
        existingMarker?.sessionId === mobileHistorySessionIdRef.current &&
        existingMarker.layer === MOBILE_HISTORY_LAYERS.LIST
      ) {
        return;
      }

      if (existingMarker?.sessionId === mobileHistorySessionIdRef.current) {
        window.history.replaceState(
          createMobileHistoryState(MOBILE_HISTORY_LAYERS.LIST),
          '',
          window.location.href
        );
        return;
      }

      window.history.replaceState(
        createMobileHistoryState(MOBILE_HISTORY_LAYERS.EXIT_BOUNDARY),
        '',
        window.location.href
      );
      window.history.pushState(
        createMobileHistoryState(MOBILE_HISTORY_LAYERS.LIST),
        '',
        window.location.href
      );
    }

    function handleMobilePopState(event) {
      if (!mobileMediaQuery.matches) {
        return;
      }

      const marker = event.state?.[MOBILE_HISTORY_STATE_KEY];

      if (marker?.sessionId !== mobileHistorySessionIdRef.current) {
        return;
      }

      if (skipNextMobilePopRef.current) {
        skipNextMobilePopRef.current = false;
        return;
      }

      if (allowMobileExitRef.current) {
        if (marker.layer !== MOBILE_HISTORY_LAYERS.EXIT_BOUNDARY) {
          window.history.back();
          return;
        }

        allowMobileExitRef.current = false;
        const exitLocation = window.location.href;

        window.history.back();
        window.setTimeout(() => {
          const currentMarker = getCurrentMobileHistoryMarker();

          if (
            document.visibilityState !== 'hidden' &&
            window.location.href === exitLocation &&
            currentMarker?.sessionId === mobileHistorySessionIdRef.current &&
            currentMarker.layer === MOBILE_HISTORY_LAYERS.EXIT_BOUNDARY
          ) {
            window.location.replace('about:blank');
          }
        }, 500);
        return;
      }

      const snapshot = mobileNavigationSnapshotRef.current;

      if (snapshot.showExitConfirm) {
        window.history.pushState(
          createMobileHistoryState(MOBILE_HISTORY_LAYERS.LIST),
          '',
          window.location.href
        );
        setShowExitConfirm(false);
        return;
      }

      if (snapshot.showDeleteConfirm) {
        setShowDeleteConfirm(false);
        return;
      }

      if (snapshot.openReactionPickerMessageId) {
        setOpenReactionPickerMessageId(null);
        return;
      }

      if (snapshot.slashQuickReplyMatch) {
        setSlashQuickReplyMatch(null);
        setActiveSlashReplyIndex(0);
        return;
      }

      if (snapshot.mobileDrawerMode) {
        setMobileDrawerMode(null);
        return;
      }

      if (snapshot.showNewConversationForm) {
        setShowNewConversationForm(false);
        return;
      }

      if (snapshot.isMobileSearchOpen) {
        setIsMobileSearchOpen(false);
        return;
      }

      if (snapshot.activePage !== APP_PAGES.INBOX) {
        setActivePage(APP_PAGES.INBOX);
        setIsMobileChatOpen(false);
        return;
      }

      if (snapshot.isMobileChatOpen) {
        setIsMobileChatOpen(false);
        return;
      }

      window.history.pushState(
        createMobileHistoryState(MOBILE_HISTORY_LAYERS.LIST),
        '',
        window.location.href
      );
      setShowExitConfirm(true);
    }

    initializeMobileHistory();
    window.addEventListener('popstate', handleMobilePopState);
    mobileMediaQuery.addEventListener?.('change', initializeMobileHistory);

    return () => {
      window.removeEventListener('popstate', handleMobilePopState);
      mobileMediaQuery.removeEventListener?.('change', initializeMobileHistory);
    };
  }, [token]);

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
    messagesRequestInProgressRef.current?.controller?.abort();
    olderMessagesAbortControllerRef.current?.abort();
    selectedConversationIdRef.current = selectedConversation?.id || null;

    if (selectedConversation && activePage === APP_PAGES.INBOX) {
      setError('');
      setMessages([]);
      messagesRef.current = [];
      setHasMoreOlderMessages(true);
      setIsLoadingOlderMessages(false);
      messagePollStateRef.current = {
        conversationId: selectedConversation.id,
        incrementalPolls: 0,
      };

      loadMessages(selectedConversation.id, { replace: true }).catch(() => {
        // Error is handled inside loadMessages.
      });
    } else {
      setMessages([]);
      messagesRef.current = [];
      setHasMoreOlderMessages(true);
      setIsLoadingOlderMessages(false);
    }
    setSlashQuickReplyMatch(null);
    setActiveSlashReplyIndex(0);
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
    if (!token || activePage !== APP_PAGES.INBOX || !isPageVisible) {
      return undefined;
    }

    loadMoreConversationsAbortControllerRef.current?.abort();

    const timeoutId = window.setTimeout(() => {
      refreshConversations(
        selectedConversationIdRef.current,
        inboxSearchQuery,
        activeConversationView,
        { resetPagination: true }
      ).catch(() => {
          // Silent search or view refresh failure.
        });
    }, 350);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [
    token,
    activePage,
    isPageVisible,
    inboxSearchQuery,
    activeConversationView,
  ]);

  useEffect(() => {
    if (activePage !== APP_PAGES.INBOX) return;

    if (filteredConversations.length === 0) {
      selectedConversationIdRef.current = null;
      setSelectedConversation(null);
      return;
    }

    if (!selectedConversation) {
      selectedConversationIdRef.current = filteredConversations[0].id;
      setSelectedConversation(filteredConversations[0]);
      return;
    }

    const selectedStillVisible = filteredConversations.some(
      (conversation) => conversation.id === selectedConversation.id
    );

    if (!selectedStillVisible) {
      selectedConversationIdRef.current = filteredConversations[0].id;
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
    if (
      !token ||
      activePage !== APP_PAGES.INBOX ||
      !isPageVisible ||
      inboxSearchQuery.trim()
    ) {
      return undefined;
    }

    let cancelled = false;
    let timeoutId = null;
    let failureCount = 0;

    const scheduleNextPoll = (delay) => {
      if (!cancelled) {
        timeoutId = window.setTimeout(runPoll, delay);
      }
    };

    const runPoll = async () => {
      try {
        await refreshConversations(
          selectedConversation?.id || null,
          '',
          activeConversationView
        );
        failureCount = 0;
      } catch {
        failureCount += 1;
      }

      const nextDelay = Math.min(
        MAX_POLL_BACKOFF_MS,
        AUTO_REFRESH_INTERVAL_MS * 2 ** failureCount
      );
      scheduleNextPoll(nextDelay);
    };

    scheduleNextPoll(AUTO_REFRESH_INTERVAL_MS);

    return () => {
      cancelled = true;
      if (timeoutId) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [
    token,
    activePage,
    isPageVisible,
    selectedConversation?.id,
    activeConversationView,
    inboxSearchQuery,
  ]);

  useEffect(() => {
    if (!token || activePage !== APP_PAGES.INBOX || !isPageVisible) {
      return undefined;
    }

    let cancelled = false;
    let timeoutId = null;

    const runSummaryPoll = async () => {
      try {
        await refreshConversationSummary();
      } catch {
        // Connection state is handled by refreshConversationSummary.
      }

      if (!cancelled) {
        timeoutId = window.setTimeout(
          runSummaryPoll,
          SUMMARY_REFRESH_INTERVAL_MS
        );
      }
    };

    timeoutId = window.setTimeout(
      runSummaryPoll,
      SUMMARY_REFRESH_INTERVAL_MS
    );

    return () => {
      cancelled = true;
      if (timeoutId) {
        window.clearTimeout(timeoutId);
      }
    };
    // This effect is keyed by page visibility/auth state; the refresh helper
    // intentionally reads the latest abort-controller ref on every poll.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, activePage, isPageVisible]);

  useEffect(() => {
    if (
      !token ||
      activePage !== APP_PAGES.INBOX ||
      !isPageVisible ||
      !selectedConversation?.id
    ) {
      return undefined;
    }

    const selectedConversationId = selectedConversation.id;
    let cancelled = false;
    let timeoutId = null;
    let failureCount = 0;

    const scheduleNextPoll = (delay) => {
      if (!cancelled) {
        timeoutId = window.setTimeout(runPoll, delay);
      }
    };

    const runPoll = async () => {
      const pollState = messagePollStateRef.current;
      const shouldRefreshExisting =
        pollState.conversationId !== selectedConversationId ||
        pollState.incrementalPolls >= FULL_MESSAGE_SYNC_EVERY_POLLS;

      try {
        await loadMessages(selectedConversationId, {
          refreshExisting: shouldRefreshExisting,
        });
        failureCount = 0;
      } catch {
        failureCount += 1;
      }

      const nextDelay = Math.min(
        MAX_POLL_BACKOFF_MS,
        ACTIVE_CHAT_REFRESH_INTERVAL_MS * 2 ** failureCount
      );
      scheduleNextPoll(nextDelay);
    };

    scheduleNextPoll(ACTIVE_CHAT_REFRESH_INTERVAL_MS);

    return () => {
      cancelled = true;
      if (timeoutId) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [token, activePage, isPageVisible, selectedConversation?.id]);

  function renderReportsPanel() {
    const summary = reportData?.summary || {};
    const reportItems = reportData?.items || [];

    const tourOptionOptions = Array.from(
      new Map(
        reportItems
          .filter((item) => item.option_code)
          .map((item) => [
            item.option_code,
            {
              value: item.option_code,
              label: item.tour_name
                ? `${item.tour_name} (${item.option_code})`
                : item.option_code,
            },
          ])
      ).values()
    ).sort((a, b) => a.label.localeCompare(b.label));

    if (
      reportFilters.option_code &&
      !tourOptionOptions.some((option) => option.value === reportFilters.option_code)
    ) {
      tourOptionOptions.unshift({
        value: reportFilters.option_code,
        label: reportFilters.option_code,
      });
    }

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
            <span>Time</span>
            <select
              value={reportFilters.time_slot}
              onChange={(event) => updateReportFilter('time_slot', event.target.value)}
            >
              <option value="">All</option>
              <option value="morning">Morning</option>
              <option value="sunset">Sunset</option>
            </select>
          </label>

          <label>
            <span>Tour option</span>
            <select
              value={reportFilters.option_code}
              onChange={(event) => updateReportFilter('option_code', event.target.value)}
            >
              <option value="">All options</option>
              {tourOptionOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          <label>
            <span>Status</span>
            <select
              value={reportFilters.result_status}
              onChange={(event) =>
                updateReportFilter('result_status', event.target.value)
              }
            >
              <option value="">All statuses</option>
              <option value="sent_waiting">Sent / waiting</option>
              <option value="delivered">Delivered</option>
              <option value="read">Read</option>
              <option value="failed">Failed</option>
              <option value="missing_phone">Missing phone</option>
              <option value="wrong_number">Wrong number</option>
              <option value="missing_details">Missing details</option>
              <option value="duplicate">Duplicate</option>
            </select>
          </label>

          <label>
            <span>Search</span>
            <input
              value={reportFilters.q}
              onChange={(event) => updateReportFilter('q', event.target.value)}
              placeholder="Reservation, name, phone..."
            />
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
                    <th>Status</th>
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
            <div className="brand glossy-login-brand">
              <div className="login-brand-logo-wrap">
                <img src={sendroLogo} alt="Sendro" className="login-brand-logo" />
              </div>
              <p>Team WhatsApp Inbox</p>
            </div>
          </div>

          <input
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="Username"
            autoComplete="username"
            required
          />

          <input
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="Password"
            type="password"
            autoComplete="current-password"
            required
          />

          <button type="submit">Login</button>

          <details className="login-recovery">
            <summary>Forgot password?</summary>
            <div className="login-recovery-note">
              <strong>Contact your Sendro administrator.</strong>
              <span>
                An administrator can reset your password from Settings → Users.
              </span>
            </div>
          </details>

          {error && <p className="error-message">{error}</p>}
        </form>
      </div>
    );
  }

  return (
    <div
      className={`app sendro-shell ${activePage === APP_PAGES.REPORTS ? 'reports-mode' : ''
        } ${activePage === APP_PAGES.SETTINGS ? 'settings-mode' : ''} ${isMobileChatOpen ? 'mobile-chat-open' : ''}`}
    >
      {error && <div className="app-error">{error}</div>}

      <header className="mobile-app-bar">
        <div className="mobile-app-logo-wrap">
          <img src={sendroLogo} alt="Sendro" className="mobile-app-logo" />
        </div>
        <button
          type="button"
          className={`mobile-new-conversation-button ${showNewConversationForm ? 'active' : ''}`}
          onClick={() => {
            setError('');
            setActivePage(APP_PAGES.INBOX);
            setIsMobileChatOpen(false);
            toggleNewConversationPanel();
          }}
          aria-label={showNewConversationForm ? 'Close new conversation form' : 'Create new conversation'}
          title={showNewConversationForm ? 'Close' : 'New conversation'}
        >
          {showNewConversationForm ? '×' : <Icon name="plus" size={22} />}
        </button>
        <div className="mobile-app-actions">
          <button
            type="button"
            onClick={focusMobileInboxSearch}
            aria-label={isMobileSearchOpen ? 'Hide conversation search' : 'Search conversations'}
            aria-pressed={isMobileSearchOpen}
          >
            <Icon name="search" size={25} />
          </button>
          <button type="button" onClick={() => openMobileDrawer('menu')} aria-label="Open menu">
            <Icon name="menu" size={27} />
          </button>
        </div>
      </header>

      <aside className={`blue-sidebar ${isSidebarCollapsed ? 'collapsed' : ''}`}>
        <div className="blue-sidebar-top">
          <div className="blue-brand">
            <div className="blue-brand-logo-wrap">
              <img src={sendroLogo} alt="Sendro" className="blue-brand-logo" />
            </div>
            <button
              type="button"
              className="blue-sidebar-toggle"
              onClick={() => setIsSidebarCollapsed((currentValue) => !currentValue)}
              aria-label={isSidebarCollapsed ? 'Show sidebar' : 'Hide sidebar'}
              title={isSidebarCollapsed ? 'Show sidebar' : 'Hide sidebar'}
            >
              <Icon name={isSidebarCollapsed ? 'sidebarExpand' : 'sidebarCollapse'} size={18} />
            </button>
          </div>

          <div className="blue-section-title">Workspace</div>

          <div className="blue-filter-list">
            <button
              type="button"
              className={`blue-filter-button ${activeConversationView === CONVERSATION_VIEWS.INBOX ? 'active' : ''
                }`}
              onClick={() => openConversationView(CONVERSATION_VIEWS.INBOX)}
              title="Inbox"
            >
              <span className="blue-nav-label"><Icon name="inbox" /><span>Inbox</span></span>
              {inboxUnreadCount > 0 && <strong>{inboxUnreadCount}</strong>}
            </button>

            <button
              type="button"
              className={`blue-filter-button ${activeConversationView === CONVERSATION_VIEWS.MINE ? 'active' : ''
                }`}
              onClick={() => openConversationView(CONVERSATION_VIEWS.MINE)}
              title="Mine"
            >
              <span className="blue-nav-label"><Icon name="user" /><span>Mine</span></span>
              {mineCount > 0 && <strong>{mineCount}</strong>}
            </button>

            <button
              type="button"
              className={`blue-filter-button ${activeConversationView === CONVERSATION_VIEWS.FOLLOW_UP ? 'active' : ''
                }`}
              onClick={() => openConversationView(CONVERSATION_VIEWS.FOLLOW_UP)}
              title="To Follow Up"
            >
              <span className="blue-nav-label"><Icon name="follow" /><span>To Follow Up</span></span>
              {Number(conversationSummary?.follow_up || 0) > 0 && (
                <strong>{conversationSummary.follow_up}</strong>
              )}
            </button>

            <button
              type="button"
              className={`blue-filter-button ${activeConversationView === CONVERSATION_VIEWS.ARCHIVED ? 'active' : ''
                }`}
              onClick={() => openConversationView(CONVERSATION_VIEWS.ARCHIVED)}
              title="Archived"
            >
              <span className="blue-nav-label"><Icon name="archive" /><span>Archived</span></span>
            </button>
          </div>

          <div className="blue-section-title blue-section-spaced">Channel</div>
          <div className="blue-channel-row">
            <span className="whatsapp-mark">W</span>
            <span className="blue-channel-label">WhatsApp</span>
            {browserUnreadCount > 0 && <strong>{browserUnreadCount}</strong>}
          </div>

          <div className="blue-section-title blue-section-spaced">Tools</div>

          {canCurrentUserViewReports && (
            <button
              type="button"
              className={`blue-settings-button ${activePage === APP_PAGES.REPORTS ? 'active' : ''}`}
              title="Reports"
              onClick={() => {
                setActivePage(APP_PAGES.REPORTS);
                setSelectedConversation(null);
                setIsMobileChatOpen(false);
              }}
            >
              <Icon name="reports" /><span className="blue-tool-label">Reports</span>
            </button>
          )}

          <button
            type="button"
            className={`blue-settings-button ${activePage === APP_PAGES.SETTINGS ? 'active' : ''}`}
            title="Settings"
            onClick={() => {
              setActivePage(APP_PAGES.SETTINGS);
              setSelectedConversation(null);
              setIsMobileChatOpen(false);
            }}
          >
            <Icon name="settings" /><span className="blue-tool-label">Settings</span>
          </button>
        </div>

        <div className="blue-sidebar-bottom">
          <div className="blue-user-box">
            <span className="blue-user-avatar">{getInitials(user?.username || 'User')}</span>
            <span className="blue-user-copy">
              <strong>{user?.username || 'User'}</strong>
              <small>{user?.role || 'user'}</small>
            </span>
          </div>

          <div className={`sendro-system-status ${systemStatus === 'live' ? 'live' : 'issue'}`}>
            <span className="sendro-system-status-icon">
              {systemStatus === 'live' ? '✓' : '!'}
            </span>
            <span>
              {systemStatus === 'live'
                ? 'Sendro is live'
                : 'Connection issue — messages may be delayed'}
            </span>
          </div>

          <button className="blue-logout-button" onClick={handleLogout} title="Logout">
            <Icon name="logout" size={18} /><span>Logout</span>
          </button>
        </div>
      </aside>

      <div className="sendro-workspace">
        <header className="workspace-topbar">
          <div className="workspace-account">
            <strong>Sunset Oia</strong>
            <Icon name="chevron" size={16} />
            <span className={`workspace-online ${systemStatus === 'live' ? 'live' : 'issue'}`}>
              <i />{systemStatus === 'live' ? 'Online' : 'Connection issue'}
            </span>
          </div>
          <div className="workspace-tools">
            <span title="Team"><Icon name="users" /></span>
            <span aria-hidden="true"><Icon name="more" /></span>
          </div>
        </header>

        <div className="sendro-workspace-columns">

      <section className="conversation-column">
        <div className="conversation-column-header">
          <div className="conversation-column-title">
            <div>
              <span>Conversations</span>
              <strong>
                {activeConversationView === CONVERSATION_VIEWS.MINE
                  ? 'Mine'
                  : activeConversationView === CONVERSATION_VIEWS.FOLLOW_UP
                    ? 'Follow Up'
                    : activeConversationView === CONVERSATION_VIEWS.ARCHIVED
                      ? 'Archived'
                      : 'Inbox'}
              </strong>
            </div>
            <button
              className={`new-conversation-fab ${showNewConversationForm ? 'active' : ''}`}
              onClick={() => {
                setError('');
                toggleNewConversationPanel();
              }}
              type="button"
              aria-label="Create new conversation"
              title="New conversation"
            >
              {showNewConversationForm ? '×' : <Icon name="plus" size={19} />}
            </button>
          </div>

          <div className={`inbox-search ${isMobileSearchOpen ? 'mobile-search-open' : ''}`}>
            <Icon name="search" size={19} />
            <input
              ref={inboxSearchInputRef}
              value={inboxSearchQuery}
              onChange={(event) => setInboxSearchQuery(event.target.value)}
              placeholder="Search conversations..."
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
            <button
              type="button"
              className="inbox-filter-button"
              aria-label="View archived conversations"
              title="Archived conversations"
              onClick={() => openConversationView(CONVERSATION_VIEWS.ARCHIVED)}
            >
              <Icon name="filter" size={18} />
            </button>
          </div>

          <div className="conversation-view-tabs" role="tablist" aria-label="Conversation views">
            <button
              type="button"
              className={activeConversationView === CONVERSATION_VIEWS.INBOX ? 'active' : ''}
              onClick={() => openConversationView(CONVERSATION_VIEWS.INBOX)}
            >
              Open <span>{inboxUnreadCount || ''}</span>
            </button>
            <button
              type="button"
              className={activeConversationView === CONVERSATION_VIEWS.MINE ? 'active' : ''}
              onClick={() => openConversationView(CONVERSATION_VIEWS.MINE)}
            >
              Mine <span>{mineCount || ''}</span>
            </button>
            <button
              type="button"
              className={activeConversationView === CONVERSATION_VIEWS.FOLLOW_UP ? 'active' : ''}
              onClick={() => openConversationView(CONVERSATION_VIEWS.FOLLOW_UP)}
            >
              Follow Up
            </button>
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
                  <span className="conversation-avatar" aria-hidden="true">
                    {getInitials(label)}
                    <i>W</i>
                  </span>

                  <span className="conversation-copy">
                    <span className="conversation-title-row">
                      <strong>{label}</strong>
                      <small className="conversation-time">
                        {formatMessageTime(conversation.last_message_at)}
                      </small>
                    </span>

                    <span className="conversation-preview-row">
                      <span className="conversation-preview">{conversation.contact_phone}</span>
                      <span
                        className={`conversation-response-dot ${getConversationResponseDotClass(
                          conversation
                        )}`}
                        title={getResponseIndicatorLabel(conversation)}
                        aria-label={getResponseIndicatorLabel(conversation)}
                      >
                        <Icon
                          name={getConversationResponseIconName(conversation)}
                          size={15}
                          strokeWidth={2.6}
                        />
                      </span>
                      {unreadCount > 0 && (
                        <span className="unread-badge">{unreadCount}</span>
                      )}
                    </span>

                    <small className="conversation-meta">

                      {isArchivedConversation(conversation) && (
                        <span className="status-pill">Archived</span>
                      )}

                      {conversation.assigned_to_user_id && (
                        <span
                          className="assigned-badge assigned-user-color"
                          style={{
                            backgroundColor: getAssignedUserColor(
                              conversation.assigned_to_user_id
                            ),
                            color: getAssignedUserTextColor(
                              conversation.assigned_to_user_id
                            ),
                          }}
                        >
                          {getAssignedUserLabel(conversation.assigned_to_user_id)}
                        </span>
                      )}
                    </small>
                  </span>
                </button>
              );
            })
          )}

          {filteredConversations.length > 0 && hasMoreConversations && (
            <button
              type="button"
              className="load-more-conversations-button"
              onClick={loadMoreConversations}
              disabled={isLoadingMoreConversations}
            >
              {isLoadingMoreConversations ? 'Loading...' : 'Load more conversations'}
            </button>
          )}
        </div>
      </section>

      <main className="chat-panel">
        {activePage === APP_PAGES.REPORTS && canCurrentUserViewReports ? (
          renderReportsPanel()
        ) : activePage === APP_PAGES.SETTINGS ? (
          <SettingsPanel
            onUsersChanged={handleSettingsUsersChanged}
            onQuickRepliesChanged={handleSettingsQuickRepliesChanged}
          />
        ) : selectedConversation ? (
          <>
            <header className="chat-header">
              <button
                type="button"
                className="mobile-chat-back"
                onClick={handleMobileChatBack}
                aria-label="Back to conversations"
              >
                <Icon name="back" size={27} />
              </button>

              <span className="chat-contact-avatar" aria-hidden="true">
                {getInitials(selectedConversation.contact_name || selectedConversation.contact_phone)}
                <i>W</i>
              </span>

              <div className="chat-contact-copy">
                <div className="chat-contact-title-row">
                  <h2>{selectedConversation.contact_name || 'Unknown contact'}</h2>
                  <span className="chat-whatsapp-label">WhatsApp</span>
                </div>
                <p>{selectedConversation.contact_phone}</p>

                <div className="conversation-status-area">
                  <p className="conversation-status-row">

                    {isArchivedConversation(selectedConversation) && (
                      <span className="status-pill">Archived</span>
                    )}

                    {selectedConversation.assigned_to_user_id ? (
                      <span
                        className="assigned-badge assigned-user-color"
                        style={{
                          backgroundColor: getAssignedUserColor(
                            selectedConversation.assigned_to_user_id
                          ),
                          color: getAssignedUserTextColor(
                            selectedConversation.assigned_to_user_id
                          ),
                        }}
                      >
                        {getAssignedUserLabel(selectedConversation.assigned_to_user_id)}
                      </span>
                    ) : null}

                  </p>
                </div>
              </div>

              {isDoneConversation(selectedConversation) && (
                <div className="chat-header-follow-up">
                  <label className="follow-up-toggle">
                    <input
                      type="checkbox"
                      checked={Boolean(selectedConversation.follow_up)}
                      onChange={(event) => handleToggleFollowUp(event.target.checked)}
                      disabled={isUpdatingFollowUp}
                    />
                    <span className="follow-up-toggle-track" aria-hidden="true">
                      <span />
                    </span>
                    <span className="follow-up-toggle-label">Follow Up</span>
                  </label>
                </div>
              )}

              <div className="chat-header-tools">
                <div
                  className={`customer-service-live ${getCustomerServiceWindowClass(
                    selectedConversation
                  )}`}
                  title={
                    isCustomerServiceSessionExpired
                      ? 'Template required'
                      : 'WhatsApp reply window'
                  }
                  aria-label={
                    isCustomerServiceSessionExpired
                      ? 'WhatsApp reply window expired'
                      : `${formatCustomerServiceWindow(selectedConversation)} remaining`
                  }
                >
                  <Icon name="clock" size={18} strokeWidth={2.1} />
                  <i aria-hidden="true" />
                  <strong>{formatCustomerServiceWindow(selectedConversation)}</strong>
                </div>
              </div>
            </header>

            <section
              className="messages"
              ref={messagesContainerRef}
              onScroll={handleMessagesScroll}
            >
              {isLoadingOlderMessages && (
                <div className="older-messages-loader">Loading older messages...</div>
              )}
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
                                title={getMessageStatusTitle(message)}
                                aria-label={getMessageStatusTitle(message)}
                              >
                                {getMessageStatusLabel(message)}
                              </span>
                            )}
                          </div>
                        )}
                      </div>

                      {message.direction === 'outbound' && message.reaction_emoji && (
                        <div className="message-reaction outgoing">
                          {message.reaction_emoji}
                        </div>
                      )}

                      {message.direction === 'inbound' &&
                        selectedConversation.status !== 'archived' &&
                        !isCustomerServiceSessionExpired && (
                          <div className="message-reaction-control incoming">
                            <button
                              type="button"
                              className={`message-reaction-trigger ${message.reaction_emoji ? 'has-reaction' : ''
                                }`}
                              onClick={() => toggleReactionPicker(message.id)}
                              disabled={reactingMessageIds.includes(message.id)}
                              title="React"
                            >
                              {message.reaction_emoji || 'R'}
                            </button>

                            {openReactionPickerMessageId === message.id && (
                              <div className="message-reaction-picker">
                                {BASIC_REACTION_EMOJIS.map((emoji) => (
                                  <button
                                    key={emoji}
                                    type="button"
                                    className={`message-reaction-option ${message.reaction_emoji === emoji ? 'selected' : ''
                                      }`}
                                    onClick={() => handleSendReaction(message.id, emoji)}
                                    disabled={reactingMessageIds.includes(message.id)}
                                    title={`React with ${emoji}`}
                                  >
                                    {emoji}
                                  </button>
                                ))}

                                <button
                                  type="button"
                                  className="message-reaction-option remove"
                                  onClick={() => handleSendReaction(message.id, null)}
                                  disabled={reactingMessageIds.includes(message.id) || !message.reaction_emoji}
                                  title="Remove reaction"
                                >
                                  ×
                                </button>
                              </div>
                            )}
                          </div>
                        )}
                    </Fragment>
                  );
                })
              )}

              <div ref={messagesEndRef} />
            </section>

            <form className="composer" onSubmit={handleSendMessage}>
              <div className="composer-body">
                <textarea
                  ref={messageInputRef}
                  value={newMessage}
                  onChange={handleComposerDraftChange}
                  onKeyDown={handleComposerKeyDown}
                  onDragOver={(event) => {
                    if (canTypeMessage) event.preventDefault();
                  }}
                  onDrop={handleQuickReplyDrop}
                  placeholder={
                    selectedConversation.status === 'archived'
                      ? 'Archived conversation'
                      : isCustomerServiceSessionExpired
                        ? 'Session expired — template required'
                        : isConversationTakenByAnotherUser
                          ? getAssignedUserLabel(
                            selectedConversation.assigned_to_user_id
                          )
                          : 'Type a message...'
                  }
                  disabled={
                    selectedConversation.status === 'archived' ||
                    isCustomerServiceSessionExpired ||
                    isConversationTakenByAnotherUser
                  }
                  rows="2"
                />

                {slashQuickReplyMatch && canTypeMessage && (
                  <div className="quick-reply-slash-picker">
                    <div className="quick-reply-slash-picker-header">
                      <span>Quick Replies</span>
                      <small>
                        {slashQuickReplyMatch.query
                          ? `Results for /${slashQuickReplyMatch.query}`
                          : 'Type to search · ↑↓ to navigate'}
                      </small>
                    </div>

                    {slashQuickReplies.length === 0 ? (
                      <div className="quick-reply-slash-empty">No matching quick replies.</div>
                    ) : (
                      <div className="quick-reply-slash-results">
                        {slashQuickReplies.map((reply, index) => (
                          <button
                            type="button"
                            key={reply.id}
                            className={index === activeSlashReplyIndex ? 'active' : ''}
                            onMouseDown={(event) => event.preventDefault()}
                            onClick={() => insertQuickReplyIntoComposer(reply, { slashMatch: slashQuickReplyMatch })}
                          >
                            <span className={reply.is_favorite ? 'favorite' : ''}>★</span>
                            <span>
                              <strong>{reply.title}</strong>
                              <small>{getQuickReplyCategoryLabel(reply)}</small>
                            </span>
                            <code>/{reply.shortcut || reply.title.toLowerCase().replace(/\s+/g, '-')}</code>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                <div className="composer-footer">
                  <button
                    type="button"
                    className="composer-helper"
                    onClick={openSlashQuickReplyPicker}
                    disabled={!canTypeMessage}
                    title="Open Quick Replies"
                  >
                    <span className="quick-reply-slash">/</span>
                    <span>Quick reply</span>
                  </button>
                  <button type="submit" disabled={!canSendMessage || !newMessage.trim()}>
                    <span>{isSending ? 'Sending...' : 'Send'}</span>
                    <Icon name="send" size={18} />
                  </button>
                </div>
              </div>
            </form>

            <div className="conversation-action-bar" aria-label="Conversation actions">
              <button type="button" onClick={handleTakeConversation} disabled={!canTakeConversation}>
                <Icon name="take" size={19} /><span>Take</span>
              </button>
              <button type="button" onClick={handleReleaseConversation} disabled={!canReleaseConversation}>
                <Icon name="release" size={19} /><span>Release</span>
              </button>
              <button type="button" onClick={handleArchiveConversation}>
                <Icon name="archive" size={19} />
                <span>{selectedConversation.status === 'archived' ? 'Inbox' : 'Archive'}</span>
              </button>
              <button type="button" className="danger" onClick={openDeleteConfirmation}>
                <Icon name="delete" size={19} /><span>Delete</span>
              </button>
            </div>
          </>
        ) : (
          <div className="no-chat-selected">Select a conversation to start.</div>
        )}
      </main>

      <aside className="future-panel" aria-label="Quick replies panel">
        <div className="future-panel-tabs">
          <span className="active"><Icon name="quick" size={17} />Quick Replies</span>
          <span>AI Assistant</span>
        </div>

        <div className="quick-replies-panel-body">
          <div className="quick-reply-search">
            <Icon name="search" size={18} />
            <input
              value={quickReplySearch}
              onChange={(event) => setQuickReplySearch(event.target.value)}
              placeholder="Search quick replies..."
            />
            {quickReplySearch && (
              <button type="button" onClick={() => setQuickReplySearch('')} aria-label="Clear quick reply search">×</button>
            )}
          </div>

          <div className="quick-reply-categories">
            <button
              type="button"
              className={quickReplyCategoryFilter === 'all' ? 'active' : ''}
              onClick={() => setQuickReplyCategoryFilter('all')}
            >
              All
            </button>
            <button
              type="button"
              className={quickReplyCategoryFilter === 'team' ? 'active' : ''}
              onClick={() => setQuickReplyCategoryFilter('team')}
            >
              Team
            </button>
            <button
              type="button"
              className={quickReplyCategoryFilter === 'mine' ? 'active' : ''}
              onClick={() => setQuickReplyCategoryFilter('mine')}
            >
              My Replies
            </button>
            <button
              type="button"
              className={quickReplyCategoryFilter === 'favorites' ? 'active' : ''}
              onClick={() => setQuickReplyCategoryFilter('favorites')}
            >
              ★ Favorites
            </button>
            {quickReplyCategories.filter((category) => !category.parent_id).map((category) => (
              <button
                type="button"
                key={category.id}
                className={quickReplyCategoryFilter === String(category.id) ? 'active' : ''}
                onClick={() => setQuickReplyCategoryFilter(String(category.id))}
              >
                {category.parent_id ? '↳ ' : ''}{category.name}
              </button>
            ))}
          </div>

          {quickReplyCategories.length > 0 && (
            <div className="quick-reply-panel-folders">
              <div>
                <span>FOLDERS</span>
                <small>{quickReplyCategories.length}</small>
              </div>
              <div>
                {quickReplyCategories.map((category) => (
                  <button
                    type="button"
                    key={category.id}
                    className={`${category.parent_id ? 'child' : ''} ${quickReplyCategoryFilter === String(category.id) ? 'active' : ''}`}
                    onClick={() => setQuickReplyCategoryFilter(String(category.id))}
                  >
                    <span><Icon name="folder" size={15} />{category.name}</span>
                    <strong>
                      {quickReplies.filter(
                        (reply) =>
                          reply.category_id === category.id ||
                          reply.parent_category_id === category.id
                      ).length}
                    </strong>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="quick-reply-section-title">
            <span>QUICK REPLIES</span>
            <small>{filteredQuickReplies.length} saved · drag or click to insert</small>
          </div>

          <div className="quick-reply-list">{renderQuickReplyList()}</div>
        </div>
      </aside>
        </div>
      </div>

      <nav className="mobile-bottom-nav" aria-label="Mobile navigation">
        <button
          type="button"
          className={!isMobileChatOpen && activePage === APP_PAGES.INBOX ? 'active' : ''}
          onClick={() => {
            const showConversationList = () => {
              setActivePage(APP_PAGES.INBOX);
              setIsMobileChatOpen(false);
              setMobileDrawerMode(null);
            };

            if (activePage !== APP_PAGES.INBOX) {
              dismissMobileHistoryLayer(
                showConversationList,
                1,
                MOBILE_HISTORY_LAYERS.PAGE
              );
            } else {
              showConversationList();
            }
          }}
        >
          <Icon name="chat" size={24} /><span>Conversations</span>
        </button>
        <button
          type="button"
          className={activeConversationView === CONVERSATION_VIEWS.INBOX ? 'active' : ''}
          onClick={() => openConversationView(CONVERSATION_VIEWS.INBOX)}
        >
          <span className="mobile-nav-icon-wrap">
            <Icon name="inbox" size={24} />
            {inboxUnreadCount > 0 && <i>{inboxUnreadCount}</i>}
          </span>
          <span>Inbox</span>
        </button>
        <button type="button" onClick={() => openMobileDrawer('quick')}>
          <Icon name="quick" size={25} /><span>Quick Replies</span>
        </button>
        <button type="button" onClick={() => openMobileDrawer('menu')}>
          <Icon name="more" size={26} /><span>More</span>
        </button>
      </nav>

      {mobileDrawerMode && (
        <div className="mobile-drawer-overlay" onClick={closeMobileDrawer}>
          <aside className="mobile-drawer" onClick={(event) => event.stopPropagation()}>
            <div className="mobile-drawer-header">
              <strong>{mobileDrawerMode === 'quick' ? 'Quick Replies' : 'Menu'}</strong>
              <button type="button" onClick={closeMobileDrawer} aria-label="Close">×</button>
            </div>

            {mobileDrawerMode === 'quick' ? (
              <>
                <div className="quick-reply-search mobile">
                  <Icon name="search" size={18} />
                  <input
                    value={quickReplySearch}
                    onChange={(event) => setQuickReplySearch(event.target.value)}
                    placeholder="Search quick replies..."
                  />
                </div>
                <div className="quick-reply-categories mobile">
                  <button
                    type="button"
                    className={quickReplyCategoryFilter === 'all' ? 'active' : ''}
                    onClick={() => setQuickReplyCategoryFilter('all')}
                  >
                    All
                  </button>
                  <button
                    type="button"
                    className={quickReplyCategoryFilter === 'team' ? 'active' : ''}
                    onClick={() => setQuickReplyCategoryFilter('team')}
                  >
                    Team
                  </button>
                  <button
                    type="button"
                    className={quickReplyCategoryFilter === 'mine' ? 'active' : ''}
                    onClick={() => setQuickReplyCategoryFilter('mine')}
                  >
                    My Replies
                  </button>
                  <button
                    type="button"
                    className={quickReplyCategoryFilter === 'favorites' ? 'active' : ''}
                    onClick={() => setQuickReplyCategoryFilter('favorites')}
                  >
                    ★ Favorites
                  </button>
                  {quickReplyCategories.map((category) => (
                    <button
                      type="button"
                      key={category.id}
                      className={quickReplyCategoryFilter === String(category.id) ? 'active' : ''}
                      onClick={() => setQuickReplyCategoryFilter(String(category.id))}
                    >
                      {category.name}
                    </button>
                  ))}
                </div>
                <div className="mobile-quick-reply-list">{renderQuickReplyList()}</div>
              </>
            ) : (
              <div className="mobile-menu-list">
                <button type="button" onClick={() => openConversationView(CONVERSATION_VIEWS.MINE)}>
                  <Icon name="user" />Mine <span>{mineCount || ''}</span>
                </button>
                <button type="button" onClick={() => openConversationView(CONVERSATION_VIEWS.FOLLOW_UP)}>
                  <Icon name="follow" />Follow Up
                </button>
                <button type="button" onClick={() => openConversationView(CONVERSATION_VIEWS.ARCHIVED)}>
                  <Icon name="archive" />Archived
                </button>
                {canCurrentUserViewReports && (
                  <button type="button" onClick={() => {
                    setActivePage(APP_PAGES.REPORTS);
                    setMobileDrawerMode(null);
                    setIsMobileChatOpen(false);
                    replaceMobileHistoryLayer(MOBILE_HISTORY_LAYERS.PAGE);
                  }}>
                    <Icon name="reports" />Reports
                  </button>
                )}
                <button type="button" onClick={() => {
                  setActivePage(APP_PAGES.SETTINGS);
                  setMobileDrawerMode(null);
                  setIsMobileChatOpen(false);
                  replaceMobileHistoryLayer(MOBILE_HISTORY_LAYERS.PAGE);
                }}>
                  <Icon name="settings" />Settings
                </button>
                <button type="button" className="danger" onClick={handleLogout}>
                  <Icon name="logout" />Logout
                </button>
              </div>
            )}
          </aside>
        </div>
      )}

      {showExitConfirm && (
        <div className="exit-confirm-overlay" onClick={handleStayInSendro}>
          <div
            className="exit-confirm-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="exit-sendro-title"
            onClick={(event) => event.stopPropagation()}
          >
            <span className="exit-confirm-mark" aria-hidden="true">S</span>
            <h3 id="exit-sendro-title">Exit Sendro?</h3>
            <p>Are you sure you want to leave Sendro?</p>
            <div className="exit-confirm-actions">
              <button type="button" className="stay" onClick={handleStayInSendro} autoFocus>
                Stay
              </button>
              <button type="button" className="exit" onClick={handleExitSendro}>
                Exit
              </button>
            </div>
          </div>
        </div>
      )}

      {showDeleteConfirm && selectedConversation && (
        <div
          className="delete-confirm-overlay"
          onClick={closeDeleteConfirmation}
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
                onClick={closeDeleteConfirmation}
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
    </div>
  );
}

export default App;
