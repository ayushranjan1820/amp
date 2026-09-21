import * as React from 'react';
import { X } from 'lucide-react';
import type { PromptHarnessEdgeConfig, PromptHarnessOutputFormat } from '../utils/workflowFlowGraph';
import {
  type LlmProvider,
  providerFromEnv,
  modelFromEnv,
} from '../utils/llmProviderCatalog';
import LlmProviderModelPicker from './agent-builder/LlmProviderModelPicker';

export interface PromptHarnessModalProps {
  open: boolean;
  /** Upstream step → downstream step */
  edge: { fromStep: number; toStep: number } | null;
  initialConfig: PromptHarnessEdgeConfig | undefined;
  /** Effective env for the downstream agent (pre-fills provider/model when no harness config exists). */
  mergedAgentEnv: Record<string, string>;
  onClose: () => void;
  /** Pass null to remove harness for this edge. */
  onSave: (cfg: PromptHarnessEdgeConfig | null) => void;
}

export default function PromptHarnessModal({
  open,
  edge,
  initialConfig,
  mergedAgentEnv,
  onClose,
  onSave,
}: PromptHarnessModalProps) {
  const [provider, setProvider] = React.useState<LlmProvider>('pwc_genai');
  const [model, setModel] = React.useState('');
  const [description, setDescription] = React.useState('');
  const [format, setFormat] = React.useState<PromptHarnessOutputFormat>('markdown');
  const [maxOutputChars, setMaxOutputChars] = React.useState('');
  /**
   * Editable credential overrides stored in the harness config.
   * Starts from `initialConfig.default_config` (if any), otherwise empty.
   * The backend merges these on top of the consuming agent's saved credentials,
   * so only values the user explicitly sets here will override the agent's own creds.
   */
  const [draftConfig, setDraftConfig] = React.useState<Record<string, string>>({});

  React.useEffect(() => {
    if (!open || !edge) return;
    const saved = initialConfig?.default_config || {};
    const merged = { ...mergedAgentEnv, ...saved };
    const p = providerFromEnv(merged);
    setProvider(p);
    setModel(Object.keys(saved).length > 0 ? modelFromEnv(p, saved) : modelFromEnv(p, mergedAgentEnv));
    setDescription((initialConfig?.expected_output_description || '').trim());
    setFormat(initialConfig?.output_format || 'markdown');
    setMaxOutputChars(
      initialConfig?.max_output_chars != null && initialConfig.max_output_chars > 0
        ? String(initialConfig.max_output_chars)
        : '',
    );
    // Seed draft with saved harness credentials only (not the inherited agent env)
    setDraftConfig({ ...saved });
  }, [open, edge, initialConfig, mergedAgentEnv]);

  if (!open || !edge) return null;

  const setCredential = (key: string, value: string) => {
    setDraftConfig((prev) => {
      const next = { ...prev, [key]: value };
      if (!value) delete next[key];
      return next;
    });
  };

  const handleSave = () => {
    const desc = description.trim();
    if (!desc) {
      onSave(null);
      onClose();
      return;
    }

    // Build default_config: start from credential overrides, then apply provider + model on top
    const dc: Record<string, string> = { ...draftConfig, LLM_PROVIDER: provider };
    // Clear all model env keys then set the active one
    delete dc.PREMIUM_MODEL;
    delete dc.ON_PREM_CLOUD_MODEL;
    delete dc.LOCAL_LLM_MODEL;
    const m = model.trim();
    if (m) {
      if (provider === 'pwc_genai') dc.PREMIUM_MODEL = m;
      else if (provider === 'ollama_cloud') dc.ON_PREM_CLOUD_MODEL = m;
      else dc.LOCAL_LLM_MODEL = m;
    }

    let max_chars: number | undefined;
    const rawCap = maxOutputChars.trim();
    if (rawCap !== '') {
      const n = parseInt(rawCap, 10);
      if (!Number.isNaN(n) && n > 0) max_chars = n;
    }

    onSave({
      expected_output_description: desc,
      output_format: format,
      default_config: dc,
      ...(max_chars != null ? { max_output_chars: max_chars } : {}),
    });
    onClose();
  };

  const handleClear = () => {
    onSave(null);
    onClose();
  };

  // The picker needs a combined view: inherited env (read-only background) merged
  // with whatever the user has typed in the harness draft, so live-fetch works.
  const effectiveCredentialConfig = { ...mergedAgentEnv, ...draftConfig };

  return (
    <div
      className="fixed inset-0 z-[125] flex items-center justify-center overflow-y-auto bg-black/75 p-3 backdrop-blur-sm sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="prompt-harness-title"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="relative w-full max-w-2xl overflow-hidden rounded-xl border border-gray-200 dark:border-white/[0.08] bg-zinc-950 shadow-[0_24px_80px_-40px_rgba(0,0,0,0.9)] ring-1 ring-white/[0.05] sm:rounded-2xl">
        {/* Header */}
        <div className="flex items-start justify-between gap-2 border-b border-gray-200 dark:border-white/[0.06] bg-gradient-to-r from-violet-500/10 via-fuchsia-500/6 to-cyan-500/10 px-3 py-2.5 sm:px-4 sm:py-3">
          <div className="min-w-0">
            <p id="prompt-harness-title" className="font-body text-xs font-semibold text-gray-900 dark:text-white sm:text-sm">
              Prompt Harness
            </p>
            <p className="mt-0.5 font-body text-[10px] leading-snug text-zinc-400 sm:text-[11px]">
              Step {edge.fromStep} → Step {edge.toStep}: LLM pass on upstream output before this step sees it.
            </p>
          </div>
          <button
            type="button"
            aria-label="Close"
            className="shrink-0 rounded-lg border border-gray-200 dark:border-white/10 bg-black/30 p-1 text-zinc-400 transition-colors hover:bg-white/10 hover:text-gray-900 dark:hover:text-white sm:p-1.5"
            onClick={onClose}
          >
            <X className="h-3.5 w-3.5 sm:h-4 sm:w-4" />
          </button>
        </div>

        {/* Body */}
        <div className="max-h-[min(72vh,640px)] space-y-4 overflow-y-auto px-3 py-3 sm:px-4 sm:py-4">
          {/* Outcome first: what the downstream step must receive */}
          <div className="rounded-xl border border-violet-500/35 bg-gradient-to-b from-violet-500/[0.12] via-violet-500/[0.04] to-zinc-950/90 p-3 shadow-[0_0_32px_-12px_rgba(139,92,246,0.35)] ring-1 ring-inset ring-violet-500/20 sm:p-4">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <label
                htmlFor="prompt-harness-description"
                className="font-body text-sm font-semibold tracking-tight text-gray-900 dark:text-white sm:text-[15px]"
              >
                Expected output
              </label>
              <span className="shrink-0 rounded-md bg-violet-500/25 px-2 py-0.5 font-body text-[10px] font-semibold uppercase tracking-wide text-violet-100">
                Required
              </span>
            </div>
            <textarea
              id="prompt-harness-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={4}
              placeholder="Describe what the downstream step should receive — e.g. bullet summary, extracted JSON fields, rewritten brief."
              className="min-h-[7.5rem] w-full resize-y rounded-lg border border-gray-200 dark:border-white/[0.12] bg-white dark:bg-black/50 px-3 py-2.5 font-body text-sm leading-relaxed text-gray-900 dark:text-zinc-100 placeholder:text-gray-400 dark:placeholder:text-zinc-500 focus:border-violet-400/50 focus:outline-none focus:ring-2 focus:ring-violet-500/35"
            />
            <p className="mt-2 font-body text-[11px] leading-snug text-zinc-400 sm:text-xs">
              This text shapes the harness prompt. Leave empty and save to remove the harness from this edge.
            </p>

            <div className="mt-4 border-t border-gray-200 dark:border-white/[0.08] pt-3">
              <label
                htmlFor="prompt-harness-max-chars"
                className="mb-1.5 block font-body text-[10px] font-semibold uppercase tracking-wide text-violet-200/90"
              >
                Max output length (optional)
              </label>
              <input
                id="prompt-harness-max-chars"
                type="number"
                min={1}
                step={1}
                placeholder="e.g. 4000 — hard cap enforced after the harness LLM"
                value={maxOutputChars}
                onChange={(e) => setMaxOutputChars(e.target.value)}
                className="w-full rounded-lg border border-gray-200 dark:border-white/[0.12] bg-white dark:bg-black/45 px-3 py-2 font-body text-xs text-gray-900 dark:text-zinc-100 placeholder:text-gray-400 dark:placeholder:text-zinc-600 focus:border-violet-400/45 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
              />
              <p className="mt-1.5 font-body text-[10px] leading-snug text-zinc-500 sm:text-[11px]">
                Leave empty for no fixed limit — the harness model may still follow your instructions, but only this
                field guarantees a ceiling.
              </p>
            </div>

            <div className="mt-4 border-t border-gray-200 dark:border-white/[0.08] pt-3">
              <label
                htmlFor="prompt-harness-format"
                className="mb-1.5 block font-body text-[10px] font-semibold uppercase tracking-wide text-violet-200/90"
              >
                Output format
              </label>
              <select
                id="prompt-harness-format"
                value={format}
                onChange={(e) => setFormat(e.target.value as PromptHarnessOutputFormat)}
                className="w-full rounded-lg border border-gray-200 dark:border-white/[0.12] bg-white dark:bg-black/45 px-3 py-2 font-body text-xs text-gray-900 dark:text-zinc-100 focus:border-violet-400/45 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
              >
                <option value="markdown">Markdown (default)</option>
                <option value="json">JSON</option>
                <option value="text">Plain text</option>
              </select>
            </div>
          </div>

          {/* LLM + credentials (tuning) */}
          <div className="space-y-2">
            <p className="font-body text-[10px] font-semibold uppercase tracking-wide text-zinc-500">
              Model &amp; credentials
            </p>
            <LlmProviderModelPicker
              provider={provider}
              model={model}
              onProviderChange={setProvider}
              onModelChange={setModel}
              credentialConfig={effectiveCredentialConfig}
              onCredentialChange={setCredential}
              showCredentials={true}
              compact={true}
            />
            <p className="font-body text-[10px] leading-snug text-zinc-500">
              Overrides you set here apply only to this harness; the agent&apos;s saved credentials stay the same.
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="flex flex-wrap items-center justify-end gap-1.5 border-t border-gray-200 dark:border-white/[0.06] bg-black/25 px-3 py-2 sm:gap-2 sm:px-4 sm:py-2.5">
          <button
            type="button"
            className="rounded-lg border border-gray-200 dark:border-white/10 px-2.5 py-1.5 font-body text-[11px] font-medium text-zinc-300 hover:bg-gray-100 dark:hover:bg-white/[0.06] sm:px-3 sm:py-2 sm:text-xs"
            onClick={handleClear}
          >
            Remove harness
          </button>
          <button
            type="button"
            className="rounded-lg border border-gray-200 dark:border-white/10 px-2.5 py-1.5 font-body text-[11px] font-medium text-zinc-300 hover:bg-gray-100 dark:hover:bg-white/[0.06] sm:px-3 sm:py-2 sm:text-xs"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            type="button"
            className="rounded-lg bg-violet-600 px-3 py-1.5 font-body text-[11px] font-semibold text-gray-900 dark:text-white shadow-[0_8px_24px_-12px_rgba(139,92,246,0.8)] hover:bg-violet-500 sm:px-4 sm:py-2 sm:text-xs"
            onClick={handleSave}
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
