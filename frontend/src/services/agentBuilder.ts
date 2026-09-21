const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api/agent-builder` : '/api/agent-builder';

export const REDACTED_SENTINEL = '__REDACTED__';

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem('admin_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export class VersionConflictError extends Error {
  current_updated_at: string | null;
  constructor(message: string, current_updated_at: string | null) {
    super(message);
    this.name = 'VersionConflictError';
    this.current_updated_at = current_updated_at;
  }
}

async function apiFetch<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
      ...(opts.headers || {}),
    },
  });
  if (!r.ok) {
    const e = await r.json().catch(() => ({}));
    if (r.status === 409) {
      const detail = (e?.detail || {}) as Record<string, unknown>;
      const msg = (detail.message as string) || 'Version conflict — reload to see the latest.';
      throw new VersionConflictError(msg, (detail.current_updated_at as string) || null);
    }
    throw new Error((typeof e?.detail === 'string' ? e.detail : null) || `Request failed (${r.status})`);
  }
  return r.json();
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CustomAgent {
  id: string;
  slug: string;
  owner_id: number | null;
  name: string;
  description: string;
  category_id: string;
  logo_url: string;
  version: string;
  status: 'draft' | 'testing' | 'deployed' | 'published' | 'archived';
  visibility: 'private' | 'unlisted' | 'public';
  agent_type: string;
  system_prompt: string;
  llm_provider: string;
  llm_model: string;
  temperature: number;
  max_tokens: number;
  tools_config: ToolRef[];
  capabilities: string[];
  example_prompts: string[];
  required_env_keys: string[];
  default_config: Record<string, string>;
  default_config_meta?: Record<string, { is_set: boolean; tail?: string; secret: boolean }>;
  downloads: number;
  rating: number;
  featured: boolean;
  created_at: string;
  updated_at: string;
  published_at: string | null;
}

export interface ToolRef {
  id?: string;
  name: string;
  description: string;
}

export interface ToolDefinition {
  id: string;
  slug: string;
  name: string;
  description: string;
  tool_type: string;
  schema_config: Record<string, unknown>;
  implementation: Record<string, unknown>;
  is_system: boolean;
  created_at: string;
}

export interface AgentVersion {
  id: string;
  agent_id: string;
  version: string;
  system_prompt: string;
  tools_config: unknown;
  llm_config: unknown;
  changelog: string;
  created_at: string;
}

export interface VersionDiffEntry {
  field: string;
  old: unknown;
  new: unknown;
}

export interface Submission {
  id: string;
  agent_id: string;
  submitted_by: number;
  status: 'pending' | 'approved' | 'rejected';
  reviewer_id: number | null;
  review_notes: string;
  submitted_at: string;
  reviewed_at: string | null;
  agent_name?: string;
  agent_description?: string;
  agent_slug?: string;
}

export interface AgentUsageStats {
  window_days: number;
  totals: {
    calls: number;
    input_tokens: number;
    output_tokens: number;
    tool_calls: number;
    errors: number;
    avg_duration_ms: number;
    p50_duration_ms: number;
    p95_duration_ms: number;
    last_call: string | null;
  };
  series: { day: string; calls: number; errors: number; tokens: number }[];
}

// ---------------------------------------------------------------------------
// Agent CRUD
// ---------------------------------------------------------------------------

export async function createAgent(data: Partial<CustomAgent>): Promise<{ success: boolean; agent: CustomAgent }> {
  return apiFetch('/agents', { method: 'POST', body: JSON.stringify(data) });
}

export interface ListAgentsResult {
  success: boolean;
  agents: CustomAgent[];
  total: number;
  limit: number;
  offset: number;
}

export async function listMyAgents(params?: {
  status?: string;
  visibility?: string;
  category_id?: string;
  search?: string;
  limit?: number;
  offset?: number;
}): Promise<ListAgentsResult> {
  const qs = new URLSearchParams();
  if (params?.status) qs.set('status', params.status);
  if (params?.visibility) qs.set('visibility', params.visibility);
  if (params?.category_id) qs.set('category_id', params.category_id);
  if (params?.search) qs.set('search', params.search);
  if (params?.limit != null) qs.set('limit', String(params.limit));
  if (params?.offset != null) qs.set('offset', String(params.offset));
  const q = qs.toString();
  return apiFetch(`/agents${q ? '?' + q : ''}`);
}

export async function getMyAgent(id: string): Promise<{ success: boolean; agent: CustomAgent }> {
  return apiFetch(`/agents/${id}`);
}

export async function updateAgent(
  id: string,
  data: Partial<CustomAgent>,
  ifMatch?: string,
): Promise<{ success: boolean; agent: CustomAgent }> {
  const headers: Record<string, string> = {};
  if (ifMatch) headers['If-Match'] = ifMatch;
  return apiFetch(`/agents/${id}`, { method: 'PUT', body: JSON.stringify(data), headers });
}

export async function deleteAgent(id: string): Promise<{ success: boolean }> {
  return apiFetch(`/agents/${id}`, { method: 'DELETE' });
}

export async function cloneAgent(id: string): Promise<{ success: boolean; agent: CustomAgent }> {
  return apiFetch(`/agents/${id}/clone`, { method: 'POST' });
}

// ---------------------------------------------------------------------------
// Tools
// ---------------------------------------------------------------------------

export async function listTools(): Promise<{ success: boolean; tools: ToolDefinition[] }> {
  return apiFetch('/tools');
}

// ---------------------------------------------------------------------------
// Versions
// ---------------------------------------------------------------------------

export async function listVersions(agentId: string): Promise<{ success: boolean; versions: AgentVersion[] }> {
  return apiFetch(`/agents/${agentId}/versions`);
}

export async function createVersion(agentId: string, changelog = ''): Promise<{ success: boolean; version: AgentVersion }> {
  return apiFetch(`/agents/${agentId}/versions`, { method: 'POST', body: JSON.stringify({ changelog }) });
}

export async function getVersionDiff(
  agentId: string,
  version: string,
): Promise<{ success: boolean; version: string; diff: VersionDiffEntry[] }> {
  return apiFetch(`/agents/${agentId}/versions/${encodeURIComponent(version)}/diff`);
}

export async function rollbackToVersion(
  agentId: string,
  version: string,
): Promise<{ success: boolean; agent: CustomAgent }> {
  return apiFetch(`/agents/${agentId}/rollback`, {
    method: 'POST',
    body: JSON.stringify({ version }),
  });
}

// ---------------------------------------------------------------------------
// Stats
// ---------------------------------------------------------------------------

export async function getAgentStats(
  agentId: string,
  days = 30,
): Promise<{ success: boolean; stats: AgentUsageStats }> {
  return apiFetch(`/agents/${agentId}/stats?days=${days}`);
}

// ---------------------------------------------------------------------------
// Test (playground) — returns SSE stream, abortable
// ---------------------------------------------------------------------------

export async function testAgentStream(
  agentId: string,
  query: string,
  sessionId: string | undefined,
  onEvent: (event: { event: string; data: unknown }) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_BASE}/agents/${agentId}/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ query, session_id: sessionId }),
    signal,
  });
  if (!response.ok) {
    const e = await response.json().catch(() => ({}));
    throw new Error(e.detail || `Test failed (${response.status})`);
  }
  const reader = response.body?.getReader();
  if (!reader) throw new Error('No response body');
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop() || '';
      for (const part of parts) {
        const trimmed = part.trim();
        if (!trimmed.startsWith('data: ')) continue;
        try {
          onEvent(JSON.parse(trimmed.slice(6)));
        } catch {
          // malformed event, skip
        }
      }
    }
    if (buffer.trim().startsWith('data: ')) {
      try {
        onEvent(JSON.parse(buffer.trim().slice(6)));
      } catch {
        // ignore trailing partial
      }
    }
  } finally {
    try {
      reader.releaseLock();
    } catch {
      // ignore release errors
    }
  }
}

// ---------------------------------------------------------------------------
// Deploy & Publish
// ---------------------------------------------------------------------------

export async function clearTestSession(agentId: string, sessionId: string): Promise<{ success: boolean }> {
  return apiFetch(`/agents/${agentId}/test/session?session_id=${encodeURIComponent(sessionId)}`, { method: 'DELETE' });
}

export async function deployAgent(id: string): Promise<{ success: boolean; agent: CustomAgent }> {
  return apiFetch(`/agents/${id}/deploy`, { method: 'POST' });
}

export async function publishAgent(id: string): Promise<{ success: boolean; auto_approved?: boolean; agent?: CustomAgent; submission?: Submission }> {
  return apiFetch(`/agents/${id}/publish`, { method: 'POST' });
}

// ---------------------------------------------------------------------------
// Admin: Review Queue
// ---------------------------------------------------------------------------

export async function listSubmissions(status?: string): Promise<{ success: boolean; submissions: Submission[] }> {
  const q = status ? `?status=${status}` : '';
  return apiFetch(`/submissions${q}`);
}

export async function reviewSubmission(
  submissionId: string,
  approved: boolean,
  notes = '',
): Promise<{ success: boolean; submission: Submission }> {
  return apiFetch(`/submissions/${submissionId}/review`, {
    method: 'POST',
    body: JSON.stringify({ approved, notes }),
  });
}

// ---------------------------------------------------------------------------
// Published agents (marketplace)
// ---------------------------------------------------------------------------

export async function listPublishedAgents(): Promise<{ success: boolean; agents: CustomAgent[] }> {
  return apiFetch('/published');
}
