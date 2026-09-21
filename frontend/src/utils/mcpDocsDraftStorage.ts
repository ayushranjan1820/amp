import type { LlmProviderChoice } from './agentConfigStorage';

const STORAGE_KEY = 'agent_marketplace_mcp_docs_draft_v1';

export type McpDocsDraftV1 = {
  v: 1;
  agentIds: string[];
  llmProvider: LlmProviderChoice;
  envValues: Record<string, string>;
};

export function loadMcpDocsDraft(): Partial<Pick<McpDocsDraftV1, 'agentIds' | 'llmProvider' | 'envValues'>> | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const p = JSON.parse(raw) as unknown;
    if (!p || typeof p !== 'object' || Array.isArray(p)) return null;
    const rec = p as Record<string, unknown>;
    const llm = rec.llmProvider;
    const validLlm: LlmProviderChoice | undefined =
      llm === 'pwc_genai' || llm === 'local_llm' || llm === 'ollama_cloud' ? llm : undefined;
    let envValues: Record<string, string> | undefined;
    if (rec.envValues && typeof rec.envValues === 'object' && !Array.isArray(rec.envValues)) {
      envValues = {};
      for (const [k, v] of Object.entries(rec.envValues)) {
        if (typeof v === 'string') envValues[k] = v;
      }
    }
    const agentIds = Array.isArray(rec.agentIds)
      ? rec.agentIds.filter((x): x is string => typeof x === 'string')
      : undefined;
    return { agentIds, llmProvider: validLlm, envValues };
  } catch {
    return null;
  }
}

export function saveMcpDocsDraft(draft: Omit<McpDocsDraftV1, 'v'>): void {
  if (typeof window === 'undefined') return;
  try {
    const payload: McpDocsDraftV1 = { v: 1, ...draft };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  } catch {
    /* quota / private mode */
  }
}
