import { KeyRound, Cpu, Server } from 'lucide-react';
import * as React from 'react';

export type LlmProvider = 'pwc_genai' | 'ollama_cloud' | 'local_llm';

export interface CredentialField {
  key: string;
  label: string;
  placeholder: string;
  required: boolean;
  secret: boolean;
  helpText: string;
  primary?: boolean;
}

export interface ProviderMeta {
  id: LlmProvider;
  label: string;
  badge: string;
  badgeColor: string;
  description: string;
  icon: React.ReactNode;
  staticModels: { value: string; label: string; isDefault?: boolean }[];
  credentialFields: CredentialField[];
  primaryKeyField: string;
  modelsFetchable: boolean;
}

export const PROVIDERS: ProviderMeta[] = [
  {
    id: 'pwc_genai',
    label: 'PwC GenAI',
    badge: 'Recommended',
    badgeColor: 'bg-violet-500/15 text-violet-400',
    description: 'PwC GenAI gateway — Gemini, GPT-4o, Claude via the Americas endpoint.',
    icon: <KeyRound className="w-4 h-4" />,
    primaryKeyField: 'PWC_GENAI_API_KEY',
    modelsFetchable: false,
    staticModels: [
      { value: 'vertex_ai.gemini-2.5-flash-image', label: 'Gemini 2.5 Flash', isDefault: true },
      { value: 'vertex_ai.gemini-2.5-pro',         label: 'Gemini 2.5 Pro' },
      { value: 'vertex_ai.gpt-4o-mini',            label: 'GPT-4o Mini' },
      { value: 'vertex_ai.gpt-4o',                 label: 'GPT-4o' },
      { value: 'vertex_ai.anthropic.claude-sonnet-4-6', label: 'Claude Sonnet 4' },
      { value: 'vertex_ai.anthropic.claude-3.5-sonnet', label: 'Claude 3.5 Sonnet' },
      { value: 'vertex_ai.anthropic.claude-3-haiku', label: 'Claude 3 Haiku (fast)' },
    ],
    credentialFields: [
      {
        key: 'PWC_GENAI_API_KEY',
        label: 'API Key',
        placeholder: 'your-pwc-genai-api-key',
        required: true,
        secret: true,
        primary: true,
        helpText: 'Your PwC GenAI platform API key. Required to access the GenAI gateway.',
      },
      {
        key: 'PWC_GENAI_BEARER_TOKEN',
        label: 'Bearer Token',
        placeholder: 'your-bearer-token',
        required: false,
        secret: true,
        helpText: 'Optional bearer token — used instead of API key when your tenant requires it.',
      },
      {
        key: 'PWC_GENAI_ENDPOINT_URL',
        label: 'Endpoint URL',
        placeholder: 'https://genai-sharedservice-americas.pwc.com/completions',
        required: false,
        secret: false,
        helpText: 'Override the default GenAI endpoint for non-US regions.',
      },
    ],
  },
  {
    id: 'ollama_cloud',
    label: 'On-prem Cloud',
    badge: 'Cloud',
    badgeColor: 'bg-blue-500/15 text-blue-400',
    description: 'Ollama-hosted open-source LLMs via the Ollama Cloud API.',
    icon: <Cpu className="w-4 h-4" />,
    primaryKeyField: 'ON_PREM_CLOUD_ACCESS_TOKEN',
    modelsFetchable: true,
    staticModels: [
      { value: 'llama3.3:70b-instruct-q4_K_M', label: 'Llama 3.3 70B Instruct', isDefault: true },
      { value: 'gemma3:27b-cloud',             label: 'Gemma 3 27B' },
      { value: 'mistral-small3.1:24b-instruct-q4_K_M', label: 'Mistral Small 3.1 24B' },
      { value: 'qwen2.5:72b-instruct',         label: 'Qwen 2.5 72B' },
      { value: 'deepseek-r1:32b',              label: 'DeepSeek R1 32B' },
      { value: 'phi4:14b',                     label: 'Phi-4 14B' },
    ],
    credentialFields: [
      {
        key: 'ON_PREM_CLOUD_ACCESS_TOKEN',
        label: 'API Token',
        placeholder: 'your-ollama-cloud-token',
        required: true,
        secret: true,
        primary: true,
        helpText: 'Get your token at ollama.com/settings/api-keys',
      },
      {
        key: 'OLLAMA_CLOUD_URL',
        label: 'API URL',
        placeholder: 'https://ollama.com/api/chat',
        required: false,
        secret: false,
        helpText: 'Ollama Cloud chat endpoint. Leave blank for the default.',
      },
    ],
  },
  {
    id: 'local_llm',
    label: 'Local / Self-hosted',
    badge: 'Self-hosted',
    badgeColor: 'bg-gray-500/15 text-gray-400',
    description: 'Run models locally via Ollama or a compatible server (llama.cpp, LMStudio, etc.).',
    icon: <Server className="w-4 h-4" />,
    primaryKeyField: 'OLLAMA_HOST',
    modelsFetchable: false,
    staticModels: [
      { value: 'DeepSeek-R1-q2_k',     label: 'DeepSeek R1 (local)', isDefault: true },
      { value: 'llama3.2:3b',          label: 'Llama 3.2 3B (local)' },
      { value: 'mistral:7b',           label: 'Mistral 7B (local)' },
      { value: 'qwen2.5:7b',           label: 'Qwen 2.5 7B (local)' },
      { value: 'phi3:mini',            label: 'Phi-3 Mini (local)' },
      { value: '__custom__',           label: 'Custom model name...' },
    ],
    credentialFields: [
      {
        key: 'OLLAMA_HOST',
        label: 'Ollama Host URL',
        placeholder: 'http://localhost:11434',
        required: false,
        secret: false,
        primary: true,
        helpText: 'Base URL of your local Ollama server.',
      },
      {
        key: 'LOCAL_LLM_URL',
        label: 'LLM Server URL',
        placeholder: 'http://127.0.0.1:4099/api/v1/generate',
        required: false,
        secret: false,
        helpText: 'If using a custom LLM server (not Ollama), provide its generate endpoint.',
      },
      {
        key: 'LOCAL_LLM_N_GPU_LAYERS',
        label: 'GPU Layers',
        placeholder: '40',
        required: false,
        secret: false,
        helpText: 'Layers to offload to GPU (llama.cpp). Leave blank for auto.',
      },
    ],
  },
];

export const PROVIDER_ENV_VALUE: Record<LlmProvider, string> = {
  pwc_genai: 'pwc_genai',
  ollama_cloud: 'ollama_cloud',
  local_llm: 'local_llm',
};

export function getProviderById(id: string): ProviderMeta {
  return PROVIDERS.find((p) => p.id === id) ?? PROVIDERS[0];
}

export function getModelEnvKey(provider: LlmProvider): string {
  if (provider === 'pwc_genai') return 'PREMIUM_MODEL';
  if (provider === 'ollama_cloud') return 'ON_PREM_CLOUD_MODEL';
  return 'LOCAL_LLM_MODEL';
}

export function providerFromEnv(env: Record<string, string>): LlmProvider {
  const raw = (env.LLM_PROVIDER || 'pwc_genai').trim().toLowerCase();
  if (raw === 'local_llm' || raw === 'ollama_cloud' || raw === 'pwc_genai') return raw as LlmProvider;
  return 'pwc_genai';
}

export function modelFromEnv(provider: LlmProvider, env: Record<string, string>): string {
  return (env[getModelEnvKey(provider)] || '').trim();
}

export function applyProviderModelToConfig(
  provider: LlmProvider,
  model: string,
  base: Record<string, string>,
): Record<string, string> {
  const next: Record<string, string> = { ...base, LLM_PROVIDER: provider };
  delete next.PREMIUM_MODEL;
  delete next.ON_PREM_CLOUD_MODEL;
  delete next.LOCAL_LLM_MODEL;
  const m = model.trim();
  if (m) next[getModelEnvKey(provider)] = m;
  return next;
}
