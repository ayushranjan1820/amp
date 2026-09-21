import { useState, useEffect, useRef } from 'react';
import {
  Eye, EyeOff, AlertCircle, CheckCircle, Info, Loader2, RefreshCw, ChevronDown, ChevronUp,
} from 'lucide-react';
import {
  PROVIDERS,
  type LlmProvider,
  type ProviderMeta,
  type CredentialField,
  getProviderById,
} from '../../utils/llmProviderCatalog';

// ─── CredentialInput ──────────────────────────────────────────────────────────

const REDACTED_SENTINEL = '__redacted__';

function CredentialInput({
  field,
  value,
  meta,
  onChange,
  compact,
}: {
  field: CredentialField;
  value: string;
  meta?: { is_set?: boolean; tail?: string };
  onChange: (v: string) => void;
  compact?: boolean;
}) {
  const [show, setShow] = useState(false);
  const [editing, setEditing] = useState(false);

  const isRedacted = field.secret && value === REDACTED_SENTINEL;
  const hasStoredSecret = isRedacted || (meta?.is_set && field.secret);
  const displayValue = isRedacted && !editing ? '' : value;

  return (
    <div>
      <div className={`flex items-center justify-between ${compact ? 'mb-1' : 'mb-1.5'}`}>
        <label className={`font-semibold text-gray-700 dark:text-gray-300 ${compact ? 'text-[11px]' : 'text-xs'}`}>
          {field.label}
          {field.required && <span className="text-red-400 ml-0.5">*</span>}
        </label>
        {(value || hasStoredSecret) && (
          <span className="flex items-center gap-1 text-[10px] text-green-400 font-medium">
            <CheckCircle className="w-3 h-3" /> Set{meta?.tail ? ` · …${meta.tail}` : ''}
          </span>
        )}
      </div>
      {hasStoredSecret && !editing ? (
        <div className="flex items-center gap-2">
          <div className={`flex-1 rounded-xl bg-gray-100 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.10] text-gray-600 dark:text-gray-400 font-mono ${compact ? 'px-2 py-1.5 text-xs' : 'px-3 py-2.5 text-sm'}`}>
            ••••••••{meta?.tail ? meta.tail : ''}
          </div>
          <button
            type="button"
            onClick={() => { setEditing(true); onChange(''); }}
            className={`rounded-xl bg-gray-100 dark:bg-white/[0.06] hover:bg-gray-200 dark:hover:bg-white/[0.1] text-violet-400 hover:text-violet-300 transition-colors whitespace-nowrap ${compact ? 'px-2 py-1.5 text-[11px]' : 'px-3 py-2.5 text-xs'}`}
          >
            Replace
          </button>
        </div>
      ) : (
        <div className="relative">
          <input
            type={field.secret && !show ? 'password' : 'text'}
            value={displayValue}
            onChange={(e) => onChange(e.target.value)}
            placeholder={field.placeholder}
            autoComplete="off"
            className={`w-full pr-10 rounded-xl bg-gray-100 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.10] text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-violet-500/40 transition-colors font-mono ${
              compact ? 'px-2.5 py-1.5 text-xs' : 'px-3 py-2.5 text-sm'
            }`}
          />
          {field.secret && (
            <button
              type="button"
              onClick={() => setShow((v) => !v)}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-700 dark:text-gray-300 transition-colors"
            >
              {show ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          )}
        </div>
      )}
      <p className={`text-gray-400 dark:text-gray-600 leading-relaxed ${compact ? 'text-[10px] mt-0.5' : 'text-[11px] mt-1'}`}>{field.helpText}</p>
    </div>
  );
}

// ─── ModelButton ─────────────────────────────────────────────────────────────

function ModelButton({
  label,
  modelValue,
  isSelected,
  isDefault,
  onClick,
  compact,
}: {
  label: string;
  modelValue: string;
  isSelected: boolean;
  isDefault?: boolean;
  onClick: () => void;
  compact?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className={`text-left rounded-xl border transition-all ${compact ? 'p-2' : 'p-3'} ${
        isSelected
          ? 'border-violet-500/50 bg-violet-500/8 ring-1 ring-violet-500/25'
          : 'border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-white/[0.01] hover:border-gray-300 dark:hover:border-white/[0.14] hover:bg-gray-50 dark:hover:bg-white/[0.03]'
      }`}
    >
      <div className="flex items-center gap-1.5 flex-wrap">
        <span className={`font-medium text-gray-900 dark:text-white leading-tight ${compact ? 'text-xs' : 'text-sm'}`}>{label}</span>
        {isDefault && (
          <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-green-500/12 text-green-400 font-bold uppercase tracking-wide">
            Default
          </span>
        )}
        {isSelected && !isDefault && (
          <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-violet-500/15 text-violet-300 font-semibold">
            Selected
          </span>
        )}
      </div>
      {modelValue !== '__custom__' && (
        <span className={`text-gray-400 dark:text-gray-600 font-mono mt-0.5 block truncate ${compact ? 'text-[9px]' : 'text-[10px]'}`}>{modelValue}</span>
      )}
    </button>
  );
}

// ─── Props ────────────────────────────────────────────────────────────────────

export interface LlmProviderModelPickerProps {
  provider: LlmProvider;
  model: string;
  onProviderChange: (provider: LlmProvider) => void;
  onModelChange: (model: string) => void;

  /**
   * When showCredentials=true, these are the current credential key→value pairs.
   * For ConfigStep this is the agent's default_config; for the harness modal it
   * is the harness's own default_config (editable credential overrides).
   */
  credentialConfig?: Record<string, string>;
  credentialConfigMeta?: Record<string, { is_set?: boolean; tail?: string }>;
  onCredentialChange?: (key: string, value: string) => void;

  /**
   * When true (agent config page): shows credential fields inline in the picker
   * and uses step-numbered headers.
   * When false (harness modal): hides credential section entirely.
   */
  showCredentials?: boolean;

  /**
   * When true: compact card labels, no step numbers (for modal use).
   * When false: full step-numbered layout (config page).
   */
  compact?: boolean;
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function LlmProviderModelPicker({
  provider,
  model,
  onProviderChange,
  onModelChange,
  credentialConfig = {},
  credentialConfigMeta = {},
  onCredentialChange,
  showCredentials = false,
  compact = false,
}: LlmProviderModelPickerProps) {
  const activeProvider: ProviderMeta = getProviderById(provider);

  // Primary credential key value (for determining whether live fetch is possible)
  const primaryKey = credentialConfig[activeProvider.primaryKeyField] || '';
  const hasKey = primaryKey.trim().length > 0;

  const needsCloudCredential =
    activeProvider.id === 'pwc_genai' || activeProvider.id === 'ollama_cloud';

  // Fetch / model state
  const [fetchedModels, setFetchedModels] = useState<string[] | null>(null);
  const [fetchingModels, setFetchingModels] = useState(false);
  const [fetchError, setFetchError] = useState('');
  const [fetchSource, setFetchSource] = useState<'live' | 'static' | null>(null);
  const [customModel, setCustomModel] = useState('');
  const [showAdvancedCreds, setShowAdvancedCreds] = useState(false);

  // Debounce ref for PwC auto-fetch
  const pwcDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Reset when provider changes
  useEffect(() => {
    setFetchedModels(null);
    setFetchError('');
    setFetchSource(null);
    setShowAdvancedCreds(false);
  }, [activeProvider.id]);

  // PwC GenAI: auto-fetch when primary key is present
  useEffect(() => {
    if (activeProvider.id !== 'pwc_genai') return;
    if (!primaryKey) {
      setFetchedModels(null);
      setFetchError('');
      setFetchSource(null);
      setFetchingModels(false);
      return;
    }
    setFetchingModels(true);
    if (pwcDebounceRef.current) clearTimeout(pwcDebounceRef.current);
    pwcDebounceRef.current = setTimeout(() => {
      fetchPwcModels(primaryKey);
    }, 800);
    return () => {
      if (pwcDebounceRef.current) clearTimeout(pwcDebounceRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [primaryKey, activeProvider.id]);

  const fetchPwcModels = async (apiKey: string) => {
    setFetchingModels(true);
    setFetchError('');
    try {
      const r = await fetch('/api/pwc-genai/models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          api_key: apiKey,
          bearer_token: credentialConfig['PWC_GENAI_BEARER_TOKEN'] || '',
          endpoint_url: credentialConfig['PWC_GENAI_ENDPOINT_URL'] || '',
        }),
      });
      if (r.status === 404 || r.status === 405 || r.status >= 500) {
        setFetchedModels(null);
        setFetchSource('static');
        return;
      }
      const data = await r.json().catch(() => ({}));
      if (r.status === 401 || r.status === 403) {
        throw new Error(data.detail || 'Invalid API key — check your PwC GenAI credentials.');
      }
      if (!r.ok) {
        setFetchedModels(null);
        setFetchSource('static');
        return;
      }
      const models: string[] = data.models || [];
      setFetchedModels(models.length > 0 ? models : null);
      setFetchSource(data.source || 'static');
      if (models.length > 0 && (!model || !models.includes(model))) {
        onModelChange(models[0]);
      }
    } catch (e: any) {
      const msg: string = e.message || '';
      if (
        msg.toLowerCase().includes('invalid') ||
        msg.toLowerCase().includes('key') ||
        msg.toLowerCase().includes('credentials')
      ) {
        setFetchError(msg);
      }
      setFetchedModels(null);
      setFetchSource('static');
    } finally {
      setFetchingModels(false);
    }
  };

  const fetchOllamaModels = async () => {
    const token = credentialConfig['ON_PREM_CLOUD_ACCESS_TOKEN'] || '';
    if (!token) return;
    setFetchingModels(true);
    setFetchError('');
    try {
      const r = await fetch('/api/ollama-cloud/tags', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || 'Failed to fetch models');
      const models: string[] = data.models || [];
      setFetchedModels(models);
      setFetchSource('live');
      if (models.length > 0 && !models.includes(model)) {
        onModelChange(models[0]);
      }
    } catch (e: any) {
      setFetchError(e.message || 'Could not reach Ollama Cloud');
      setFetchSource(null);
    } finally {
      setFetchingModels(false);
    }
  };

  const isCustomModel =
    !!model &&
    !activeProvider.staticModels.some((m) => m.value === model && m.value !== '__custom__');

  const modelsToShow: { value: string; label: string; isDefault?: boolean }[] =
    needsCloudCredential && !hasKey
      ? []
      : fetchedModels && fetchedModels.length > 0
        ? fetchedModels.map((m, i) => ({ value: m, label: m, isDefault: i === 0 }))
        : activeProvider.staticModels;

  // ── Step number badge (only in non-compact layout) ──────────────────────────
  const stepBadge = (n: number) =>
    compact ? null : (
      <span className="flex items-center justify-center w-5 h-5 rounded-full bg-violet-500/20 text-violet-400 text-[11px] font-bold">
        {n}
      </span>
    );

  const sectionHeader = (label: string, step: number, right?: React.ReactNode) => (
    <div
      className={`flex items-center gap-2.5 border-b border-gray-200 dark:border-white/[0.06] ${
        compact ? 'px-3 py-2' : 'px-4 py-3 bg-gray-50 dark:bg-white/[0.02]'
      }`}
    >
      {stepBadge(step)}
      <span className={compact
        ? 'font-body text-[10px] font-semibold uppercase tracking-wide text-zinc-500'
        : 'text-sm font-semibold text-gray-900 dark:text-white'
      }>
        {label}
      </span>
      {right && <div className="ml-auto flex items-center gap-2">{right}</div>}
    </div>
  );

  // step offsets: credentials section is step 2, model is step 3 (non-compact only)
  const credStep = 2;
  const modelStep = showCredentials ? 3 : 2;

  const primaryField = activeProvider.credentialFields.find((f) => f.primary);
  const advancedFields = activeProvider.credentialFields.filter((f) => !f.primary);

  const modelGridCls = compact
    ? 'grid gap-1.5 sm:grid-cols-2'
    : 'grid gap-2 sm:grid-cols-2 lg:grid-cols-3';

  return (
    <div className={compact ? 'space-y-3' : 'space-y-5'}>
      {/* ── Step 1: Provider cards ── */}
      <div>
        {compact ? (
          <label className="mb-1 block font-body text-[10px] font-semibold uppercase tracking-wide text-zinc-500">
            LLM Provider
          </label>
        ) : (
          <div className="flex items-center gap-2 mb-3">
            {stepBadge(1)}
            <label className="text-sm font-semibold text-gray-800 dark:text-gray-200">Choose LLM Provider</label>
          </div>
        )}
        <div className={`grid sm:grid-cols-3 ${compact ? 'mt-1 gap-1.5' : 'gap-2.5 mt-3'}`}>
          {PROVIDERS.map((p) => {
            const isActive = p.id === activeProvider.id;
            return (
              <button
                key={p.id}
                onClick={() => {
                  onProviderChange(p.id);
                  if (p.id === 'local_llm') {
                    const first = p.staticModels.find((m) => m.isDefault)?.value || p.staticModels[0].value;
                    if (first !== '__custom__') onModelChange(first);
                  } else {
                    onModelChange('');
                  }
                }}
                className={`text-left rounded-xl border transition-all ${
                  compact ? 'p-2.5' : 'p-4'
                } ${
                  isActive
                    ? 'border-violet-500/50 bg-violet-500/6 ring-1 ring-violet-500/20'
                    : 'border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-white/[0.02] hover:border-gray-300 dark:hover:border-white/[0.14] hover:bg-gray-100 dark:hover:bg-white/[0.04]'
                }`}
              >
                <div className={`flex items-start justify-between gap-2 ${compact ? 'mb-1' : 'mb-1.5'}`}>
                  <span className={`font-semibold text-gray-900 dark:text-white leading-tight ${compact ? 'text-xs' : 'text-sm'}`}>
                    {p.label}
                  </span>
                  <span
                    className={`rounded-full font-semibold whitespace-nowrap ${p.badgeColor} ${
                      compact ? 'text-[9px] px-1 py-0.5' : 'text-[10px] px-1.5 py-0.5'
                    }`}
                  >
                    {p.badge}
                  </span>
                </div>
                <p
                  className={`text-gray-500 leading-relaxed ${
                    compact ? 'text-[10px] line-clamp-2' : 'text-[11px]'
                  }`}
                >
                  {p.description}
                </p>
                {isActive && (
                  <div className={`flex items-center gap-1.5 ${compact ? 'mt-1.5' : 'mt-2.5'}`}>
                    <div className="w-1.5 h-1.5 rounded-full bg-violet-400 animate-pulse" />
                    <span className="text-[10px] text-violet-400 font-semibold">Active</span>
                  </div>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* ── Step 2: Credentials ── */}
      {showCredentials && onCredentialChange && (
        <div className="rounded-xl border border-gray-200 dark:border-white/[0.08] bg-gray-50 dark:bg-white/[0.02] overflow-hidden">
          {sectionHeader(
            activeProvider.id === 'local_llm' ? 'Server Configuration' : 'API Credentials',
            credStep,
            activeProvider.id !== 'local_llm' && (
              hasKey ? (
                <span
                  className={`flex items-center gap-1 text-green-400 font-medium ${compact ? 'text-[10px]' : 'text-xs'}`}
                >
                  <CheckCircle className={compact ? 'w-3 h-3' : 'w-3.5 h-3.5'} />
                  {activeProvider.id === 'ollama_cloud' ? 'Token provided' : 'Key provided'}
                </span>
              ) : (
                <span className={`flex items-center gap-1 text-amber-400 ${compact ? 'text-[10px]' : 'text-xs'}`}>
                  <AlertCircle className={compact ? 'w-3 h-3' : 'w-3.5 h-3.5'} /> Required
                </span>
              )
            ),
          )}
          <div className={compact ? 'p-3 space-y-3' : 'p-4 space-y-4'}>
            {/* Primary credential field */}
            {primaryField && (
              <CredentialInput
                field={primaryField}
                value={credentialConfig[primaryField.key] || ''}
                meta={credentialConfigMeta[primaryField.key]}
                onChange={(v) => onCredentialChange(primaryField.key, v)}
                compact={compact}
              />
            )}

            {/* PwC: fetch status / retry */}
            {activeProvider.id === 'pwc_genai' && (
              <>
                {fetchError && (
                  <div className="flex items-start gap-2 p-3 rounded-xl bg-red-500/8 border border-red-500/15">
                    <AlertCircle className="w-3.5 h-3.5 text-red-400 flex-shrink-0 mt-0.5" />
                    <div>
                      <p className="text-xs text-red-400 font-medium">{fetchError}</p>
                      <p className="text-[11px] text-gray-500 mt-0.5">
                        Showing default model list. Check your key and try again.
                      </p>
                    </div>
                  </div>
                )}
                {hasKey && !fetchingModels && (
                  <button
                    onClick={() => fetchPwcModels(primaryKey)}
                    className="flex items-center gap-1.5 text-xs text-violet-400 hover:text-violet-300 transition-colors"
                  >
                    <RefreshCw className="w-3 h-3" />
                    {fetchedModels ? 'Refresh model list' : 'Retry fetching models'}
                  </button>
                )}
                {fetchingModels && (
                  <span className="flex items-center gap-1.5 text-xs text-violet-400">
                    <Loader2 className="w-3 h-3 animate-spin" /> Fetching models…
                  </span>
                )}
              </>
            )}

            {/* Ollama Cloud: fetch button */}
            {activeProvider.id === 'ollama_cloud' && hasKey && (
              <div className="flex flex-wrap items-center gap-2">
                <button
                  onClick={fetchOllamaModels}
                  disabled={fetchingModels}
                  className={`inline-flex items-center rounded-xl bg-violet-600/80 hover:bg-violet-600 disabled:opacity-50 disabled:cursor-not-allowed text-gray-900 dark:text-white font-semibold transition-colors ${
                    compact ? 'gap-1.5 px-3 py-1.5 text-xs' : 'gap-2 px-4 py-2 text-sm'
                  }`}
                >
                  {fetchingModels ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <RefreshCw className="w-3.5 h-3.5" />
                  )}
                  {fetchingModels ? 'Fetching…' : fetchedModels ? 'Refresh Models' : 'Fetch Available Models'}
                </button>
                {fetchedModels && (
                  <span className="text-xs text-green-400 font-medium">
                    {fetchedModels.length} model{fetchedModels.length !== 1 ? 's' : ''} found
                  </span>
                )}
              </div>
            )}
            {activeProvider.id === 'ollama_cloud' && fetchError && (
              <div className="flex items-start gap-2 p-3 rounded-xl bg-red-500/8 border border-red-500/15">
                <AlertCircle className="w-3.5 h-3.5 text-red-400 flex-shrink-0 mt-0.5" />
                <div>
                  <p className="text-xs text-red-400 font-medium">{fetchError}</p>
                  <p className="text-[11px] text-gray-500 mt-0.5">Check your token and try again.</p>
                </div>
              </div>
            )}

            {/* Local: remaining fields inline (no "advanced" collapsible) */}
            {activeProvider.id === 'local_llm' &&
              advancedFields.map((field) => (
                <CredentialInput
                  key={field.key}
                  field={field}
                  value={credentialConfig[field.key] || ''}
                  meta={credentialConfigMeta[field.key]}
                  onChange={(v) => onCredentialChange(field.key, v)}
                  compact={compact}
                />
              ))}

            {/* PwC / Ollama Cloud: collapsible advanced fields */}
            {activeProvider.id !== 'local_llm' && advancedFields.length > 0 && (
              <div>
                <button
                  onClick={() => setShowAdvancedCreds((v) => !v)}
                  className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-700 dark:text-gray-300 transition-colors"
                >
                  {showAdvancedCreds ? (
                    <ChevronUp className="w-3.5 h-3.5" />
                  ) : (
                    <ChevronDown className="w-3.5 h-3.5" />
                  )}
                  {activeProvider.id === 'pwc_genai'
                    ? 'Advanced options (Bearer Token, Endpoint URL)'
                    : 'Advanced options (Custom API URL)'}
                </button>
                {showAdvancedCreds && (
                  <div className={`pl-3 border-l border-gray-200 dark:border-white/[0.06] ${compact ? 'mt-2 space-y-3' : 'mt-3 space-y-4'}`}>
                    {advancedFields.map((field) => (
                      <CredentialInput
                        key={field.key}
                        field={field}
                        value={credentialConfig[field.key] || ''}
                        meta={credentialConfigMeta[field.key]}
                        onChange={(v) => onCredentialChange(field.key, v)}
                        compact={compact}
                      />
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Step 3 (or 2): Model selection ── */}
      <div className="rounded-xl border border-gray-200 dark:border-white/[0.08] overflow-hidden">
        {sectionHeader(
          compact ? 'MODEL' : 'Select Model',
          modelStep,
          activeProvider.id === 'pwc_genai' && !compact ? (
            fetchingModels ? (
              <span className="flex items-center gap-1.5 text-xs text-violet-400">
                <Loader2 className="w-3 h-3 animate-spin" /> Fetching models…
              </span>
            ) : hasKey && fetchedModels && fetchSource === 'live' ? (
              <span className="flex items-center gap-1 text-xs text-green-400 font-medium">
                <CheckCircle className="w-3.5 h-3.5" /> {fetchedModels.length} models loaded
              </span>
            ) : hasKey ? (
              <span className="text-xs text-gray-500">Catalogue</span>
            ) : null
          ) : activeProvider.id === 'ollama_cloud' && fetchedModels ? (
            <span className="text-xs text-green-400 font-medium">Live from Ollama Cloud</span>
          ) : null,
        )}

        <div className={compact ? 'p-3 space-y-2.5' : 'p-4 space-y-3'}>
          {/* PwC GenAI */}
          {activeProvider.id === 'pwc_genai' && (
            <>
              {!showCredentials && fetchError && (
                <div className="flex items-start gap-2 p-3 rounded-xl bg-red-500/8 border border-red-500/15">
                  <AlertCircle className="w-3.5 h-3.5 text-red-400 flex-shrink-0 mt-0.5" />
                  <p className="text-xs text-red-400 font-medium">{fetchError}</p>
                </div>
              )}
              {!showCredentials && hasKey && !fetchingModels && (
                <button
                  onClick={() => fetchPwcModels(primaryKey)}
                  className="flex items-center gap-1.5 text-xs text-violet-400 hover:text-violet-300 transition-colors"
                >
                  <RefreshCw className="w-3 h-3" />
                  {fetchedModels ? 'Refresh model list' : 'Retry fetching models'}
                </button>
              )}
              {fetchingModels ? (
                <div
                  className={`flex items-center justify-center text-gray-500 ${compact ? 'gap-2 py-3' : 'gap-3 py-6'}`}
                >
                  <Loader2 className={`animate-spin text-violet-400 ${compact ? 'w-4 h-4' : 'w-5 h-5'}`} />
                  <span className={compact ? 'text-xs' : 'text-sm'}>Fetching available models…</span>
                </div>
              ) : modelsToShow.length === 0 ? (
                <div
                  className={`flex items-start rounded-xl bg-gray-50 dark:bg-white/[0.02] border border-gray-200 dark:border-white/[0.06] ${
                    compact ? 'gap-2 py-2.5 px-2' : 'gap-3 py-4 px-2'
                  }`}
                >
                  <Info className={`text-gray-500 flex-shrink-0 mt-0.5 ${compact ? 'w-3.5 h-3.5' : 'w-4 h-4'}`} />
                  <p className={`text-gray-500 leading-relaxed ${compact ? 'text-xs' : 'text-sm'}`}>
                    {showCredentials
                      ? 'Enter your API key above to load available models.'
                      : 'No PwC GenAI API key found in this agent\'s config.'}
                  </p>
                </div>
              ) : (
                <>
                  {(!fetchedModels || fetchSource === 'static') && hasKey && (
                    <div
                      className={`flex items-start gap-2 rounded-xl bg-blue-500/5 border border-blue-500/10 ${
                        compact ? 'mb-1.5 p-2' : 'mb-2 p-3'
                      }`}
                    >
                      <Info
                        className={`text-blue-400 flex-shrink-0 mt-0.5 ${compact ? 'w-3 h-3' : 'w-3.5 h-3.5'}`}
                      />
                      <p
                        className={`text-gray-600 dark:text-gray-400 leading-relaxed ${compact ? 'text-[10px]' : 'text-[11px]'}`}
                      >
                        Showing fallback catalogue.{' '}
                        <strong className="text-gray-700 dark:text-gray-300">Gemini 2.5 Flash</strong> is a solid default.
                      </p>
                    </div>
                  )}
                  <div className={modelGridCls}>
                    {modelsToShow.map((m) => (
                      <ModelButton
                        key={m.value}
                        label={m.label}
                        modelValue={m.value}
                        isDefault={!!m.isDefault}
                        isSelected={!!model && model === m.value}
                        onClick={() => onModelChange(m.value)}
                        compact={compact}
                      />
                    ))}
                  </div>
                </>
              )}
            </>
          )}

          {/* Ollama Cloud */}
          {activeProvider.id === 'ollama_cloud' && (
            <>
              {!showCredentials && hasKey && (
                <div className={`flex flex-wrap items-center ${compact ? 'gap-2' : 'gap-3'}`}>
                  <button
                    onClick={fetchOllamaModels}
                    disabled={fetchingModels}
                    className={`inline-flex items-center rounded-xl bg-violet-600/80 hover:bg-violet-600 disabled:opacity-50 disabled:cursor-not-allowed text-gray-900 dark:text-white font-semibold transition-colors ${
                      compact ? 'gap-1.5 px-3 py-1.5 text-xs' : 'gap-2 px-4 py-2 text-sm'
                    }`}
                  >
                    {fetchingModels ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <RefreshCw className="w-3.5 h-3.5" />
                    )}
                    {fetchingModels ? 'Fetching…' : fetchedModels ? 'Refresh Models' : 'Fetch Available Models'}
                  </button>
                  {fetchedModels && (
                    <span className="text-xs text-green-400 font-medium">
                      {fetchedModels.length} model{fetchedModels.length !== 1 ? 's' : ''} found
                    </span>
                  )}
                </div>
              )}
              {!showCredentials && fetchError && (
                <div className="flex items-start gap-2 p-3 rounded-xl bg-red-500/8 border border-red-500/15">
                  <AlertCircle className="w-3.5 h-3.5 text-red-400 flex-shrink-0 mt-0.5" />
                  <p className="text-xs text-red-400 font-medium">{fetchError}</p>
                </div>
              )}
              {!hasKey && (
                <div
                  className={`flex items-start rounded-xl bg-gray-50 dark:bg-white/[0.02] border border-gray-200 dark:border-white/[0.06] ${
                    compact ? 'gap-2 py-2.5 px-2' : 'gap-3 py-4 px-2'
                  }`}
                >
                  <Info className={`text-gray-500 flex-shrink-0 mt-0.5 ${compact ? 'w-3.5 h-3.5' : 'w-4 h-4'}`} />
                  <p className={`text-gray-500 leading-relaxed ${compact ? 'text-xs' : 'text-sm'}`}>
                    {showCredentials
                      ? 'Enter your API token above to load available models.'
                      : 'No Ollama Cloud token found. Default models shown.'}
                  </p>
                </div>
              )}
              {modelsToShow.length > 0 && (
                <>
                  <div className={modelGridCls}>
                    {modelsToShow.map((m) => (
                      <ModelButton
                        key={m.value}
                        label={m.label}
                        modelValue={m.value}
                        isDefault={!!m.isDefault}
                        isSelected={!!model && model === m.value}
                        onClick={() => onModelChange(m.value)}
                        compact={compact}
                      />
                    ))}
                  </div>
                  {!fetchedModels && !fetchError && hasKey && (
                    <p className="text-[11px] text-gray-400 dark:text-gray-600">
                      Click <strong className="text-gray-600 dark:text-gray-400">Fetch Available Models</strong> to load your account's actual model list.
                    </p>
                  )}
                </>
              )}
            </>
          )}

          {/* Local / Self-hosted */}
          {activeProvider.id === 'local_llm' && (
            <>
              <div className={modelGridCls}>
                {activeProvider.staticModels.map((m) => (
                  <ModelButton
                    key={m.value}
                    label={m.label}
                    modelValue={m.value}
                    isDefault={!!m.isDefault}
                    isSelected={m.value === '__custom__' ? isCustomModel : model === m.value}
                    onClick={() => {
                      if (m.value === '__custom__') {
                        onModelChange(customModel || '');
                      } else {
                        onModelChange(m.value);
                        setCustomModel('');
                      }
                    }}
                    compact={compact}
                  />
                ))}
              </div>
              {(isCustomModel || activeProvider.staticModels.some((m) => m.value === '__custom__')) && (
                <input
                  type="text"
                  value={isCustomModel ? model : customModel}
                  onChange={(e) => {
                    setCustomModel(e.target.value);
                    onModelChange(e.target.value);
                  }}
                  placeholder="e.g. llama3.2:3b or my-custom-model"
                  className={`w-full rounded-xl bg-gray-100 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-violet-500/40 font-mono transition-colors ${
                    compact ? 'px-3 py-1.5 text-xs' : 'px-4 py-2.5 text-sm'
                  }`}
                />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
