const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

// ===================== SSE Streaming Types =====================

export interface SSEEvent {
  event: 'start' | 'thinking' | 'routing' | 'response_chunk' | 'progress' | 'done' | 'error' | 'heartbeat' | 'browser_screenshot' | 'ppt_slide_snapshot';
  data: any;
}

/** Bounding boxes in viewport pixels (same space as the JPEG screenshot). */
export interface BrowserScreenshotOverlay {
  kind: string;
  label?: string | null;
  x: number;
  y: number;
  width: number;
  height: number;
}

/** PPT Generator Agent: streamed SVG preview per slide as it is authored */
export interface PptSlideSnapshotEvent {
  slide_index: number;
  slide_type?: string;
  title?: string;
  image: string;
  mime: string;
}

export interface BrowserScreenshotEvent {
  step: number | string;
  status: 'success' | 'error' | string;
  image: string;
  mime: string;
  /** Viewport size when the screenshot was taken (for debugging / future use). */
  viewport?: { width: number; height: number };
  /** Highlights for elements the agent clicked, filled, hovered, or selected. */
  overlays?: BrowserScreenshotOverlay[];
}

/** Optional fields on response_chunk SSE payloads (e.g. BRD agent: reset before final markdown). */
export interface ResponseChunkMeta {
  chunk?: string;
  reset?: boolean;
  phase?: string;
}

export interface StreamCallbacks {
  onStart?: (data: { agent: string; timestamp: string }) => void;
  onThinking?: (step: ThinkingStep) => void;
  onRouting?: (data: { agent_id: string; agent_name: string; confidence: number; reasoning: string }) => void;
  onResponseChunk?: (chunk: string, meta?: ResponseChunkMeta) => void;
  onProgress?: (data: { stage: string; message: string; percent?: number }) => void;
  onDone?: (data: any) => void;
  onError?: (error: { message: string }) => void;
  onBrowserScreenshot?: (data: BrowserScreenshotEvent) => void;
  onPptSlideSnapshot?: (data: PptSlideSnapshotEvent) => void;
}

function _parseSSEBuffer(buffer: string, callbacks: StreamCallbacks): string {
  const parts = buffer.split('\n\n');
  const remainder = parts.pop() || '';
  for (const part of parts) {
    const trimmed = part.trim();
    if (!trimmed.startsWith('data: ')) continue;
    try {
      const parsed: SSEEvent = JSON.parse(trimmed.slice(6));
      switch (parsed.event) {
        case 'start': callbacks.onStart?.(parsed.data); break;
        case 'thinking': callbacks.onThinking?.(parsed.data); break;
        case 'routing': callbacks.onRouting?.(parsed.data); break;
        case 'response_chunk': {
          const d = parsed.data as ResponseChunkMeta;
          const ch = typeof d?.chunk === 'string' ? d.chunk : '';
          callbacks.onResponseChunk?.(ch, d);
          break;
        }
        case 'progress': callbacks.onProgress?.(parsed.data); break;
        case 'done': callbacks.onDone?.(parsed.data); break;
        case 'error': callbacks.onError?.(parsed.data); break;
        case 'browser_screenshot': callbacks.onBrowserScreenshot?.(parsed.data); break;
        case 'ppt_slide_snapshot': callbacks.onPptSlideSnapshot?.(parsed.data); break;
      }
    } catch (e) {
      console.warn('[SSE] Parse error:', e);
    }
  }
  return remainder;
}

const STREAM_CONNECT_TIMEOUT_MS = 30_000;
/** Default max time without any SSE bytes before the reader is cancelled (must exceed single slow LLM turns). */
const STREAM_READ_IDLE_TIMEOUT_MS = 300_000;

export async function streamFromEndpoint(
  endpoint: string,
  body: object,
  callbacks: StreamCallbacks,
  headers?: Record<string, string>,
  readIdleTimeoutMs: number = STREAM_READ_IDLE_TIMEOUT_MS,
): Promise<void> {
  const token = typeof localStorage !== 'undefined' ? localStorage.getItem('admin_token') : null;

  const connectController = new AbortController();
  const connectTimer = setTimeout(() => connectController.abort(), STREAM_CONNECT_TIMEOUT_MS);

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${endpoint}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
      body: JSON.stringify(body),
      signal: connectController.signal,
    });
  } catch (err: any) {
    if (err.name === 'AbortError') {
      throw new Error('Server is not responding. Please check that the backend is running.');
    }
    throw new Error(
      err.message?.includes('Failed to fetch') || err.message?.includes('NetworkError')
        ? 'Cannot reach the server. Please check that the backend is running.'
        : err.message,
    );
  } finally {
    clearTimeout(connectTimer);
  }

  if (!response.ok) {
    const errText = await response.text().catch(() => '');
    throw new Error(`Request failed (${response.status}): ${errText}`);
  }

  const reader = response.body?.getReader();
  if (!reader) throw new Error('No response body');

  const decoder = new TextDecoder();
  let buffer = '';
  let idleTimer: ReturnType<typeof setTimeout> | null = null;

  const resetIdleTimer = () => {
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = setTimeout(() => reader.cancel(), readIdleTimeoutMs);
  };

  try {
    resetIdleTimer();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      resetIdleTimer();
      buffer += decoder.decode(value, { stream: true });
      buffer = _parseSSEBuffer(buffer, callbacks);
    }

    if (buffer.trim()) {
      _parseSSEBuffer(buffer + '\n\n', callbacks);
    }
  } finally {
    if (idleTimer) clearTimeout(idleTimer);
  }
}

export async function chatWithAgentStream(
  agent: Agent,
  query: string,
  options: {
    sessionId?: string;
    contextData?: any;
    clearHistory?: boolean;
    fileContent?: string;
    fileType?: string;
    fileName?: string;
    emailRecipients?: string[];
    githubToken?: string;
    mongodbUri?: string;
    rawText?: string;
    collectionName?: string;
    /** SQL DB Agent: include generated SQL in the assistant reply */
    showSql?: boolean;
    /** ETL Agent: inline data (CSV/JSON/TSV) to transform */
    dataSource?: string;
    /** ETL Agent: format hint for data_source ("csv", "json", "tsv") */
    dataFormat?: string;
    userConfig?: Record<string, string>;
    /** Override SSE read idle timeout (ms). PPT generator uses a long default when unset. */
    streamReadIdleTimeoutMs?: number;
    /** Browser Automation Agent: override headless mode (visible vs headless Chromium) */
    headless?: boolean;
    /** Browser Automation Agent: CDP URL e.g. http://127.0.0.1:9222 (Chrome --remote-debugging-port=9222) */
    cdpEndpoint?: string;
    /** Browser Automation Agent: save cookies to disk (default on server); ignored when CDP is used */
    rememberLogins?: boolean;
    /** Browser Automation Agent: reuse the same browser tab for this chat session across messages */
    keepBrowserSession?: boolean;
    /** Browser Automation Agent: optional absolute path for saved profile (rarely needed) */
    persistentProfileDir?: string;
    /** Browser Automation Agent: run exported Playwright Python only (skips LLM planning) */
    rerunStandaloneScript?: string;
    /** When present with dsl_bundle data, server replays in-browser (screenshots + HTML report) instead of subprocess-only */
    replayStepsExecuted?: Record<string, unknown>[];
    /** WebMCP Agent: local bridge base URL (http://127.0.0.1:3847) */
    webmcpBridgeUrl?: string;
    /** WebMCP Agent: bearer token shared with the bridge + Chrome extension */
    webmcpBridgeToken?: string;
    /** WebMCP Agent: optional hostname allowlist */
    webmcpAllowedHosts?: string[];
    /** WebMCP Agent: require non-empty allowlist */
    webmcpRequireHostAllowlist?: boolean;
    webmcpMaxSteps?: number;
    webmcpBridgeTimeoutSec?: number;
    webmcpWallTimeSec?: number;
  } | undefined,
  callbacks: StreamCallbacks,
): Promise<void> {
  if (agent.external_api_url) {
    const body: any = {
      query,
      agent_id: agent.id,
    };
    if (options?.sessionId) body.session_id = options.sessionId;
    if (options?.userConfig !== undefined) body.user_config = options.userConfig;
    return streamFromEndpoint(
      '/external-agent',
      body,
      callbacks,
      undefined,
      options?.streamReadIdleTimeoutMs ?? STREAM_READ_IDLE_TIMEOUT_MS,
    );
  }

  const rawEndpoint = agent.usage?.api_endpoint || '';
  if (!rawEndpoint) {
    callbacks.onError?.({ message: 'Agent endpoint not configured. Please check agent settings.' });
    return;
  }
  const parts = rawEndpoint.split(' ');
  const endpointPath = (parts.length > 1 ? parts[1] : parts[0]).replace('/api', '');
  /** Align with server `PPT_AGENT_STREAM_TIMEOUT_SEC` (default 1200s): long gaps between SSE chunks during slide LLM turns. */
  const pptStreamReadIdleMs = 1_200_000;
  const streamReadIdle =
    options?.streamReadIdleTimeoutMs ??
    (endpointPath === '/ppt-generator' ? pptStreamReadIdleMs : STREAM_READ_IDLE_TIMEOUT_MS);
  const body: any = { query };
  if (options?.sessionId) body.session_id = options.sessionId;
  if (options?.contextData) body.context_data = options.contextData;
  if (options?.clearHistory !== undefined) body.clear_history = options.clearHistory;
  if (options?.fileContent) body.file_content = options.fileContent;
  if (options?.fileType) body.file_type = options.fileType;
  if (options?.fileName) body.file_name = options.fileName;
  if (options?.emailRecipients?.length) body.email_recipients = options.emailRecipients;
  if (options?.githubToken) body.github_token = options.githubToken;
  if (options?.mongodbUri) body.mongodb_uri = options.mongodbUri;
  if (options?.rawText) body.raw_text = options.rawText;
  if (options?.collectionName) body.collection_name = options.collectionName;
  if (options?.showSql !== undefined) body.show_sql = options.showSql;
  if (options?.dataSource) body.data_source = options.dataSource;
  if (options?.dataFormat) body.data_format = options.dataFormat;

  if (endpointPath === '/browser-agent' && options?.rerunStandaloneScript) {
    body.rerun_standalone_script = options.rerunStandaloneScript;
    if (options.replayStepsExecuted && options.replayStepsExecuted.length > 0) {
      body.replay_steps_executed = options.replayStepsExecuted;
    }
  }

  if (endpointPath === '/browser-agent' && options?.cdpEndpoint?.trim()) {
    body.cdp_endpoint = options.cdpEndpoint.trim();
  }

  if (endpointPath === '/browser-agent') {
    if (options?.rememberLogins !== undefined) {
      body.remember_logins = options.rememberLogins;
    }
    if (options?.keepBrowserSession !== undefined) {
      body.keep_browser_session = options.keepBrowserSession;
    }
    if (options?.persistentProfileDir?.trim()) {
      body.persistent_profile_dir = options.persistentProfileDir.trim();
    }
  }

  if (endpointPath === '/browser-agent' && options?.userConfig) {
    const uc = { ...options.userConfig };
    const raw = uc.BROWSER_HEADLESS?.trim().toLowerCase() ?? '';
    if (options.headless !== undefined) {
      body.headless = options.headless;
    } else if (raw) {
      body.headless = raw === 'true' || raw === '1' || raw === 'yes';
    }
    delete uc.BROWSER_HEADLESS;
    body.user_config = uc;
  } else if (endpointPath === '/browser-agent' && options?.headless !== undefined) {
    body.headless = options.headless;
  } else if (options?.userConfig !== undefined) {
    body.user_config = options.userConfig;
  }

  if (endpointPath === '/webmcp-agent') {
    body.bridge_base_url = (options?.webmcpBridgeUrl ?? '').trim();
    body.bridge_token = (options?.webmcpBridgeToken ?? '').trim();
    if (options?.webmcpAllowedHosts?.length) body.allowed_hosts = options.webmcpAllowedHosts;
    if (options?.webmcpRequireHostAllowlist !== undefined) {
      body.require_host_allowlist = options.webmcpRequireHostAllowlist;
    }
    if (options?.webmcpMaxSteps !== undefined) body.max_steps = options.webmcpMaxSteps;
    if (options?.webmcpBridgeTimeoutSec !== undefined) {
      body.bridge_timeout_sec = options.webmcpBridgeTimeoutSec;
    }
    if (options?.webmcpWallTimeSec !== undefined) body.wall_time_sec = options.webmcpWallTimeSec;
  }

  return streamFromEndpoint(endpointPath, body, callbacks, undefined, streamReadIdle);
}

export async function pingWebmcpBridge(body: {
  bridge_base_url: string;
  bridge_token: string;
}): Promise<{ ok: boolean; error?: string; health?: unknown; session?: unknown; tool_count?: number }> {
  const token = typeof localStorage !== 'undefined' ? localStorage.getItem('admin_token') : null;
  const res = await fetch(`${API_BASE}/webmcp-agent/bridge-ping`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    return { ok: false, error: (data as { detail?: string }).detail || res.statusText || 'Request failed' };
  }
  return data as { ok: boolean; error?: string; health?: unknown; session?: unknown; tool_count?: number };
}

export async function streamGlobalChat(
  body: {
    query: string;
    session_id?: string;
    skip_save?: boolean;
    target_agent?: string;
    github_token?: string;
    file_content?: string;
    file_type?: string;
    file_name?: string;
  },
  callbacks: StreamCallbacks,
): Promise<void> {
  return streamFromEndpoint('/global-chat', body, callbacks);
}

export async function streamMongoRAG(
  body: Record<string, any>,
  callbacks: StreamCallbacks,
): Promise<void> {
  return streamFromEndpoint('/mongodb-rag', body, callbacks);
}

// ===================== Types =====================

export interface Agent {
  id: string;
  name: string;
  type: string;
  category: string;
  status: string;
  admin_only?: boolean;
  autonomy_quotient: number;
  description: string;
  logo: string;
  version: string;
  path: string;
  capabilities: string[];
  /** Optional Mermaid source for the agent detail “Architecture” panel (catalog-driven). */
  architecture_diagram_mermaid?: string;
  tools: Array<{
    name: string;
    description: string;
    module: string;
  }>;
  llm_providers: Array<{
    name: string;
    type: string;
    default: boolean;
    cost: string;
    description: string;
    models: string[];
  }>;
  configuration?: {
    env_file?: string;
    required_settings?: Array<{
      key: string;
      description: string;
      default?: string;
      required?: boolean;
    }>;
    optional_settings?: Array<{
      key: string;
      description: string;
      default?: string;
      example?: string;
      control?: 'boolean' | 'choice' | 'select';
      options?: Array<{ value: string; label: string }>;
    }>;
    environment_variables?: Array<{
      name: string;
      description: string;
      required?: boolean;
    }>;
  };
  usage: {
    entry_point: string;
    class_name: string;
    initialization?: string;
    example_prompts: string[];
    api_endpoint: string;
    setup_steps?: string[];
  };
  import_config?: {
    module: string;
    instance_name?: string;
    class_name?: string;
    type: 'instance' | 'class' | 'function';
  };
  routing?: {
    keywords: string[];
    is_fallback?: boolean;
    confidence: number;
  };
  invocation?: {
    method: string;
    params: Record<string, string>;
    is_async: boolean;
    result_path: string[];
    has_model_dump?: boolean;
    requires_github_session?: boolean;
  };
  default_config?: Record<string, string>;
  server_configured_keys?: string[];
  external_api_url?: string;
  external_payload_template?: string;
  external_payload_format?: 'json' | 'form_data';
  external_headers?: Record<string, string>;
  external_method?: string;
}

export interface Category {
  id: string;
  name: string;
  description: string;
  icon: string;
  order: number;
}

export interface AgentsCatalog {
  metadata: {
    version: string;
    last_updated: string;
    total_agents: number;
    /** Optional Tailwind-style scale (50–900 hex). Drives UI --color-primary-* via App bootstrap. */
    primary_colors?: Record<string, string>;
  };
  categories: Category[];
  agents: Agent[];
}

export interface ThinkingStep {
  type: 'thinking' | 'tool' | 'tool_call' | 'tool_result' | 'observation' | 'action' | 'info' | 'llm_call' | 'llm_response';
  content: string;
  tool_name?: string;
  tool_input?: string;
  /** LLM trace (from server-side activity stream) */
  model?: string;
  provider?: string;
  prompt_length?: number;
  response_length?: number;
  truncated?: boolean;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  thinking_steps?: ThinkingStep[];
}

export interface ChatResponse {
  success: boolean;
  query: string;
  response: string;
  timestamp: string;
  tickets?: any[];
  state?: string;
  session_id?: string;
  thinking_steps?: ThinkingStep[];
  sandbox_port?: number;
  sandbox_url?: string;
  stackblitz_repo?: string;
}

export async function getAgents(): Promise<AgentsCatalog> {
  const token = localStorage.getItem('admin_token');
  const response = await fetch(`${API_BASE}/agents`, {
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (!response.ok) {
    throw new Error('Failed to fetch agents');
  }
  return response.json();
}

export async function getAgentById(id: string): Promise<Agent> {
  const token = localStorage.getItem('admin_token');
  const response = await fetch(`${API_BASE}/agents/${id}`, {
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (!response.ok) {
    if (response.status === 403) {
      throw new Error('You do not have access to this agent.');
    }
    throw new Error('Failed to fetch agent');
  }
  return response.json();
}

export async function getHealth(): Promise<any> {
  const response = await fetch(`${API_BASE}/health`);
  if (!response.ok) {
    throw new Error('Health check failed');
  }
  return response.json();
}


export interface BPMNChatResponse extends ChatResponse {
  bpmn_xml?: string;
}

export interface GitHubRepoResponse extends ChatResponse {
  requires_token?: boolean;
  repo_url?: string;
  architecture_diagram?: string;
  task_id?: string;
}

export interface TaskStatusResponse {
  task_id: string;
  status: 'running' | 'completed' | 'not_found';
  progress: string;
  thinking_steps: ThinkingStep[];
  response?: string;
  success?: boolean;
}

export interface ResearchSource {
  title: string;
  url: string;
  snippet: string;
}

export interface MarketResearchResponse extends ChatResponse {
  sources?: ResearchSource[];
  email_sent?: boolean;
  email_recipients?: string[];
  tool_results?: Array<{
    tool: string;
    input: any;
    status: string;
    result?: any;
  }>;
}


export async function pollTaskStatus(taskId: string): Promise<TaskStatusResponse> {
  const response = await fetch(`${API_BASE}/unit-test/task/${taskId}`);
  if (!response.ok) {
    throw new Error('Failed to fetch task status');
  }
  return response.json();
}

export interface CostSummary {
  totals: { total_events: number; total_cost: number; total_prompt_tokens: number; total_completion_tokens: number; total_tokens: number };
  today: { total_events: number; total_cost: number; total_prompt_tokens: number; total_completion_tokens: number; total_tokens: number };
  by_type: Array<{ event_type: string; count: number; cost: number; tokens: number }>;
  today_by_type: Array<{ event_type: string; count: number; cost: number; tokens: number }>;
  by_agent: Array<{ agent_name: string; count: number; cost: number; tokens: number }>;
  today_by_agent: Array<{ agent_name: string; count: number; cost: number; tokens: number }>;
  daily_trend: Array<{ date: string; count: number; cost: number; tokens: number }>;
  recent_events: Array<{
    id: number; event_type: string; agent_name: string; model: string | null;
    prompt_tokens: number; completion_tokens: number; total_tokens: number;
    estimated_cost: number; metadata: Record<string, unknown>; created_at: string;
  }>;
}

export async function getCostSummary(token: string): Promise<CostSummary> {
  const response = await fetch(`${API_BASE}/admin/cost-summary`, {
    headers: { 'Authorization': `Bearer ${token}` },
  });
  if (!response.ok) {
    throw new Error('Failed to fetch cost summary');
  }
  return response.json();
}

export interface UsageSummary {
  total_requests: number;
  today_requests: number;
  by_agent: Array<{ agent_name: string; count: number }>;
  by_ip: Array<{ ip_address: string; city: string; region: string; country: string; latitude: number | null; longitude: number | null; zipcode: string; timezone: string; isp: string; org: string; count: number }>;
  by_country: Array<{ country: string; count: number }>;
  daily_trend: Array<{ date: string; count: number }>;
}

export interface UsageLog {
  id: number;
  agent_name: string;
  agent_id: string;
  ip_address: string;
  city: string;
  region: string;
  country: string;
  user_agent: string;
  query_preview: string;
  session_id: string;
  created_at: string;
  latitude: number | null;
  longitude: number | null;
  zipcode: string;
  timezone: string;
  isp: string;
  org: string;
}

export async function getUsageSummary(token: string): Promise<UsageSummary> {
  const response = await fetch(`${API_BASE}/admin/usage-summary`, {
    headers: { 'Authorization': `Bearer ${token}` },
  });
  if (!response.ok) {
    throw new Error('Failed to fetch usage summary');
  }
  return response.json();
}

export async function getUsageLogs(
  token: string,
  limit = 100,
  offset = 0,
  agent?: string,
): Promise<{ logs: UsageLog[]; limit: number; offset: number; total: number }> {
  let url = `${API_BASE}/admin/usage-logs?limit=${limit}&offset=${offset}`;
  if (agent) url += `&agent=${encodeURIComponent(agent)}`;
  const response = await fetch(url, {
    headers: { 'Authorization': `Bearer ${token}` },
  });
  if (!response.ok) {
    throw new Error('Failed to fetch usage logs');
  }
  const data = await response.json();
  const total = typeof data.total === 'number' ? data.total : data.logs?.length ?? 0;
  return { ...data, total };
}

// Maintenance Mode Functions
export async function getMaintenanceStatus(): Promise<{ enabled: boolean; message: string }> {
  const response = await fetch(`${API_BASE}/maintenance`);
  if (!response.ok) throw new Error('Failed to fetch maintenance status');
  return response.json();
}

export async function setMaintenanceMode(enabled: boolean, message?: string): Promise<{ success: boolean; enabled: boolean; message: string }> {
  const token = localStorage.getItem('admin_token');
  const response = await fetch(`${API_BASE}/admin/maintenance`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ enabled, ...(message !== undefined ? { message } : {}) }),
  });
  if (!response.ok) throw new Error('Failed to update maintenance mode');
  return response.json();
}

// Catalog Management Functions
export async function getCatalog(): Promise<AgentsCatalog> {
  const token = localStorage.getItem('admin_token');
  const response = await fetch(`${API_BASE}/catalog`, {
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (!response.ok) {
    const e = await response.json().catch(() => ({}));
    throw new Error(
      typeof e.detail === 'string' ? e.detail : `Failed to fetch catalog (${response.status})`,
    );
  }
  return response.json();
}

export async function updateCatalog(catalogData: AgentsCatalog): Promise<{ success: boolean; message: string; timestamp: string }> {
  const token = localStorage.getItem('admin_token');
  const response = await fetch(`${API_BASE}/catalog`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(catalogData),
  });
  if (!response.ok) {
    throw new Error('Failed to update catalog');
  }
  return response.json();
}

export async function generateWorkflow(instruction: string): Promise<any> {
  const token = localStorage.getItem('admin_token');
  const response = await fetch(`${API_BASE}/admin/workflows/generate`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ instruction }),
  });
  if (!response.ok) {
    const e = await response.json().catch(() => ({}));
    throw new Error(
      typeof e.detail === 'string' ? e.detail : `Failed to generate workflow (${response.status})`,
    );
  }
  return response.json();
}

export async function fetchAllVectorIndexes(): Promise<any> {
  const token = localStorage.getItem('admin_token');
  const response = await fetch(`${API_BASE}/admin/knowledge-base/all-vector-indexes`, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
  if (!response.ok) throw new Error('Failed to fetch vector indexes');
  return response.json();
}

export async function executeWorkflow(
  definition: object,
  agentUserConfigs?: Record<string, Record<string, string>>,
): Promise<any> {
  const token = localStorage.getItem('admin_token');
  const response = await fetch(`${API_BASE}/admin/workflows/execute`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({
      definition,
      ...(agentUserConfigs && Object.keys(agentUserConfigs).length > 0
        ? { agent_user_configs: agentUserConfigs }
        : {}),
    }),
  });
  if (!response.ok) throw new Error('Failed to execute workflow');
  return response.json();
}

export async function executeWorkflowStream(
  data: {
    definition: object;
    workflow_id?: string;
    agent_user_configs?: Record<string, Record<string, string>>;
    agent_extra_kwargs?: Record<string, Record<string, unknown>>;
    step_mode?: string;
  },
  onEvent: (event: { event: string; data: any }) => void,
): Promise<void> {
  const token = localStorage.getItem('admin_token');
  const sseUrl = `${API_BASE}/admin/workflows/execute-stream`;
  console.log('[SSE] Starting stream to:', sseUrl);
  const response = await fetch(sseUrl, {
    method: 'POST',
    cache: 'no-store',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'text/event-stream',
      'X-Accel-Buffering': 'no',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const errText = await response.text().catch(() => '');
    throw new Error(`Failed to execute workflow (${response.status}): ${errText}`);
  }
  console.log('[SSE] Stream connected, reading events...');

  const reader = response.body?.getReader();
  if (!reader) throw new Error('No response body');

  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      console.log('[SSE] Stream ended');
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed.startsWith('data: ')) {
        try {
          const parsed = JSON.parse(trimmed.slice(6));
          console.log('[SSE] Event:', parsed.event, parsed.data?.step_number || '');
          onEvent(parsed);
        } catch (e) {
          console.error('[SSE] Parse error:', e, trimmed);
        }
      }
    }
  }

  if (buffer.trim()) {
    const trimmed = buffer.trim();
    if (trimmed.startsWith('data: ')) {
      try {
        const parsed = JSON.parse(trimmed.slice(6));
        console.log('[SSE] Final event:', parsed.event);
        onEvent(parsed);
      } catch {}
    }
  }
}

export async function executeWorkflowStepStream(
  data: {
    step: Record<string, unknown>;
    query: string;
    agent_user_configs?: Record<string, Record<string, string>>;
    agent_extra_kwargs?: Record<string, Record<string, unknown>>;
  },
  onEvent: (event: { event: string; data: any }) => void,
): Promise<void> {
  const token = localStorage.getItem('admin_token');
  const sseUrl = `${API_BASE}/admin/workflows/execute-step-stream`;
  const response = await fetch(sseUrl, {
    method: 'POST',
    cache: 'no-store',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'text/event-stream',
      'X-Accel-Buffering': 'no',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const errText = await response.text().catch(() => '');
    throw new Error(`Failed to re-run step (${response.status}): ${errText}`);
  }

  const reader = response.body?.getReader();
  if (!reader) throw new Error('No response body');

  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed.startsWith('data: ')) {
        try {
          onEvent(JSON.parse(trimmed.slice(6)));
        } catch (e) {
          console.error('[SSE] Parse error:', e, trimmed);
        }
      }
    }
  }

  if (buffer.trim()) {
    const trimmed = buffer.trim();
    if (trimmed.startsWith('data: ')) {
      try {
        onEvent(JSON.parse(trimmed.slice(6)));
      } catch {}
    }
  }
}

export async function submitWorkflowInput(
  executionId: string,
  stepNumber: number,
  input: string,
): Promise<any> {
  const token = localStorage.getItem('admin_token');
  const response = await fetch(
    `${API_BASE}/admin/workflows/execute-stream/${executionId}/respond`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ step_number: stepNumber, input }),
    },
  );
  if (!response.ok) throw new Error('Failed to submit response');
  return response.json();
}

export async function saveWorkflow(data: {
  id?: string;
  name: string;
  instruction: string;
  definition: object;
  mermaid_code: string;
  /** When set, stored on the workflow for server-side runs. Omit to leave existing stored configs unchanged. */
  agent_user_configs?: Record<string, Record<string, string>>;
  /** When true, agents in this workflow load + persist mem0 memories on every run. Omit to keep the existing setting. */
  memory_enabled?: boolean;
}): Promise<any> {
  const token = localStorage.getItem('admin_token');
  const response = await fetch(`${API_BASE}/admin/workflows/save`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(data),
  });
  if (!response.ok) throw new Error('Failed to save workflow');
  return response.json();
}

export interface WorkflowMemoryItem {
  id?: string;
  memory?: string;
  text?: string;
  content?: string;
  user_id?: string;
  hash?: string;
  metadata?: Record<string, unknown> | null;
  categories?: string[] | null;
  created_at?: string;
  updated_at?: string;
  [key: string]: unknown;
}

export interface WorkflowMemoriesResponse {
  success: boolean;
  available?: boolean;
  memory_enabled?: boolean;
  results: WorkflowMemoryItem[];
  page?: number;
  page_size?: number;
  mem_user_id?: string;
  error?: string;
}

export async function getWorkflowMemories(
  workflowId: string,
  opts: { page?: number; pageSize?: number; targetUserId?: number } = {},
): Promise<WorkflowMemoriesResponse> {
  const token = localStorage.getItem('admin_token');
  const params = new URLSearchParams();
  if (opts.page) params.set('page', String(opts.page));
  if (opts.pageSize) params.set('page_size', String(opts.pageSize));
  if (opts.targetUserId !== undefined) params.set('target_user_id', String(opts.targetUserId));
  const qs = params.toString();
  const response = await fetch(
    `${API_BASE}/admin/workflows/${workflowId}/memories${qs ? `?${qs}` : ''}`,
    {
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    },
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => '');
    throw new Error(detail || `Failed to load memories (${response.status})`);
  }
  return response.json();
}

export interface WorkflowMemoryUser {
  user_id: number;
  username: string | null;
  is_owner: boolean;
}

export interface WorkflowMemoryUsersResponse {
  success: boolean;
  owner_user_id: number | null;
  users: WorkflowMemoryUser[];
}

export async function getWorkflowMemoryUsers(
  workflowId: string,
): Promise<WorkflowMemoryUsersResponse> {
  const token = localStorage.getItem('admin_token');
  const response = await fetch(
    `${API_BASE}/admin/workflows/${workflowId}/memory-users`,
    {
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    },
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => '');
    throw new Error(detail || `Failed to load memory users (${response.status})`);
  }
  return response.json();
}

export async function listWorkflows(): Promise<any> {
  const token = localStorage.getItem('admin_token');
  const response = await fetch(`${API_BASE}/admin/workflows`, {
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (!response.ok) throw new Error('Failed to list workflows');
  return response.json();
}

export async function getWorkflow(id: string): Promise<any> {
  const token = localStorage.getItem('admin_token');
  const response = await fetch(`${API_BASE}/admin/workflows/${id}`, {
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (!response.ok) throw new Error('Failed to get workflow');
  return response.json();
}

export async function deleteWorkflow(id: string): Promise<any> {
  const token = localStorage.getItem('admin_token');
  const response = await fetch(`${API_BASE}/admin/workflows/${id}`, {
    method: 'DELETE',
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (!response.ok) throw new Error('Failed to delete workflow');
  return response.json();
}

export async function listWorkflowExecutions(workflowId: string): Promise<any> {
  const token = localStorage.getItem('admin_token');
  const response = await fetch(`${API_BASE}/admin/workflows/${workflowId}/executions`, {
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (!response.ok) throw new Error('Failed to list executions');
  return response.json();
}

export async function getWorkflowExecution(executionId: string, opts?: { full?: boolean }): Promise<any> {
  const token = localStorage.getItem('admin_token');
  const qs = opts?.full ? '?full=true' : '';
  const response = await fetch(`${API_BASE}/admin/workflows/executions/${executionId}${qs}`, {
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (!response.ok) throw new Error('Failed to get execution');
  return response.json();
}

export async function getWorkflowExecutionStep(executionId: string, stepNumber: number): Promise<any> {
  const token = localStorage.getItem('admin_token');
  const response = await fetch(
    `${API_BASE}/admin/workflows/executions/${executionId}/steps/${stepNumber}`,
    { headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) } },
  );
  if (!response.ok) throw new Error('Failed to get execution step');
  return response.json();
}

export async function deleteWorkflowExecution(executionId: string): Promise<any> {
  const token = localStorage.getItem('admin_token');
  const response = await fetch(`${API_BASE}/admin/workflows/executions/${executionId}`, {
    method: 'DELETE',
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (!response.ok) throw new Error('Failed to delete execution');
  return response.json();
}

export async function kbGetStatus(): Promise<any> {
  const token = localStorage.getItem('admin_token');
  const r = await fetch(`${API_BASE}/admin/knowledge-base/status`, { headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) } });
  if (!r.ok) throw new Error('Failed to get KB status');
  return r.json();
}

export async function kbListDatabases(): Promise<any> {
  const token = localStorage.getItem('admin_token');
  const r = await fetch(`${API_BASE}/admin/knowledge-base/databases`, { headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) } });
  if (!r.ok) throw new Error('Failed to list databases');
  return r.json();
}

export async function kbListCollections(dbName: string): Promise<any> {
  const token = localStorage.getItem('admin_token');
  const r = await fetch(`${API_BASE}/admin/knowledge-base/collections/${encodeURIComponent(dbName)}`, { headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) } });
  if (!r.ok) throw new Error('Failed to list collections');
  return r.json();
}

export async function kbListIndexes(dbName: string, collName: string): Promise<any> {
  const token = localStorage.getItem('admin_token');
  const r = await fetch(`${API_BASE}/admin/knowledge-base/indexes/${encodeURIComponent(dbName)}/${encodeURIComponent(collName)}`, { headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) } });
  if (!r.ok) throw new Error('Failed to list indexes');
  return r.json();
}

export async function kbGetStats(dbName: string, collName: string): Promise<any> {
  const token = localStorage.getItem('admin_token');
  const r = await fetch(`${API_BASE}/admin/knowledge-base/stats/${encodeURIComponent(dbName)}/${encodeURIComponent(collName)}`, { headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) } });
  if (!r.ok) throw new Error('Failed to get stats');
  return r.json();
}

export async function kbCreateIndex(data: { db_name: string; collection_name: string; index_name: string; embedding_field?: string; dimensions?: number; similarity?: string }): Promise<any> {
  const token = localStorage.getItem('admin_token');
  const r = await fetch(`${API_BASE}/admin/knowledge-base/indexes`, { method: 'POST', headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) }, body: JSON.stringify(data) });
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || 'Failed to create index'); }
  return r.json();
}

export async function kbDeleteIndex(dbName: string, collName: string, indexName: string): Promise<any> {
  const token = localStorage.getItem('admin_token');
  const r = await fetch(`${API_BASE}/admin/knowledge-base/indexes/${encodeURIComponent(dbName)}/${encodeURIComponent(collName)}/${encodeURIComponent(indexName)}`, { method: 'DELETE', headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) } });
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || 'Failed to delete index'); }
  return r.json();
}

export async function kbIngestFile(data: { db_name: string; project_id: string; file_name: string; file_type: string; file_content_b64: string }): Promise<any> {
  const token = localStorage.getItem('admin_token');
  const r = await fetch(`${API_BASE}/admin/knowledge-base/ingest`, { method: 'POST', headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) }, body: JSON.stringify(data) });
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || 'Failed to ingest file'); }
  return r.json();
}

export async function kbDeleteFile(dbName: string, collName: string, fileName: string): Promise<any> {
  const token = localStorage.getItem('admin_token');
  const r = await fetch(`${API_BASE}/admin/knowledge-base/files/${encodeURIComponent(dbName)}/${encodeURIComponent(collName)}/${encodeURIComponent(fileName)}`, { method: 'DELETE', headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) } });
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || 'Failed to delete file'); }
  return r.json();
}

export async function kbCreateCollection(data: { db_name: string; collection_name: string }): Promise<any> {
  const token = localStorage.getItem('admin_token');
  const r = await fetch(`${API_BASE}/admin/knowledge-base/collections`, { method: 'POST', headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) }, body: JSON.stringify(data) });
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || 'Failed to create collection'); }
  return r.json();
}

export async function kbBrowseDocuments(dbName: string, collName: string, page: number = 1, pageSize: number = 20, search: string = ''): Promise<any> {
  const token = localStorage.getItem('admin_token');
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (search) params.set('search', search);
  const r = await fetch(`${API_BASE}/admin/knowledge-base/documents/${encodeURIComponent(dbName)}/${encodeURIComponent(collName)}?${params}`, { headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) } });
  if (!r.ok) throw new Error('Failed to browse documents');
  return r.json();
}

export async function kbListAllIndexes(dbName: string): Promise<any> {
  const token = localStorage.getItem('admin_token');
  const r = await fetch(`${API_BASE}/admin/knowledge-base/all-indexes/${encodeURIComponent(dbName)}`, { headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) } });
  if (!r.ok) throw new Error('Failed to list all indexes');
  return r.json();
}

export async function kbDeleteCollection(dbName: string, collName: string): Promise<any> {
  const token = localStorage.getItem('admin_token');
  const r = await fetch(`${API_BASE}/admin/knowledge-base/collections/${encodeURIComponent(dbName)}/${encodeURIComponent(collName)}`, { method: 'DELETE', headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) } });
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || 'Failed to delete collection'); }
  return r.json();
}

export async function kbRenameCollection(dbName: string, collName: string, newName: string): Promise<any> {
  const token = localStorage.getItem('admin_token');
  const r = await fetch(`${API_BASE}/admin/knowledge-base/collections/${encodeURIComponent(dbName)}/${encodeURIComponent(collName)}/rename`, { method: 'PUT', headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) }, body: JSON.stringify({ new_name: newName }) });
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || 'Failed to rename collection'); }
  return r.json();
}

export async function kbVectorSearch(data: { db_name: string; collection_name: string; query: string; index_name?: string; limit?: number }): Promise<any> {
  const token = localStorage.getItem('admin_token');
  const r = await fetch(`${API_BASE}/admin/knowledge-base/vector-search`, { method: 'POST', headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) }, body: JSON.stringify(data) });
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || 'Vector search failed'); }
  return r.json();
}

export interface AdminUser {
  id: number;
  username: string;
  role: string;
  menu_permissions: string[];
  /** null = all catalog agents; [] = none */
  agent_permissions?: string[] | null;
  is_active: boolean;
  created_at: string;
}

export async function listUsers(): Promise<{ success: boolean; users: AdminUser[] }> {
  const token = localStorage.getItem('admin_token');
  const r = await fetch(`${API_BASE}/admin/users`, {
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || 'Failed to list users'); }
  return r.json();
}

export async function createUser(data: {
  username: string;
  password: string;
  role: string;
  menu_permissions: string[];
  agent_permissions?: string[] | null;
}): Promise<{ success: boolean; user: AdminUser }> {
  const token = localStorage.getItem('admin_token');
  const r = await fetch(`${API_BASE}/admin/users`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify(data),
  });
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || 'Failed to create user'); }
  return r.json();
}

export async function updateUser(userId: number, data: {
  role?: string;
  menu_permissions?: string[];
  agent_permissions?: string[] | null;
  is_active?: boolean;
  password?: string;
}): Promise<{ success: boolean; user: AdminUser }> {
  const token = localStorage.getItem('admin_token');
  const r = await fetch(`${API_BASE}/admin/users/${userId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify(data),
  });
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || 'Failed to update user'); }
  return r.json();
}

export async function deleteUser(userId: number): Promise<{ success: boolean }> {
  const token = localStorage.getItem('admin_token');
  const r = await fetch(`${API_BASE}/admin/users/${userId}`, {
    method: 'DELETE',
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || 'Failed to delete user'); }
  return r.json();
}

export interface WebTestPlaywrightRunResult {
  success: boolean;
  exit_code: number | null;
  stdout: string;
  stderr: string;
  message?: string | null;
}

/** Run Web Test Agent Playwright TypeScript on the server (requires Node.js + network for first run). */
export async function runWebTestPlaywrightSpec(
  specSource: string,
  options?: { headed?: boolean; timeoutSec?: number },
): Promise<WebTestPlaywrightRunResult> {
  const token = typeof localStorage !== 'undefined' ? localStorage.getItem('admin_token') : null;
  const r = await fetch(`${API_BASE}/web-test/run-playwright-spec`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({
      spec_source: specSource,
      headed: options?.headed !== false,
      timeout_sec: options?.timeoutSec ?? 600,
    }),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const detail = typeof data?.detail === 'string' ? data.detail : JSON.stringify(data?.detail || data);
    throw new Error(detail || `Run failed (${r.status})`);
  }
  return data as WebTestPlaywrightRunResult;
}
