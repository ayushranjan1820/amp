import type { Agent } from '../services/api';
import { getAgentsMarketplaceApiBase } from './agentsApiBase';
import { isLlmBundledConfigKey, type LlmProviderChoice } from './agentConfigStorage';

/** Collect unique env var names from catalog `configuration` (matches server user_config). */
export function collectEnvKeysFromAgents(agents: Agent[]): string[] {
  const seen = new Set<string>();
  const ordered: string[] = [];

  const add = (k: string | undefined) => {
    if (!k || typeof k !== 'string') return;
    const t = k.trim();
    if (!t || seen.has(t)) return;
    seen.add(t);
    ordered.push(t);
  };

  for (const agent of agents) {
    const cfg = agent.configuration;
    if (!cfg) continue;
    for (const s of cfg.required_settings ?? []) add(s.key);
    for (const s of cfg.optional_settings ?? []) add(s.key);
    for (const ev of cfg.environment_variables ?? []) add(ev.name);
  }

  return ordered;
}

function uniqueKeyOrder(keys: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const k of keys) {
    const t = k?.trim();
    if (!t || seen.has(t)) continue;
    seen.add(t);
    out.push(t);
  }
  return out;
}

/** Catalog env keys for agents only — excludes LLM routing/credentials (handled by MCP LLM block). */
export function collectAgentEnvKeysExcludingLlm(agents: Agent[]): string[] {
  return uniqueKeyOrder(
    collectEnvKeysFromAgents(agents).filter(
      (k) => k && k !== 'USE_LOCAL_LLM' && !isLlmBundledConfigKey(k),
    ),
  );
}

const PWC_LLM_ENV_ORDER = [
  'PWC_GENAI_API_KEY',
  'PWC_GENAI_BEARER_TOKEN',
  'PWC_GENAI_ENDPOINT_URL',
] as const;

const LOCAL_LLM_ENV_ORDER = [
  'OLLAMA_HOST',
  'LOCAL_LLM_URL',
  'LOCAL_LLM_MODEL',
  'LOCAL_LLM_BASE_URL',
  'LOCAL_LLM_TEMPERATURE',
  'LOCAL_LLM_MAX_TOKENS',
  'LOCAL_LLM_N_GPU_LAYERS',
  'LOCAL_LLM_N_BATCH',
  'LOCAL_LLM_N_CTX',
  'DEFAULT_LLM_PROVIDER',
] as const;

const OLLAMA_CLOUD_ENV_ORDER = [
  'ON_PREM_CLOUD_ACCESS_TOKEN',
  'OLLAMA_CLOUD_BEARER_TOKEN',
  'ON_PREM_CLOUD_MODEL',
  'OLLAMA_CLOUD_URL',
] as const;

/**
 * Env keys for the MCP header LLM section for one provider (no `LLM_PROVIDER` — that is set from UI state).
 * Includes extra catalog keys (e.g. GEMINI_*) when agents declare them.
 */
export function mcpLlmCredentialKeysForProvider(provider: LlmProviderChoice, agents: Agent[]): string[] {
  const allCatalog = collectEnvKeysFromAgents(agents);
  if (provider === 'pwc_genai') {
    const gemini = allCatalog.filter((k) => k.startsWith('GEMINI_'));
    return uniqueKeyOrder([...PWC_LLM_ENV_ORDER, ...gemini]);
  }
  if (provider === 'local_llm') {
    const fromCatalog = allCatalog.filter(
      (k) =>
        k.startsWith('LOCAL_LLM_') ||
        k === 'OLLAMA_HOST' ||
        k === 'DEFAULT_LLM_PROVIDER' ||
        k === 'LOCAL_LLM_BASE_URL',
    );
    return uniqueKeyOrder([...LOCAL_LLM_ENV_ORDER, ...fromCatalog]);
  }
  const fromCatalog = allCatalog.filter((k) => k.startsWith('OLLAMA_CLOUD_'));
  return uniqueKeyOrder([...OLLAMA_CLOUD_ENV_ORDER, ...fromCatalog]);
}

/**
 * Full MCP header key list: API base, credentials for the chosen LLM provider, then non-LLM agent keys.
 * `LLM_PROVIDER` is applied when building the JSON object (not listed here so it is not duplicated in the form).
 */
export function mergedMcpEnvKeysForAgentsAndLlm(agents: Agent[], llmProvider: LlmProviderChoice): string[] {
  const llm = mcpLlmCredentialKeysForProvider(llmProvider, agents);
  const rest = collectAgentEnvKeysExcludingLlm(agents);
  return uniqueKeyOrder(['AGENTS_API_BASE', ...llm, ...rest]);
}

/** Human-friendly placeholder for docs / mcp.json templates. */
export function placeholderForEnvKey(key: string): string {
  const k = key.toUpperCase();
  if (k.includes('EMAIL')) return 'you@company.com';
  if (k.includes('BEARER_TOKEN') || k === 'PWC_GENAI_BEARER_TOKEN') return 'your-bearer-token';
  if (k.includes('TOKEN') || k.includes('API_KEY') || k.includes('_KEY') && k.includes('API')) {
    if (k.includes('GITHUB')) return 'ghp_your_github_pat';
    return 'your-api-token-here';
  }
  if (k.includes('URI') || (k.includes('URL') && !k.includes('API_BASE'))) {
    if (k.includes('MONGO')) return 'mongodb+srv://user:pass@cluster.mongodb.net/';
    if (k.includes('OLLAMA')) return 'http://localhost:11434';
    return 'https://your-service.example.com';
  }
  if (k.includes('HOST') && k.includes('OLLAMA')) return 'http://localhost:11434';
  if (k.includes('ENDPOINT')) return 'https://genai.example.com/v1/chat';
  if (k.includes('PROJECT_KEY') || (k.endsWith('_KEY') && !k.includes('API'))) return 'PROJ';
  if (k.includes('FROM_EMAIL')) return 'verified@yourdomain.com';
  if (k.includes('SECRET')) return 'your-secret';
  return `your-${key.toLowerCase().replace(/_/g, '-')}`;
}

function getApiBase(): string {
  return getAgentsMarketplaceApiBase();
}

export function buildEnvObjectFromKeys(keys: string[]): Record<string, string> {
  const env: Record<string, string> = {
    AGENTS_API_BASE: getApiBase(),
  };
  for (const key of keys) {
    env[key] = placeholderForEnvKey(key);
  }
  return env;
}

/** Keys for MCP env / X-Marketplace-Agent-Env: API base plus catalog keys from selected agents. */
export function mergedMcpEnvKeysForAgents(agents: Agent[]): string[] {
  const catalog = collectEnvKeysFromAgents(agents);
  const out: string[] = ['AGENTS_API_BASE'];
  for (const k of catalog) {
    if (k !== 'AGENTS_API_BASE') out.push(k);
  }
  return out;
}

export function defaultValueForMcpEnvKey(key: string): string {
  if (key === 'AGENTS_API_BASE') return getApiBase();
  return placeholderForEnvKey(key);
}

/** How a key should be labeled in MCP credential UI (stricter tier wins across agents). */
export type McpEnvKeyTier = 'base' | 'required' | 'optional';

export type McpEnvKeyMeta = { tier: McpEnvKeyTier; description?: string };

function normKey(k: string | undefined): string | null {
  if (!k || typeof k !== 'string') return null;
  const t = k.trim();
  return t || null;
}

/** Classify merged env keys from selected agents' catalog configuration. */
export function mcpEnvKeyMetaForKeys(agents: Agent[], keys: string[]): Record<string, McpEnvKeyMeta> {
  const out: Record<string, McpEnvKeyMeta> = {};

  for (const key of keys) {
    if (key === 'AGENTS_API_BASE') {
      out[key] = {
        tier: 'base',
        description: 'Base URL of the Agent Marketplace API (local or deployed).',
      };
      continue;
    }

    let required = false;
    let description: string | undefined;

    for (const agent of agents) {
      const cfg = agent.configuration;
      if (!cfg) continue;

      for (const s of cfg.required_settings ?? []) {
        if (normKey(s.key) !== key) continue;
        required = true;
        if (!description && s.description) description = s.description;
      }
      for (const s of cfg.optional_settings ?? []) {
        if (normKey(s.key) !== key) continue;
        if (!description && s.description) description = s.description;
      }
      for (const ev of cfg.environment_variables ?? []) {
        if (normKey(ev.name) !== key) continue;
        if (ev.required === true) required = true;
        if (!description && ev.description) description = ev.description;
      }
    }

    out[key] = { tier: required ? 'required' : 'optional', description };
  }

  const mcpLlmFallback: Record<string, McpEnvKeyMeta> = {
    PWC_GENAI_API_KEY: {
      tier: 'required',
      description: 'PwC GenAI API key (used when LLM provider is PwC GenAI).',
    },
    PWC_GENAI_BEARER_TOKEN: {
      tier: 'optional',
      description: 'Optional bearer token for PwC GenAI when your setup uses it instead of an API key.',
    },
    PWC_GENAI_ENDPOINT_URL: {
      tier: 'optional',
      description: 'Override PwC GenAI HTTP endpoint when your tenant uses a non-default URL.',
    },
    OLLAMA_HOST: {
      tier: 'optional',
      description: 'Ollama server base URL (e.g. http://localhost:11434) for local stack integrations.',
    },
    LOCAL_LLM_URL: {
      tier: 'optional',
      description: 'Local LLM HTTP generate endpoint (default http://127.0.0.1:4099/api/v1/generate).',
    },
    LOCAL_LLM_MODEL: {
      tier: 'optional',
      description: 'Model name sent to your local LLM server.',
    },
    LOCAL_LLM_BASE_URL: {
      tier: 'optional',
      description: 'Alternate base URL key some agents use for local LLM routing.',
    },
    LOCAL_LLM_TEMPERATURE: { tier: 'optional', description: 'Sampling temperature for local LLM calls.' },
    LOCAL_LLM_MAX_TOKENS: { tier: 'optional', description: 'Max tokens for local LLM responses.' },
    LOCAL_LLM_N_GPU_LAYERS: { tier: 'optional', description: 'GPU layers (local LLM server).' },
    LOCAL_LLM_N_BATCH: { tier: 'optional', description: 'Batch size (local LLM server).' },
    LOCAL_LLM_N_CTX: { tier: 'optional', description: 'Context window size (local LLM server).' },
    DEFAULT_LLM_PROVIDER: {
      tier: 'optional',
      description: 'Legacy default provider hint; prefer the LLM provider control above for MCP.',
    },
    ON_PREM_CLOUD_ACCESS_TOKEN: {
      tier: 'required',
      description: 'Ollama Cloud API token (ollama.com).',
    },
    OLLAMA_CLOUD_BEARER_TOKEN: {
      tier: 'optional',
      description: 'Alternate env name for the Ollama Cloud token.',
    },
    ON_PREM_CLOUD_MODEL: {
      tier: 'optional',
      description: 'Ollama Cloud model id (e.g. gemma3:27b-cloud).',
    },
    OLLAMA_CLOUD_URL: {
      tier: 'optional',
      description: 'Ollama Cloud chat API URL (default https://ollama.com/api/chat).',
    },
  };

  for (const key of keys) {
    if (!out[key] && mcpLlmFallback[key]) {
      out[key] = mcpLlmFallback[key];
    }
  }

  return out;
}
