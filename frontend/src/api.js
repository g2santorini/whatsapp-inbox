const API_BASE = '/api';
const TOKEN_KEY = 'sendro_access_token';
const OLD_TOKEN_KEY = 'whinly_access_token';

export function getToken() {
  const sendroToken = localStorage.getItem(TOKEN_KEY);

  if (sendroToken) {
    return sendroToken;
  }

  const oldToken = localStorage.getItem(OLD_TOKEN_KEY);

  if (oldToken) {
    localStorage.setItem(TOKEN_KEY, oldToken);
    localStorage.removeItem(OLD_TOKEN_KEY);
    return oldToken;
  }

  return null;
}

export function saveToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.removeItem(OLD_TOKEN_KEY);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(OLD_TOKEN_KEY);
}

async function apiRequest(path, options = {}) {
  const token = getToken();

  const headers = {
    ...(options.headers || {}),
  };

  if (options.body && !(options.body instanceof URLSearchParams)) {
    headers['Content-Type'] = 'application/json';
  }

  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(errorText || `Request failed with status ${response.status}`);
  }

  return response.json();
}

export async function login(username, password) {
  const formData = new URLSearchParams();
  formData.append('username', username);
  formData.append('password', password);

  const data = await apiRequest('/token', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body: formData,
  });

  saveToken(data.access_token);
  return data;
}

export async function getCurrentUser() {
  return apiRequest('/users/me/');
}

export async function getUsers() {
  return apiRequest('/users/');
}

export async function getConversations() {
  return apiRequest('/conversations/');
}

export async function createConversation(contactName, contactPhone) {
  return apiRequest('/conversations/', {
    method: 'POST',
    body: JSON.stringify({
      contact_name: contactName,
      contact_phone: contactPhone,
    }),
  });
}

export async function getMessages(conversationId) {
  return apiRequest(`/conversations/${conversationId}/messages/`);
}

export async function sendMessage(conversationId, content) {
  return apiRequest(`/conversations/${conversationId}/messages/`, {
    method: 'POST',
    body: JSON.stringify({ content }),
  });
}

export async function takeConversation(conversationId) {
  return apiRequest(`/conversations/${conversationId}/take/`, {
    method: 'POST',
  });
}

export async function releaseConversation(conversationId) {
  return apiRequest(`/conversations/${conversationId}/release/`, {
    method: 'POST',
  });
}

export async function markConversationAsRead(conversationId) {
  return apiRequest(`/conversations/${conversationId}/mark-as-read/`, {
    method: 'POST',
  });
}

export async function simulateInboundMessage(conversationId, content) {
  return apiRequest(`/conversations/${conversationId}/simulate-inbound/`, {
    method: 'POST',
    body: JSON.stringify({ content }),
  });
}