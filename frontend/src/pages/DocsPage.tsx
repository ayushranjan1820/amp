import { useState, useEffect, useMemo, useCallback } from 'react';
import {
  Copy,
  Check,
  BookOpen,
  Plug,
  Globe,
  ChevronRight,
  ArrowRight,
  Zap,
  Cpu,
  Server,
  MonitorSmartphone,
  Radio,
  FileText,
  FileDown,
  FileCode,
} from 'lucide-react';
import { getAgents, type Agent } from '../services/api';
import McpAgentEnvPicker from '../components/McpAgentEnvPicker';
import type { LlmProviderChoice } from '../utils/agentConfigStorage';
import { mergedMcpEnvKeysForAgentsAndLlm } from '../utils/catalogEnvKeys';
import { loadMcpDocsDraft, saveMcpDocsDraft } from '../utils/mcpDocsDraftStorage';
import { getAgentsMarketplaceApiBase, resolveAgentsApiBaseInput } from '../utils/agentsApiBase';

/** Cursor / streamable HTTP — POST+GET+DELETE on mount root (recommended). */
function getMcpRootUrl(): string {
  return `${getAgentsMarketplaceApiBase()}/mcp`;
}

/** VS Code `type: "sse"` — legacy SSE GET + POST to /mcp/messages/. */
function getMcpSseUrl(): string {
  return `${getAgentsMarketplaceApiBase()}/mcp/sse`;
}

type Section = 'overview' | 'cursor' | 'vscode' | 'faq';

const MCP_DOCS_LLM_OPTIONS: { value: LlmProviderChoice; label: string }[] = [
  { value: 'pwc_genai', label: 'PwC GenAI' },
  { value: 'local_llm', label: 'Local LLM' },
  { value: 'ollama_cloud', label: 'On-prem Cloud' },
];

const NAV_ITEMS: { id: Section; label: string; icon: React.ReactNode }[] = [
  { id: 'overview', label: 'Overview', icon: <BookOpen className="w-4 h-4" /> },
  { id: 'cursor', label: 'Cursor IDE', icon: <CursorIcon /> },
  { id: 'vscode', label: 'VS Code', icon: <VSCodeIcon /> },
  { id: 'faq', label: 'FAQ', icon: <Zap className="w-4 h-4" /> },
];

function CursorIcon() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
      <path d="M3.5 2A1.5 1.5 0 0 0 2 3.5v17A1.5 1.5 0 0 0 3.5 22h17a1.5 1.5 0 0 0 1.5-1.5v-17A1.5 1.5 0 0 0 20.5 2h-17Zm8.204 5.1a.75.75 0 0 1 .592 0l5.25 2.25a.75.75 0 0 1 0 1.38L12.75 13l4.796 2.27a.75.75 0 0 1 0 1.38l-5.25 2.25a.75.75 0 0 1-.592 0l-5.25-2.25a.75.75 0 0 1 0-1.38L11.25 13 6.454 10.73a.75.75 0 0 1 0-1.38l5.25-2.25Z" />
    </svg>
  );
}

function VSCodeIcon() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
      <path d="M17.583 2.322a1.5 1.5 0 0 1 1.917.974l.001.003 2.4 7.391a1.5 1.5 0 0 1-.57 1.655L12.61 18.9a1 1 0 0 1-1.22 0L2.67 12.345a1.5 1.5 0 0 1-.57-1.655l2.4-7.39a1.5 1.5 0 0 1 1.917-.975l4.583 1.68L15 2l2.583.322ZM12 4.656 8.068 3.213 6.2 8.965l5.8 4.243 5.8-4.243-1.868-5.752L12 4.656Z" />
    </svg>
  );
}

export default function DocsPage() {
  const [copied, setCopied] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState<Section>('overview');
  const [agents, setAgents] = useState<Agent[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const initialMcpDocsDraft = useMemo(() => loadMcpDocsDraft(), []);
  const [cursorMcpAgentIds, setCursorMcpAgentIds] = useState<string[]>(
    () => initialMcpDocsDraft?.agentIds ?? [],
  );
  const [cursorMcpLlmProvider, setCursorMcpLlmProvider] = useState<LlmProviderChoice>(
    () => initialMcpDocsDraft?.llmProvider ?? 'pwc_genai',
  );
  const [cursorMcpEnvValues, setCursorMcpEnvValues] = useState<Record<string, string>>(() => {
    const env = { ...(initialMcpDocsDraft?.envValues ?? {}) };
    env.AGENTS_API_BASE = resolveAgentsApiBaseInput(env.AGENTS_API_BASE);
    return env;
  });

  useEffect(() => {
    getAgents()
      .then((data) => setAgents(data.agents.filter((a) => a.status === 'active')))
      .catch(() => {})
      .finally(() => setIsLoading(false));
  }, []);

  const copy = (text: string, key: string) => {
    navigator.clipboard.writeText(text);
    setCopied(key);
    setTimeout(() => setCopied(null), 2000);
  };

  const downloadTextFile = useCallback((filename: string, text: string) => {
    const blob = new Blob([text], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.rel = 'noopener';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }, []);

  const scrollTo = (id: Section) => {
    setActiveSection(id);
    document.getElementById(`section-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const cursorMcpSelectedAgents = useMemo(
    () => agents.filter((a) => cursorMcpAgentIds.includes(a.id)),
    [agents, cursorMcpAgentIds],
  );

  const cursorMcpMergedKeys = useMemo(
    () => mergedMcpEnvKeysForAgentsAndLlm(cursorMcpSelectedAgents, cursorMcpLlmProvider),
    [cursorMcpSelectedAgents, cursorMcpLlmProvider],
  );

  useEffect(() => {
    setCursorMcpEnvValues((prev) => {
      const next: Record<string, string> = {};
      for (const k of cursorMcpMergedKeys) {
        if (k === 'AGENTS_API_BASE') {
          next[k] = prev[k] !== undefined ? prev[k] : getAgentsMarketplaceApiBase();
        } else {
          next[k] = prev[k] !== undefined ? prev[k] : '';
        }
      }
      return next;
    });
  }, [cursorMcpMergedKeys]);

  useEffect(() => {
    saveMcpDocsDraft({
      agentIds: cursorMcpAgentIds,
      llmProvider: cursorMcpLlmProvider,
      envValues: cursorMcpEnvValues,
    });
  }, [cursorMcpAgentIds, cursorMcpLlmProvider, cursorMcpEnvValues]);

  const onCursorMcpEnvValueChange = useCallback((key: string, value: string) => {
    setCursorMcpEnvValues((prev) => ({ ...prev, [key]: value }));
  }, []);

  /** Export JSON: no placeholder tokens — empty fields omitted except AGENTS_API_BASE (falls back to API base). */
  const cursorMcpEnvObject = useMemo(() => {
    const out: Record<string, string> = {};
    for (const k of cursorMcpMergedKeys) {
      const trimmed = (cursorMcpEnvValues[k] ?? '').trim();
      if (k === 'AGENTS_API_BASE') {
        out[k] = trimmed || getAgentsMarketplaceApiBase();
        continue;
      }
      if (trimmed) out[k] = trimmed;
    }
    out.LLM_PROVIDER = cursorMcpLlmProvider;
    if (cursorMcpAgentIds.length > 0) {
      out.MCP_ALLOWED_AGENT_IDS = [...cursorMcpAgentIds].sort().join(',');
    }
    return out;
  }, [cursorMcpAgentIds, cursorMcpMergedKeys, cursorMcpEnvValues, cursorMcpLlmProvider]);

  const cursorSseLocalConfig = useMemo(() => {
    const envJson = JSON.stringify(cursorMcpEnvObject);
    return JSON.stringify(
      {
        mcpServers: {
          pwc_agents: {
            url: getMcpRootUrl(),
            headers: {
              'X-Marketplace-Agent-Env': envJson,
            },
          },
        },
      },
      null,
      2,
    );
  }, [cursorMcpEnvObject]);

  const cursorSseRemoteConfig = useMemo(() => {
    const remoteEnv = { ...cursorMcpEnvObject, AGENTS_API_BASE: getAgentsMarketplaceApiBase() };
    const envJson = JSON.stringify(remoteEnv);
    return JSON.stringify(
      {
        mcpServers: {
          pwc_agents: {
            url: getMcpRootUrl(),
            headers: {
              'X-Marketplace-Agent-Env': envJson,
            },
          },
        },
      },
      null,
      2,
    );
  }, [cursorMcpEnvObject]);

  /** Same env header as Cursor — VS Code uses explicit SSE transport at /mcp/sse (see Microsoft MCP docs). */
  const vscodeMcpConfig = useMemo(() => {
    const envJson = JSON.stringify(cursorMcpEnvObject);
    return JSON.stringify(
      {
        servers: {
          pwc_agents: {
            type: 'sse',
            url: getMcpSseUrl(),
            headers: {
              'X-Marketplace-Agent-Env': envJson,
            },
            metadata: { name: 'Agent Marketplace' },
          },
        },
      },
      null,
      2,
    );
  }, [cursorMcpEnvObject]);

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950">
      {/* ── Hero ───────────────────────────────────────── */}
      <div className="relative overflow-hidden bg-gradient-to-br from-primary-600 via-primary-700 to-primary-900 dark:from-primary-900 dark:via-gray-900 dark:to-gray-950">
        <div className="absolute inset-0 opacity-10">
          <div className="absolute inset-0" style={{ backgroundImage: 'radial-gradient(circle at 1px 1px, white 1px, transparent 0)', backgroundSize: '40px 40px' }} />
        </div>
        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-16 lg:py-24">
          <div className="flex items-center gap-2 text-primary-200 dark:text-primary-400 mb-4">
            <Plug className="w-5 h-5" />
            <span className="font-body text-sm font-semibold uppercase tracking-wider">IDE Integration Guide</span>
          </div>
          <h1 className="font-heading text-3xl sm:text-4xl lg:text-5xl font-bold text-gray-900 dark:text-white mb-4 leading-tight">
            Connect your IDE to the<br />Agent Marketplace
          </h1>
          <p className="font-body text-lg text-primary-100 dark:text-gray-300 max-w-2xl mb-8">
            Use any of our {agents.length || '20+'} AI agents directly from Cursor, VS Code, or any MCP-compatible tool.
            One URL, all agents, zero setup friction.
          </p>
          <div className="flex flex-wrap gap-3">
            <button onClick={() => scrollTo('cursor')} className="flex items-center gap-2 px-5 py-2.5 bg-white/10 hover:bg-white/20 border border-white/20 rounded-lg text-gray-900 dark:text-white font-body text-sm font-semibold transition-all">
              <CursorIcon /> Cursor Setup
            </button>
            <button onClick={() => scrollTo('vscode')} className="flex items-center gap-2 px-5 py-2.5 bg-white/10 hover:bg-white/20 border border-white/20 rounded-lg text-gray-900 dark:text-white font-body text-sm font-semibold transition-all">
              <VSCodeIcon /> VS Code Setup
            </button>
            <button onClick={() => scrollTo('faq')} className="flex items-center gap-2 px-5 py-2.5 bg-white/10 hover:bg-white/20 border border-white/20 rounded-lg text-gray-900 dark:text-white font-body text-sm font-semibold transition-all">
              <Zap className="w-4 h-4" /> FAQ
            </button>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12 lg:py-16">
        <div className="flex gap-10">
          {/* ── Sticky sidebar nav ────────────────────── */}
          <aside className="hidden lg:block w-56 shrink-0">
            <nav className="sticky top-24 space-y-1">
              {NAV_ITEMS.map((item) => (
                <button
                  key={item.id}
                  onClick={() => scrollTo(item.id)}
                  className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-left font-body text-sm transition-all ${
                    activeSection === item.id
                      ? 'bg-primary-100 dark:bg-primary-900/20 text-primary-700 dark:text-primary-400 font-semibold'
                      : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800/50 hover:text-gray-900 dark:hover:text-white'
                  }`}
                >
                  {item.icon}
                  {item.label}
                </button>
              ))}
            </nav>
          </aside>

          {/* ── Main content ──────────────────────────── */}
          <div className="flex-1 min-w-0 space-y-16">
            {/* ── Overview ────────────────────────────── */}
            <section id="section-overview">
              <SectionHeader icon={<BookOpen className="w-5 h-5" />} title="Overview" subtitle="How MCP connects your IDE to the Agent Marketplace" />
              <div className="mt-6 grid sm:grid-cols-3 gap-4">
                <FeatureCard icon={<Globe className="w-5 h-5 text-primary-500" />} title="One URL, All Agents" description="A single MCP endpoint gives your IDE access to every agent in the marketplace — JIRA, BRD, Web Search, Security, and more." />
                <FeatureCard icon={<MonitorSmartphone className="w-5 h-5 text-emerald-500" />} title="Works Everywhere" description="Compatible with Cursor, VS Code (GitHub Copilot MCP), Windsurf, and any tool that supports the Model Context Protocol." />
                <FeatureCard icon={<Server className="w-5 h-5 text-violet-500" />} title="Local or Remote" description="Point to localhost during development, or your deployed URL in production. Same config, same experience." />
              </div>

              <div className="mt-8 p-5 bg-gradient-to-r from-primary-50 to-violet-50 dark:from-primary-950/30 dark:to-violet-950/20 rounded-xl border border-primary-200 dark:border-primary-800/40">
                <h3 className="font-heading text-sm font-bold text-gray-900 dark:text-white mb-2 flex items-center gap-2">
                  <Zap className="w-4 h-4 text-primary-500" /> How It Works
                </h3>
                <div className="flex flex-col sm:flex-row items-start sm:items-center gap-3 sm:gap-2 font-body text-sm text-gray-700 dark:text-gray-300">
                  <StepPill n={1} text="Add MCP config to your IDE" />
                  <ChevronRight className="w-4 h-4 text-gray-600 dark:text-gray-400 hidden sm:block" />
                  <StepPill n={2} text="IDE discovers all agent tools" />
                  <ChevronRight className="w-4 h-4 text-gray-600 dark:text-gray-400 hidden sm:block" />
                  <StepPill n={3} text="Invoke any agent from chat" />
                </div>
                <p className="font-body text-xs text-gray-500 dark:text-gray-400 mt-3">
                  The MCP server dynamically exposes every active agent from the catalog. When a new agent is added to the marketplace, it becomes available in your IDE automatically — no config changes needed.
                </p>
              </div>
            </section>

            {/* ── Cursor ──────────────────────────────── */}
            <section id="section-cursor">
              <SectionHeader icon={<CursorIcon />} title="Cursor IDE" subtitle="Connect all agents with a single config file" badge="Recommended" />
              <div className="mt-6 space-y-4">
                <StepCard
                  variant="modern"
                  step={1}
                  title="Create the MCP config"
                  description={
                    <>
                      Wire up <Code>.cursor/mcp.json</Code> with the MCP base URL (<Code>/mcp</Code> — Streamable HTTP), build the <Code>X-Marketplace-Agent-Env</Code> header from your agents, then paste one of the snippets below.
                    </>
                  }
                >
                  <div className="space-y-4">
                    <nav
                      className="flex flex-col gap-2 rounded-lg border border-gray-200/80 bg-white/90 px-3 py-2.5 dark:border-gray-800 dark:bg-gray-900/40 sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-1 sm:gap-y-1 sm:px-3.5"
                      aria-label="MCP setup steps"
                    >
                      {[
                        { k: 'file', label: 'File' },
                        { k: 'url', label: 'URL' },
                        { k: 'env', label: 'Header JSON' },
                        { k: 'copy', label: 'Snippet' },
                      ].map((item, i, arr) => (
                        <span key={item.k} className="flex items-center gap-1 font-body text-[11px] text-gray-600 dark:text-gray-400">
                          <span className="rounded-md bg-gray-100 px-1.5 py-0.5 font-semibold tabular-nums text-gray-800 dark:bg-gray-800 dark:text-gray-200">
                            {i + 1}
                          </span>
                          <span className="font-medium text-gray-700 dark:text-gray-300">{item.label}</span>
                          {i < arr.length - 1 && (
                            <ChevronRight className="mx-0.5 hidden h-3.5 w-3.5 shrink-0 text-gray-700 dark:text-gray-600 sm:inline" aria-hidden />
                          )}
                        </span>
                      ))}
                    </nav>

                    <CursorWorkflowStep
                      step={1}
                      title="Config file location"
                      subtitle="Per-project or global"
                      icon={<FileText className="h-3.5 w-3.5 text-gray-600 dark:text-gray-400" strokeWidth={2} aria-hidden />}
                    >
                      <p className="font-body text-xs leading-relaxed text-gray-600 dark:text-gray-400">
                        Create <Code>.cursor/mcp.json</Code> in the repo root for this project only, or <Code>~/.cursor/mcp.json</Code> in your home folder to reuse the same MCP servers everywhere.
                      </p>
                    </CursorWorkflowStep>

                    <CursorWorkflowStep
                      step={2}
                      title="Streamable HTTP URL"
                      subtitle="HTTP to /mcp (recommended)"
                      icon={<Radio className="h-3.5 w-3.5 text-violet-500" strokeWidth={2} aria-hidden />}
                    >
                      <p className="font-body text-xs leading-relaxed text-gray-600 dark:text-gray-400">
                        Point <Code>url</Code> at <Code>…/mcp</Code> (not <Code>…/mcp/sse</Code>) so Cursor uses Streamable HTTP without transport fallback. Put credential keys as a <strong>JSON string</strong> in{' '}
                        <Code>headers[&quot;X-Marketplace-Agent-Env&quot;]</Code> — the marketplace does <strong>not</strong> read them from the server&apos;s <Code>.env</Code> for this transport.
                      </p>
                    </CursorWorkflowStep>

                    <CursorWorkflowStep
                      step={3}
                      title="Agents &amp; env values"
                      subtitle="Merged into X-Marketplace-Agent-Env"
                      icon={<Zap className="h-3.5 w-3.5 text-amber-500" strokeWidth={2} aria-hidden />}
                    >
                      <div className="mb-4 space-y-2 rounded-xl border border-violet-200/80 bg-violet-50/50 p-3.5 dark:border-violet-900/50 dark:bg-violet-950/25 sm:p-4">
                        <div className="flex items-start gap-2">
                          <Cpu className="mt-0.5 h-4 w-4 shrink-0 text-violet-600 dark:text-violet-400" strokeWidth={2} aria-hidden />
                          <div className="min-w-0 flex-1 space-y-1.5">
                            <div>
                              <p className="font-heading text-xs font-semibold text-gray-900 dark:text-gray-100">
                                1. LLM provider
                              </p>
                              <p className="font-body text-[10px] leading-snug text-gray-600 dark:text-gray-400">
                                Choose which backend runs model calls for every tool invoked over{' '}
                                <Code>/mcp</Code>. The header includes <Code>LLM_PROVIDER</Code> plus only the credential
                                fields for that mode; agent-specific keys follow in the same JSON.
                              </p>
                            </div>
                            <select
                              id="docs-mcp-llm-provider"
                              value={cursorMcpLlmProvider}
                              disabled={isLoading}
                              onChange={(e) => setCursorMcpLlmProvider(e.target.value as LlmProviderChoice)}
                              className="w-full max-w-md rounded-lg border border-gray-200 bg-white px-2.5 py-2 font-body text-sm text-gray-900 outline-none focus:border-violet-500 focus:ring-2 focus:ring-violet-500/25 disabled:opacity-50 dark:border-gray-600 dark:bg-gray-900 dark:text-white dark:focus:border-violet-500"
                              aria-label="LLM provider for MCP"
                            >
                              {MCP_DOCS_LLM_OPTIONS.map((o) => (
                                <option key={o.value} value={o.value}>
                                  {o.label}
                                </option>
                              ))}
                            </select>
                          </div>
                        </div>
                      </div>
                      <McpAgentEnvPicker
                        agents={agents}
                        selectedIds={cursorMcpAgentIds}
                        onSelectionChange={setCursorMcpAgentIds}
                        disabled={isLoading}
                        envKeys={cursorMcpMergedKeys}
                        envValues={cursorMcpEnvValues}
                        onEnvValueChange={onCursorMcpEnvValueChange}
                      />
                      <div className="mt-3">
                        <button
                          type="button"
                          disabled={isLoading}
                          onClick={() => downloadTextFile('mcp.json', cursorSseLocalConfig)}
                          className="inline-flex items-center gap-1.5 rounded-lg bg-primary-600 px-3 py-2 font-body text-xs font-semibold text-gray-900 dark:text-white shadow-sm transition-colors hover:bg-primary-700 disabled:pointer-events-none disabled:opacity-50 dark:bg-primary-500 dark:hover:bg-primary-600"
                          title="Downloads mcp.json for .cursor/ — localhost /mcp URL and your current X-Marketplace-Agent-Env values"
                        >
                          <FileDown className="h-3.5 w-3.5 shrink-0" strokeWidth={2} aria-hidden />
                          Generate mcp.json
                        </button>
                      </div>
                      <p className="font-body mt-2 flex items-start gap-2 rounded-md border border-gray-200/80 bg-gray-50/90 px-2.5 py-2 text-[11px] leading-snug text-gray-600 dark:border-gray-700/80 dark:bg-gray-900/50 dark:text-gray-300">
                        <Zap className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary-500" strokeWidth={2} />
                        <span>
                          {(() => {
                            const llmLabel =
                              MCP_DOCS_LLM_OPTIONS.find((o) => o.value === cursorMcpLlmProvider)?.label ??
                              cursorMcpLlmProvider;
                            const n = Object.keys(cursorMcpEnvObject).length;
                            if (cursorMcpAgentIds.length === 0) {
                              return `Snippets include AGENTS_API_BASE, LLM_PROVIDER (${llmLabel}), and the credential fields for that provider. Pick agents below to add MCP_ALLOWED_AGENT_IDS and merge each agent’s keys.`;
                            }
                            return `${n} key(s) in the header JSON — ${llmLabel} LLM block, ${cursorMcpAgentIds.length} agent(s), AGENTS_API_BASE, and MCP_ALLOWED_AGENT_IDS (only those tools appear in the IDE).`;
                          })()}
                        </span>
                      </p>
                    </CursorWorkflowStep>

                    <CursorWorkflowStep
                      step={4}
                      title="Copy a snippet"
                      subtitle="Local dev or deployed API"
                      icon={<Copy className="h-3.5 w-3.5 text-gray-600 dark:text-gray-400" strokeWidth={2} aria-hidden />}
                    >
                      <p className="font-body mb-3 text-[11px] leading-relaxed text-gray-500 dark:text-gray-400">
                        Replace placeholders with real secrets. No <Code>headers</Code> support? Pass <Code>user_config</Code> on each tool call instead.
                      </p>
                      <div className="space-y-3">
                        <CodeBlock
                          code={cursorSseLocalConfig}
                          copyKey="cursor-sse-local"
                          copied={copied}
                          onCopy={copy}
                          label="Local · localhost /mcp + header"
                          fileName=".cursor/mcp.json"
                        />
                        <CodeBlock
                          code={cursorSseRemoteConfig}
                          copyKey="cursor-sse-remote"
                          copied={copied}
                          onCopy={copy}
                          label="Deployed · https://your-host/mcp + AGENTS_API_BASE"
                          fileName=".cursor/mcp.json"
                        />
                      </div>
                    </CursorWorkflowStep>
                  </div>
                </StepCard>

                <StepCard
                  step={2}
                  title="Reload Cursor"
                  description="Restart Cursor or press Ctrl+Shift+P and run 'Developer: Reload Window'. The MCP server will appear in the tools list."
                />

                <StepCard
                  step={3}
                  title="Use any agent"
                  description={<>Open the <strong>Agent</strong> or <strong>Chat</strong> panel (<Code>Ctrl+L</Code>), then ask naturally:</>}
                >
                  <CodeBlock
                    code={`Use the jira_agent tool to show me the project dashboard with analytics\n\nUse the brd_generation tool to create a BRD for a mobile banking app\n\nUse the web_search_agent tool to find the latest AI developments`}
                    copyKey="cursor-examples"
                    copied={copied}
                    onCopy={copy}
                    label="Example prompts"
                    lang="text"
                    fileName="prompts.txt"
                  />
                </StepCard>
              </div>
            </section>

            {/* ── VS Code ─────────────────────────────── */}
            <section id="section-vscode">
              <SectionHeader icon={<VSCodeIcon />} title="VS Code" subtitle="Use with GitHub Copilot MCP support" />
              <div className="mt-6 space-y-4">
                <StepCard
                  step={1}
                  title="Enable MCP in Copilot"
                  description={<>Make sure you have <strong>GitHub Copilot</strong> with MCP support enabled. Go to VS Code Settings and enable <Code>chat.mcp.enabled</Code>.</>}
                />

                <StepCard
                  step={2}
                  title="Create the MCP config"
                  description={
                    <>
                      Create <Code>.vscode/mcp.json</Code> in your project root. The snippet below stays in sync with the{' '}
                      <button
                        type="button"
                        onClick={() => scrollTo('cursor')}
                        className="font-semibold text-primary-600 underline decoration-primary-600/30 underline-offset-2 hover:text-primary-700 dark:text-primary-400 dark:hover:text-primary-300"
                      >
                        Cursor IDE
                      </button>{' '}
                      section — selected agents and credential fields update <Code>X-Marketplace-Agent-Env</Code> here automatically.
                    </>
                  }
                >
                  <div className="mb-3">
                    <button
                      type="button"
                      disabled={isLoading}
                      onClick={() => downloadTextFile('mcp.json', vscodeMcpConfig)}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-primary-600 px-3 py-2 font-body text-xs font-semibold text-gray-900 dark:text-white shadow-sm transition-colors hover:bg-primary-700 disabled:pointer-events-none disabled:opacity-50 dark:bg-primary-500 dark:hover:bg-primary-600"
                      title="Downloads mcp.json for .vscode/ — localhost /mcp/sse (SSE) and current X-Marketplace-Agent-Env"
                    >
                      <FileDown className="h-3.5 w-3.5 shrink-0" strokeWidth={2} aria-hidden />
                      Generate .vscode/mcp.json
                    </button>
                  </div>
                  <CodeBlock
                    code={vscodeMcpConfig}
                    copyKey="vscode-all"
                    copied={copied}
                    onCopy={copy}
                    label="MCP server config (localhost)"
                    fileName=".vscode/mcp.json"
                  />
                </StepCard>

                <StepCard
                  step={3}
                  title="Use agents in Copilot Chat"
                  description={<>Open <strong>Copilot Chat</strong> (<Code>Ctrl+Shift+I</Code>), switch to <strong>Agent</strong> mode, and invoke tools by name or let Copilot route automatically.</>}
                >
                  <CodeBlock
                    code={`Use the jira_agent tool to search for open bugs\n\nUse the shannon_security tool to scan https://example.com`}
                    copyKey="vscode-examples"
                    copied={copied}
                    onCopy={copy}
                    label="Example prompts"
                    lang="text"
                    fileName="prompts.txt"
                  />
                </StepCard>
              </div>
            </section>

            {/* ── FAQ ──────────────────────────────────── */}
            <section id="section-faq">
              <SectionHeader icon={<Zap className="w-5 h-5" />} title="FAQ & Troubleshooting" subtitle="Common questions and solutions" />
              <div className="mt-6 space-y-3">
                <FaqItem q="Do I need to install anything locally?" a={'No. The MCP server runs inside the FastAPI process. Cursor should use the Streamable HTTP URL (`/mcp`). VS Code with `type: "sse"` uses `/mcp/sse`. Add the URL and headers to your MCP config — no extra local install.'} />
                <FaqItem q="How do I add a new agent?" a="Add the agent via the admin catalog editor (PUT /api/catalog) or update the agents catalog in MongoDB. The MCP server reads the catalog dynamically — your IDE will see the new tool on the next connection." />
                <FaqItem q="Can I use a specific agent only?" a="Yes. In the Cursor IDE section, select agents in the picker — the generated header includes MCP_ALLOWED_AGENT_IDS so the MCP server only lists those tools. Omit that key (or use an empty selection in older snippets) to expose every active agent. You can also point to an individual agent endpoint — see each agent&apos;s Docs tab." />
                <FaqItem q='I get "Cannot connect to the agents server"' a="Make sure the FastAPI server is running and the URL matches your setup: for Cursor use `http://localhost:8000/mcp` (or your deployed `https://host/mcp`). For VS Code SSE, use `…/mcp/sse`. Your reverse proxy must allow GET, POST, and DELETE on `/mcp` when using Streamable HTTP." />
                <FaqItem q='Cursor shows "Server creation failed" or "Client closed"' a="This usually means the URL is wrong or the server isn't running. Double-check the URL in .cursor/mcp.json. After fixing, restart Cursor to reconnect." />
                <FaqItem q="Is there a timeout for long-running agents?" a="Yes. The MCP server has a 180-second timeout per tool call. Agents like Market Research or Company Research that do extensive web scraping will complete within this window." />
                <FaqItem q="Can multiple users connect to the same deployed server?" a="Yes. Each IDE session gets its own MCP session (Streamable HTTP or SSE). Scale the API tier if many concurrent tool calls hit the same host." />
                <FaqItem q="How do I use my own JIRA / API keys with MCP?" a="Put catalog keys as a JSON string in headers X-Marketplace-Agent-Env in .cursor/mcp.json or .vscode/mcp.json (or pass user_config on each tool call). The MCP layer forwards them to the API. Use the Cursor IDE section on this page to merge keys from selected agents — the VS Code snippet updates to match." />
                <FaqItem q="Does the server use .env for my credentials?" a="For remote HTTP MCP (Cursor URL transport), catalog keys come only from X-Marketplace-Agent-Env and per-call user_config — not from the server&apos;s .env. Use stdio MCP with mcp.json `env` if you want the IDE to inject env vars into the MCP process instead." />
              </div>
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Sub-components ──────────────────────────────────────── */

function SectionHeader({ icon, title, subtitle, badge }: { icon: React.ReactNode; title: string; subtitle: string; badge?: string }) {
  return (
    <div className="flex items-start gap-3">
      <div className="mt-1 w-9 h-9 bg-primary-100 dark:bg-primary-900/30 rounded-lg flex items-center justify-center text-primary-600 dark:text-primary-400 shrink-0">
        {icon}
      </div>
      <div>
        <div className="flex items-center gap-2">
          <h2 className="font-heading text-xl font-bold text-gray-900 dark:text-white">{title}</h2>
          {badge && <span className="px-2 py-0.5 bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 font-body text-[10px] font-bold uppercase tracking-wider rounded-full">{badge}</span>}
        </div>
        <p className="font-body text-sm text-gray-500 dark:text-gray-400 mt-0.5">{subtitle}</p>
      </div>
    </div>
  );
}

function FeatureCard({ icon, title, description }: { icon: React.ReactNode; title: string; description: string }) {
  return (
    <div className="p-5 bg-white dark:bg-gray-900/50 border border-gray-100 dark:border-gray-800 rounded-xl">
      <div className="mb-3">{icon}</div>
      <h3 className="font-heading text-sm font-bold text-gray-900 dark:text-white mb-1">{title}</h3>
      <p className="font-body text-xs text-gray-500 dark:text-gray-400 leading-relaxed">{description}</p>
    </div>
  );
}

function StepPill({ n, text }: { n: number; text: string }) {
  return (
    <span className="inline-flex items-center gap-2 px-3 py-1.5 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
      <span className="w-5 h-5 bg-primary-500 text-gray-900 dark:text-white text-[10px] font-bold rounded-full flex items-center justify-center">{n}</span>
      <span className="text-xs font-medium">{text}</span>
    </span>
  );
}

function CursorWorkflowStep({
  step: stepNum,
  title,
  subtitle,
  icon,
  children,
}: {
  step: number;
  title: string;
  subtitle?: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="overflow-hidden rounded-xl border border-gray-200/85 bg-white shadow-sm dark:border-gray-800/90 dark:bg-gray-900/45 dark:shadow-none">
      <div className="flex min-w-0">
        <div
          className="w-1 shrink-0 bg-gradient-to-b from-primary-500 via-violet-500 to-primary-600 opacity-95"
          aria-hidden
        />
        <div className="min-w-0 flex-1 p-3.5 sm:p-4">
          <div className="flex items-start gap-3">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gray-100 text-xs font-bold text-gray-700 dark:bg-gray-800 dark:text-gray-200">
              {stepNum}
            </span>
            <div className="min-w-0 flex-1 pt-0.5">
              <div className="flex flex-wrap items-center gap-2">
                <h4 className="font-heading text-sm font-semibold tracking-tight text-gray-900 dark:text-white">{title}</h4>
                {icon}
              </div>
              {subtitle ? (
                <p className="font-body mt-0.5 text-[11px] leading-snug text-gray-500 dark:text-gray-400">{subtitle}</p>
              ) : null}
            </div>
          </div>
          <div className="mt-3 border-t border-gray-100 pt-3 dark:border-gray-800/80 sm:ml-11 sm:border-t-0 sm:pt-0">
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}

function StepCard({
  step,
  title,
  description,
  children,
  variant = 'default',
}: {
  step: number;
  title: string;
  description: React.ReactNode;
  children?: React.ReactNode;
  variant?: 'default' | 'modern';
}) {
  if (variant === 'modern') {
    return (
      <div className="overflow-visible rounded-2xl border border-gray-200/90 bg-gradient-to-b from-white via-white to-gray-50/95 shadow-lg shadow-gray-900/[0.05] ring-1 ring-black/[0.04] dark:border-gray-800 dark:from-gray-900 dark:via-gray-900/95 dark:to-gray-950 dark:shadow-black/30 dark:ring-white/[0.06]">
        <div className="h-1 overflow-hidden rounded-t-2xl bg-gradient-to-r from-primary-500 via-violet-500 to-primary-600" aria-hidden />
        <div className="p-5 sm:p-6">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:gap-5">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary-500 to-primary-700 text-sm font-bold text-gray-900 dark:text-white shadow-md shadow-primary-900/20">
              {step}
            </span>
            <div className="min-w-0 flex-1">
              <h3 className="font-heading text-lg font-bold tracking-tight text-gray-900 dark:text-white">{title}</h3>
              <p className="font-body mt-1 text-sm leading-relaxed text-gray-600 dark:text-gray-400">{description}</p>
            </div>
          </div>
          {children && (
            <div className="mt-6 rounded-xl border border-gray-200/70 bg-gray-50/40 p-3.5 dark:border-gray-800/70 dark:bg-gray-950/35 sm:mt-5 sm:p-4">
              {children}
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-gray-100 bg-white p-5 dark:border-gray-800 dark:bg-gray-900/50">
      <div className="mb-3 flex items-start gap-3">
        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary-500 text-xs font-bold text-gray-900 dark:text-white">{step}</span>
        <div>
          <h3 className="font-heading text-sm font-bold text-gray-900 dark:text-white">{title}</h3>
          <p className="font-body mt-0.5 text-xs leading-relaxed text-gray-500 dark:text-gray-400">{description}</p>
        </div>
      </div>
      {children && <div className="ml-9">{children}</div>}
    </div>
  );
}

const JSON_TOKENS: Record<string, string> = {
  key: 'text-sky-300',
  str: 'text-emerald-300/90',
  num: 'text-amber-300',
  kw: 'text-violet-300',
  sym: 'text-slate-500',
  plain: 'text-slate-400',
  ws: '',
};

function tokenizeJsonLine(line: string): Array<{ k: keyof typeof JSON_TOKENS; text: string }> {
  const out: Array<{ k: keyof typeof JSON_TOKENS; text: string }> = [];
  let i = 0;
  while (i < line.length) {
    const ch = line[i];
    if (/\s/.test(ch)) {
      let j = i;
      while (j < line.length && /\s/.test(line[j])) j++;
      out.push({ k: 'ws', text: line.slice(i, j) });
      i = j;
      continue;
    }
    if (ch === '"') {
      let j = i + 1;
      let closed = false;
      while (j < line.length) {
        if (line[j] === '\\') {
          j += 2;
          continue;
        }
        if (line[j] === '"') {
          j++;
          closed = true;
          break;
        }
        j++;
      }
      const raw = line.slice(i, j);
      let k = j;
      while (k < line.length && /\s/.test(line[k])) k++;
      const isKey = closed && line[k] === ':';
      out.push({ k: isKey ? 'key' : 'str', text: raw });
      i = j;
      continue;
    }
    if (/[-0-9]/.test(ch)) {
      let j = i;
      while (j < line.length && /[0-9.eE+-]/.test(line[j])) j++;
      out.push({ k: 'num', text: line.slice(i, j) });
      i = j;
      continue;
    }
    if ('{}[],:'.includes(ch)) {
      out.push({ k: 'sym', text: ch });
      i++;
      continue;
    }
    if (/[a-z]/.test(ch)) {
      let j = i;
      while (j < line.length && /[a-z]/.test(line[j])) j++;
      const w = line.slice(i, j);
      out.push({ k: /^(true|false|null)$/.test(w) ? 'kw' : 'plain', text: w });
      i = j;
      continue;
    }
    out.push({ k: 'plain', text: ch });
    i++;
  }
  return out;
}

function CodeBlock({
  code,
  copyKey,
  copied,
  onCopy,
  label,
  lang = 'json',
  fileName,
}: {
  code: string;
  copyKey: string;
  copied: string | null;
  onCopy: (text: string, key: string) => void;
  label?: string;
  lang?: string;
  fileName?: string;
}) {
  const lines = code.split('\n');
  const tabLabel = fileName ?? (lang === 'json' ? 'config.json' : 'untitled');
  const langBadge = lang === 'json' ? 'JSON' : lang === 'text' ? 'TEXT' : lang.toUpperCase();

  return (
    <div>
      {label ? (
        <p className="font-body mb-2 text-[11px] font-medium text-gray-600 dark:text-gray-400">{label}</p>
      ) : null}
      <div
        className="overflow-hidden rounded-xl border border-gray-800/90 bg-[#1e1e1e] shadow-[0_12px_40px_-12px_rgba(0,0,0,0.45)] ring-1 ring-white/[0.06] dark:border-gray-950 dark:bg-[#161616] dark:shadow-black/50"
        data-language={lang}
      >
        <div className="flex h-9 items-center gap-2 border-b border-black/40 bg-[#2d2d2d] px-2.5 dark:border-white/[0.06] dark:bg-[#252526]">
          <span className="flex shrink-0 gap-1.5 pl-0.5" aria-hidden>
            <span className="h-2.5 w-2.5 rounded-full bg-[#ff5f57] shadow-inner shadow-black/20" />
            <span className="h-2.5 w-2.5 rounded-full bg-[#febc2e] shadow-inner shadow-black/20" />
            <span className="h-2.5 w-2.5 rounded-full bg-[#28c840] shadow-inner shadow-black/20" />
          </span>
          <div className="flex min-w-0 flex-1 items-center justify-center gap-1.5 px-2">
            <FileCode className="h-3.5 w-3.5 shrink-0 text-gray-500" strokeWidth={1.75} aria-hidden />
            <span className="truncate font-mono text-[11px] font-medium text-gray-200">{tabLabel}</span>
          </div>
          <span className="shrink-0 rounded bg-black/25 px-1.5 py-0.5 font-mono text-[9px] font-semibold uppercase tracking-wide text-gray-500">
            {langBadge}
          </span>
          <button
            onClick={() => onCopy(code, copyKey)}
            className="flex shrink-0 items-center gap-1 rounded-md border border-gray-200 dark:border-white/10 bg-white/5 px-2 py-1 font-mono text-[10px] font-medium text-gray-700 dark:text-gray-300 transition-colors hover:border-primary-500/40 hover:bg-primary-500/15 hover:text-primary-200"
            title="Copy to clipboard"
            type="button"
          >
            {copied === copyKey ? (
              <>
                <Check className="h-3 w-3 text-emerald-400" strokeWidth={2.5} />
                <span className="hidden sm:inline">Copied</span>
              </>
            ) : (
              <>
                <Copy className="h-3 w-3 text-gray-600 dark:text-gray-400" strokeWidth={2} />
                <span className="hidden sm:inline">Copy</span>
              </>
            )}
          </button>
        </div>
        <div className="max-h-[min(420px,55vh)] overflow-y-auto overscroll-contain">
          <div className="flex min-w-0">
            <div
              className="shrink-0 select-none border-r border-gray-200 dark:border-white/[0.06] bg-[#1a1a1a] py-3 pl-3 pr-2.5 text-right font-mono text-[10px] leading-[1.55] tabular-nums text-gray-600 dark:bg-[#121212] dark:text-gray-600"
              aria-hidden
            >
              {lines.map((_, idx) => (
                <div key={idx}>{idx + 1}</div>
              ))}
            </div>
            <pre className="min-w-0 flex-1 overflow-x-auto py-3 pr-3 pl-2 sm:pr-4">
              <code className="font-mono text-[11px] leading-[1.55]">
              {lang === 'json'
                ? lines.map((line, row) => (
                    <span key={row} className="block whitespace-pre">
                      {tokenizeJsonLine(line).map((t, col) => (
                        <span key={col} className={JSON_TOKENS[t.k] || undefined}>
                          {t.text}
                        </span>
                      ))}
                    </span>
                  ))
                : lines.map((line, row) => (
                    <span key={row} className="block whitespace-pre text-gray-700 dark:text-gray-300">
                      {line}
                    </span>
                  ))}
              </code>
            </pre>
          </div>
        </div>
      </div>
    </div>
  );
}

function Code({ children }: { children: React.ReactNode }) {
  return <code className="text-xs bg-gray-200 dark:bg-gray-700 text-gray-800 dark:text-gray-200 px-1.5 py-0.5 rounded">{children}</code>;
}

function FaqItem({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border border-gray-100 dark:border-gray-800 rounded-xl overflow-hidden">
      <button onClick={() => setOpen(!open)} className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-gray-50 dark:hover:bg-gray-900/30 transition-colors">
        <span className="font-body text-sm font-semibold text-gray-900 dark:text-white pr-4">{q}</span>
        <ArrowRight className={`w-4 h-4 text-gray-600 dark:text-gray-400 shrink-0 transition-transform ${open ? 'rotate-90' : ''}`} />
      </button>
      {open && (
        <div className="px-5 pb-4">
          <p className="font-body text-sm text-gray-600 dark:text-gray-300 leading-relaxed">{a}</p>
        </div>
      )}
    </div>
  );
}
