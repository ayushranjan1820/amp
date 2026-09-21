import { useEffect, useMemo, useState } from 'react';
import { Cpu, RefreshCw, Loader2, CheckCircle2, AlertTriangle, KeyRound } from 'lucide-react';
import { getAgentsMarketplaceApiBase } from '../utils/agentsApiBase';
import { loadAgentConfig, saveAgentConfig } from '../utils/agentConfigStorage';

interface ModelInfo {
  id: string;
  display_name: string;
  created_at: string;
  type: string;
}

interface ApiResponse {
  success: boolean;
  models?: ModelInfo[];
  count?: number;
  error?: string;
}

interface Props {
  /** Called after the user saves a new model selection so the parent can remount the config panel. */
  onModelSaved?: (modelId: string) => void;
}

const STORAGE_KEY = 'CLAUDE_CODE_MODEL';
const AGENT_ID = 'claude_code';

export default function ClaudeCodeModelPicker({ onModelSaved }: Props) {
  const apiBase = useMemo(() => getAgentsMarketplaceApiBase(), []);

  const [savedConfig, setSavedConfig] = useState<Record<string, string>>(() => loadAgentConfig(AGENT_ID));
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [selectedId, setSelectedId] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedFlash, setSavedFlash] = useState(false);

  const anthropicKey = (savedConfig.ANTHROPIC_API_KEY || '').trim();
  const currentlySavedModel = (savedConfig[STORAGE_KEY] || '').trim();

  useEffect(() => {
    if (!selectedId && currentlySavedModel) {
      setSelectedId(currentlySavedModel);
    }
  }, [currentlySavedModel, selectedId]);

  const refreshSavedConfig = () => {
    setSavedConfig(loadAgentConfig(AGENT_ID));
  };

  const fetchModels = async () => {
    if (!anthropicKey) {
      setError('Save your ANTHROPIC_API_KEY in the configuration above first, save this config to disk, then click Fetch.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const url = `${apiBase}/api/claude-code/models?anthropic_api_key=${encodeURIComponent(anthropicKey)}`;
      const res = await fetch(url);
      const data: ApiResponse = await res.json().catch(() => ({ success: false, error: 'Invalid JSON response' }));
      if (!res.ok || !data.success) {
        throw new Error(data.error || `HTTP ${res.status}`);
      }
      const list = (data.models || []).filter((m) => !!m.id);
      list.sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''));
      setModels(list);
      if (!selectedId && currentlySavedModel && list.some((m) => m.id === currentlySavedModel)) {
        setSelectedId(currentlySavedModel);
      } else if (!selectedId && list.length > 0) {
        setSelectedId(list[0].id);
      }
    } catch (e: any) {
      setError(e?.message || 'Failed to fetch models');
      setModels([]);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = () => {
    if (!selectedId) return;
    const current = loadAgentConfig(AGENT_ID);
    const next = { ...current, [STORAGE_KEY]: selectedId };
    saveAgentConfig(AGENT_ID, next);
    setSavedConfig(next);
    setSavedFlash(true);
    setTimeout(() => setSavedFlash(false), 2500);
    onModelSaved?.(selectedId);
  };

  const handleClear = () => {
    const current = loadAgentConfig(AGENT_ID);
    if (!current[STORAGE_KEY]) return;
    const next = { ...current };
    delete next[STORAGE_KEY];
    saveAgentConfig(AGENT_ID, next);
    setSavedConfig(next);
    setSelectedId('');
    onModelSaved?.('');
  };

  const isDirty = !!selectedId && selectedId !== currentlySavedModel;

  return (
    <section className="rounded-2xl border border-violet-200/60 bg-gradient-to-br from-violet-50/70 via-white/80 to-sky-50/60 p-4 shadow-sm ring-1 ring-violet-500/10 dark:border-violet-500/25 dark:from-violet-950/30 dark:via-zinc-950/80 dark:to-sky-950/20 sm:p-5">
      <header className="mb-3 flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500/20 to-sky-500/15 ring-1 ring-violet-400/30 dark:from-violet-500/25 dark:to-sky-500/20">
          <Cpu className="h-4 w-4 text-violet-600 dark:text-violet-300" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="font-body text-sm font-semibold text-gray-900 dark:text-white">Anthropic Model</h3>
          <p className="mt-0.5 font-body text-xs leading-relaxed text-gray-600 dark:text-zinc-400">
            Fetch the models available to your <code className="rounded bg-violet-100/80 px-1 py-0.5 font-mono text-[10px] text-violet-700 dark:bg-violet-500/15 dark:text-violet-200">ANTHROPIC_API_KEY</code>, pick one,
            and save it. Code generation will use the selected model.
          </p>
        </div>
      </header>

      {!anthropicKey && (
        <div className="mb-3 flex items-start gap-2 rounded-lg border border-amber-300/60 bg-amber-50/80 p-2.5 text-[12px] text-amber-900 dark:border-amber-500/30 dark:bg-amber-950/30 dark:text-amber-200">
          <KeyRound className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <span>
            Save your <strong>ANTHROPIC_API_KEY</strong> in the required credentials section above (and save this config), then click <em>Fetch models</em>.
          </span>
        </div>
      )}

      {/* Stack controls: sidebar is narrow while `sm:` is viewport-wide, row layout overflowed */}
      <div className="flex min-w-0 flex-col gap-2">
        <button
          type="button"
          onClick={fetchModels}
          disabled={loading || !anthropicKey}
          className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-violet-600 px-3 py-2 font-body text-xs font-semibold text-white shadow-sm transition-all hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-violet-500/90 dark:hover:bg-violet-500"
        >
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          {loading ? 'Fetching…' : models.length ? 'Refresh list' : 'Fetch models'}
        </button>

        <select
          value={selectedId}
          onChange={(e) => setSelectedId(e.target.value)}
          disabled={models.length === 0}
          className="min-w-0 w-full rounded-lg border border-violet-200/80 bg-white/90 px-3 py-2 font-body text-xs text-gray-900 shadow-inner shadow-violet-900/[0.02] focus:border-violet-400/60 focus:outline-none focus:ring-2 focus:ring-violet-500/25 disabled:cursor-not-allowed disabled:opacity-60 dark:border-violet-500/30 dark:bg-zinc-900/60 dark:text-white"
        >
          {models.length === 0 ? (
            <option value="">{currentlySavedModel ? `Saved: ${currentlySavedModel}` : 'No models loaded yet'}</option>
          ) : (
            models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.display_name} — {m.id}
              </option>
            ))
          )}
        </select>

        <button
          type="button"
          onClick={handleSave}
          disabled={!selectedId || !isDirty}
          className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-2 font-body text-xs font-semibold text-white shadow-sm transition-all hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-emerald-500/90 dark:hover:bg-emerald-500"
        >
          {savedFlash ? <CheckCircle2 className="h-3.5 w-3.5" /> : null}
          {savedFlash ? 'Saved!' : 'Use this model'}
        </button>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 font-body text-[11px] text-gray-600 dark:text-zinc-400">
        <span className="inline-flex items-center gap-1.5">
          <CheckCircle2 className={`h-3 w-3 ${currentlySavedModel ? 'text-emerald-500' : 'text-gray-400'}`} aria-hidden />
          Active: {currentlySavedModel ? (
            <code className="rounded bg-emerald-100/80 px-1.5 py-0.5 font-mono text-[10px] text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300">
              {currentlySavedModel}
            </code>
          ) : (
            <span className="text-gray-500 dark:text-zinc-500">none saved — using server default</span>
          )}
        </span>
        {currentlySavedModel && (
          <button
            type="button"
            onClick={handleClear}
            className="rounded text-[11px] font-medium text-rose-600 underline-offset-2 hover:underline dark:text-rose-400"
          >
            Clear
          </button>
        )}
        <button
          type="button"
          onClick={refreshSavedConfig}
          className="ml-auto inline-flex items-center gap-1 text-[10px] uppercase tracking-wide text-gray-500 hover:text-gray-700 dark:text-zinc-500 dark:hover:text-zinc-300"
          title="Reload current saved values from local storage"
        >
          <RefreshCw className="h-3 w-3" />
          Reload state
        </button>
      </div>

      {error && (
        <div className="mt-3 flex items-start gap-2 rounded-lg border border-rose-300/60 bg-rose-50/80 p-2.5 text-[12px] text-rose-800 dark:border-rose-500/30 dark:bg-rose-950/30 dark:text-rose-200">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <span className="break-words">{error}</span>
        </div>
      )}

      {models.length > 0 && !error && (
        <p className="mt-2 font-body text-[10.5px] text-gray-500 dark:text-zinc-500">
          {models.length} model{models.length === 1 ? '' : 's'} available to this API key.
        </p>
      )}
    </section>
  );
}
