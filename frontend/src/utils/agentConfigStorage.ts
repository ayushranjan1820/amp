const STORAGE_PREFIX = 'agent_config_';

export type LlmProviderChoice = 'pwc_genai' | 'local_llm' | 'ollama_cloud';

export interface ConfigVisibilityRule {
  key: string;
  equals?: string | string[];
  not_equals?: string | string[];
}

type ConfigVisibleWhen = ConfigVisibilityRule | ConfigVisibilityRule[];

/** Whether a catalog field is shown for the selected LLM backend (cross-provider keys stay hidden). */
function isConfigKeyVisibleForLlmProvider(key: string, provider: LlmProviderChoice): boolean {
  if (key.startsWith('PWC_GENAI_') || key.startsWith('GEMINI_')) {
    return provider === 'pwc_genai';
  }
  if (key.startsWith('OLLAMA_CLOUD_') || key.startsWith('ON_PREM_CLOUD_')) {
    return provider === 'ollama_cloud';
  }
  if (key.startsWith('LOCAL_LLM_')) {
    return provider === 'local_llm';
  }
  if (key === 'OLLAMA_HOST') {
    return provider === 'local_llm';
  }
  if (key === 'DEFAULT_LLM_PROVIDER') {
    return provider !== 'ollama_cloud';
  }
  return true;
}

function envBoolish(s: string | undefined): boolean {
  const t = (s ?? '').trim().toLowerCase();
  return t === 'true' || t === '1' || t === 'yes';
}

/**
 * Merge admin defaults + in-memory form values (same clear-empty rules as persisted config).
 */
export function getDraftEffectiveConfig(agent: AgentLike, values: Record<string, string>): Record<string, string> {
  const adminDefaults = agent.default_config || {};
  const merged: Record<string, string> = {};

  for (const [k, v] of Object.entries(adminDefaults)) {
    if (v?.trim()) merged[k] = v;
  }
  for (const [k, v] of Object.entries(values)) {
    if (v?.trim()) merged[k] = v;
    else if (Object.prototype.hasOwnProperty.call(values, k)) {
      merged[k] = '';
    }
  }

  return merged;
}

/** Migrate USE_LOCAL_LLM → LLM_PROVIDER and drop stale legacy keys. */
export function migrateLegacyUseLocalLlmInConfig(cfg: Record<string, string>): {
  config: Record<string, string>;
  changed: boolean;
} {
  const hasLlm = cfg.LLM_PROVIDER !== undefined && String(cfg.LLM_PROVIDER).trim() !== '';
  if (hasLlm) {
    if (cfg.USE_LOCAL_LLM === undefined) return { config: cfg, changed: false };
    const next = { ...cfg };
    delete next.USE_LOCAL_LLM;
    return { config: next, changed: true };
  }
  const leg = cfg.USE_LOCAL_LLM;
  if (leg === undefined || leg === null || String(leg).trim() === '') {
    return { config: cfg, changed: false };
  }
  const next = { ...cfg };
  next.LLM_PROVIDER = envBoolish(String(leg)) ? 'local_llm' : 'pwc_genai';
  delete next.USE_LOCAL_LLM;
  return { config: next, changed: true };
}

/** Env keys shown inside the LLM provider card (not in Required/Optional lists). */
export function isLlmBundledConfigKey(key: string): boolean {
  if (key === 'LLM_PROVIDER') return true;
  if (key.startsWith('PWC_GENAI_')) return true;
  if (key.startsWith('GEMINI_')) return true;
  if (key.startsWith('OLLAMA_CLOUD_') || key.startsWith('ON_PREM_CLOUD_')) return true;
  if (key === 'OLLAMA_HOST' || key === 'DEFAULT_LLM_PROVIDER') return true;
  if (key.startsWith('LOCAL_LLM_')) return true;
  return false;
}

/** Resolved LLM backend from saved config, catalog default, or legacy USE_LOCAL_LLM. */
export function getEffectiveLlmProvider(
  fields: AgentConfigField[],
  effective: Record<string, string>,
): LlmProviderChoice {
  const v = effective['LLM_PROVIDER']?.trim().toLowerCase();
  if (v === 'pwc_genai' || v === 'local_llm' || v === 'ollama_cloud') {
    return v;
  }
  const legacy = effective['USE_LOCAL_LLM'];
  if (legacy !== undefined && legacy !== null && String(legacy).trim() !== '') {
    return envBoolish(String(legacy)) ? 'local_llm' : 'pwc_genai';
  }
  const field = fields.find(f => f.key === 'LLM_PROVIDER');
  const d = (field?.default ?? 'pwc_genai').trim().toLowerCase();
  if (d === 'pwc_genai' || d === 'local_llm' || d === 'ollama_cloud') return d;
  return 'pwc_genai';
}

function _canonicalWebSearchProvider(v: string): string {
  const raw = (v || '').trim().toLowerCase();
  if (raw === 'free' || raw === 'free_web' || raw === 'free_ollama' || raw === 'ollama' || raw === 'ollama_free') {
    return 'free_ollama';
  }
  if (raw === 'free_duckduckgo' || raw === 'duckduckgo' || raw === 'duck' || raw === 'ddg') {
    return 'free_duckduckgo';
  }
  if (raw === 'perplexity') return 'perplexity';
  return raw;
}

function _canonicalZohoBackend(v: string): string {
  const raw = (v || '').trim().toLowerCase();
  if (raw === 'mcp' || raw === 'rest') return raw;
  return raw;
}

function _normalizeForVisibility(
  fields: AgentConfigField[],
  key: string,
  raw: string,
): string {
  const field = fields.find((f) => f.key === key);
  if (field?.control === 'boolean') {
    return envBoolish(raw) ? 'true' : 'false';
  }
  if (key.endsWith('_WEB_SEARCH_PROVIDER')) {
    return _canonicalWebSearchProvider(raw);
  }
  if (key === 'ZOHO_BACKEND') {
    return _canonicalZohoBackend(raw);
  }
  return (raw || '').trim().toLowerCase();
}

function _resolveEffectiveValueForVisibility(
  fields: AgentConfigField[],
  effective: Record<string, string>,
  key: string,
): string {
  const configured = (effective[key] ?? '').trim();
  if (configured) return _normalizeForVisibility(fields, key, configured);
  const fallback = (fields.find((f) => f.key === key)?.default ?? '').trim();
  return _normalizeForVisibility(fields, key, fallback);
}

function _toRuleArray(v: string | string[] | undefined): string[] {
  if (v === undefined) return [];
  return Array.isArray(v) ? v : [v];
}

function _isFieldVisibleByRules(
  field: AgentConfigField,
  fields: AgentConfigField[],
  effective: Record<string, string>,
): boolean {
  if (!field.visible_when) return true;
  const rules = Array.isArray(field.visible_when) ? field.visible_when : [field.visible_when];
  for (const r of rules) {
    const ruleKey = (r.key || '').trim();
    if (!ruleKey) continue;
    const actual = _resolveEffectiveValueForVisibility(fields, effective, ruleKey);
    const equals = _toRuleArray(r.equals).map((x) => _normalizeForVisibility(fields, ruleKey, String(x)));
    const notEquals = _toRuleArray(r.not_equals).map((x) => _normalizeForVisibility(fields, ruleKey, String(x)));

    if (equals.length > 0 && !equals.includes(actual)) return false;
    if (notEquals.length > 0 && notEquals.includes(actual)) return false;
  }
  return true;
}

export function filterConfigFieldsForLlmProvider(
  fields: AgentConfigField[],
  provider: LlmProviderChoice,
  effective: Record<string, string> = {},
): AgentConfigField[] {
  return fields.filter(f => {
    if (f.key === 'USE_LOCAL_LLM') return false;
    if (!isConfigKeyVisibleForLlmProvider(f.key, provider)) return false;
    return _isFieldVisibleByRules(f, fields, effective);
  });
}

/** @deprecated use getEffectiveLlmProvider */
export function isUseLocalLlmSelected(fields: AgentConfigField[], effective: Record<string, string>): boolean {
  return getEffectiveLlmProvider(fields, effective) !== 'pwc_genai';
}

/** @deprecated use filterConfigFieldsForLlmProvider */
export function filterConfigFieldsForLocalLlm(
  fields: AgentConfigField[],
  useLocalLlm: boolean,
): AgentConfigField[] {
  return filterConfigFieldsForLlmProvider(fields, useLocalLlm ? 'local_llm' : 'pwc_genai');
}

export interface AgentConfigField {
  key: string;
  description: string;
  required: boolean;
  value?: string;
  default?: string;
  example?: string;
  /** When set to `boolean`, the config panel renders a toggle (stored as \"true\" / \"false\"). */
  control?: 'boolean' | 'choice' | 'select';
  options?: Array<{ value: string; label: string }>;
  visible_when?: ConfigVisibleWhen;
}

interface AgentLike {
  id: string;
  name?: string;
  server_configured_keys?: string[];
  default_config?: Record<string, string>;
  configuration?: {
    required_settings?: Array<{
      key: string;
      description: string;
      default?: string;
      control?: 'boolean' | 'choice' | 'select';
      options?: Array<{ value: string; label: string }>;
      example?: string;
      visible_when?: ConfigVisibleWhen;
    }>;
    optional_settings?: Array<{
      key: string;
      description: string;
      default?: string;
      example?: string;
      control?: 'boolean' | 'choice' | 'select';
      options?: Array<{ value: string; label: string }>;
      visible_when?: ConfigVisibleWhen;
    }>;
    environment_variables?: Array<{ name: string; description: string; required?: boolean }>;
  };
}

export function getAgentConfigKey(agentId: string): string {
  return `${STORAGE_PREFIX}${agentId}`;
}

export function loadAgentConfig(agentId: string): Record<string, string> {
  try {
    const raw = localStorage.getItem(getAgentConfigKey(agentId));
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

export function saveAgentConfig(agentId: string, config: Record<string, string>): void {
  localStorage.setItem(getAgentConfigKey(agentId), JSON.stringify(config));
}

export function clearAgentConfig(agentId: string): void {
  localStorage.removeItem(getAgentConfigKey(agentId));
}

export function getConfigFields(agent: Pick<AgentLike, 'configuration'>): AgentConfigField[] {
  if (!agent.configuration) return [];

  const fields: AgentConfigField[] = [];
  const seenKeys = new Set<string>();

  const appendField = (f: AgentConfigField) => {
    if (seenKeys.has(f.key)) return;
    seenKeys.add(f.key);
    fields.push(f);
  };

  if (agent.configuration.required_settings) {
    for (const s of agent.configuration.required_settings) {
      appendField({
        key: s.key,
        description: s.description,
        required: true,
        default: s.default,
        example: (s as { example?: string }).example,
        ...((s as { control?: string }).control === 'boolean' ? { control: 'boolean' as const } : {}),
        ...((s as { control?: string }).control === 'choice' && (s as { options?: AgentConfigField['options'] }).options?.length
          ? {
              control: 'choice' as const,
              options: ((s as unknown) as { options: NonNullable<AgentConfigField['options']> }).options,
            }
          : {}),
        ...((s as { control?: string }).control === 'select' && (s as { options?: AgentConfigField['options'] }).options?.length
          ? {
              control: 'select' as const,
              options: ((s as unknown) as { options: NonNullable<AgentConfigField['options']> }).options,
            }
          : {}),
        ...((s as { visible_when?: ConfigVisibleWhen }).visible_when
          ? { visible_when: (s as { visible_when: ConfigVisibleWhen }).visible_when }
          : {}),
      });
    }
  }

  if (agent.configuration.optional_settings) {
    for (const s of agent.configuration.optional_settings) {
      appendField({
        key: s.key,
        description: s.description,
        required: false,
        default: s.default,
        example: s.example,
        ...(s.control === 'boolean' ? { control: 'boolean' as const } : {}),
        ...(s.control === 'choice' && s.options?.length
          ? { control: 'choice' as const, options: s.options }
          : {}),
        ...(s.control === 'select' && s.options?.length
          ? { control: 'select' as const, options: s.options }
          : {}),
        ...(s.visible_when ? { visible_when: s.visible_when } : {}),
      });
    }
  }

  if (agent.configuration.environment_variables) {
    for (const ev of agent.configuration.environment_variables) {
      appendField({ key: ev.name, description: ev.description, required: ev.required ?? false });
    }
  }

  return fields;
}

/**
 * Build the effective config for an agent by layering:
 *   1. Admin-set default_config from the catalog (lowest priority)
 *   2. User-set values from localStorage (highest priority, overrides admin)
 *
 * Only non-empty string values are included.
 */
export function getEffectiveConfig(agent: AgentLike): Record<string, string> {
  const adminDefaults = agent.default_config || {};
  const userOverrides = loadAgentConfig(agent.id);
  const merged: Record<string, string> = {};

  for (const [k, v] of Object.entries(adminDefaults)) {
    if (v?.trim()) merged[k] = v;
  }
  for (const [k, v] of Object.entries(userOverrides)) {
    if (v?.trim()) merged[k] = v;
    else if (Object.prototype.hasOwnProperty.call(userOverrides, k)) {
      merged[k] = '';
    }
  }

  return merged;
}

function _fillUserConfigFieldValue(
  f: AgentConfigField,
  effective: Record<string, string>,
): string {
  let v = effective[f.key];
  if (f.control === 'boolean' && (v === undefined || v === null || String(v).trim() === '')) {
    const d = (f.default ?? 'false').trim().toLowerCase();
    v = d === 'true' || d === '1' || d === 'yes' ? 'true' : 'false';
  }
  if (f.key === 'LLM_PROVIDER' && (v === undefined || v === null || !String(v).trim())) {
    v = (f.default ?? 'pwc_genai').trim();
  }
  if (f.key === 'ON_PREM_CLOUD_MODEL' && (v === undefined || v === null || !String(v).trim())) {
    v = (f.default ?? 'gemma3:27b-cloud').trim();
  }
  return v !== undefined && v !== null ? String(v) : '';
}

/**
 * Whether to put a catalog key in the API ``user_config`` body.
 *
 * - Non-empty resolved value → include (user or admin default).
 * - Empty but present in browser storage → include ``""`` so the server clears that override
 *   (``merge_configs`` pops the key).
 * - Empty and user never saved this key → omit so the server keeps catalog ``default_config``.
 *
 * Sending every field as ``""`` used to wipe admin defaults on each chat request.
 */
function _putUserConfigKey(
  payload: Record<string, string>,
  key: string,
  resolvedValue: string,
  rawUser: Record<string, string>,
): void {
  const trimmed = resolvedValue.trim();
  if (trimmed) {
    payload[key] = resolvedValue;
    return;
  }
  if (Object.prototype.hasOwnProperty.call(rawUser, key)) {
    payload[key] = '';
  }
}

/** Shaped ``user_config`` for API/MCP: only keys that are set or explicitly cleared in this browser. */
export function getUserConfigPayloadForRequest(agent: AgentLike): Record<string, string> | undefined {
  const fields = getConfigFields(agent);
  if (fields.length === 0) return undefined;
  const effective = getEffectiveConfig(agent);
  const rawUser = loadAgentConfig(agent.id);
  const payload: Record<string, string> = {};
  for (const f of fields) {
    _putUserConfigKey(payload, f.key, _fillUserConfigFieldValue(f, effective), rawUser);
  }
  return Object.keys(payload).length > 0 ? payload : undefined;
}

/**
 * Same values as {@link getUserConfigPayloadForRequest} but only for fields shown for the
 * effective LLM provider (PWC vs local vs Ollama cloud). Use for MCP env / IDE snippets so
 * `LLM_PROVIDER` and credentials match the Config tab.
 */
export function getUserConfigPayloadForActiveLlmProvider(agent: AgentLike): Record<string, string> | undefined {
  const fields = getConfigFields(agent);
  if (fields.length === 0) return undefined;
  const effective = getEffectiveConfig(agent);
  const rawUser = loadAgentConfig(agent.id);
  const provider = getEffectiveLlmProvider(fields, effective);
  const visibleFields = filterConfigFieldsForLlmProvider(fields, provider, effective);
  const payload: Record<string, string> = {};
  for (const f of visibleFields) {
    _putUserConfigKey(payload, f.key, _fillUserConfigFieldValue(f, effective), rawUser);
  }
  /** Catalogs often list PWC/local/Ollama keys without an explicit `LLM_PROVIDER` row — MCP/API still need it. */
  const catalogHasLlmKeys = fields.some((f) => isLlmBundledConfigKey(f.key));
  if (catalogHasLlmKeys && !String(payload.LLM_PROVIDER ?? '').trim()) {
    payload.LLM_PROVIDER = provider;
  }
  return Object.keys(payload).length > 0 ? payload : undefined;
}

/**
 * Returns required fields that have no value in either admin defaults or user storage.
 */
function _ollamaTokenRequiredButEmpty(
  fields: AgentConfigField[],
  effective: Record<string, string>,
  provider: LlmProviderChoice,
): boolean {
  if (provider !== 'ollama_cloud') return false;
  if (!fields.some(f => f.key === 'ON_PREM_CLOUD_ACCESS_TOKEN')) return false;
  return !effective['ON_PREM_CLOUD_ACCESS_TOKEN']?.trim();
}

export function getMissingRequiredFieldsForEffective(
  _agent: AgentLike,
  fields: AgentConfigField[],
  effective: Record<string, string>,
): AgentConfigField[] {
  const provider = getEffectiveLlmProvider(fields, effective);
  const visible = filterConfigFieldsForLlmProvider(fields, provider, effective);
  const missing = visible.filter(f => f.required && !effective[f.key]?.trim()
    && !(effective[f.key] === undefined && _agent.server_configured_keys?.includes(f.key)));
  if (_ollamaTokenRequiredButEmpty(fields, effective, provider)) {
    const tok = fields.find(f => f.key === 'ON_PREM_CLOUD_ACCESS_TOKEN');
    if (tok && !missing.some(m => m.key === tok.key)) missing.push(tok);
  }
  return missing;
}

export function getMissingRequiredFields(agent: AgentLike, fields: AgentConfigField[]): AgentConfigField[] {
  return getMissingRequiredFieldsForEffective(agent, fields, getEffectiveConfig(agent));
}

export function hasRequiredConfigForEffective(
  _agent: AgentLike,
  fields: AgentConfigField[],
  effective: Record<string, string>,
): boolean {
  return getMissingRequiredFieldsForEffective(_agent, fields, effective).length === 0;
}

export function hasRequiredConfig(agent: AgentLike, fields: AgentConfigField[]): boolean {
  return hasRequiredConfigForEffective(agent, fields, getEffectiveConfig(agent));
}

export type WorkflowAgentUserConfigResult =
  | { ok: true; configs: Record<string, Record<string, string>> }
  | {
      ok: false;
      missing: Array<{ agentId: string; agentName: string; missingKeys: string[] }>;
    };

/**
 * Build per-agent config payloads for workflow execution from catalog + localStorage.
 * Fails if any step uses an agent with required settings that are not satisfied.
 */
export function buildAgentUserConfigsForWorkflow(
  steps: Array<{ agent_id?: string }>,
  agents: AgentLike[],
): WorkflowAgentUserConfigResult {
  const byId = new Map(agents.map(a => [a.id, a]));
  const seen = new Set<string>();
  const configs: Record<string, Record<string, string>> = {};
  const missing: Array<{ agentId: string; agentName: string; missingKeys: string[] }> = [];

  for (const step of steps) {
    const aid = step.agent_id;
    if (!aid || seen.has(aid)) continue;
    seen.add(aid);
    const agent = byId.get(aid);
    if (!agent) continue;
    const fields = getConfigFields(agent);
    if (fields.length === 0) continue;
    if (!hasRequiredConfig(agent, fields)) {
      missing.push({
        agentId: aid,
        agentName: agent.name || aid,
        missingKeys: getMissingRequiredFields(agent, fields).map(f => f.key),
      });
    } else {
      const payload = getUserConfigPayloadForRequest(agent);
      if (payload) configs[aid] = payload;
    }
  }

  if (missing.length) return { ok: false, missing };
  return { ok: true, configs };
}

/**
 * Build per-agent config to persist on the workflow (server). Uses the same layering as
 * execution (catalog defaults + localStorage). Only non-empty field values are stored.
 */
/**
 * Like buildAgentUserConfigsForWorkflow but layers credentials from the workflow record
 * (server) under browser/catalog values so execution works when localStorage is empty.
 */
export function buildAgentUserConfigsForWorkflowWithServerOverlay(
  steps: Array<{ agent_id?: string }>,
  agents: AgentLike[],
  serverOverlay: Record<string, Record<string, string>> | null | undefined,
): WorkflowAgentUserConfigResult {
  const byId = new Map(agents.map(a => [a.id, a]));
  const seen = new Set<string>();
  const configs: Record<string, Record<string, string>> = {};
  const missing: Array<{ agentId: string; agentName: string; missingKeys: string[] }> = [];

  for (const step of steps) {
    const aid = step.agent_id;
    if (!aid || seen.has(aid)) continue;
    seen.add(aid);
    const agent = byId.get(aid);
    if (!agent) continue;
    const fields = getConfigFields(agent);
    if (fields.length === 0) continue;

    const base = getEffectiveConfig(agent);
    const effective = { ...(serverOverlay?.[aid] || {}), ...base };

    const provider = getEffectiveLlmProvider(fields, effective);
    const visible = filterConfigFieldsForLlmProvider(fields, provider, effective);
    const miss = visible.filter(f => f.required && !effective[f.key]?.trim());
    if (_ollamaTokenRequiredButEmpty(fields, effective, provider)) {
      const tok = fields.find(f => f.key === 'ON_PREM_CLOUD_ACCESS_TOKEN');
      if (tok && !miss.some(m => m.key === tok.key)) miss.push(tok);
    }
    if (miss.length) {
      missing.push({
        agentId: aid,
        agentName: agent.name || aid,
        missingKeys: miss.map(f => f.key),
      });
    } else {
      const payload: Record<string, string> = {};
      for (const f of fields) {
        payload[f.key] = effective[f.key] ?? '';
      }
      configs[aid] = payload;
    }
  }

  if (missing.length) return { ok: false, missing };
  return { ok: true, configs };
}

export function buildAgentUserConfigsForWorkflowStorage(
  steps: Array<{ agent_id?: string }>,
  agents: AgentLike[],
): Record<string, Record<string, string>> {
  const byId = new Map(agents.map(a => [a.id, a]));
  const seen = new Set<string>();
  const configs: Record<string, Record<string, string>> = {};

  for (const step of steps) {
    const aid = step.agent_id;
    if (!aid || seen.has(aid)) continue;
    seen.add(aid);
    const agent = byId.get(aid);
    if (!agent) continue;
    const fields = getConfigFields(agent);
    if (fields.length === 0) continue;
    const effective = getEffectiveConfig(agent);
    const entry: Record<string, string> = {};
    for (const f of fields) {
      const v = effective[f.key];
      if (v?.trim()) entry[f.key] = v.trim();
    }
    if (Object.keys(entry).length) configs[aid] = entry;
  }

  return configs;
}

/** Merge workflow-stored credentials into localStorage so the Connection panel shows them (browser overrides server for same keys). */
export function applyServerAgentConfigsToLocal(
  configs: Record<string, Record<string, string>> | null | undefined,
  steps: Array<{ agent_id?: string }>,
  agents: AgentLike[],
): void {
  if (!configs || typeof configs !== 'object') return;
  const byId = new Map(agents.map(a => [a.id, a]));
  const seen = new Set<string>();

  for (const step of steps) {
    const aid = step.agent_id;
    if (!aid || seen.has(aid)) continue;
    seen.add(aid);
    if (!byId.has(aid)) continue;
    const fromServer = configs[aid];
    if (!fromServer || !Object.keys(fromServer).length) continue;
    const current = loadAgentConfig(aid);
    const merged = { ...fromServer, ...current };
    saveAgentConfig(aid, merged);
  }
}
