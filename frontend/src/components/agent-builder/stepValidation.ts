import type { CustomAgent } from '../../services/agentBuilder';

export type StepStatus = 'incomplete' | 'warning' | 'complete';

export interface StepValidation {
  status: StepStatus;
  reason?: string;
}

function hasValueOrRedacted(cfg: Record<string, string> | undefined, key: string): boolean {
  if (!cfg) return false;
  const v = cfg[key];
  // The backend redacts secrets to '__REDACTED__'; that still means "this key is set"
  return !!v && v.trim().length > 0;
}

export function validateIdentity(agent: Partial<CustomAgent>): StepValidation {
  if (!agent.name || !agent.name.trim()) {
    return { status: 'incomplete', reason: 'Name is required' };
  }
  if (!agent.description || !agent.description.trim()) {
    return { status: 'warning', reason: 'A description helps users discover the agent' };
  }
  return { status: 'complete' };
}

export function validatePrompt(agent: Partial<CustomAgent>): StepValidation {
  const sp = (agent.system_prompt || '').trim();
  if (!sp) return { status: 'incomplete', reason: 'System prompt is required' };
  if (sp.length < 30) {
    return { status: 'warning', reason: 'System prompt is very short — add role and constraints' };
  }
  return { status: 'complete' };
}

interface ToolMeta {
  id?: string;
  name?: string;
  schema_config?: { env_keys?: string[] };
}

export function validateTools(
  agent: Partial<CustomAgent>,
  toolMetaById?: Map<string, ToolMeta>,
): StepValidation {
  const tools = agent.tools_config || [];
  if (!toolMetaById || toolMetaById.size === 0) {
    return tools.length === 0 ? { status: 'warning', reason: 'No tools selected (optional)' } : { status: 'complete' };
  }
  const cfg = (agent.default_config || {}) as Record<string, string>;
  const unconfigured: string[] = [];
  for (const t of tools) {
    const id = (t as ToolRef).id || (t as ToolRef).name;
    if (!id) continue;
    const meta = toolMetaById.get(id);
    const keys = meta?.schema_config?.env_keys || [];
    if (keys.some((k) => !hasValueOrRedacted(cfg, k))) {
      unconfigured.push(meta?.name || id);
    }
  }
  if (unconfigured.length > 0) {
    return {
      status: 'incomplete',
      reason: `${unconfigured.join(', ')} need${unconfigured.length === 1 ? 's' : ''} credentials`,
    };
  }
  return tools.length === 0
    ? { status: 'warning', reason: 'No tools selected (optional)' }
    : { status: 'complete' };
}

export function validateConfig(agent: Partial<CustomAgent>): StepValidation {
  const provider = agent.llm_provider || 'pwc_genai';
  const cfg = (agent.default_config || {}) as Record<string, string>;
  const needsCloudKey = provider === 'pwc_genai' || provider === 'ollama_cloud';
  if (needsCloudKey) {
    const keyField = provider === 'pwc_genai' ? 'PWC_GENAI_API_KEY' : 'ON_PREM_CLOUD_ACCESS_TOKEN';
    if (!hasValueOrRedacted(cfg, keyField)) {
      return { status: 'incomplete', reason: 'API key required' };
    }
  }
  if (!agent.llm_model) {
    return { status: 'incomplete', reason: 'Pick a model' };
  }
  return { status: 'complete' };
}

export function validateTest(agent: Partial<CustomAgent>, agentId: string | null): StepValidation {
  if (!agentId) return { status: 'incomplete', reason: 'Save the agent first' };
  if (!(agent.system_prompt || '').trim()) return { status: 'incomplete', reason: 'Add a system prompt' };
  return { status: 'complete' };
}

export function validateDeploy(agent: Partial<CustomAgent>): StepValidation {
  if (agent.status === 'published') return { status: 'complete' };
  if (agent.status === 'deployed') return { status: 'complete' };
  if (!(agent.system_prompt || '').trim()) return { status: 'incomplete', reason: 'Cannot deploy without a system prompt' };
  return { status: 'warning', reason: 'Not yet deployed' };
}

interface ToolRef {
  id?: string;
  name?: string;
}

export function isAgentDirty(a: Partial<CustomAgent>, b: Partial<CustomAgent>): boolean {
  // Compare a stable subset of fields the user can edit
  const keys: (keyof CustomAgent)[] = [
    'name', 'description', 'category_id', 'logo_url', 'system_prompt',
    'llm_provider', 'llm_model', 'temperature', 'max_tokens',
    'tools_config', 'capabilities', 'example_prompts',
    'required_env_keys', 'default_config', 'visibility',
  ];
  for (const k of keys) {
    if (JSON.stringify(a[k] ?? null) !== JSON.stringify(b[k] ?? null)) return true;
  }
  return false;
}
