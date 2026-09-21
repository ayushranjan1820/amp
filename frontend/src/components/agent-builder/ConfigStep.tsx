import { useEffect } from 'react';
import { type CustomAgent } from '../../services/agentBuilder';
import {
  PROVIDERS,
  PROVIDER_ENV_VALUE,
  type LlmProvider,
} from '../../utils/llmProviderCatalog';
import LlmProviderModelPicker from './LlmProviderModelPicker';

interface Props {
  agent: Partial<CustomAgent>;
  updateField: <K extends keyof CustomAgent>(key: K, value: CustomAgent[K]) => void;
}

export default function ConfigStep({ agent, updateField }: Props) {
  const cfg = (agent.default_config || {}) as Record<string, string>;

  const setKey = (key: string, value: string) => {
    const next = { ...cfg, [key]: value };
    if (!value) delete next[key];
    updateField('default_config', next as Record<string, string>);
  };

  const storedProvider = (cfg['LLM_PROVIDER'] || agent.llm_provider || 'pwc_genai') as LlmProvider;
  const activeProvider = PROVIDERS.find((p) => p.id === storedProvider) || PROVIDERS[0];

  const primaryKeyValue = cfg[activeProvider.primaryKeyField] || '';
  const hasKey = primaryKeyValue.trim().length > 0;
  const needsCloudCredential =
    activeProvider.id === 'pwc_genai' || activeProvider.id === 'ollama_cloud';

  // Clear model when cloud credentials are removed
  useEffect(() => {
    if (!needsCloudCredential) return;
    if (!hasKey && (agent.llm_model || '').trim()) {
      updateField('llm_model', '');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasKey, needsCloudCredential]);

  const missingRequired = activeProvider.credentialFields
    .filter((f) => f.required && !cfg[f.key])
    .map((f) => f.label);

  return (
    <div className="space-y-7">
      {/* Header */}
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-1">Configuration</h2>
        <p className="text-sm text-gray-500">
          Choose your LLM provider, enter your API credentials, then select a model.
        </p>
      </div>

      {/* Provider → Credentials → Model (all in one shared picker, non-compact) */}
      <LlmProviderModelPicker
        provider={storedProvider}
        model={agent.llm_model || ''}
        onProviderChange={(p) => {
          setKey('LLM_PROVIDER', PROVIDER_ENV_VALUE[p]);
          updateField('llm_provider', p);
        }}
        onModelChange={(m) => updateField('llm_model', m)}
        credentialConfig={cfg}
        credentialConfigMeta={agent.default_config_meta || {}}
        onCredentialChange={setKey}
        showCredentials={true}
        compact={false}
      />

      {/* ── Parameters ── */}
      <div className="rounded-xl border border-gray-200 dark:border-white/[0.06] overflow-hidden">
        <div className="flex items-center gap-2.5 px-4 py-3 border-b border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-white/[0.02]">
          <span className="flex items-center justify-center w-5 h-5 rounded-full bg-violet-500/20 text-violet-400 text-[11px] font-bold">4</span>
          <span className="text-sm font-semibold text-gray-900 dark:text-white">Parameters</span>
        </div>
        <div className="p-4 grid gap-5 sm:grid-cols-2">
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-sm font-medium text-gray-700 dark:text-gray-300">Temperature</label>
              <span className="text-sm font-mono text-violet-400">{(agent.temperature ?? 0.7).toFixed(1)}</span>
            </div>
            <input
              type="range"
              min={0}
              max={2}
              step={0.1}
              value={agent.temperature ?? 0.7}
              onChange={(e) => updateField('temperature', parseFloat(e.target.value))}
              className="w-full accent-violet-500"
            />
            <div className="flex justify-between text-[10px] text-gray-400 dark:text-gray-600 mt-1">
              <span>Precise (0)</span>
              <span>Balanced (0.7)</span>
              <span>Creative (2)</span>
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Max Tokens</label>
            <select
              value={agent.max_tokens || 4096}
              onChange={(e) => updateField('max_tokens', parseInt(e.target.value))}
              className="w-full px-3 py-2.5 rounded-xl bg-gray-100 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-violet-500/40 appearance-none"
            >
              <option value={1024}  className="bg-white dark:bg-zinc-900">1,024 — Short</option>
              <option value={2048}  className="bg-white dark:bg-zinc-900">2,048 — Medium</option>
              <option value={4096}  className="bg-white dark:bg-zinc-900">4,096 — Standard</option>
              <option value={8192}  className="bg-white dark:bg-zinc-900">8,192 — Long</option>
              <option value={16384} className="bg-white dark:bg-zinc-900">16,384 — Very long</option>
            </select>
          </div>
        </div>
      </div>

      {/* ── Capabilities ── */}
      <div>
        <label className="block text-sm font-semibold text-gray-700 dark:text-gray-300 mb-1.5">
          Capabilities
          <span className="text-gray-400 dark:text-gray-600 font-normal ml-1">— shown on the agent card</span>
        </label>
        <div className="space-y-2">
          {(agent.capabilities || []).map((cap, i) => (
            <div key={i} className="flex gap-2">
              <input
                type="text"
                value={cap}
                onChange={(e) => {
                  const updated = [...(agent.capabilities || [])];
                  updated[i] = e.target.value;
                  updateField('capabilities', updated);
                }}
                placeholder="e.g. Natural language Q&A"
                className="flex-1 px-3 py-2 rounded-xl bg-gray-100 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-600 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500/40 transition-colors"
              />
              <button
                onClick={() => updateField('capabilities', (agent.capabilities || []).filter((_, j) => j !== i))}
                className="p-2 rounded-lg hover:bg-red-500/10 text-gray-500 hover:text-red-400 transition-colors"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          ))}
          <button
            onClick={() => updateField('capabilities', [...(agent.capabilities || []), ''])}
            className="text-sm text-violet-400 hover:text-violet-300 transition-colors"
          >
            + Add capability
          </button>
        </div>
      </div>

      {/* ── Summary ── */}
      <div className="rounded-xl bg-gray-50 dark:bg-white/[0.02] border border-gray-200 dark:border-white/[0.06] p-4">
        <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">Configuration Summary</h4>
        <div className="grid grid-cols-2 gap-y-2 text-sm">
          <span className="text-gray-500">Provider</span>
          <span className="text-gray-900 dark:text-white">{activeProvider.label}</span>
          <span className="text-gray-500">Model</span>
          <span className="text-gray-900 dark:text-white font-mono text-xs truncate">{agent.llm_model || '—'}</span>
          <span className="text-gray-500">Temperature</span>
          <span className="text-gray-900 dark:text-white">{(agent.temperature ?? 0.7).toFixed(1)}</span>
          <span className="text-gray-500">Max Tokens</span>
          <span className="text-gray-900 dark:text-white">{(agent.max_tokens || 4096).toLocaleString()}</span>
          <span className="text-gray-500">Tools</span>
          <span className="text-gray-900 dark:text-white">{(agent.tools_config || []).length} selected</span>
          <span className="text-gray-500">Credentials</span>
          <span className={missingRequired.length ? 'text-amber-400' : 'text-green-400'}>
            {missingRequired.length
              ? `${missingRequired.length} required field${missingRequired.length > 1 ? 's' : ''} missing`
              : 'Ready'}
          </span>
        </div>
      </div>
    </div>
  );
}
