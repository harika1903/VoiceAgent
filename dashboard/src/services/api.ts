import type {
  Agent,
  AgentSpec,
  ApiKeyItem,
  CallHistoryResponse,
  KBDocument,
  KBSearchResponse,
  KBStats,
  OrgProfile,
  SessionState,
  StartCallResponse,
  TranscriptResponse,
  UsageSummary,
} from '../types';

export * from '../types';

const API_BASE = '';

function getApiKey(): string {
  return localStorage.getItem('va_api_key') || '';
}

export function setApiKey(key: string) {
  localStorage.setItem('va_api_key', key);
}

export function clearApiKey() {
  localStorage.removeItem('va_api_key');
}

export function hasApiKey(): boolean {
  return !!getApiKey();
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const key = getApiKey();
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Authorization': `Bearer ${key}`,
      'Content-Type': 'application/json',
      ...options.headers,
    },
  });
  if (res.status === 401) {
    clearApiKey();
    window.location.href = '/dashboard/login';
    throw new Error('Unauthorized');
  }
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

// ── Agents ───────────────────────────────────────────────────────────────

export const agents = {
  list: () => request<Agent[]>('/v1/agents'),
  get: (id: string) => request<Agent>(`/v1/agents/${id}`),
  create: (id: string, spec: AgentSpec) => request<Agent>(`/v1/agents/${id}`, { method: 'POST', body: JSON.stringify(spec) }),
  update: (id: string, spec: AgentSpec) => request<Agent>(`/v1/agents/${id}`, { method: 'PUT', body: JSON.stringify(spec) }),
  delete: (id: string) => request<void>(`/v1/agents/${id}`, { method: 'DELETE' }),
};

// ── Calls ────────────────────────────────────────────────────────────────

export const calls = {
  list: (params: { limit?: number; offset?: number; agent_id?: string; status?: string } = {}) => {
    const q = new URLSearchParams();
    if (params.limit) q.set('limit', String(params.limit));
    if (params.offset) q.set('offset', String(params.offset));
    if (params.agent_id) q.set('agent_id', params.agent_id);
    if (params.status) q.set('status', params.status);
    return request<CallHistoryResponse>(`/v1/calls?${q}`);
  },
  get: (id: string) => request<SessionState>(`/v1/calls/${id}`),
  transcript: (id: string) => request<TranscriptResponse>(`/v1/calls/${id}/transcript`),
  startWeb: (agentId: string) => request<StartCallResponse>('/v1/calls/web', { method: 'POST', body: JSON.stringify({ agent_id: agentId }) }),
  end: (id: string) => request<{ ok: boolean }>(`/v1/calls/${id}/end`, { method: 'POST', body: JSON.stringify({ reason: 'admin_stop' }) }),
};

// ── Knowledge Base ───────────────────────────────────────────────────────

export const kb = {
  list: () => request<KBDocument[]>('/v1/kb/documents'),
  upload: (documents: { id: string; text: string; metadata?: Record<string, unknown> }[]) =>
    request<{ added: number; total: number }>('/v1/kb/documents', { method: 'POST', body: JSON.stringify({ documents }) }),
  delete: (docId: string) => request<{ deleted: boolean }>(`/v1/kb/documents/${docId}`, { method: 'DELETE' }),
  search: (q: string, topK = 3) => request<KBSearchResponse>(`/v1/kb/search?q=${encodeURIComponent(q)}&top_k=${topK}`),
  stats: () => request<KBStats>('/v1/kb/stats'),
};

// ── Settings ─────────────────────────────────────────────────────────────

export const settings = {
  listKeys: () => request<{ keys: ApiKeyItem[] }>('/v1/keys'),
  createKey: (label: string) => request<{ id: number; label: string; raw_key: string; created_at: string }>('/v1/keys', { method: 'POST', body: JSON.stringify({ label }) }),
  revokeKey: (id: number) => request<{ ok: boolean }>(`/v1/keys/${id}`, { method: 'DELETE' }),
  getOrg: () => request<OrgProfile>('/v1/org'),
  updateOrg: (name: string) => request<OrgProfile>('/v1/org', { method: 'PUT', body: JSON.stringify({ name }) }),
  usage: (days = 30) => request<UsageSummary>(`/v1/usage/summary?days=${days}`),
};
