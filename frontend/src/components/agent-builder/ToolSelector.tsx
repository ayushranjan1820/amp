import { useState, useEffect, useMemo, useCallback } from 'react';
import {
  Search, Wrench, Globe, Code, Database, Mail, FileText, Monitor, Loader2,
  Cpu, Shield, Zap, MessageSquare, Image, Volume2, Hash, Clock, BookOpen,
  GitBranch, Key, ChevronDown, Settings, BarChart3, Eye, EyeOff,
  CheckCircle, AlertTriangle, X, Plus, HardDrive, Cloud, Inbox,
} from 'lucide-react';
import { listTools, REDACTED_SENTINEL, type ToolDefinition, type CustomAgent, type ToolRef } from '../../services/agentBuilder';
import { connectGoogle, disconnectGoogle, getGoogleOAuthConfig, GMAIL_SCOPES, DRIVE_SCOPES } from '../../services/googleAuth';

// ─── Icon map ────────────────────────────────────────────────────────────────

const TOOL_ICONS: Record<string, React.ReactNode> = {
  tool_web_search:         <Globe className="w-5 h-5" />,
  tool_web_scrape:         <Globe className="w-5 h-5" />,
  tool_llm_call:           <Cpu className="w-5 h-5" />,
  tool_ocr:                <Image className="w-5 h-5" />,
  tool_text_to_speech:     <Volume2 className="w-5 h-5" />,
  tool_embeddings:         <Zap className="w-5 h-5" />,
  tool_file_processor:     <FileText className="w-5 h-5" />,
  tool_csv_analyzer:       <BarChart3 className="w-5 h-5" />,
  tool_document_formatter: <FileText className="w-5 h-5" />,
  tool_ppt_generator:      <FileText className="w-5 h-5" />,
  tool_brd_generator:      <BookOpen className="w-5 h-5" />,
  tool_email_composer:     <Mail className="w-5 h-5" />,
  tool_code_executor:      <Code className="w-5 h-5" />,
  tool_unit_test_gen:      <Code className="w-5 h-5" />,
  tool_jira:               <Settings className="w-5 h-5" />,
  tool_github:             <GitBranch className="w-5 h-5" />,
  tool_slack_notify:       <MessageSquare className="w-5 h-5" />,
  tool_google_drive:       <HardDrive className="w-5 h-5" />,
  tool_sharepoint:         <Cloud className="w-5 h-5" />,
  tool_gmail:              <Mail className="w-5 h-5" />,
  tool_outlook:            <Inbox className="w-5 h-5" />,
  tool_zoho_mail:          <Mail className="w-5 h-5" />,
  tool_zoho_calendar:      <Clock className="w-5 h-5" />,
  tool_zoho_crm:           <BarChart3 className="w-5 h-5" />,
  tool_zoho_desk:          <Inbox className="w-5 h-5" />,
  tool_zoho_cliq:          <MessageSquare className="w-5 h-5" />,
  tool_sql_query:          <Database className="w-5 h-5" />,
  tool_mongodb:            <Database className="w-5 h-5" />,
  tool_etl_transform:      <Database className="w-5 h-5" />,
  tool_http_api:           <Globe className="w-5 h-5" />,
  tool_browser_automation: <Monitor className="w-5 h-5" />,
  tool_security_scan:      <Shield className="w-5 h-5" />,
  tool_json_processor:     <Hash className="w-5 h-5" />,
  tool_regex:              <Code className="w-5 h-5" />,
  tool_calculator:         <Hash className="w-5 h-5" />,
  tool_datetime:           <Clock className="w-5 h-5" />,
  tool_knowledge_base:     <BookOpen className="w-5 h-5" />,
};

const CATEGORY_META: Record<string, { label: string; icon: React.ReactNode; color: string }> = {
  search:        { label: 'Search & Research',    icon: <Globe className="w-4 h-4" />,    color: 'text-blue-400' },
  ai:            { label: 'LLM & AI',             icon: <Cpu className="w-4 h-4" />,      color: 'text-violet-400' },
  files:         { label: 'File Processing',       icon: <FileText className="w-4 h-4" />, color: 'text-amber-400' },
  content:       { label: 'Content Generation',    icon: <Zap className="w-4 h-4" />,      color: 'text-pink-400' },
  code:          { label: 'Code & Execution',      icon: <Code className="w-4 h-4" />,     color: 'text-green-400' },
  integrations:  { label: 'Integrations',          icon: <Settings className="w-4 h-4" />, color: 'text-orange-400' },
  data:          { label: 'Database & Data',       icon: <Database className="w-4 h-4" />, color: 'text-cyan-400' },
  communication: { label: 'Communication & HTTP',  icon: <Globe className="w-4 h-4" />,    color: 'text-blue-400' },
  automation:    { label: 'Browser & Automation',  icon: <Monitor className="w-4 h-4" />,  color: 'text-indigo-400' },
  security:      { label: 'Security & Compliance', icon: <Shield className="w-4 h-4" />,   color: 'text-red-400' },
  utilities:     { label: 'Utilities',             icon: <Wrench className="w-4 h-4" />,   color: 'text-gray-600 dark:text-gray-400' },
};

// ─── Env key metadata (label, placeholder, whether to mask) ──────────────────

interface EnvKeyMeta { label: string; placeholder: string; secret: boolean; help: string; visible_when?: { key: string; equals: string } }

const ENV_KEY_META: Record<string, EnvKeyMeta> = {
  OLLAMA_API_KEY:           { label: 'On-prem API Key',         placeholder: 'ollama-xxxxxxxxxxxxxxxx',             secret: true,  help: 'Get your key at https://ollama.com/settings/api-keys' },
  PWC_GENAI_API_KEY:        { label: 'PwC GenAI API Key',       placeholder: 'your-pwc-genai-api-key',             secret: true,  help: 'PwC GenAI platform credential' },
  PWC_GENAI_BEARER_TOKEN:   { label: 'PwC GenAI Bearer Token',  placeholder: 'your-bearer-token',                  secret: true,  help: 'Optional — used instead of API key for some tenants' },
  PWC_GENAI_ENDPOINT_URL:   { label: 'PwC GenAI Endpoint',      placeholder: 'https://genai-sharedservice-americas.pwc.com/completions', secret: false, help: 'Override for non-US regions' },
  ELEVENLABS_API_KEY:       { label: 'ElevenLabs API Key',      placeholder: 'el_xxxxxxxxxxxxxxxx',                secret: true,  help: 'Get your key at https://elevenlabs.io' },
  JIRA_URL:                 { label: 'JIRA Base URL',           placeholder: 'https://yourorg.atlassian.net',       secret: false, help: 'Your Atlassian site URL' },
  JIRA_EMAIL:               { label: 'JIRA Email',              placeholder: 'you@company.com',                    secret: false, help: 'Email linked to your JIRA account' },
  JIRA_API_TOKEN:           { label: 'JIRA API Token',          placeholder: 'your-jira-api-token',                secret: true,  help: 'Create at https://id.atlassian.com/manage-profile/security/api-tokens' },
  GITHUB_TOKEN:             { label: 'GitHub Token',            placeholder: 'ghp_xxxxxxxxxxxxxxxxxxxx',           secret: true,  help: 'Personal Access Token from github.com/settings/tokens' },
  SLACK_WEBHOOK_URL:        { label: 'Slack Webhook URL',       placeholder: 'https://hooks.slack.com/services/...',secret: true,  help: 'Incoming webhook URL from Slack app settings' },
  GOOGLE_DRIVE_ACCESS_TOKEN:{ label: 'Google Drive OAuth Token',placeholder: 'ya29.a0...',                         secret: true,  help: 'OAuth2 access token with drive scope. Generate via Google Cloud Console / OAuth playground.' },
  GMAIL_ACCESS_TOKEN:       { label: 'Gmail OAuth Token',       placeholder: 'ya29.a0...',                         secret: true,  help: 'OAuth2 token with gmail.modify scope (read + draft).' },
  MS_GRAPH_ACCESS_TOKEN:    { label: 'Microsoft Graph Token',   placeholder: 'eyJ0eXAi...',                        secret: true,  help: 'Bearer token from Azure AD with Mail.ReadWrite / Files.ReadWrite scopes.' },
  SHAREPOINT_SITE_ID:       { label: 'SharePoint Site ID',      placeholder: 'contoso.sharepoint.com,guid,guid',  secret: false, help: 'Optional. Omit to use the user\'s default OneDrive. Find via /sites?search=…' },
  DATABASE_URL:             { label: 'Database URL',            placeholder: 'postgresql://user:pass@host/db',      secret: true,  help: 'Connection string for your SQL database' },
  MONGODB_URI:              { label: 'MongoDB URI',             placeholder: 'mongodb+srv://user:pass@cluster.mongodb.net/', secret: true, help: 'MongoDB Atlas or self-hosted URI' },
  SMTP_HOST:                { label: 'SMTP Host',               placeholder: 'smtp.gmail.com',                     secret: false, help: 'Your email SMTP server hostname' },
  SMTP_USER:                { label: 'SMTP Username',           placeholder: 'you@gmail.com',                      secret: false, help: 'Email address for SMTP authentication' },
  SMTP_PASSWORD:            { label: 'SMTP Password',           placeholder: 'your-smtp-password',                 secret: true,  help: 'App password for your SMTP account' },
  ON_PREM_CLOUD_ACCESS_TOKEN:   { label: 'On-prem Cloud API Token', placeholder: 'your-ollama-cloud-token',            secret: true,  help: 'Get at https://ollama.com/settings/api-keys (same as OLLAMA_API_KEY)' },
  // Zoho MCP connection — pre-authorized in the Zoho MCP console, so no OAuth keys.
  ZOHO_MCP_URL:             { label: 'Zoho MCP Server URL',     placeholder: 'https://agent-000000.zohomcp.in/mcp/<key>/message', secret: true, help: 'Connection URL ending in /message. With Authorization via Connection enabled, this replaces the client id, secret and refresh token.', visible_when: { key: 'ZOHO_BACKEND', equals: 'mcp' } },
  ZOHO_BACKEND:             { label: 'Zoho Transport',          placeholder: 'mcp',                                secret: false, help: 'mcp or rest. Auto-selects mcp when an MCP URL is set.' },
  // Zoho REST fallback — one OAuth app covers Mail, Calendar, CRM, Desk and Cliq.
  ZOHO_CLIENT_ID:           { label: 'Zoho Client ID',          placeholder: '1000.ABCDEFGHIJKLMNOP',              secret: false, help: 'REST transport only. From your app in the Zoho API Console at https://api-console.zoho.com', visible_when: { key: 'ZOHO_BACKEND', equals: 'rest' } },
  ZOHO_CLIENT_SECRET:       { label: 'Zoho Client Secret',      placeholder: 'your-zoho-client-secret',            secret: true,  help: 'Client secret of the same Zoho API Console app', visible_when: { key: 'ZOHO_BACKEND', equals: 'rest' } },
  ZOHO_REFRESH_TOKEN:       { label: 'Zoho Refresh Token',      placeholder: '1000.abc123...',                     secret: true,  help: 'Generate with access_type=offline for the scopes you need. Long-lived; the access token is refreshed automatically.', visible_when: { key: 'ZOHO_BACKEND', equals: 'rest' } },
  ZOHO_ACCESS_TOKEN:        { label: 'Zoho Access Token',       placeholder: '1000.xyz789...',                     secret: true,  help: 'Optional. Usually left blank — it is fetched from the refresh token and expires hourly.' },
  ZOHO_DC:                  { label: 'Zoho Data Center',        placeholder: 'us',                                 secret: false, help: 'us, eu, in, au, jp, ca, cn or sa. Must match your account region or every call 404s.' },
  ZOHO_ACCOUNTS_BASE_URL:   { label: 'Zoho Accounts URL',       placeholder: 'https://accounts.zoho.com',          secret: false, help: 'Optional override for the accounts host. Takes precedence over the data center setting.' },
  ZOHO_ORG_ID:              { label: 'Zoho Desk Org ID',        placeholder: '700123456',                          secret: false, help: 'Required for Zoho Desk. Find it under Desk → Setup → Developer Space → API.' },
  ZOHO_CALENDAR_ID:         { label: 'Zoho Calendar UID',       placeholder: 'a1b2c3d4e5f6...',                    secret: false, help: 'Optional. Defaults to the account’s default calendar.' },
  ZOHO_CRM_OWNER_ID:        { label: 'Zoho CRM Owner ID',       placeholder: '4876543000000123456',                secret: false, help: 'Optional. CRM user who should own tasks this agent creates.' },
  ZOHO_PROJECTS_PORTAL_ID:  { label: 'Zoho Projects Portal ID', placeholder: 'Your numeric portal ID', secret: false, help: 'Required for Projects tasks on MCP and REST. Obtain the numeric ID using Get Portals; a portal name is not an ID.' },
  ZOHO_PROJECTS_PROJECT_ID: { label: 'Zoho Projects Project ID', placeholder: 'Your numeric project ID', secret: false, help: 'Required for Projects tasks on MCP and REST. Obtain the ID using Get Projects List for the selected portal.' },
  ZOHO_CLIQ_CHANNEL:        { label: 'Zoho Cliq Channel',       placeholder: 'support-escalations',                secret: false, help: 'Channel unique name (not display name) to post into. Required on MCP and on REST without a webhook.' },
  ZOHO_CLIQ_WEBHOOK_URL:    { label: 'Zoho Cliq Webhook URL',   placeholder: 'https://cliq.zoho.com/api/v2/channelsbyname/x/message?zapikey=...', secret: true, help: 'Incoming webhook. Used in preference to the channel API and needs no Cliq OAuth scope.' },
  ZOHO_DESK_DEPARTMENT_ID:  { label: 'Zoho Desk Department ID', placeholder: '700123456000000123',                 secret: false, help: 'Optional. Restricts ticket reads to one department.' },
  ZOHO_FROM_ADDRESS:        { label: 'Zoho Send-As Address',    placeholder: 'ops@yourcompany.com',                secret: false, help: 'Zoho mailbox that sends outbound mail. Defaults to the account’s primary address.' },
  ZOHO_TIMEZONE:            { label: 'Zoho Timezone',           placeholder: 'Asia/Kolkata',                       secret: false, help: 'IANA timezone for calendar events and due dates.' },
  ZOHO_MEETING_DURATION_MINUTES: { label: 'Default Meeting Length (min)', placeholder: '30',                       secret: false, help: 'Used when the request does not state a duration.' },
  ZOHO_DRY_RUN:             { label: 'Zoho Dry Run',            placeholder: 'true',                               secret: false, help: 'true plans writes without sending mail or creating records. Applies to MCP and REST.' },
  ZOHO_CONFIRM_WRITES:      { label: 'Zoho Confirm Writes',     placeholder: 'false',                              secret: false, help: 'Must be true (with dry run off) before any Zoho write executes. Applies to MCP and REST.' },
};

function isEnvKeyVisible(key: string, values: Record<string, string>): boolean {
  const rule = ENV_KEY_META[key]?.visible_when;
  if (!rule) return true;
  const value = values[rule.key]?.trim().toLowerCase()
    || (rule.key === 'ZOHO_BACKEND' ? (values.ZOHO_MCP_URL?.trim() ? 'mcp' : 'rest') : '');
  return value === rule.equals;
}

function getEnvKeyMeta(key: string): EnvKeyMeta {
  if (ENV_KEY_META[key]) return ENV_KEY_META[key];
  const lk = key.toLowerCase();
  const secret = lk.includes('key') || lk.includes('token') || lk.includes('secret') || lk.includes('password');
  const isUrl = lk.includes('url') || lk.includes('host') || lk.includes('endpoint');
  return {
    label: key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
    placeholder: isUrl ? 'https://...' : `your-${key.toLowerCase().replace(/_/g, '-')}`,
    secret,
    help: '',
  };
}

// ─── Google OAuth tool registry ──────────────────────────────────────────────

const GOOGLE_OAUTH_TOOLS: Record<string, { scopes: string[]; label: string }> = {
  tool_gmail:        { scopes: GMAIL_SCOPES, label: 'Gmail' },
  tool_google_drive: { scopes: DRIVE_SCOPES, label: 'Google Drive' },
};

// ─── Types ───────────────────────────────────────────────────────────────────

interface Props {
  agent: Partial<CustomAgent>;
  updateField: <K extends keyof CustomAgent>(key: K, value: CustomAgent[K]) => void;
  onUnconfiguredTools?: (names: string[]) => void;
}

type ConfigStatus = 'ok' | 'missing' | 'none';

// ─── Main component ──────────────────────────────────────────────────────────

export default function ToolSelector({ agent, updateField, onUnconfiguredTools }: Props) {
  const [tools, setTools] = useState<ToolDefinition[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [expandedCats, setExpandedCats] = useState<Set<string>>(new Set());

  // Config form state
  const [configuringId, setConfiguringId] = useState<string | null>(null);
  const [draftValues, setDraftValues] = useState<Record<string, string>>({});
  const [showSecrets, setShowSecrets] = useState<Set<string>>(new Set());
  const [configError, setConfigError] = useState('');

  // Google OAuth state
  const [googleBusy, setGoogleBusy] = useState<string | null>(null); // tool id currently connecting
  const [googleError, setGoogleError] = useState('');
  const [googleConfigured, setGoogleConfigured] = useState<boolean | null>(null);
  useEffect(() => {
    getGoogleOAuthConfig()
      .then(cfg => setGoogleConfigured(cfg.configured))
      .catch(() => setGoogleConfigured(false));
  }, []);

  useEffect(() => {
    listTools()
      .then(({ tools: t }) => setTools(t))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  // ── Helpers ──

  const dc = useMemo(() => (agent.default_config || {}) as Record<string, string>, [agent.default_config]);

  const getEnvKeys = useCallback((tool: ToolDefinition): string[] => {
    const sc = tool.schema_config as Record<string, unknown>;
    return (sc?.env_keys as string[]) || [];
  }, []);

  const getCategory = useCallback((tool: ToolDefinition): string => {
    const sc = tool.schema_config as Record<string, unknown>;
    return (sc?.category as string) || 'utilities';
  }, []);

  const selectedIds = useMemo(
    () => new Set((agent.tools_config || []).map((t: any) => (typeof t === 'string' ? t : t.id || t.name))),
    [agent.tools_config]
  );

  const getConfigStatus = useCallback((tool: ToolDefinition): ConfigStatus => {
    // Google OAuth tools: configured when an account is connected
    if (GOOGLE_OAUTH_TOOLS[tool.id]) {
      return dc.GOOGLE_CONNECTED_EMAIL ? 'ok' : 'missing';
    }
    const keys = getEnvKeys(tool);
    if (keys.length === 0) return 'none';
    // A redacted sentinel still counts as "set" — the value lives encrypted on the server
    const missing = keys.filter(k => {
      const v = dc[k];
      return !v || v === '';
    });
    return missing.length === 0 ? 'ok' : 'missing';
  }, [getEnvKeys, dc]);

  // Notify parent of unconfigured tools
  useEffect(() => {
    if (!onUnconfiguredTools) return;
    const unconfigured = Array.from(selectedIds)
      .map(id => tools.find(t => t.id === id))
      .filter((t): t is ToolDefinition => !!t && getConfigStatus(t) === 'missing')
      .map(t => t.name);
    onUnconfiguredTools(unconfigured);
  }, [selectedIds, tools, getConfigStatus, onUnconfiguredTools]);

  // ── Tool add / remove ──

  const addTool = useCallback((tool: ToolDefinition) => {
    const current = (agent.tools_config || []) as ToolRef[];
    updateField('tools_config', [
      ...current,
      { id: tool.id, name: tool.name, description: tool.description },
    ]);
  }, [agent.tools_config, updateField]);

  const removeTool = useCallback((toolId: string) => {
    const current = (agent.tools_config || []) as ToolRef[];
    updateField('tools_config', current.filter((t) => (t.id || t.name) !== toolId));
  }, [agent.tools_config, updateField]);

  // ── Click handler on a tool card ──

  const handleToolClick = (tool: ToolDefinition) => {
    if (configuringId === tool.id) {
      setConfiguringId(null);
      return;
    }
    if (selectedIds.has(tool.id)) {
      removeTool(tool.id);
      if (configuringId === tool.id) setConfiguringId(null);
      return;
    }
    // Google OAuth tools: open the connect panel
    if (GOOGLE_OAUTH_TOOLS[tool.id]) {
      setGoogleError('');
      setConfigError('');
      setConfiguringId(tool.id);
      return;
    }
    const envKeys = getEnvKeys(tool);
    if (envKeys.length === 0) {
      addTool(tool);
      return;
    }
    // Open inline config form
    const initial: Record<string, string> = {};
    for (const k of envKeys) initial[k] = dc[k] || '';
    setDraftValues(initial);
    setConfigError('');
    setConfiguringId(tool.id);
  };

  // ── Open config for an already-selected tool ──
  const handleReconfigure = (e: React.MouseEvent, tool: ToolDefinition) => {
    e.stopPropagation();
    if (GOOGLE_OAUTH_TOOLS[tool.id]) {
      setGoogleError('');
      setConfigError('');
      setConfiguringId(tool.id);
      return;
    }
    const envKeys = getEnvKeys(tool);
    const initial: Record<string, string> = {};
    for (const k of envKeys) initial[k] = dc[k] || '';
    setDraftValues(initial);
    setConfigError('');
    setConfiguringId(tool.id);
  };

  // ── Google OAuth handlers ──
  const handleGoogleConnect = useCallback(async (tool: ToolDefinition) => {
    setGoogleError('');
    if (!agent.id) {
      setGoogleError('Save the agent first (use the Save button) before connecting a Google account.');
      return;
    }
    const meta = GOOGLE_OAUTH_TOOLS[tool.id];
    if (!meta) return;
    setGoogleBusy(tool.id);
    try {
      const res = await connectGoogle(agent.id, meta.scopes);
      // Mirror the connection state into local default_config so the UI flips to "connected".
      // Secret values use REDACTED so autosave preserves the encrypted DB values.
      const newDc: Record<string, string> = {
        ...dc,
        GOOGLE_CONNECTED_EMAIL: res.email || dc.GOOGLE_CONNECTED_EMAIL || '',
        GOOGLE_ACCESS_TOKEN: REDACTED_SENTINEL,
        GMAIL_ACCESS_TOKEN: REDACTED_SENTINEL,
        GOOGLE_DRIVE_ACCESS_TOKEN: REDACTED_SENTINEL,
      };
      if (res.has_refresh_token) newDc.GOOGLE_REFRESH_TOKEN = REDACTED_SENTINEL;
      updateField('default_config', newDc);
      // Track env_keys so validateTools considers it complete
      const existingKeys = agent.required_env_keys || [];
      const envKeys = getEnvKeys(tool);
      updateField(
        'required_env_keys',
        Array.from(new Set([...existingKeys, ...envKeys, 'GOOGLE_CONNECTED_EMAIL'])),
      );
      if (!selectedIds.has(tool.id)) addTool(tool);
      setConfiguringId(null);
    } catch (e) {
      setGoogleError((e as Error).message || 'Connection failed');
    } finally {
      setGoogleBusy(null);
    }
  }, [agent.id, agent.required_env_keys, dc, updateField, getEnvKeys, selectedIds, addTool]);

  const handleGoogleDisconnect = useCallback(async () => {
    if (!agent.id) return;
    setGoogleError('');
    setGoogleBusy('__disconnect__');
    try {
      await disconnectGoogle(agent.id);
      const stripped = { ...dc };
      delete stripped.GOOGLE_CONNECTED_EMAIL;
      delete stripped.GOOGLE_ACCESS_TOKEN;
      delete stripped.GOOGLE_REFRESH_TOKEN;
      delete stripped.GOOGLE_TOKEN_EXPIRES_AT;
      delete stripped.GMAIL_ACCESS_TOKEN;
      delete stripped.GOOGLE_DRIVE_ACCESS_TOKEN;
      updateField('default_config', stripped);
    } catch (e) {
      setGoogleError((e as Error).message || 'Disconnect failed');
    } finally {
      setGoogleBusy(null);
    }
  }, [agent.id, dc, updateField]);

  // ── Confirm config: save keys and add/keep tool ──
  const handleConfirm = (tool: ToolDefinition) => {
    const envKeys = getEnvKeys(tool);
    const required = envKeys.filter(key => isEnvKeyVisible(key, draftValues));
    const missing = required.filter(k => !draftValues[k]?.trim());
    if (missing.length > 0) {
      setConfigError(`Please fill in: ${missing.map(k => getEnvKeyMeta(k).label).join(', ')}`);
      return;
    }
    // Save to default_config
    const newDc = { ...dc, ...Object.fromEntries(Object.entries(draftValues).filter(([, v]) => v.trim())) };
    updateField('default_config', newDc);
    // Update required_env_keys list
    const existingKeys = agent.required_env_keys || [];
    updateField('required_env_keys', Array.from(new Set([...existingKeys, ...envKeys])));
    // Add tool if not already selected
    if (!selectedIds.has(tool.id)) addTool(tool);
    setConfiguringId(null);
    setConfigError('');
  };

  const handleCancel = () => {
    setConfiguringId(null);
    setConfigError('');
  };

  const toggleSecret = (key: string) => {
    setShowSecrets(prev => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  };

  // ── Grouped data ──

  const grouped = useMemo(() => {
    const map = new Map<string, ToolDefinition[]>();
    const filtered = tools.filter(t =>
      !search ||
      t.name.toLowerCase().includes(search.toLowerCase()) ||
      t.description.toLowerCase().includes(search.toLowerCase())
    );
    for (const t of filtered) {
      const cat = getCategory(t);
      if (!map.has(cat)) map.set(cat, []);
      map.get(cat)!.push(t);
    }
    const order = Object.keys(CATEGORY_META);
    return [...map.entries()].sort(
      (a, b) =>
        (order.indexOf(a[0]) === -1 ? 99 : order.indexOf(a[0])) -
        (order.indexOf(b[0]) === -1 ? 99 : order.indexOf(b[0]))
    );
  }, [tools, search, getCategory]);

  useEffect(() => {
    if (grouped.length && expandedCats.size === 0) {
      setExpandedCats(new Set(grouped.map(([cat]) => cat)));
    }
  }, [grouped.length]);

  // ── Unconfigured tools for warning banner ──
  const unconfiguredSelected = useMemo(() =>
    Array.from(selectedIds)
      .map(id => tools.find(t => t.id === id))
      .filter((t): t is ToolDefinition => !!t && getConfigStatus(t) === 'missing'),
    [selectedIds, tools, getConfigStatus]
  );

  // ─────────────────────────────────────────────────────────────────────────
  // Render
  // ─────────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-5">
      {/* Header */}
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-1">Tools</h2>
        <p className="text-sm text-gray-500">
          Select the tools your agent can use. Tools that need API keys will ask you to configure them before being added.
        </p>
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
        <input
          type="search"
          name="agent-builder-tool-filter"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search tools..."
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
          data-1p-ignore
          data-lpignore="true"
          data-form-type="other"
          className="w-full pl-10 pr-4 py-2.5 rounded-xl bg-gray-100 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-violet-500/40 text-sm transition-colors"
        />
      </div>

      {/* Selected summary */}
      {selectedIds.size > 0 && (
        <div className={`rounded-xl border p-3 ${unconfiguredSelected.length > 0 ? 'bg-amber-500/5 border-amber-500/20' : 'bg-violet-500/5 border-violet-500/10'}`}>
          <div className="flex items-center justify-between mb-2">
            <span className={`text-xs font-semibold ${unconfiguredSelected.length > 0 ? 'text-amber-400' : 'text-violet-400'}`}>
              {selectedIds.size} tool{selectedIds.size > 1 ? 's' : ''} selected
              {unconfiguredSelected.length > 0 && ` · ${unconfiguredSelected.length} need configuration`}
            </span>
            <button
              onClick={() => { updateField('tools_config', []); setConfiguringId(null); }}
              className="text-xs text-gray-500 hover:text-red-400 transition-colors"
            >
              Clear all
            </button>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {Array.from(selectedIds).map(id => {
              const tool = tools.find(t => t.id === id);
              const status = tool ? getConfigStatus(tool) : 'none';
              return (
                <span
                  key={id}
                  className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium ring-1 ${
                    status === 'missing'
                      ? 'bg-amber-500/10 text-amber-400 ring-amber-500/20'
                      : 'bg-violet-500/10 text-violet-400 ring-violet-500/20'
                  }`}
                >
                  {status === 'missing'
                    ? <AlertTriangle className="w-3 h-3" />
                    : status === 'ok'
                    ? <CheckCircle className="w-3 h-3" />
                    : <span className="[&_svg]:w-3 [&_svg]:h-3">{TOOL_ICONS[id] || <Wrench className="w-3 h-3" />}</span>
                  }
                  {tool?.name || id}
                  {status === 'missing' && tool && (
                    <button
                      onClick={e => handleReconfigure(e, tool)}
                      className="ml-0.5 underline underline-offset-2 hover:text-gray-900 dark:hover:text-white transition-colors"
                    >
                      Configure
                    </button>
                  )}
                  <button
                    onClick={() => tool ? removeTool(tool.id) : removeTool(id)}
                    className="ml-0.5 hover:text-gray-900 dark:hover:text-white transition-colors leading-none"
                  >
                    &times;
                  </button>
                </span>
              );
            })}
          </div>
        </div>
      )}

      {/* Unconfigured warning */}
      {unconfiguredSelected.length > 0 && configuringId === null && (
        <div className="rounded-xl bg-amber-500/5 border border-amber-500/15 px-4 py-3 flex items-start gap-3">
          <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-amber-400">Configuration required</p>
            <p className="text-xs text-amber-400/70 mt-0.5">
              {unconfiguredSelected.map(t => t.name).join(', ')} need{unconfiguredSelected.length === 1 ? 's' : ''} API keys before your agent can use them.
              Click <strong>Configure</strong> on each tool to add the required credentials.
            </p>
          </div>
        </div>
      )}

      {/* Tool catalogue */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-6 h-6 text-violet-400 animate-spin" />
        </div>
      ) : grouped.length === 0 ? (
        <div className="text-center py-8 text-gray-500 text-sm">
          {search ? 'No tools match your search.' : 'No tools available.'}
        </div>
      ) : (
        <div className="space-y-3">
          {grouped.map(([cat, catTools]) => {
            const meta = CATEGORY_META[cat] || { label: cat, icon: <Wrench className="w-4 h-4" />, color: 'text-gray-600 dark:text-gray-400' };
            const isExpanded = expandedCats.has(cat);
            const selectedInCat = catTools.filter(t => selectedIds.has(t.id)).length;
            const unconfiguredInCat = catTools.filter(t => selectedIds.has(t.id) && getConfigStatus(t) === 'missing').length;

            return (
              <div key={cat} className="rounded-xl border border-gray-200 dark:border-white/[0.06] overflow-hidden">
                {/* Category header */}
                <button
                  onClick={() => {
                    setExpandedCats(prev => {
                      const next = new Set(prev);
                      next.has(cat) ? next.delete(cat) : next.add(cat);
                      return next;
                    });
                  }}
                  className="w-full flex items-center gap-3 px-4 py-3 bg-gray-50 dark:bg-white/[0.02] hover:bg-gray-100 dark:hover:bg-white/[0.04] transition-colors"
                >
                  <span className={meta.color}>{meta.icon}</span>
                  <span className="text-sm font-semibold text-gray-900 dark:text-white flex-1 text-left">{meta.label}</span>
                  <span className="text-xs text-gray-400 dark:text-gray-600">{catTools.length} tools</span>
                  {unconfiguredInCat > 0 && (
                    <span className="px-1.5 py-0.5 rounded-full bg-amber-500/15 text-amber-400 text-[10px] font-bold">
                      ⚠ {unconfiguredInCat}
                    </span>
                  )}
                  {selectedInCat > 0 && unconfiguredInCat === 0 && (
                    <span className="px-1.5 py-0.5 rounded-full bg-violet-500/15 text-violet-400 text-[10px] font-bold">
                      {selectedInCat}
                    </span>
                  )}
                  <ChevronDown className={`w-4 h-4 text-gray-500 transition-transform ${isExpanded ? 'rotate-180' : ''}`} />
                </button>

                {/* Tool grid */}
                {isExpanded && (
                  <div className="p-3 space-y-2">
                    {catTools.map(tool => {
                      const isSelected = selectedIds.has(tool.id);
                      const isConfiguring = configuringId === tool.id;
                      const envKeys = getEnvKeys(tool);
                      const status = isSelected ? getConfigStatus(tool) : 'none';
                      const hasKeys = envKeys.length > 0;

                      return (
                        <div
                          key={tool.id}
                          className={`rounded-xl border transition-all overflow-hidden ${
                            isConfiguring
                              ? 'border-violet-500/50 bg-violet-500/5 ring-1 ring-violet-500/20'
                              : isSelected
                              ? status === 'missing'
                                ? 'border-amber-500/30 bg-amber-500/5'
                                : 'border-violet-500/40 bg-violet-500/5 ring-1 ring-violet-500/20'
                              : 'border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-white/[0.01] hover:border-gray-300 dark:hover:border-white/[0.12] hover:bg-gray-50 dark:hover:bg-white/[0.03]'
                          }`}
                        >
                          {/* Tool card header — always clickable */}
                          <div
                            className="flex items-start gap-3 p-3.5 cursor-pointer"
                            onClick={() => handleToolClick(tool)}
                          >
                            {/* Icon */}
                            <div className={`w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 ${
                              isConfiguring ? 'bg-violet-500/25 text-violet-300'
                              : isSelected && status === 'ok' ? 'bg-violet-500/20 text-violet-400'
                              : isSelected && status === 'missing' ? 'bg-amber-500/15 text-amber-400'
                              : 'bg-gray-100 dark:bg-white/[0.06] text-gray-600 dark:text-gray-400'
                            }`}>
                              {TOOL_ICONS[tool.id] || <Wrench className="w-5 h-5" />}
                            </div>

                            {/* Info */}
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 flex-wrap">
                                <span className="font-medium text-gray-900 dark:text-white text-sm leading-tight">{tool.name}</span>
                                {/* Status badges */}
                                {isSelected && status === 'ok' && (
                                  <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-green-400">
                                    <CheckCircle className="w-3 h-3" /> Configured
                                  </span>
                                )}
                                {isSelected && status === 'missing' && (
                                  <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-amber-400">
                                    <AlertTriangle className="w-3 h-3" /> Needs config
                                  </span>
                                )}
                                {!isSelected && hasKeys && (
                                  <span className="inline-flex items-center gap-1 text-[10px] text-amber-500/70">
                                    <Key className="w-3 h-3" /> Requires API key
                                  </span>
                                )}
                                {isSelected && !hasKeys && (
                                  <span className="w-4 h-4 rounded-full bg-violet-500 flex items-center justify-center flex-shrink-0">
                                    <svg className="w-2.5 h-2.5 text-gray-900 dark:text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" /></svg>
                                  </span>
                                )}
                              </div>
                              <p className="text-[11px] text-gray-500 mt-0.5 line-clamp-2 leading-relaxed">
                                {tool.description}
                              </p>
                              {!isSelected && hasKeys && (
                                <p className="text-[10px] text-amber-500/50 mt-1 font-mono">
                                  {envKeys.join(' · ')}
                                </p>
                              )}
                            </div>

                            {/* Right actions */}
                            <div className="flex items-center gap-1.5 flex-shrink-0 ml-1" onClick={e => e.stopPropagation()}>
                              {isSelected && status === 'missing' && (
                                <button
                                  onClick={e => handleReconfigure(e, tool)}
                                  className="px-2 py-1 rounded-lg bg-amber-500/10 hover:bg-amber-500/20 text-amber-400 text-[10px] font-semibold transition-colors"
                                >
                                  Configure
                                </button>
                              )}
                              {isSelected && status === 'ok' && hasKeys && (
                                <button
                                  onClick={e => handleReconfigure(e, tool)}
                                  className="px-2 py-1 rounded-lg bg-gray-100 dark:bg-white/[0.06] hover:bg-gray-200 dark:hover:bg-white/[0.1] text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white text-[10px] transition-colors"
                                >
                                  Edit
                                </button>
                              )}
                            </div>
                          </div>

                          {/* ── Inline Config Form ── */}
                          {isConfiguring && GOOGLE_OAUTH_TOOLS[tool.id] && (
                            <div
                              className="border-t border-violet-500/20 px-4 pb-4 pt-3 space-y-4"
                              onClick={e => e.stopPropagation()}
                            >
                              <div className="flex items-center gap-2 mb-1">
                                <Key className="w-4 h-4 text-violet-400" />
                                <span className="text-sm font-semibold text-gray-900 dark:text-white">Connect — {tool.name}</span>
                                <button
                                  onClick={handleCancel}
                                  className="ml-auto p-1 rounded-lg hover:bg-gray-100 dark:hover:bg-white/[0.08] text-gray-500 hover:text-gray-700 dark:text-gray-300 transition-colors"
                                >
                                  <X className="w-4 h-4" />
                                </button>
                              </div>

                              {googleConfigured === false && (
                                <div className="rounded-lg bg-amber-500/8 border border-amber-500/20 px-3 py-2.5 text-xs text-amber-300/90 space-y-1">
                                  <p className="font-semibold flex items-center gap-1.5"><AlertTriangle className="w-3.5 h-3.5" /> Google OAuth not set up on the server</p>
                                  <p className="text-amber-300/70 leading-relaxed">
                                    Ask an admin to create a <strong>Web application</strong> OAuth client at
                                    {' '}<span className="font-mono">console.cloud.google.com → APIs & Services → Credentials</span>,
                                    then set <span className="font-mono">GOOGLE_OAUTH_CLIENT_ID</span> and
                                    {' '}<span className="font-mono">GOOGLE_OAUTH_CLIENT_SECRET</span> in the server env.
                                    Add <span className="font-mono">https://your-app/</span> to authorized JS origins.
                                  </p>
                                </div>
                              )}

                              {!agent.id && (
                                <div className="rounded-lg bg-amber-500/5 border border-amber-500/20 px-3 py-2 text-xs text-amber-300">
                                  Save the agent first to enable Google connection.
                                </div>
                              )}

                              {dc.GOOGLE_CONNECTED_EMAIL ? (
                                <div className="space-y-3">
                                  <div className="flex items-center gap-3 px-3 py-3 rounded-lg bg-green-500/8 border border-green-500/20">
                                    <CheckCircle className="w-5 h-5 text-green-400 flex-shrink-0" />
                                    <div className="flex-1 min-w-0">
                                      <p className="text-xs text-gray-600 dark:text-gray-400">Connected as</p>
                                      <p className="text-sm font-mono text-gray-900 dark:text-white truncate">{dc.GOOGLE_CONNECTED_EMAIL}</p>
                                    </div>
                                  </div>
                                  <p className="text-[11px] text-gray-500 leading-relaxed">
                                    The agent will use this account at runtime via Google's official APIs. Tokens auto-refresh.
                                    Reconnect to grant additional scopes (e.g. Drive after Gmail).
                                  </p>
                                  <div className="flex gap-2">
                                    <button
                                      onClick={() => handleGoogleConnect(tool)}
                                      disabled={!agent.id || googleConfigured === false || googleBusy !== null}
                                      className="flex-1 inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-gray-100 dark:bg-white/[0.06] hover:bg-gray-200 dark:hover:bg-white/[0.1] text-gray-900 dark:text-white text-sm font-semibold transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                                    >
                                      {googleBusy === tool.id ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
                                      Reconnect
                                    </button>
                                    <button
                                      onClick={handleGoogleDisconnect}
                                      disabled={googleBusy !== null}
                                      className="px-4 py-2.5 rounded-xl border border-red-500/20 text-red-400 hover:bg-red-500/10 text-sm transition-colors disabled:opacity-40"
                                    >
                                      {googleBusy === '__disconnect__' ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Disconnect'}
                                    </button>
                                  </div>
                                </div>
                              ) : (
                                <div className="space-y-3">
                                  <p className="text-xs text-gray-500 leading-relaxed">
                                    Authorize the agent to access your <strong>{GOOGLE_OAUTH_TOOLS[tool.id].label}</strong> via the official Google sign-in popup.
                                    No tokens are pasted manually — Google issues an access token + refresh token that's stored encrypted on this agent.
                                  </p>
                                  <button
                                    onClick={() => handleGoogleConnect(tool)}
                                    disabled={!agent.id || googleConfigured === false || googleBusy !== null}
                                    className="w-full inline-flex items-center justify-center gap-3 px-4 py-3 rounded-xl bg-white hover:bg-gray-100 text-gray-800 text-sm font-semibold transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                                  >
                                    {googleBusy === tool.id ? (
                                      <Loader2 className="w-5 h-5 animate-spin text-gray-400 dark:text-gray-600" />
                                    ) : (
                                      <svg width="18" height="18" viewBox="0 0 18 18" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                                        <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.17-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.71v2.26h2.92c1.71-1.57 2.68-3.88 2.68-6.61z"/>
                                        <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.81.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.32A9 9 0 0 0 9 18z"/>
                                        <path fill="#FBBC05" d="M3.97 10.71A5.41 5.41 0 0 1 3.68 9c0-.59.1-1.17.29-1.71V4.97H.96A9 9 0 0 0 0 9c0 1.45.35 2.83.96 4.03l3.01-2.32z"/>
                                        <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58A9 9 0 0 0 9 0 9 9 0 0 0 .96 4.97l3.01 2.32C4.68 5.16 6.66 3.58 9 3.58z"/>
                                      </svg>
                                    )}
                                    Connect with Google
                                  </button>
                                  {googleError && (
                                    <p className="text-xs text-red-400 flex items-start gap-1">
                                      <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" /> {googleError}
                                    </p>
                                  )}
                                </div>
                              )}
                            </div>
                          )}

                          {isConfiguring && !GOOGLE_OAUTH_TOOLS[tool.id] && (
                            <div
                              className="border-t border-violet-500/20 px-4 pb-4 pt-3 space-y-4"
                              onClick={e => e.stopPropagation()}
                            >
                              <div className="flex items-center gap-2 mb-1">
                                <Key className="w-4 h-4 text-violet-400" />
                                <span className="text-sm font-semibold text-gray-900 dark:text-white">Configure — {tool.name}</span>
                                <button
                                  onClick={handleCancel}
                                  className="ml-auto p-1 rounded-lg hover:bg-gray-100 dark:hover:bg-white/[0.08] text-gray-500 hover:text-gray-700 dark:text-gray-300 transition-colors"
                                >
                                  <X className="w-4 h-4" />
                                </button>
                              </div>
                              <p className="text-xs text-gray-500">
                                These credentials are stored in your agent's config and used at runtime.
                              </p>

                              {/* Fields */}
                              <div className="space-y-3">
                                {envKeys.filter(key => isEnvKeyVisible(key, draftValues)).map(key => {
                                  const meta = getEnvKeyMeta(key);
                                  const isSecret = meta.secret;
                                  const isShown = showSecrets.has(key);
                                  const val = draftValues[key] || '';
                                  const isRedacted = val === REDACTED_SENTINEL;
                                  const displayValue = isRedacted ? '' : val;
                                  const placeholder = isRedacted ? '••••••• saved — type to replace' : meta.placeholder;
                                  return (
                                    <div key={key}>
                                      <label className="flex items-center gap-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                                        {meta.label}
                                        <span className="text-red-400">*</span>
                                        {(val && !isRedacted) || isRedacted ? (
                                          <CheckCircle className="w-3 h-3 text-green-400 ml-auto" />
                                        ) : null}
                                      </label>
                                      <div className="relative">
                                        <input
                                          type={isSecret && !isShown ? 'password' : 'text'}
                                          value={displayValue}
                                          onChange={e => setDraftValues(prev => ({ ...prev, [key]: e.target.value }))}
                                          placeholder={placeholder}
                                          className="w-full px-3 py-2 pr-9 rounded-lg bg-gray-100 dark:bg-black/30 border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-600 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-violet-500/40 transition-colors"
                                          autoComplete="off"
                                          spellCheck={false}
                                        />
                                        {isSecret && (
                                          <button
                                            type="button"
                                            onClick={() => toggleSecret(key)}
                                            className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-700 dark:text-gray-300 transition-colors"
                                          >
                                            {isShown ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                                          </button>
                                        )}
                                      </div>
                                      {meta.help && (
                                        <p className="text-[11px] text-gray-400 dark:text-gray-600 mt-1">{meta.help}</p>
                                      )}
                                    </div>
                                  );
                                })}
                              </div>

                              {/* Error */}
                              {configError && (
                                <p className="text-xs text-red-400 flex items-center gap-1">
                                  <AlertTriangle className="w-3.5 h-3.5" /> {configError}
                                </p>
                              )}

                              {/* Actions */}
                              <div className="flex gap-2 pt-1">
                                <button
                                  onClick={() => handleConfirm(tool)}
                                  className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-violet-600 hover:bg-violet-700 text-gray-900 dark:text-white text-sm font-semibold transition-colors"
                                >
                                  <Plus className="w-4 h-4" />
                                  {selectedIds.has(tool.id) ? 'Save Configuration' : 'Add Tool'}
                                </button>
                                <button
                                  onClick={handleCancel}
                                  className="px-4 py-2.5 rounded-xl border border-gray-200 dark:border-white/[0.08] text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:border-gray-300 dark:hover:border-white/[0.15] text-sm transition-colors"
                                >
                                  Cancel
                                </button>
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
