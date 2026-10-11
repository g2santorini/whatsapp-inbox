import { getToken } from './api';

const BASE = import.meta.env.VITE_API_BASE || '/api';

async function request(path, method = 'GET', body) {
  const token = getToken();
  const response = await fetch(`${BASE}/projects${path}`, {
    method,
    credentials: 'include',
    headers: {
      Authorization: `Bearer ${token || ''}`,
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
    },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`);
  }
  return response.json();
}

export const projectApi = {
  list: () => request('/'),
  get: (id) => request(`/${id}`),
  create: (payload) => request('/', 'POST', payload),
  update: (id, payload) => request(`/${id}`, 'PATCH', payload),
  addMember: (id, payload) => request(`/${id}/members`, 'POST', payload),
  removeMember: (id, userId) => request(`/${id}/members/${userId}`, 'DELETE'),
  updateMember: (id, userId, payload) => request(`/${id}/members/${userId}`, 'PATCH', payload),
  addMilestone: (id, payload) => request(`/${id}/milestones`, 'POST', payload),
  renameMilestone: (id, milestoneId, payload) => request(`/${id}/milestones/${milestoneId}`, 'PATCH', payload),
  addTask: (id, payload) => request(`/${id}/tasks`, 'POST', payload),
  updateTask: (id, taskId, payload) => request(`/${id}/tasks/${taskId}`, 'PATCH', payload),
  addComment: (id, taskId, payload) => request(`/${id}/tasks/${taskId}/comments`, 'POST', payload),
};
