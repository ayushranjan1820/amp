import { useState, useEffect, useCallback, useMemo } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  ArrowLeft,
  Copy,
  Check,
  Wrench,
  Settings,
  AlertTriangle,
  Zap,
  Shield,
  ChevronRight,
  Sparkles,
  Layers,
  Terminal,
  PanelLeft,
  Network,
  Cpu,
  CheckCircle2,
  Plug,
  Radio,
  Database,
} from 'lucide-react';
import ChatInterface from '../components/ChatInterface';
import AgentConfigPanel from '../components/AgentConfigPanel';
import MermaidDiagram from '../components/MermaidDiagram';
import ClaudeCodeMemoryView from '../components/ClaudeCodeMemoryView';
import { getAgentById, type Agent } from '../services/api';
import { useAuth } from '../context/AuthContext';
import {
  getConfigFields,
  getUserConfigPayloadForActiveLlmProvider,
  hasRequiredConfig,
} from '../utils/agentConfigStorage';
import { getAgentsMarketplaceApiBase } from '../utils/agentsApiBase';

type TabType = 'overview' | 'architecture' | 'tools' | 'config' | 'api' | 'memory';

function autonomyBarColor(quotient: number): string {
  if (quotient >= 80) return '#10b981';
  if (quotient >= 60) return '#f59e0b';
  return '#f97316';
}

/** Match `chatWithAgentStream` / `streamFromEndpoint` — POST JSON to `/api{suffix}` with SSE. */
function catalogEndpointToFetchUrl(origin: string, rawEndpoint: string): { method: string; fullUrl: string } | null {
  const raw = rawEndpoint?.trim();
  if (!raw) return null;
  const parts = raw.split(/\s+/);
  const method = (parts.length > 1 ? parts[0] : 'POST').toUpperCase();
  const pathPiece = (parts.length > 1 ? parts[1] : parts[0]).replace('/api', '');
  const suffix = pathPiece.startsWith('/') ? pathPiece : `/${pathPiece}`;
  const base = origin.replace(/\/$/, '');
  return { method, fullUrl: `${base}/api${suffix}` };
}

function buildAgentApiCurl(fullUrl: string, method: string): string {
  const m = method || 'POST';
  return [
    '# Response is Server-Sent Events: lines like  data: {"event":"response_chunk",...}',
    '# Use -N so curl does not buffer the stream.',
    `curl -N -sS -X ${m} '${fullUrl}' \\`,
    `  -H 'Content-Type: application/json' \\`,
    `  -H 'Accept: text/event-stream' \\`,
    `  -d '{"query":"Your message","session_id":"optional-thread-id"}'`,
    '',
    '# Optional: same Bearer token the web UI uses when signed in (localStorage key admin_token):',
    `#   -H 'Authorization: Bearer YOUR_JWT'`,
    '',
    '# Common optional JSON fields (when supported by this agent): session_id, user_config,',
    '# clear_history, file_content, file_type, file_name, context_data — see marketplace API code.',
  ].join('\n');
}

function buildExternalAgentCurl(origin: string, agentId: string): string {
  const url = `${origin.replace(/\/$/, '')}/api/external-agent`;
  return [
    '# External / proxied agent — same SSE stream as the in-app chat.',
    `curl -N -sS -X POST '${url}' \\`,
    `  -H 'Content-Type: application/json' \\`,
    `  -H 'Accept: text/event-stream' \\`,
    `  -d '{"query":"Your message","agent_id":"${agentId}","session_id":"optional"}'`,
  ].join('\n');
}

function parseHttpOrigin(base: string): string | null {
  const t = base.trim();
  if (!t || !/^https?:\/\//i.test(t)) return null;
  try {
    return new URL(t).origin;
  } catch {
    return null;
  }
}

/**
 * Readable header JSON: `AGENTS_API_BASE`, then `LLM_PROVIDER`, then other keys A–Z, then allowlist.
 */
function formatMcpEnvForMarketplaceHeader(env: Record<string, string>): Record<string, string> {
  const allow = env.MCP_ALLOWED_AGENT_IDS;
  const base = env.AGENTS_API_BASE;
  const llm = env.LLM_PROVIDER;
  const skip = new Set(['AGENTS_API_BASE', 'MCP_ALLOWED_AGENT_IDS', 'LLM_PROVIDER']);
  const out: Record<string, string> = {};
  if (base != null && String(base).trim()) out.AGENTS_API_BASE = String(base).trim();
  if (llm != null && String(llm).trim()) out.LLM_PROVIDER = String(llm).trim();
  for (const k of Object.keys(env).sort((a, b) => a.localeCompare(b))) {
    if (skip.has(k)) continue;
    out[k] = env[k];
  }
  if (allow != null && String(allow).trim()) out.MCP_ALLOWED_AGENT_IDS = String(allow).trim();
  return out;
}

/**
 * MCP `X-Marketplace-Agent-Env` payload: saved Config for the **active LLM provider** only
 * (same rules as the Config tab), plus `AGENTS_API_BASE` and `MCP_ALLOWED_AGENT_IDS`.
 * Credential keys match the selected provider; `LLM_PROVIDER` is explicit when the agent uses LLM config.
 */
function buildMcpEnvForAgentSnippet(agent: Agent, _pageOrigin: string): Record<string, string> {
  const env: Record<string, string> = {};
  const payload = getUserConfigPayloadForActiveLlmProvider(agent);
  if (payload) {
    for (const [k, v] of Object.entries(payload)) {
      env[k] = v;
    }
  }
  if (!env.AGENTS_API_BASE?.trim()) {
    env.AGENTS_API_BASE = getAgentsMarketplaceApiBase();
  }
  env.MCP_ALLOWED_AGENT_IDS = agent.id;
  return formatMcpEnvForMarketplaceHeader(env);
}

/** Where Cursor/VS Code open MCP — API host from `AGENTS_API_BASE` when set, else the current page origin. */
function resolveMcpMountOrigin(pageOrigin: string, env: Record<string, string>): string {
  const parsed = parseHttpOrigin(env.AGENTS_API_BASE || '');
  if (parsed) return parsed;
  return pageOrigin.replace(/\/$/, '');
}

function buildCursorMcpJson(pageOrigin: string, envObject: Record<string, string>): string {
  const root = pageOrigin.replace(/\/$/, '');
  const env = JSON.stringify(envObject);
  return JSON.stringify(
    {
      mcpServers: {
        marketplace_agents: {
          url: `${root}/mcp`,
          headers: {
            'X-Marketplace-Agent-Env': env,
          },
        },
      },
    },
    null,
    2,
  );
}

function buildVscodeMcpJson(pageOrigin: string, envObject: Record<string, string>): string {
  const root = pageOrigin.replace(/\/$/, '');
  const env = JSON.stringify(envObject);
  return JSON.stringify(
    {
      servers: {
        marketplace_agents: {
          type: 'sse',
          url: `${root}/mcp/sse`,
          headers: {
            'X-Marketplace-Agent-Env': env,
          },
          metadata: { name: 'Agent Marketplace' },
        },
      },
    },
    null,
    2,
  );
}

export default function AgentPage() {
  const { id } = useParams<{ id: string }>();
  const [agent, setAgent] = useState<Agent | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabType>('overview');
  const [copied, setCopied] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [isConfigured, setIsConfigured] = useState(true);
  const [configDraftDirty, setConfigDraftDirty] = useState(false);
  const { isAuthenticated, agentPermissions, role, menuPermissions, isLoading: authLoading } = useAuth();

  const canViewAgentArchitecture =
    isAuthenticated &&
    !authLoading &&
    (role === 'super_admin' || menuPermissions.includes('agent-architecture'));

  const handleConfigChange = useCallback((configured: boolean) => {
    setIsConfigured(configured);
  }, []);

  useEffect(() => {
    if (!canViewAgentArchitecture && activeTab === 'architecture') {
      setActiveTab('overview');
    }
  }, [canViewAgentArchitecture, activeTab]);

  useEffect(() => {
    if (agent?.id !== 'claude_code' && activeTab === 'memory') {
      setActiveTab('overview');
    }
  }, [agent?.id, activeTab]);

  useEffect(() => {
    async function fetchAgent() {
      if (!id) return;
      try {
        const data = await getAgentById(id);
        setAgent(data);
        const fields = getConfigFields(data);
        setIsConfigured(fields.length === 0 || hasRequiredConfig(data, fields));
      } catch (err: any) {
        setError(err.message);
      } finally {
        setIsLoading(false);
      }
    }
    fetchAgent();
  }, [id]);

  const tabs = useMemo(() => {
    const rows: { id: TabType; label: string; icon: typeof Layers }[] = [
      { id: 'overview', label: 'Overview', icon: Layers },
    ];
    if (canViewAgentArchitecture) {
      rows.push({ id: 'architecture', label: 'Architecture', icon: Network });
    }
    rows.push(
      { id: 'tools', label: 'Tools', icon: Wrench },
      { id: 'config', label: 'Config', icon: Settings },
      { id: 'api', label: 'API', icon: Terminal },
    );
    if (agent?.id === 'claude_code') {
      rows.push({ id: 'memory', label: 'Memory', icon: Database });
    }
    return rows;
  }, [agent?.id, canViewAgentArchitecture]);

  const apiDocSnippets = useMemo(() => {
    const origin = typeof window !== 'undefined' ? window.location.origin : '';
    if (!agent) return null;
    const catalog = catalogEndpointToFetchUrl(origin, agent.usage?.api_endpoint || '');
    const mcpEnv = buildMcpEnvForAgentSnippet(agent, origin);
    const mcpMountOrigin = resolveMcpMountOrigin(origin, mcpEnv);
    return {
      origin,
      mcpMountOrigin,
      catalog,
      curlCatalog: catalog ? buildAgentApiCurl(catalog.fullUrl, catalog.method) : '',
      curlExternal: agent.external_api_url ? buildExternalAgentCurl(origin, agent.id) : '',
      mcpEnv,
      cursorMcp: buildCursorMcpJson(mcpMountOrigin, mcpEnv),
      vscodeMcp: buildVscodeMcpJson(mcpMountOrigin, mcpEnv),
    };
  }, [agent, activeTab]);

  const copyToClipboard = (text: string, key: string) => {
    navigator.clipboard.writeText(text);
    setCopied(key);
    setTimeout(() => setCopied(null), 2000);
  };

  if (isLoading) {
    return (
      <div className="min-h-screen gradient-hero-modern flex items-center justify-center">
        <div className="flex flex-col items-center gap-5">
          <div className="relative">
            <div className="absolute -inset-1 rounded-2xl bg-primary-500/20 blur-lg animate-pulse" />
            <div className="relative w-14 h-14 rounded-2xl bg-gradient-to-br from-primary-500 to-primary-600 shadow-lg shadow-primary-600/30 ring-1 ring-white/20" />
          </div>
          <div className="h-3.5 w-36 rounded-full bg-white/10 animate-pulse" />
          <p className="font-body text-xs text-gray-500">Loading agent…</p>
        </div>
      </div>
    );
  }

  if (error || !agent) {
    return (
      <div className="min-h-screen gradient-hero-modern flex items-center justify-center px-4">
        <div className="text-center space-y-5 max-w-sm">
          <div className="w-16 h-16 mx-auto rounded-2xl bg-red-500/10 ring-1 ring-red-500/20 flex items-center justify-center backdrop-blur-sm">
            <AlertTriangle className="w-8 h-8 text-red-400" />
          </div>
          <p className="font-body text-sm text-red-200/90">{error || 'Agent not found'}</p>
          <Link to="/" className="btn-primary rounded-xl">Back to Marketplace</Link>
        </div>
      </div>
    );
  }

  if (agent.admin_only && !isAuthenticated) {
    const returnTo = id ? encodeURIComponent(`/agent/${id}`) : '';
    const loginHref = returnTo ? `/admin/login?returnTo=${returnTo}` : '/admin/login';
    return (
      <div className="min-h-screen gradient-hero-modern flex items-center justify-center px-4">
        <div className="text-center space-y-5 max-w-md">
          <div className="w-16 h-16 mx-auto rounded-2xl bg-amber-500/10 ring-1 ring-amber-500/25 flex items-center justify-center backdrop-blur-sm">
            <Shield className="w-8 h-8 text-amber-400" />
          </div>
          <h2 className="font-heading text-2xl font-bold text-gray-900 dark:text-white tracking-tight">Access Denied</h2>
          <p className="font-body text-sm text-gray-400">
            This agent is restricted to signed-in administrators. Sign in and you will return to this page automatically.
          </p>
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-center gap-3 pt-1">
            <Link to={loginHref} className="btn-primary rounded-xl text-center py-3 px-6">
              Sign in to continue
            </Link>
            <Link
              to="/"
              className="rounded-xl border border-white/10 bg-white/5 hover:bg-white/10 text-gray-200 font-body text-sm font-medium py-3 px-6 transition-colors text-center"
            >
              Back to Marketplace
            </Link>
          </div>
        </div>
      </div>
    );
  }

  // Custom agents (built on this platform) are not in the catalog ACL —
  // skip the permission gate for them; visibility is controlled by status/visibility fields.
  const isCustomAgent = agent.id.startsWith('custom_') || (agent as any)._is_custom;
  if (!authLoading && isAuthenticated && !isCustomAgent && !agentPermissions.includes(agent.id)) {
    return (
      <div className="min-h-screen gradient-hero-modern flex items-center justify-center px-4">
        <div className="text-center space-y-5 max-w-md">
          <div className="w-16 h-16 mx-auto rounded-2xl bg-amber-500/10 ring-1 ring-amber-500/25 flex items-center justify-center backdrop-blur-sm">
            <Shield className="w-8 h-8 text-amber-400" />
          </div>
          <h2 className="font-heading text-2xl font-bold text-gray-900 dark:text-white tracking-tight">Access Denied</h2>
          <p className="font-body text-sm text-gray-400">
            Your account is not assigned this agent. Ask a super admin to grant access in User Management.
          </p>
          <Link to="/" className="btn-primary rounded-xl">Back to Marketplace</Link>
        </div>
      </div>
    );
  }

  const isActive = agent.status === 'active';
  const autonomy = agent.autonomy_quotient ?? 50;
  const autonomyColor = autonomyBarColor(autonomy);
  const categoryLabel = (agent.category || agent.type || 'Agent').toString();

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950">
      <section className="relative overflow-hidden gradient-hero-modern border-b border-white/5">
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.35]"
          aria-hidden
        >
          <div className="absolute -left-24 top-0 h-56 w-56 rounded-full bg-primary-500/18 blur-[80px]" />
          <div className="absolute -right-16 bottom-0 h-64 w-64 rounded-full bg-amber-400/10 blur-[72px]" />
        </div>

        <div
          className="absolute inset-0 opacity-[0.05] [mask-image:linear-gradient(to_bottom,black_0%,black_35%,transparent_72%)]"
          aria-hidden
        >
          <svg className="h-full w-full min-h-0" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMin slice">
            <defs>
              <pattern id="agent-page-grid" width="32" height="32" patternUnits="userSpaceOnUse">
                <path d="M 32 0 L 0 0 0 32" fill="none" stroke="white" strokeWidth="0.4" />
              </pattern>
            </defs>
            <rect width="100%" height="100%" fill="url(#agent-page-grid)" />
          </svg>
        </div>

        <div className="relative w-full max-w-full mx-auto px-2 sm:px-3 lg:px-4 pt-3 pb-5 sm:pt-4 sm:pb-6">
          <nav className="flex items-center gap-2 text-xs sm:text-sm font-body text-gray-500 mb-3 sm:mb-4">
            <Link
              to="/"
              className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 -ml-2 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-white/5 transition-colors"
            >
              <ArrowLeft className="w-3.5 h-3.5 shrink-0" />
              Marketplace
            </Link>
            <ChevronRight className="w-3.5 h-3.5 text-gray-600 shrink-0" />
            <span className="text-gray-200 font-medium truncate">{agent.name}</span>
          </nav>

          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:gap-8">
            <div className="flex gap-3 sm:gap-4 min-w-0 flex-1 lg:items-center">
              <div className="relative shrink-0 self-start lg:self-center">
                <div
                  className="absolute -inset-0.5 rounded-xl bg-gradient-to-br from-primary-500/35 via-transparent to-amber-500/25 opacity-70 blur-[1px]"
                  aria-hidden
                />
                <div className="relative flex h-12 w-12 sm:h-14 sm:w-14 items-center justify-center overflow-hidden rounded-xl border border-gray-200 dark:border-white/10 bg-white dark:bg-zinc-950/80 shadow-lg shadow-black/10 dark:shadow-black/30 ring-1 ring-gray-200 dark:ring-white/5 backdrop-blur-sm">
                  {agent.logo.startsWith('/') || agent.logo.startsWith('http') ? (
                    <img src={agent.logo} alt={agent.name} className="h-8 w-8 sm:h-9 sm:w-9 object-contain" />
                  ) : (
                    <span className="text-2xl sm:text-3xl leading-none" aria-hidden>
                      {agent.logo}
                    </span>
                  )}
                </div>
              </div>

              <div className="min-w-0 flex-1 pt-0">
                {isActive && (
                  <div className="mb-1.5 inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.06] px-2 py-0.5 backdrop-blur-md sm:mb-2 sm:gap-2 sm:px-2.5 sm:py-1">
                    <span className="relative flex h-1.5 w-1.5 sm:h-2 sm:w-2">
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400/50 opacity-75" />
                      <span className="relative inline-flex h-1.5 w-1.5 sm:h-2 sm:w-2 rounded-full bg-emerald-400" />
                    </span>
                    <span className="font-body text-[0.625rem] font-medium tracking-wide text-gray-300 sm:text-xs">
                      Live in catalog
                    </span>
                  </div>
                )}

                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="font-heading text-xl font-bold tracking-tight text-gray-900 dark:text-white sm:text-2xl lg:text-[1.625rem] leading-tight">
                    {agent.name}
                  </h1>
                  <span
                    className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[0.625rem] font-semibold sm:px-2.5 sm:py-1 sm:text-xs ${
                      isActive
                        ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300'
                        : 'border-white/10 bg-white/5 text-gray-400'
                    }`}
                  >
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${isActive ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.6)]' : 'bg-gray-500'}`}
                    />
                    {agent.status}
                  </span>
                </div>

                <div className="mt-1.5 flex flex-wrap items-center gap-1.5 sm:mt-2 sm:gap-2">
                  <span className="inline-flex max-w-full items-center rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 font-body text-[0.5625rem] font-semibold uppercase tracking-wider text-zinc-400 sm:px-2.5 sm:py-1 sm:text-[0.625rem]">
                    <span className="truncate">{categoryLabel}</span>
                  </span>
                  <span className="font-body text-[0.625rem] tabular-nums text-zinc-500 sm:text-xs">v{agent.version}</span>
                </div>

                <p className="mt-2 max-w-2xl font-body text-xs leading-snug text-zinc-400 sm:mt-2.5 sm:text-sm sm:leading-relaxed line-clamp-2 lg:line-clamp-3">
                  {agent.description}
                </p>

                <div className="mt-3 max-w-xs sm:max-w-md">
                  <div className="mb-1 flex items-center justify-between">
                    <span className="font-body text-[0.5625rem] font-semibold uppercase tracking-widest text-zinc-500 sm:text-[0.625rem]">
                      Autonomy index
                    </span>
                    <span
                      className="font-body text-[0.625rem] font-bold tabular-nums"
                      style={{ color: autonomyColor }}
                    >
                      {autonomy}%
                    </span>
                  </div>
                  <div className="h-1 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-zinc-800/90 ring-1 ring-inset ring-gray-300 dark:ring-white/5 sm:h-1.5">
                    <div
                      className="h-full rounded-full transition-all duration-500"
                      style={{
                        width: `${autonomy}%`,
                        backgroundColor: autonomyColor,
                        boxShadow: `0 0 14px ${autonomyColor}45`,
                      }}
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <div className="relative">
        <div
          className="pointer-events-none absolute inset-x-0 top-0 h-48 bg-gradient-to-b from-primary-500/[0.03] to-transparent dark:from-primary-500/[0.06]"
          aria-hidden
        />

        <div className="relative w-full max-w-full mx-auto px-2 sm:px-3 lg:px-4 -mt-3 pb-10 sm:pb-12">
          <div className="flex flex-col xl:flex-row gap-6 xl:gap-8">
            <div className={`transition-all duration-300 ease-out ${sidebarOpen ? 'xl:w-[480px] 2xl:w-[520px]' : 'xl:w-12'} flex-shrink-0`}>
              <button
                type="button"
                onClick={() => setSidebarOpen(!sidebarOpen)}
                className="hidden xl:flex items-center justify-center gap-2 mb-3 w-full xl:w-auto rounded-xl border border-gray-200/80 bg-white/80 px-3 py-2 text-xs font-body font-semibold text-gray-600 shadow-sm backdrop-blur-sm transition-colors hover:border-primary-300 hover:text-primary-700 dark:border-white/[0.08] dark:bg-zinc-900/80 dark:text-zinc-400 dark:hover:border-primary-500/30 dark:hover:text-primary-300"
                aria-expanded={sidebarOpen}
              >
                <PanelLeft className="w-3.5 h-3.5 shrink-0" />
                {sidebarOpen ? 'Hide panel' : 'Details'}
              </button>

            {sidebarOpen && (
              <div className="space-y-4 animate-fade-in">
                <div className="rounded-2xl border border-gray-200/90 bg-white shadow-xl shadow-gray-900/[0.04] ring-1 ring-black/[0.02] overflow-visible dark:border-white/[0.08] dark:bg-gradient-to-b dark:from-zinc-900/95 dark:via-[#0c0e14] dark:to-[#08090d] dark:shadow-2xl dark:shadow-black/40 dark:ring-white/[0.04]">
                  <div className="relative px-2 pt-2 pb-1.5 border-b border-gray-100 dark:border-white/[0.06]">
                    <div
                      className="pointer-events-none absolute inset-x-4 top-0 h-px bg-gradient-to-r from-transparent via-primary-500/40 to-transparent opacity-60"
                      aria-hidden
                    />
                    <div className="flex gap-0.5 overflow-x-auto rounded-xl bg-gray-100/95 p-1 dark:bg-zinc-950/90">
                    {tabs.map((tab) => (
                      <button
                        key={tab.id}
                        type="button"
                        onClick={() => setActiveTab(tab.id)}
                        className={`flex min-w-[2.75rem] flex-1 shrink-0 items-center justify-center gap-1 px-1.5 py-2 rounded-lg text-[0.6875rem] font-body font-semibold transition-all sm:min-w-0 ${
                          activeTab === tab.id
                            ? 'bg-white text-primary-700 shadow-sm ring-1 ring-black/[0.04] dark:bg-zinc-800 dark:text-primary-300 dark:ring-white/10'
                            : 'text-gray-500 hover:text-gray-800 dark:text-zinc-500 dark:hover:text-zinc-300'
                        }`}
                      >
                        <tab.icon className="w-3.5 h-3.5 shrink-0 opacity-90" />
                        <span className="hidden sm:inline truncate">{tab.label}</span>
                        {tab.id === 'config' && !isConfigured && (
                          <span className="w-1.5 h-1.5 shrink-0 rounded-full bg-amber-500 animate-pulse" />
                        )}
                      </button>
                    ))}
                    </div>
                  </div>

                  <div
                    className={`relative rounded-b-2xl border-t border-gray-100/70 bg-gradient-to-b from-white via-gray-50/40 to-white/95 px-4 py-5 sm:px-5 sm:py-6 dark:border-white/[0.05] dark:from-zinc-900/30 dark:via-[#0a0c12]/70 dark:to-[#060708] ${
                      activeTab === 'config' ? 'overflow-visible' : 'overflow-hidden'
                    }`}
                  >
                    <div
                      className="pointer-events-none absolute -right-20 -top-24 h-48 w-48 rounded-full bg-primary-500/[0.06] blur-3xl dark:bg-primary-400/[0.08]"
                      aria-hidden
                    />
                    <div
                      className="pointer-events-none absolute inset-x-0 top-0 h-32 bg-gradient-to-b from-primary-500/[0.04] to-transparent dark:from-primary-400/[0.06]"
                      aria-hidden
                    />
                    <div className="relative">
                    {activeTab === 'overview' && (
                      <div className="space-y-4">
                        <section className="relative overflow-hidden rounded-2xl border border-gray-200/70 bg-white/90 shadow-lg shadow-gray-900/[0.04] ring-1 ring-black/[0.03] backdrop-blur-md dark:border-white/[0.08] dark:bg-zinc-900/50 dark:shadow-black/40 dark:ring-white/[0.05]">
                          <div
                            className="pointer-events-none absolute -right-16 -top-20 h-40 w-40 rounded-full bg-gradient-to-br from-primary-400/15 via-primary-500/8 to-transparent blur-2xl dark:from-primary-400/12"
                            aria-hidden
                          />

                          <div className="relative flex items-center justify-between gap-3 border-b border-gray-100/90 px-3 py-2.5 dark:border-white/[0.06]">
                            <div className="flex min-w-0 items-center gap-2.5">
                              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary-500 to-primary-600 text-white shadow-md shadow-primary-600/30 ring-1 ring-white/15 dark:shadow-primary-500/20">
                                <Zap className="h-3.5 w-3.5" aria-hidden />
                              </span>
                              <div className="min-w-0 leading-tight">
                                <h3 className="font-body text-xs font-semibold tracking-tight text-gray-900 dark:text-white">
                                  Capabilities
                                </h3>
                                <p className="font-body text-[10px] text-gray-500 dark:text-zinc-500">
                                  {(agent.capabilities || []).length} items
                                </p>
                              </div>
                            </div>
                            <span className="shrink-0 rounded-lg bg-gray-900 px-2 py-0.5 font-body text-[10px] font-bold tabular-nums text-white dark:bg-white dark:text-zinc-900">
                              {(agent.capabilities || []).length}
                            </span>
                          </div>

                          <div className="relative">
                            <div
                              className="pointer-events-none absolute inset-x-0 bottom-0 z-[1] h-8 bg-gradient-to-t from-white to-transparent dark:from-zinc-900/95"
                              aria-hidden
                            />
                            <div className="max-h-[min(280px,50vh)] overflow-y-auto overscroll-y-contain px-2.5 py-2 scrollbar-thin scrollbar-track-transparent scrollbar-thumb-gray-300/50 dark:scrollbar-thumb-zinc-600/45">
                              <ul className="space-y-1">
                                {(agent.capabilities || []).map((cap, i) => (
                                  <li key={i}>
                                    <div className="group/cap-item flex items-start gap-2 rounded-lg border border-gray-100/80 bg-gray-50/70 px-2 py-1.5 dark:border-white/[0.06] dark:bg-zinc-800/30 transition-colors hover:border-primary-200/60 hover:bg-white dark:hover:border-primary-500/20 dark:hover:bg-zinc-800/50">
                                      <span className="flex h-5 min-w-[1.25rem] shrink-0 items-center justify-center rounded-md bg-primary-500/90 font-body text-[9px] font-bold tabular-nums text-white dark:bg-primary-600">
                                        {i + 1}
                                      </span>
                                      <p className="min-w-0 flex-1 font-body text-[11px] font-medium leading-snug text-gray-800 dark:text-zinc-200">
                                        {cap}
                                      </p>
                                      <CheckCircle2
                                        className="mt-px h-3 w-3 shrink-0 text-primary-500/35 opacity-0 group-hover/cap-item:opacity-100 dark:text-primary-400/45"
                                        aria-hidden
                                      />
                                    </div>
                                  </li>
                                ))}
                              </ul>
                            </div>
                          </div>
                        </section>

                        <div
                          className="h-px bg-gradient-to-r from-transparent via-gray-200 to-transparent dark:via-white/[0.08]"
                          aria-hidden
                        />

                        <section className="rounded-2xl border border-gray-200/70 bg-white/70 p-4 shadow-sm shadow-gray-900/[0.02] ring-1 ring-black/[0.02] backdrop-blur-sm dark:border-white/[0.07] dark:bg-zinc-900/35 dark:shadow-black/20 dark:ring-white/[0.03]">
                          <h3 className="mb-3 flex items-center gap-2.5 font-body">
                            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500/12 to-primary-500/10 ring-1 ring-violet-500/15 dark:from-violet-400/18 dark:to-primary-400/10 dark:ring-violet-400/20">
                              <Sparkles className="h-4 w-4 text-violet-600 dark:text-violet-300" aria-hidden />
                            </span>
                            <span className="min-w-0">
                              <span className="block text-[11px] font-bold uppercase tracking-[0.14em] text-gray-500 dark:text-zinc-400">
                                LLM providers
                              </span>
                              <span className="mt-0.5 block text-[10px] font-medium leading-tight text-gray-400 dark:text-zinc-500">
                                Models and pricing in catalog
                              </span>
                            </span>
                          </h3>
                          <div className="space-y-2.5">
                            {(agent.llm_providers || []).map((provider, i) => (
                              <div
                                key={i}
                                className="relative overflow-hidden rounded-2xl border border-gray-200/65 bg-gradient-to-br from-white to-gray-50/90 p-3.5 transition-all hover:border-primary-300/50 hover:shadow-md hover:shadow-primary-500/[0.06] dark:border-white/[0.07] dark:from-zinc-900/80 dark:to-zinc-950/90 dark:hover:border-primary-500/30 dark:hover:shadow-primary-500/5"
                              >
                                <div
                                  className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-primary-400/35 to-transparent dark:via-primary-400/25"
                                  aria-hidden
                                />
                                <div className="relative flex gap-3">
                                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary-500/12 to-zinc-500/5 ring-1 ring-primary-500/12 dark:from-primary-400/18 dark:to-zinc-900 dark:ring-primary-400/15">
                                    <Cpu className="h-4 w-4 text-primary-600 dark:text-primary-400" aria-hidden />
                                  </div>
                                  <div className="min-w-0 flex-1">
                                    <div className="flex flex-wrap items-center gap-2">
                                      <p className="font-body text-sm font-semibold tracking-tight text-gray-900 dark:text-white">
                                        {provider.name}
                                      </p>
                                      {provider.default && (
                                        <span className="rounded-full bg-primary-500/12 px-2 py-0.5 font-body text-[10px] font-semibold uppercase tracking-wide text-primary-700 ring-1 ring-primary-500/20 dark:bg-primary-400/15 dark:text-primary-300 dark:ring-primary-400/25">
                                          Default
                                        </span>
                                      )}
                                    </div>
                                    <p className="mt-1 font-body text-[11px] leading-relaxed text-gray-500 line-clamp-2 dark:text-zinc-400">
                                      {provider.description}
                                    </p>
                                  </div>
                                  <div className="shrink-0 text-right">
                                    <span className="inline-block rounded-lg bg-gray-100/90 px-2 py-1 font-body text-[10px] font-bold tabular-nums text-primary-700 dark:bg-zinc-800 dark:text-primary-300">
                                      {provider.cost}
                                    </span>
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        </section>
                      </div>
                    )}

                    {activeTab === 'architecture' && canViewAgentArchitecture && (
                      <div className="space-y-4">
                        <p className="font-body text-[11px] leading-relaxed text-gray-500 dark:text-zinc-400">
                          Reference topology for this agent from the catalog. Use fullscreen for a larger canvas.
                        </p>
                        {agent.architecture_diagram_mermaid ? (
                          <MermaidDiagram
                            chart={agent.architecture_diagram_mermaid.trim()}
                            presentation="architecture"
                          />
                        ) : (
                          <div className="rounded-2xl border border-dashed border-gray-200/90 bg-gray-50/50 px-4 py-10 text-center dark:border-white/[0.1] dark:bg-zinc-900/40">
                            <Network className="mx-auto mb-3 h-8 w-8 text-gray-300 dark:text-zinc-600" />
                            <p className="font-body text-xs font-medium text-gray-600 dark:text-zinc-400">
                              No architecture diagram yet
                            </p>
                            <p className="mt-1 font-body text-[11px] text-gray-500 dark:text-zinc-500">
                              Add <code className="rounded bg-gray-200/80 px-1 py-0.5 font-mono text-[10px] dark:bg-zinc-800">architecture_diagram_mermaid</code> to this agent in the catalog.
                            </p>
                          </div>
                        )}
                      </div>
                    )}

                    {activeTab === 'tools' && (
                      <section className="rounded-2xl border border-gray-200/70 bg-white/75 p-4 shadow-sm shadow-gray-900/[0.02] ring-1 ring-black/[0.02] backdrop-blur-sm dark:border-white/[0.07] dark:bg-zinc-900/40 dark:shadow-black/25 dark:ring-white/[0.04]">
                        <h3 className="mb-4 flex items-center gap-2.5 font-body">
                          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500/12 to-primary-500/10 ring-1 ring-emerald-500/15 dark:from-emerald-400/15 dark:to-primary-400/10 dark:ring-emerald-400/20">
                            <Wrench className="h-4 w-4 text-emerald-600 dark:text-emerald-400" aria-hidden />
                          </span>
                          <span className="min-w-0">
                            <span className="block text-[11px] font-bold uppercase tracking-[0.14em] text-gray-500 dark:text-zinc-400">
                              Tools
                            </span>
                            <span className="mt-0.5 block text-[10px] font-medium leading-tight text-gray-400 dark:text-zinc-500">
                              Functions exposed to the agent runtime
                            </span>
                          </span>
                        </h3>
                        {(agent.tools || []).length === 0 ? (
                          <p className="rounded-xl border border-dashed border-gray-200/90 bg-gray-50/60 px-4 py-8 text-center font-body text-xs text-gray-500 dark:border-white/[0.1] dark:bg-zinc-950/40 dark:text-zinc-500">
                            No tools listed for this agent yet.
                          </p>
                        ) : (
                          <ul className="grid grid-cols-1 gap-3">
                            {(agent.tools || []).map((tool, i) => (
                              <li key={i}>
                                <div className="group relative overflow-hidden rounded-2xl border border-gray-200/65 bg-gradient-to-br from-white to-gray-50/90 p-3.5 transition-all duration-200 hover:border-primary-300/55 hover:shadow-md hover:shadow-primary-500/[0.06] dark:border-white/[0.07] dark:from-zinc-900/85 dark:to-zinc-950/95 dark:hover:border-primary-500/35 dark:hover:shadow-primary-500/[0.04]">
                                  <div
                                    className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-primary-400/35 to-transparent opacity-0 transition-opacity group-hover:opacity-100 dark:via-primary-400/25"
                                    aria-hidden
                                  />
                                  <div className="relative flex gap-3">
                                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary-500/12 to-zinc-500/5 ring-1 ring-primary-500/12 dark:from-primary-400/18 dark:to-zinc-900 dark:ring-primary-400/15">
                                      <Wrench className="h-4 w-4 text-primary-600 dark:text-primary-400" aria-hidden />
                                    </div>
                                    <div className="min-w-0 flex-1">
                                      <h4 className="font-body text-sm font-semibold tracking-tight text-gray-900 dark:text-white">
                                        {tool.name}
                                      </h4>
                                      <p className="mt-1 font-body text-[11px] leading-relaxed text-gray-600 dark:text-zinc-400">
                                        {tool.description}
                                      </p>
                                      {tool.module && (
                                        <code className="mt-2 inline-flex max-w-full items-center gap-1 truncate rounded-lg border border-gray-200/80 bg-gray-900/[0.04] px-2 py-1 font-mono text-[10px] font-medium text-primary-700 ring-1 ring-black/[0.03] dark:border-white/[0.08] dark:bg-zinc-950/80 dark:text-primary-300 dark:ring-white/[0.06]">
                                          {tool.module}
                                        </code>
                                      )}
                                    </div>
                                  </div>
                                </div>
                              </li>
                            ))}
                          </ul>
                        )}
                      </section>
                    )}

                    {activeTab === 'config' && (
                      <div className="space-y-4">
                        <AgentConfigPanel
                          key={agent.id}
                          agent={agent}
                          onConfigChange={handleConfigChange}
                          onDraftDirtyChange={setConfigDraftDirty}
                        />
                      </div>
                    )}

                    {activeTab === 'api' && apiDocSnippets && (
                      <div className="space-y-5">
                        <section className="relative overflow-hidden rounded-2xl border border-gray-200/70 bg-white/80 p-4 shadow-lg shadow-gray-900/[0.04] ring-1 ring-black/[0.03] backdrop-blur-md dark:border-white/[0.08] dark:bg-gradient-to-b dark:from-zinc-900/90 dark:via-zinc-950/95 dark:to-[#060708] dark:shadow-black/40 dark:ring-white/[0.05] sm:p-5">
                          <div
                            className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-sky-400/50 to-transparent dark:via-sky-400/35"
                            aria-hidden
                          />
                          <div
                            className="pointer-events-none absolute -right-24 -top-24 h-48 w-48 rounded-full bg-sky-400/[0.07] blur-3xl dark:bg-sky-400/[0.06]"
                            aria-hidden
                          />

                          <h3 className="relative mb-4 flex items-start gap-3 font-body">
                            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-sky-500/15 via-primary-500/10 to-sky-500/5 shadow-inner shadow-sky-500/10 ring-1 ring-sky-500/20 dark:from-sky-400/20 dark:via-primary-400/12 dark:to-sky-900/20 dark:ring-sky-400/25">
                              <Terminal className="h-[18px] w-[18px] text-sky-600 dark:text-sky-400" aria-hidden />
                            </span>
                            <span className="min-w-0 flex-1 pt-0.5">
                              <span className="flex flex-wrap items-center gap-2">
                                <span className="text-[11px] font-bold uppercase tracking-[0.14em] text-gray-600 dark:text-zinc-300">
                                  HTTP API
                                </span>
                                <span className="inline-flex items-center gap-1 rounded-full border border-sky-200/80 bg-sky-50/90 px-2 py-0.5 font-body text-[9px] font-semibold uppercase tracking-wide text-sky-800 shadow-sm dark:border-sky-500/30 dark:bg-sky-950/50 dark:text-sky-200/95">
                                  <Radio className="h-2.5 w-2.5 opacity-80" aria-hidden />
                                  SSE stream
                                </span>
                              </span>
                              <span className="mt-1 block text-[11px] font-medium leading-snug text-gray-500 dark:text-zinc-400">
                                JSON request body, same progressive stream as the in-app chat panel.
                              </span>
                            </span>
                          </h3>

                          <div className="relative mb-4 grid grid-cols-1 gap-2 sm:grid-cols-3">
                            <div className="rounded-xl border border-gray-200/75 bg-gradient-to-br from-white to-gray-50/90 p-3 shadow-sm dark:border-white/[0.08] dark:from-zinc-900/80 dark:to-zinc-950/90">
                              <p className="font-body text-[9px] font-bold uppercase tracking-[0.12em] text-gray-400 dark:text-zinc-500">
                                Method
                              </p>
                              <p className="mt-1 font-mono text-sm font-semibold tracking-tight text-emerald-600 dark:text-emerald-400">
                                POST
                              </p>
                            </div>
                            <div className="rounded-xl border border-gray-200/75 bg-gradient-to-br from-white to-gray-50/90 p-3 shadow-sm dark:border-white/[0.08] dark:from-zinc-900/80 dark:to-zinc-950/90">
                              <p className="font-body text-[9px] font-bold uppercase tracking-[0.12em] text-gray-400 dark:text-zinc-500">
                                Content-Type
                              </p>
                              <p className="mt-1 break-all font-mono text-[10px] font-medium leading-snug text-gray-800 dark:text-zinc-200">
                                application/json
                              </p>
                            </div>
                            <div className="rounded-xl border border-gray-200/75 bg-gradient-to-br from-white to-gray-50/90 p-3 shadow-sm dark:border-white/[0.08] dark:from-zinc-900/80 dark:to-zinc-950/90">
                              <p className="font-body text-[9px] font-bold uppercase tracking-[0.12em] text-gray-400 dark:text-zinc-500">
                                Accept
                              </p>
                              <p className="mt-1 break-all font-mono text-[10px] font-medium leading-snug text-gray-800 dark:text-zinc-200">
                                text/event-stream
                              </p>
                            </div>
                          </div>

                          <div className="relative mb-4 rounded-2xl border border-gray-200/70 bg-gray-50/50 p-3.5 dark:border-white/[0.08] dark:bg-zinc-950/40">
                            <p className="font-body text-[10px] font-bold uppercase tracking-[0.14em] text-gray-500 dark:text-zinc-500">
                              Payload shape
                            </p>
                            <p className="mt-2 font-body text-[11px] leading-relaxed text-gray-600 dark:text-zinc-400">
                              Each SSE line is{' '}
                              <code className="rounded-md border border-gray-200/80 bg-white/90 px-1.5 py-0.5 font-mono text-[10px] text-gray-800 dark:border-white/[0.1] dark:bg-zinc-900/90 dark:text-zinc-200">
                                data: {'{'}...{'}'}
                              </code>{' '}
                              with an <code className="font-mono text-[10px] text-primary-700 dark:text-primary-300">event</code> field. Common values:
                            </p>
                            <div className="mt-2.5 flex flex-wrap gap-1.5">
                              {(
                                ['response_chunk', 'thinking', 'done', 'error'] as const
                              ).map((ev) => (
                                <code
                                  key={ev}
                                  className="inline-flex items-center rounded-lg border border-primary-500/15 bg-primary-500/[0.06] px-2 py-1 font-mono text-[10px] font-medium text-primary-800 dark:border-primary-400/25 dark:bg-primary-400/[0.08] dark:text-primary-200"
                                >
                                  {ev}
                                </code>
                              ))}
                            </div>
                          </div>

                          {agent.external_api_url && (
                            <div className="relative mb-4 overflow-hidden rounded-2xl border border-sky-200/70 bg-gradient-to-br from-sky-50/95 via-white to-sky-50/40 p-3.5 shadow-sm dark:border-sky-500/20 dark:from-sky-950/40 dark:via-zinc-950/60 dark:to-sky-950/20">
                              <div
                                className="pointer-events-none absolute -right-8 -top-8 h-24 w-24 rounded-full bg-sky-400/15 blur-2xl dark:bg-sky-400/10"
                                aria-hidden
                              />
                              <p className="relative font-body text-[11px] leading-relaxed text-sky-950 dark:text-sky-100/90">
                                <span className="mr-1.5 inline-flex items-center rounded-md bg-sky-600/10 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-sky-800 dark:bg-sky-400/15 dark:text-sky-200">
                                  External
                                </span>
                                The web UI streams via{' '}
                                <code className="rounded-md border border-sky-200/80 bg-white/90 px-1 py-0.5 font-mono text-[10px] dark:border-sky-500/25 dark:bg-black/25">
                                  POST /api/external-agent
                                </code>{' '}
                                with <code className="font-mono text-[10px] text-sky-900 dark:text-sky-200">agent_id</code> (cURL below). The catalog path may still describe the backing service.
                              </p>
                            </div>
                          )}

                          <h4 className="mb-2 font-body text-[10px] font-bold uppercase tracking-widest text-gray-400 dark:text-zinc-500">
                            Catalog endpoint
                          </h4>
                          <div className="mb-2 flex items-center gap-2 rounded-xl border border-white/[0.08] bg-gradient-to-r from-gray-900 to-gray-950 p-2.5 shadow-inner dark:from-[#0c0e14] dark:to-[#08090d]">
                            <span className="shrink-0 rounded-lg bg-emerald-500/15 px-2 py-1 font-body text-[10px] font-bold uppercase tracking-wide text-emerald-300 ring-1 ring-emerald-400/25">
                              {apiDocSnippets.catalog?.method || 'POST'}
                            </span>
                            <code className="min-w-0 flex-1 break-all font-mono text-[11px] leading-snug text-gray-200">
                              {apiDocSnippets.catalog?.fullUrl || '(not configured)'}
                            </code>
                            <button
                              type="button"
                              onClick={() =>
                                copyToClipboard(apiDocSnippets.catalog?.fullUrl || agent.usage?.api_endpoint || '', 'endpoint-url')
                              }
                              className="shrink-0 rounded-lg p-2 text-gray-600 dark:text-gray-400 transition-colors hover:bg-gray-100 dark:hover:bg-white/10 hover:text-gray-900 dark:hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-500/60"
                              aria-label="Copy URL"
                            >
                              {copied === 'endpoint-url' ? (
                                <Check className="h-3.5 w-3.5 text-emerald-400" />
                              ) : (
                                <Copy className="h-3.5 w-3.5" />
                              )}
                            </button>
                          </div>
                          <p className="mb-4 font-body text-[10px] text-gray-500 dark:text-zinc-500">
                            Catalog label:{' '}
                            <code className="rounded bg-gray-100/90 px-1 py-0.5 font-mono text-[10px] text-gray-700 dark:bg-zinc-800/80 dark:text-zinc-300">
                              {agent.usage?.api_endpoint || 'N/A'}
                            </code>
                          </p>

                          <h4 className="mb-2 font-body text-[10px] font-bold uppercase tracking-widest text-gray-400 dark:text-zinc-500">
                            Request body (JSON)
                          </h4>
                          <div className="mb-4 overflow-hidden rounded-xl border border-gray-200/70 shadow-sm dark:border-white/[0.08]">
                            <table className="w-full text-left font-body text-[11px]">
                              <thead>
                                <tr className="border-b border-gray-200/80 bg-gray-50/95 dark:border-white/[0.06] dark:bg-zinc-900/90">
                                  <th className="px-3 py-2.5 font-semibold text-gray-600 dark:text-zinc-400">Field</th>
                                  <th className="px-3 py-2.5 font-semibold text-gray-600 dark:text-zinc-400">Req</th>
                                  <th className="px-3 py-2.5 font-semibold text-gray-600 dark:text-zinc-400">Description</th>
                                </tr>
                              </thead>
                              <tbody className="divide-y divide-gray-100/90 text-gray-700 dark:divide-white/[0.05] dark:text-zinc-300">
                                <tr className="bg-white/40 dark:bg-zinc-950/20">
                                  <td className="px-3 py-2.5 font-mono text-[10px] text-primary-700 dark:text-primary-300">query</td>
                                  <td className="px-3 py-2.5">
                                    <span className="inline-flex rounded-md bg-amber-500/12 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-amber-800 dark:bg-amber-400/15 dark:text-amber-200">
                                      Yes
                                    </span>
                                  </td>
                                  <td className="px-3 py-2.5 text-gray-600 dark:text-zinc-400">User message / instruction.</td>
                                </tr>
                                <tr className="bg-gray-50/30 dark:bg-zinc-900/15">
                                  <td className="px-3 py-2.5 font-mono text-[10px] text-primary-700 dark:text-primary-300">session_id</td>
                                  <td className="px-3 py-2.5 text-gray-500 dark:text-zinc-500">No</td>
                                  <td className="px-3 py-2.5 text-gray-600 dark:text-zinc-400">Stable id to continue the same thread.</td>
                                </tr>
                                <tr className="bg-white/40 dark:bg-zinc-950/20">
                                  <td className="px-3 py-2.5 font-mono text-[10px] text-primary-700 dark:text-primary-300">user_config</td>
                                  <td className="px-3 py-2.5 text-gray-500 dark:text-zinc-500">No</td>
                                  <td className="px-3 py-2.5 text-gray-600 dark:text-zinc-400">Agent keys from the Config tab (same as saved UI settings).</td>
                                </tr>
                                <tr className="bg-gray-50/30 dark:bg-zinc-900/15">
                                  <td className="px-3 py-2.5 font-mono text-[10px] text-primary-700 dark:text-primary-300">clear_history</td>
                                  <td className="px-3 py-2.5 text-gray-500 dark:text-zinc-500">No</td>
                                  <td className="px-3 py-2.5 text-gray-600 dark:text-zinc-400">When true, start a fresh conversation for that session.</td>
                                </tr>
                                <tr className="bg-white/40 dark:bg-zinc-950/20">
                                  <td className="px-3 py-2.5 font-mono text-[10px] text-primary-700 dark:text-primary-300">…</td>
                                  <td className="px-3 py-2.5 text-gray-500 dark:text-zinc-500">—</td>
                                  <td className="px-3 py-2.5 text-gray-600 dark:text-zinc-400">
                                    Optional: <code className="font-mono text-[10px]">context_data</code>, file upload fields,{' '}
                                    <code className="font-mono text-[10px]">data_source</code> / <code className="font-mono text-[10px]">show_sql</code>, etc., depending on agent type.
                                  </td>
                                </tr>
                              </tbody>
                            </table>
                          </div>

                          {apiDocSnippets.curlCatalog ? (
                            <div>
                              <h4 className="mb-2 font-body text-[10px] font-bold uppercase tracking-widest text-gray-400 dark:text-zinc-500">
                                cURL (streaming)
                              </h4>
                              <div className="relative">
                                <button
                                  type="button"
                                  onClick={() => copyToClipboard(apiDocSnippets.curlCatalog, 'curl-catalog')}
                                  className="absolute right-2 top-2 z-10 inline-flex items-center gap-1 rounded-lg border border-gray-200 dark:border-white/10 bg-white dark:bg-gray-800/95 px-2 py-1.5 font-body text-[10px] font-semibold text-gray-700 dark:text-gray-200 shadow-lg backdrop-blur-sm transition-colors hover:bg-gray-100 dark:hover:bg-gray-700/95 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-500/70"
                                >
                                  {copied === 'curl-catalog' ? (
                                    <Check className="h-3 w-3 text-emerald-400" />
                                  ) : (
                                    <Copy className="h-3 w-3" />
                                  )}
                                  Copy
                                </button>
                                <pre className="max-h-64 overflow-x-auto overflow-y-auto rounded-xl border border-white/[0.08] bg-gradient-to-b from-gray-900 to-gray-950 p-3 pb-4 pr-14 pt-10 shadow-inner dark:from-[#0c0e14] dark:to-[#060708] sm:p-4 sm:pr-16">
                                  <code className="font-mono text-[10px] text-gray-200 whitespace-pre sm:text-[11px]">
                                    {apiDocSnippets.curlCatalog}
                                  </code>
                                </pre>
                              </div>
                            </div>
                          ) : (
                            <p className="rounded-2xl border border-dashed border-amber-200/90 bg-amber-50/60 px-3.5 py-3.5 font-body text-[11px] leading-relaxed text-amber-950 dark:border-amber-500/25 dark:bg-amber-950/25 dark:text-amber-100/90">
                              No catalog <code className="font-mono text-[10px]">api_endpoint</code> is set for this agent, so the direct route URL cannot be shown. Use MCP below or the external route if configured.
                            </p>
                          )}

                          {agent.external_api_url && apiDocSnippets.curlExternal && (
                            <div className="relative mt-5 border-t border-gray-200/70 pt-5 dark:border-white/[0.06]">
                              <h4 className="mb-2 font-body text-[10px] font-bold uppercase tracking-widest text-gray-400 dark:text-zinc-500">
                                External agent route
                              </h4>
                              <p className="mb-3 font-body text-[11px] leading-relaxed text-gray-600 dark:text-zinc-400">
                                Invoked through the marketplace proxy at{' '}
                                <code className="rounded-md border border-gray-200/80 bg-gray-50/90 px-1.5 py-0.5 font-mono text-[10px] dark:border-white/[0.1] dark:bg-zinc-800/80">
                                  /api/external-agent
                                </code>{' '}
                                with <code className="font-mono text-[10px] text-primary-700 dark:text-primary-300">agent_id</code> set to this catalog id.
                              </p>
                              <div className="relative">
                                <button
                                  type="button"
                                  onClick={() => copyToClipboard(apiDocSnippets.curlExternal, 'curl-external')}
                                  className="absolute right-2 top-2 z-10 inline-flex items-center gap-1 rounded-lg border border-gray-200 dark:border-white/10 bg-white dark:bg-gray-800/95 px-2 py-1.5 font-body text-[10px] font-semibold text-gray-700 dark:text-gray-200 shadow-lg backdrop-blur-sm transition-colors hover:bg-gray-100 dark:hover:bg-gray-700/95 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-500/70"
                                >
                                  {copied === 'curl-external' ? (
                                    <Check className="h-3 w-3 text-emerald-400" />
                                  ) : (
                                    <Copy className="h-3 w-3" />
                                  )}
                                  Copy
                                </button>
                                <pre className="max-h-48 overflow-x-auto overflow-y-auto rounded-xl border border-white/[0.08] bg-gradient-to-b from-gray-900 to-gray-950 p-3 pb-4 pr-14 pt-10 shadow-inner dark:from-[#0c0e14] dark:to-[#060708]">
                                  <code className="font-mono text-[10px] text-gray-200 whitespace-pre">
                                    {apiDocSnippets.curlExternal}
                                  </code>
                                </pre>
                              </div>
                            </div>
                          )}
                        </section>

                        <section className="overflow-hidden rounded-2xl border border-gray-200/60 bg-gradient-to-b from-white via-white to-gray-50/90 p-5 shadow-lg shadow-gray-900/[0.04] ring-1 ring-black/[0.03] backdrop-blur-sm dark:border-white/[0.08] dark:from-zinc-900/95 dark:via-zinc-900/80 dark:to-[#0a0c12] dark:shadow-black/35 dark:ring-white/[0.06] sm:p-6">
                          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                            <div className="flex min-w-0 gap-3.5">
                              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-500/18 via-violet-500/10 to-emerald-500/12 shadow-inner shadow-violet-500/10 ring-1 ring-violet-500/20 dark:from-violet-400/22 dark:via-violet-500/12 dark:to-emerald-500/14 dark:ring-violet-400/25">
                                <Plug className="h-5 w-5 text-violet-600 dark:text-violet-300" aria-hidden />
                              </span>
                              <div className="min-w-0">
                                <p className="font-body text-[10px] font-bold uppercase tracking-[0.16em] text-violet-600 dark:text-violet-400">
                                  IDE · Model Context Protocol
                                </p>
                                <h3 className="mt-1 font-body text-base font-semibold tracking-tight text-gray-900 dark:text-white">
                                  Cursor &amp; VS Code
                                </h3>
                                <p className="mt-1.5 max-w-md font-body text-[11px] leading-relaxed text-gray-600 dark:text-zinc-400">
                                  Wire this agent into your editor as marketplace MCP tools—same server, different transport per app.
                                </p>
                              </div>
                            </div>
                            <div className="flex shrink-0 flex-col gap-2 sm:items-end">
                              <div className="flex flex-wrap gap-2 sm:justify-end">
                                <span className="inline-flex items-center gap-1.5 rounded-xl border border-emerald-500/20 bg-emerald-500/[0.07] px-2.5 py-1.5 font-body text-[9px] font-bold uppercase tracking-wider text-emerald-800 dark:border-emerald-400/25 dark:bg-emerald-500/10 dark:text-emerald-200/90">
                                  <Radio className="h-3 w-3 opacity-80" aria-hidden />
                                  Streamable
                                </span>
                                <span className="inline-flex items-center gap-1.5 rounded-xl border border-sky-500/20 bg-sky-500/[0.07] px-2.5 py-1.5 font-body text-[9px] font-bold uppercase tracking-wider text-sky-900 dark:border-sky-400/25 dark:bg-sky-500/10 dark:text-sky-100/90">
                                  <Network className="h-3 w-3 opacity-80" aria-hidden />
                                  SSE
                                </span>
                              </div>
                              <div className="flex max-w-full flex-col gap-1.5 rounded-xl border border-gray-200/80 bg-white/70 px-3 py-2.5 dark:border-white/[0.08] dark:bg-zinc-950/40">
                                <code className="block truncate font-mono text-[10px] text-gray-800 dark:text-zinc-200">
                                  {apiDocSnippets.mcpMountOrigin}/mcp
                                </code>
                                <code className="block truncate border-t border-gray-200/60 pt-1.5 font-mono text-[10px] text-gray-600 dark:border-white/[0.06] dark:text-zinc-400">
                                  {apiDocSnippets.mcpMountOrigin}/mcp/sse
                                </code>
                              </div>
                            </div>
                          </div>

                          <div className="mt-4 rounded-xl border border-gray-100/90 bg-gray-50/80 p-3.5 dark:border-white/[0.06] dark:bg-zinc-950/35">
                            <p className="font-body text-[11px] leading-relaxed text-gray-600 dark:text-zinc-400">
                              Endpoints above: first is recommended for Cursor; second is typical for VS Code Copilot MCP. The{' '}
                              <code className="font-mono text-[10px] text-gray-800 dark:text-zinc-200">url</code> respects{' '}
                              <code className="font-mono text-[10px] text-gray-800 dark:text-zinc-200">AGENTS_API_BASE</code> in the header when it is an absolute{' '}
                              <code className="font-mono text-[10px] text-gray-800 dark:text-zinc-200">http(s)</code> URL; otherwise it follows this page&apos;s origin.{' '}
                              <code className="font-mono text-[10px] text-gray-800 dark:text-zinc-200">X-Marketplace-Agent-Env</code> carries{' '}
                              <code className="font-mono text-[10px] text-gray-800 dark:text-zinc-200">AGENTS_API_BASE</code>,{' '}
                              <code className="font-mono text-[10px] text-gray-800 dark:text-zinc-200">LLM_PROVIDER</code>, and credentials for the active mode. The server at{' '}
                              <code className="font-mono text-[10px] text-gray-800 dark:text-zinc-200">/mcp</code> can infer{' '}
                              <code className="font-mono text-[10px] text-gray-800 dark:text-zinc-200">LLM_PROVIDER</code> when omitted. Reopen this tab after Config changes; snippets may include secrets.
                            </p>
                          </div>

                          <Link
                            to="/docs"
                            className="group mt-4 inline-flex w-full items-center justify-center gap-2 rounded-xl border border-primary-500/25 bg-primary-500/[0.06] px-4 py-2.5 font-body text-[11px] font-semibold text-primary-700 transition-colors hover:border-primary-500/40 hover:bg-primary-500/[0.1] dark:border-primary-400/30 dark:bg-primary-500/10 dark:text-primary-200 dark:hover:border-primary-400/45 dark:hover:bg-primary-500/[0.14] sm:w-auto sm:justify-start"
                          >
                            <span>MCP docs — env, troubleshooting, multi-agent</span>
                            <ChevronRight className="h-3.5 w-3.5 opacity-70 transition-transform group-hover:translate-x-0.5" aria-hidden />
                          </Link>

                          <div className="mt-6 space-y-6">
                            <div>
                              <div className="mb-2 flex flex-wrap items-center gap-2">
                                <span className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900/[0.06] px-2 py-1 font-body text-[10px] font-semibold text-gray-800 dark:bg-white/[0.06] dark:text-zinc-200">
                                  <Terminal className="h-3.5 w-3.5 text-violet-600 dark:text-violet-400" aria-hidden />
                                  Cursor
                                </span>
                                <code className="rounded-lg border border-gray-200/90 bg-white px-2 py-1 font-mono text-[10px] text-gray-700 dark:border-white/[0.1] dark:bg-zinc-900/80 dark:text-zinc-300">
                                  .cursor/mcp.json
                                </code>
                              </div>
                              <p className="mb-2.5 font-body text-[10px] leading-relaxed text-gray-500 dark:text-zinc-500">
                                Point <code className="font-mono text-[10px] text-gray-700 dark:text-zinc-300">url</code> at{' '}
                                <code className="font-mono text-[10px] text-gray-700 dark:text-zinc-300">…/mcp</code>. Reload the editor after saving.
                              </p>
                              <div className="relative">
                                <button
                                  type="button"
                                  onClick={() => copyToClipboard(apiDocSnippets.cursorMcp, 'mcp-cursor')}
                                  className="absolute right-2 top-2 z-10 inline-flex items-center gap-1 rounded-lg border border-gray-200 dark:border-white/10 bg-white dark:bg-gray-800/95 px-2 py-1.5 font-body text-[10px] font-semibold text-gray-700 dark:text-gray-200 shadow-lg backdrop-blur-sm transition-colors hover:bg-gray-100 dark:hover:bg-gray-700/95 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-500/70"
                                  aria-label="Copy Cursor MCP config"
                                >
                                  {copied === 'mcp-cursor' ? (
                                    <Check className="h-3 w-3 text-emerald-400" />
                                  ) : (
                                    <Copy className="h-3 w-3" />
                                  )}
                                  Copy
                                </button>
                                <pre className="max-h-56 overflow-x-auto overflow-y-auto rounded-xl border border-white/[0.08] bg-gradient-to-b from-gray-900 to-gray-950 p-3 pb-4 pr-14 pt-10 shadow-inner dark:from-[#0c0e14] dark:to-[#060708] sm:p-4 sm:pr-16">
                                  <code className="font-mono text-[10px] text-gray-200 whitespace-pre sm:text-[11px]">
                                    {apiDocSnippets.cursorMcp}
                                  </code>
                                </pre>
                              </div>
                            </div>

                            <div className="border-t border-gray-200/70 pt-6 dark:border-white/[0.06]">
                              <div className="mb-2 flex flex-wrap items-center gap-2">
                                <span className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900/[0.06] px-2 py-1 font-body text-[10px] font-semibold text-gray-800 dark:bg-white/[0.06] dark:text-zinc-200">
                                  <Cpu className="h-3.5 w-3.5 text-sky-600 dark:text-sky-400" aria-hidden />
                                  VS Code
                                </span>
                                <code className="rounded-lg border border-gray-200/90 bg-white px-2 py-1 font-mono text-[10px] text-gray-700 dark:border-white/[0.1] dark:bg-zinc-900/80 dark:text-zinc-300">
                                  .vscode/mcp.json
                                </code>
                              </div>
                              <p className="mb-2.5 font-body text-[10px] leading-relaxed text-gray-500 dark:text-zinc-500">
                                Enable MCP in Copilot (<code className="font-mono text-[10px] text-gray-700 dark:text-zinc-300">chat.mcp.enabled</code>). Use{' '}
                                <code className="font-mono text-[10px] text-gray-700 dark:text-zinc-300">type: &quot;sse&quot;</code> and{' '}
                                <code className="font-mono text-[10px] text-gray-700 dark:text-zinc-300">…/mcp/sse</code>.
                              </p>
                              <div className="relative">
                                <button
                                  type="button"
                                  onClick={() => copyToClipboard(apiDocSnippets.vscodeMcp, 'mcp-vscode')}
                                  className="absolute right-2 top-2 z-10 inline-flex items-center gap-1 rounded-lg border border-gray-200 dark:border-white/10 bg-white dark:bg-gray-800/95 px-2 py-1.5 font-body text-[10px] font-semibold text-gray-700 dark:text-gray-200 shadow-lg backdrop-blur-sm transition-colors hover:bg-gray-100 dark:hover:bg-gray-700/95 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-500/70"
                                  aria-label="Copy VS Code MCP config"
                                >
                                  {copied === 'mcp-vscode' ? (
                                    <Check className="h-3 w-3 text-emerald-400" />
                                  ) : (
                                    <Copy className="h-3 w-3" />
                                  )}
                                  Copy
                                </button>
                                <pre className="max-h-56 overflow-x-auto overflow-y-auto rounded-xl border border-white/[0.08] bg-gradient-to-b from-gray-900 to-gray-950 p-3 pb-4 pr-14 pt-10 shadow-inner dark:from-[#0c0e14] dark:to-[#060708] sm:p-4 sm:pr-16">
                                  <code className="font-mono text-[10px] text-gray-200 whitespace-pre sm:text-[11px]">
                                    {apiDocSnippets.vscodeMcp}
                                  </code>
                                </pre>
                              </div>
                            </div>
                          </div>
                        </section>

                        {agent.usage?.initialization && (
                          <div className="rounded-2xl border border-gray-200/70 bg-white/75 p-4 dark:border-white/[0.07] dark:bg-zinc-900/40">
                            <h3 className="font-body text-[10px] font-bold text-gray-400 dark:text-zinc-500 mb-2 uppercase tracking-widest">
                              Initialization
                            </h3>
                            <div className="relative">
                              <pre className="p-3 bg-gray-900 dark:bg-gray-950 rounded-xl overflow-x-auto border border-white/[0.06]">
                                <code className="font-body text-[11px] text-gray-200">{agent.usage.initialization}</code>
                              </pre>
                              <button
                                type="button"
                                onClick={() => copyToClipboard(agent.usage?.initialization || '', 'init')}
                                className="absolute top-2 right-2 p-1.5 bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 rounded-lg transition-colors border border-gray-200 dark:border-white/10"
                              >
                                {copied === 'init' ? (
                                  <Check className="w-3 h-3 text-green-400" />
                                ) : (
                                  <Copy className="w-3 h-3 text-gray-400" />
                                )}
                              </button>
                            </div>
                          </div>
                        )}

                        {agent.usage?.setup_steps && agent.usage.setup_steps.length > 0 && (
                          <div className="rounded-2xl border border-gray-200/70 bg-white/75 p-4 dark:border-white/[0.07] dark:bg-zinc-900/40">
                            <h3 className="font-body text-[10px] font-bold text-gray-400 dark:text-zinc-500 mb-2 uppercase tracking-widest">
                              Setup
                            </h3>
                            <ol className="space-y-1.5">
                              {agent.usage.setup_steps.map((step, i) => (
                                <li key={i} className="flex items-start gap-2 font-body text-[11px] text-gray-700 dark:text-gray-300">
                                  <span className="flex-shrink-0 w-5 h-5 gradient-primary text-white rounded-full flex items-center justify-center text-[10px] font-bold mt-0.5">
                                    {i + 1}
                                  </span>
                                  <span>{step}</span>
                                </li>
                              ))}
                            </ol>
                          </div>
                        )}

                        {agent.usage?.example_prompts && agent.usage.example_prompts.length > 0 && (
                          <div className="rounded-2xl border border-gray-200/70 bg-white/75 p-4 dark:border-white/[0.07] dark:bg-zinc-900/40">
                            <h3 className="font-body text-[10px] font-bold text-gray-400 dark:text-zinc-500 mb-2 uppercase tracking-widest">
                              Examples
                            </h3>
                            <ul className="space-y-1.5">
                              {agent.usage.example_prompts.map((prompt, i) => (
                                <li
                                  key={i}
                                  className="p-2.5 bg-gray-50/80 dark:bg-zinc-950/50 rounded-xl border border-gray-100 dark:border-gray-700/50 font-body text-[11px] text-gray-700 dark:text-gray-300 italic"
                                >
                                  &ldquo;{prompt}&rdquo;
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    )}

                    {activeTab === 'memory' && agent.id === 'claude_code' && <ClaudeCodeMemoryView />}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          <div className="flex-1 min-w-0">
            <div className="sticky top-20">
              <ChatInterface
                key={agent.id}
                agent={agent}
                blockedByUnsavedConfig={configDraftDirty}
                onOpenConfigTab={() => {
                  setSidebarOpen(true);
                  setActiveTab('config');
                }}
              />
            </div>
          </div>
        </div>
        </div>
      </div>

      <div className="h-8" />
    </div>
  );
}
