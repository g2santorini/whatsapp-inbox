import { getToken } from './api';

const BASE = import.meta.env.VITE_API_BASE || '/api';

async function request(path, method = 'GET', payload) {
  const response = await fetch(`${BASE}/tasks${path}`, {
    method,
    credentials: 'include',
    headers: {
      Authorization: `Bearer ${getToken() || ''}`,
      ...(payload !== undefined ? { 'Content-Type': 'application/json' } : {}),
    },
    ...(payload !== undefined ? { body: JSON.stringify(payload) } : {}),
  });
  const json = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(json.detail || `Request failed (${response.status})`);
  return json;
}

export const tasksApi = {
  list: () => request('/'),
  overview: () => request('/overview'),
  team: () => request('/team'),
  create: (data) => request('/standalone', 'POST', data),
  detail: (id) => request(`/standalone/${id}`),
  update: (id, data) => request(`/standalone/${id}`, 'PATCH', data),
  claim: (task) => request(task.kind === 'project' ? `/project/${task.task_id}/claim` : `/standalone/${task.task_id}/claim`, 'POST'),
  release: (task) => request(task.kind === 'project' ? `/project/${task.task_id}/release` : `/standalone/${task.task_id}/release`, 'POST'),
  comment: (id, body) => request(`/standalone/${id}/comments`, 'POST', { body }),
};
