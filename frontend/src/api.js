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
    credentials: 'include',
  });

  if (!response.ok) {
    const errorText = await response.text();
    const requestError = new Error(
      errorText || `Request failed with status ${response.status}`
    );
    requestError.status = response.status;
    requestError.retryAfter = Number(response.headers.get('Retry-After')) || 0;
    throw requestError;
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

  if (data.access_token) {
    saveToken(data.access_token);
  }

  return data;
}

export async function verifyMfaLogin(challengeToken, code, trustDevice = false) {
  const data = await apiRequest('/token/mfa', {
    method: 'POST',
    body: JSON.stringify({
      challenge_token: challengeToken,
      code,
      trust_device: Boolean(trustDevice),
    }),
  });

  saveToken(data.access_token);
  return data;
}

export async function startMfaSetup() {
  return apiRequest('/users/me/mfa/setup', {
    method: 'POST',
  });
}

export async function confirmMfaSetup(code) {
  return apiRequest('/users/me/mfa/confirm', {
    method: 'POST',
    body: JSON.stringify({ code }),
  });
}

export async function getCurrentUser() {
  return apiRequest('/users/me/');
}

export async function updateMyPreferences(preferences) {
  return apiRequest('/users/me/preferences', {
    method: 'PATCH',
    body: JSON.stringify(preferences),
  });
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

export async function resetUserMfa(userId) {
  return apiRequest(`/users/${userId}/mfa/reset`, {
    method: 'POST',
  });
}

export async function revokeUserSessions(userId) {
  return apiRequest(`/users/${userId}/sessions/revoke`, {
    method: 'POST',
  });
}

export async function changeMyPassword(currentPassword, newPassword) {
  return apiRequest('/users/me/password', {
    method: 'PATCH',
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });
}

export async function getQuickReplyCategories() {
  return apiRequest('/quick-reply-categories/');
}

export async function createQuickReplyCategory(categoryData) {
  return apiRequest('/quick-reply-categories/', {
    method: 'POST',
    body: JSON.stringify(categoryData),
  });
}

export async function updateQuickReplyCategory(categoryId, updates) {
  return apiRequest(`/quick-reply-categories/${categoryId}`, {
    method: 'PATCH',
    body: JSON.stringify(updates),
  });
}

export async function deleteQuickReplyCategory(categoryId) {
  return apiRequest(`/quick-reply-categories/${categoryId}`, {
    method: 'DELETE',
  });
}

export async function getQuickReplies(filters = {}) {
  const params = new URLSearchParams();

  if (filters.q && String(filters.q).trim()) {
    params.set('q', String(filters.q).trim());
  }

  if (filters.categoryId !== undefined && filters.categoryId !== null) {
    params.set('category_id', String(filters.categoryId));
  }

  if (filters.favoritesOnly) {
    params.set('favorites_only', 'true');
  }

  const queryString = params.toString();
  return apiRequest(`/quick-replies/${queryString ? `?${queryString}` : ''}`);
}

export async function createQuickReply(quickReplyData) {
  return apiRequest('/quick-replies/', {
    method: 'POST',
    body: JSON.stringify(quickReplyData),
  });
}

export async function updateQuickReply(quickReplyId, updates) {
  return apiRequest(`/quick-replies/${quickReplyId}`, {
    method: 'PATCH',
    body: JSON.stringify(updates),
  });
}

export async function deleteQuickReply(quickReplyId) {
  return apiRequest(`/quick-replies/${quickReplyId}`, {
    method: 'DELETE',
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

export async function getConversations(options = {}) {
  const normalizedOptions =
    typeof options === 'string' ? { searchQuery: options } : options;

  const params = new URLSearchParams();
  const trimmedSearchQuery = String(normalizedOptions.searchQuery || '').trim();

  if (trimmedSearchQuery) {
    params.set('q', trimmedSearchQuery);
  }

  if (normalizedOptions.view) {
    params.set('view', String(normalizedOptions.view));
  }

  if (normalizedOptions.limit) {
    params.set('limit', String(normalizedOptions.limit));
  }

  if (normalizedOptions.offset) {
    params.set('offset', String(normalizedOptions.offset));
  }

  const queryString = params.toString();

  return apiRequest(`/conversations/${queryString ? `?${queryString}` : ''}`, {
    signal: normalizedOptions.signal,
  });
}

// Instagram uses separate tenant-scoped, GET-only APIs. The WhatsApp polling
// and send paths remain unchanged. Do not add automatic Instagram polling yet.
export async function getInstagramTenants(options = {}) {
  return apiRequest('/channels/instagram/tenants', {
    signal: options.signal,
  });
}

export async function getInstagramConversations(tenantId, options = {}) {
  const params = new URLSearchParams({
    tenant_id: String(tenantId),
    limit: String(options.limit || 50),
  });
  return apiRequest(`/channels/instagram/conversations?${params}`, {
    signal: options.signal,
  });
}

export async function getInstagramMessages(tenantId, conversationId, options = {}) {
  const params = new URLSearchParams({
    tenant_id: String(tenantId),
    limit: String(options.limit || 50),
  });
  if (options.beforeId) params.set('before_id', String(options.beforeId));
  return apiRequest(
    `/channels/instagram/conversations/${encodeURIComponent(conversationId)}/messages?${params}`,
    { signal: options.signal }
  );
}

export async function getWhatsAppLivePanel(options = {}) {
  return apiRequest('/conversations/live-panel/', { signal: options.signal });
}

export async function getConversationSummary(options = {}) {
  return apiRequest('/conversations/summary/', {
    signal: options.signal,
  });
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
    `/conversations/${conversationId}/messages/${queryString ? `?${queryString}` : ''}`,
    {
      signal: options.signal,
    }
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

export async function archiveOldConversations({
  hours = 36,
  dryRun = true,
  limit = 200,
} = {}) {
  const params = new URLSearchParams({
    hours: String(hours),
    dry_run: dryRun ? 'true' : 'false',
    limit: String(limit),
  });

  return apiRequest(`/conversations/archive-old/?${params.toString()}`, {
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


// GET-only staging GDPR preview. The server enforces MFA and tenant isolation.
export async function getPrivacyTenants(options = {}) {
  return apiRequest('/privacy/requests/tenants', { signal: options.signal });
}

export async function getPrivacyCases(tenantId, options = {}) {
  const query = new URLSearchParams({ tenant_id: String(tenantId), limit: '50', offset: '0' });
  return apiRequest(`/privacy/requests?${query}`, { signal: options.signal });
}

export async function getPrivacyCase(tenantId, caseRef, options = {}) {
  const query = new URLSearchParams({ tenant_id: String(tenantId) });
  return apiRequest(`/privacy/requests/${encodeURIComponent(caseRef)}?${query}`, {
    signal: options.signal,
  });
}


// Optional staging-only manual GDPR workflow. These endpoints are not mounted
// unless a separate reviewed write gate is explicitly enabled on staging.
export async function getPrivacyWorkflowStatus(options = {}) {
  return apiRequest('/privacy/workflow', { signal: options.signal });
}

// Non-mutating subject count inspection. POST keeps IDs out of URL logs.
// This does not save a case link, reveal message text or delete any records.
export async function previewPrivacyConversation(tenantId, ref, platform, conversationId) {
  return apiRequest(`/privacy/requests/${encodeURIComponent(ref)}/subject-preview`, {
    method: 'POST',
    body: JSON.stringify({ tenant_id: tenantId, platform, conversation_id: conversationId }),
  });
}

export async function createPrivacyRequest(tenantId, channel) {
  return apiRequest('/privacy/requests', {
    method: 'POST',
    body: JSON.stringify({ tenant_id: tenantId, channel }),
  });
}

export async function verifyPrivacyIdentity(tenantId, ref) {
  const params = new URLSearchParams({ tenant_id: String(tenantId) });
  return apiRequest(`/privacy/requests/${encodeURIComponent(ref)}/identity-check?${params}`, {
    method: 'POST',
    body: JSON.stringify({ externally_confirmed: true }),
  });
}

export async function reviewPrivacyScope(tenantId, ref, evidence) {
  const params = new URLSearchParams({ tenant_id: String(tenantId) });
  return apiRequest(`/privacy/requests/${encodeURIComponent(ref)}/scope-review?${params}`, {
    method: 'POST',
    body: JSON.stringify(evidence),
  });
}

export async function recordPrivacyResponse(tenantId, ref) {
  const params = new URLSearchParams({ tenant_id: String(tenantId) });
  return apiRequest(`/privacy/requests/${encodeURIComponent(ref)}/response?${params}`, {
    method: 'POST',
    body: JSON.stringify({ externally_confirmed: true }),
  });
}
