const API_BASE = import.meta.env.VITE_API_BASE || '/api';
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

export async function createUser(userData) {
  return apiRequest('/users/', {
    method: 'POST',
    body: JSON.stringify(userData),
  });
}

export async function updateUser(userId, updates) {
  return apiRequest(`/users/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify(updates),
  });
}

export async function resetUserPassword(userId, password) {
  return apiRequest(`/users/${userId}/password`, {
    method: 'PATCH',
    body: JSON.stringify({ password }),
  });
}

export async function getMessageMediaBlob(messageId) {
  const token = getToken();

  const headers = {};

  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}/messages/${messageId}/media`, {
    headers,
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(errorText || `Media request failed with status ${response.status}`);
  }

  return response.blob();
}

export async function getConversations(searchQuery = '') {
  const trimmedSearchQuery = String(searchQuery || '').trim();

  if (!trimmedSearchQuery) {
    return apiRequest('/conversations/');
  }

  const params = new URLSearchParams({
    q: trimmedSearchQuery,
  });

  return apiRequest(`/conversations/?${params.toString()}`);
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

export async function createTemplateConversation({
  contactName,
  contactPhone,
  templateName,
  languageCode,
  variables,
  previewContent,
}) {
  return apiRequest('/conversations/send-template/', {
    method: 'POST',
    body: JSON.stringify({
      contact_name: contactName,
      contact_phone: contactPhone,
      template_name: templateName,
      language_code: languageCode,
      variables,
      preview_content: previewContent,
    }),
  });
}

export async function getMessages(conversationId, options = {}) {
  const params = new URLSearchParams();

  if (options.limit) {
    params.set('limit', String(options.limit));
  }

  if (options.afterId) {
    params.set('after_id', String(options.afterId));
  }

  if (options.beforeId) {
    params.set('before_id', String(options.beforeId));
  }

  const queryString = params.toString();

  return apiRequest(
    `/conversations/${conversationId}/messages/${queryString ? `?${queryString}` : ''}`
  );
}

export async function sendMessage(conversationId, content) {
  return apiRequest(`/conversations/${conversationId}/messages/`, {
    method: 'POST',
    body: JSON.stringify({ content }),
  });
}

export async function sendMessageReaction(messageId, emoji) {
  return apiRequest(`/messages/${messageId}/reaction/`, {
    method: 'POST',
    body: JSON.stringify({ emoji }),
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

export async function closeConversation(conversationId) {
  return apiRequest(`/conversations/${conversationId}/close/`, {
    method: 'POST',
  });
}

export async function archiveConversation(conversationId) {
  return apiRequest(`/conversations/${conversationId}/archive/`, {
    method: 'POST',
  });
}

export async function unarchiveConversation(conversationId) {
  return apiRequest(`/conversations/${conversationId}/unarchive/`, {
    method: 'POST',
  });
}

export async function deleteConversation(conversationId) {
  return apiRequest(`/conversations/${conversationId}/`, {
    method: 'DELETE',
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

export async function updateConversationFollowUp(conversationId, followUp) {
  return apiRequest(`/conversations/${conversationId}/follow-up`, {
    method: 'PATCH',
    body: JSON.stringify({
      follow_up: followUp,
    }),
  });
}

export async function getTemplateReportItems(filters = {}) {
  const params = new URLSearchParams();

  const allowedFilters = [
    'operation_date',
    'date_from',
    'date_to',
    'option_code',
    'status',
    'whatsapp_status',
    'time_slot',
    'result_status',
    'q',
    'limit',
    'offset',
  ];

  allowedFilters.forEach((key) => {
    const value = filters[key];

    if (value !== undefined && value !== null && String(value).trim() !== '') {
      params.append(key, String(value).trim());
    }
  });

  if (filters.problems_only === true) {
    params.append('problems_only', 'true');
  }

  const queryString = params.toString();

  if (!queryString) {
    return apiRequest('/template-report-items/');
  }

  return apiRequest(`/template-report-items/?${queryString}`);
}