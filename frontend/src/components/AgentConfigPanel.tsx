import { useState, useEffect, useMemo, useRef, useId, type ReactNode, type KeyboardEvent } from 'react';
import {
  Save,
  Trash2,
  Eye,
  EyeOff,
  CheckCircle2,
  AlertTriangle,
  Settings,
  ShieldCheck,
  ShieldAlert,
  Laptop2,
  Cloud,
  Globe,
  Sparkles,
  ChevronDown,
  Search,
  X,
  KeyRound,
  Paperclip,
  FileText,
  Upload,
} from 'lucide-react';
import {
  AGENTS_WITH_FILE_CONFIG,
  supportsFileConfig,
  loadAgentFiles,
  saveAgentFiles,
  clearAgentFiles,
  fileToStored,
  type StoredAgentFile,
} from '../utils/agentConfigFiles';
import {
  type AgentConfigField,
  getConfigFields,
  loadAgentConfig,
  saveAgentConfig,
  clearAgentConfig,
  getDraftEffectiveConfig,
  filterConfigFieldsForLlmProvider,
  getEffectiveLlmProvider,
  getMissingRequiredFieldsForEffective,
  hasRequiredConfigForEffective,
  isLlmBundledConfigKey,
  migrateLegacyUseLocalLlmInConfig,
  type LlmProviderChoice,
} from '../utils/agentConfigStorage';
import type { Agent } from '../services/api';
import ClaudeCodeModelPicker from './ClaudeCodeModelPicker';

interface AgentConfigPanelProps {
  agent: Agent;
  onConfigChange?: (isConfigured: boolean) => void;
  /** Fired when local draft differs from last saved config (Save button would be enabled). */
  onDraftDirtyChange?: (dirty: boolean) => void;
  /** Dense layout for embedding in workflow cards or modals */
  compact?: boolean;
  /** Called after Save or Clear so parents can refresh derived UI */
  onSaved?: () => void;
  /** Dark embedded card (e.g. workflow step): grid fields, glass inputs, no inner scroll */
  workflowEmbed?: boolean;
}

export default function AgentConfigPanel({
  agent,
  onConfigChange,
  onDraftDirtyChange,
  compact = false,
  onSaved,
  workflowEmbed = false,
}: AgentConfigPanelProps) {
  const fields = getConfigFields(agent);
  const [values, setValues] = useState<Record<string, string>>({});
  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({});
  const [saved, setSaved] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [files, setFiles] = useState<StoredAgentFile[]>([]);
  const [fileError, setFileError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const hasFileConfig = supportsFileConfig(agent.id);
  const fileConfigMeta = hasFileConfig ? AGENTS_WITH_FILE_CONFIG[agent.id] : null;

  const adminDefaults = agent.default_config || {};
  const hasAnyAdminDefaults = Object.values(adminDefaults).some(v => v?.trim());

  useEffect(() => {
    const raw = loadAgentConfig(agent.id);
    const { config: loaded, changed } = migrateLegacyUseLocalLlmInConfig(raw);
    if (changed) saveAgentConfig(agent.id, loaded);
    setValues(loaded);
    setDirty(false);
    setFiles(hasFileConfig ? loadAgentFiles(agent.id) : []);
    setFileError(null);
  }, [agent.id, hasFileConfig]);

  const handleFilesPicked = async (picked: FileList | null) => {
    if (!picked || picked.length === 0 || !fileConfigMeta) return;
    setFileError(null);
    const allowedExts = fileConfigMeta.accept
      .split(',')
      .map((s) => s.trim().replace(/^\./, '').toLowerCase())
      .filter(Boolean);
    const accepted: StoredAgentFile[] = [];
    for (const f of Array.from(picked)) {
      const ext = (f.name.split('.').pop() || '').toLowerCase();
      if (allowedExts.length && !allowedExts.includes(ext)) {
        setFileError(`Unsupported file type: ${f.name}`);
        continue;
      }
      if (f.size > 10 * 1024 * 1024) {
        setFileError(`${f.name} is larger than 10 MB`);
        continue;
      }
      try {
        accepted.push(await fileToStored(f));
      } catch (e) {
        setFileError(`Failed to read ${f.name}`);
      }
    }
    if (!accepted.length) return;
    setFiles((prev) => {
      const merged = [...prev];
      for (const a of accepted) {
        const idx = merged.findIndex((m) => m.file_name === a.file_name);
        if (idx >= 0) merged[idx] = a;
        else merged.push(a);
      }
      const trimmed = fileConfigMeta.maxCount > 0 ? merged.slice(-fileConfigMeta.maxCount) : merged;
      saveAgentFiles(agent.id, trimmed);
      onSaved?.();
      return trimmed;
    });
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleRemoveFile = (name: string) => {
    setFiles((prev) => {
      const next = prev.filter((f) => f.file_name !== name);
      saveAgentFiles(agent.id, next);
      onSaved?.();
      return next;
    });
  };

  const handleClearAllFiles = () => {
    clearAgentFiles(agent.id);
    setFiles([]);
    onSaved?.();
  };

  const draftEffective = useMemo(() => getDraftEffectiveConfig(agent, values), [agent, values]);

  const displayFields = useMemo(() => {
    const visible = filterConfigFieldsForLlmProvider(
      fields,
      getEffectiveLlmProvider(fields, draftEffective),
      draftEffective,
    );
    if (agent.id === 'claude_code') {
      return visible.filter((f) => f.key !== 'CLAUDE_CODE_MODEL');
    }
    return visible;
  }, [agent.id, draftEffective, fields]);

  useEffect(() => {
    onConfigChange?.(hasRequiredConfigForEffective(agent, fields, draftEffective));
  }, [agent, fields, draftEffective, onConfigChange]);

  useEffect(() => {
    onDraftDirtyChange?.(dirty);
  }, [dirty, onDraftDirtyChange]);

  if (fields.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-center">
        <div className="w-12 h-12 bg-gray-100 dark:bg-gray-800 rounded-xl flex items-center justify-center mb-3">
          <ShieldCheck className="w-6 h-6 text-green-500" />
        </div>
        <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">No Configuration Needed</p>
        <p className="text-xs text-gray-500 dark:text-gray-400">This agent works out of the box.</p>
      </div>
    );
  }

  const isSecretField = (key: string) => {
    const lower = key.toLowerCase();
    return lower.includes('token') || lower.includes('key') || lower.includes('secret') || lower.includes('password') || key === 'ZOHO_MCP_URL';
  };

  const handleChange = (key: string, value: string) => {
    setValues((prev) => {
      const next = { ...prev, [key]: value };
      // Chat reads saved localStorage only — persist web-search provider immediately so API requests match the UI.
      if (key.endsWith('_WEB_SEARCH_PROVIDER')) {
        saveAgentConfig(agent.id, next);
      }
      return next;
    });
    setDirty(true);
    setSaved(false);
  };

  const handleLlmProviderChange = (v: string) => {
    setValues((prev) => {
      const next: Record<string, string> = { ...prev, LLM_PROVIDER: v };
      delete next.USE_LOCAL_LLM;
      return next;
    });
    setDirty(true);
    setSaved(false);
  };

  const handleSave = () => {
    saveAgentConfig(agent.id, values);
    setDirty(false);
    setSaved(true);
    onConfigChange?.(hasRequiredConfigForEffective(agent, fields, getDraftEffectiveConfig(agent, values)));
    onSaved?.();
    setTimeout(() => setSaved(false), 2500);
  };

  const handleCancel = () => {
    const raw = loadAgentConfig(agent.id);
    const { config: loaded, changed } = migrateLegacyUseLocalLlmInConfig(raw);
    if (changed) saveAgentConfig(agent.id, loaded);
    setValues(loaded);
    setDirty(false);
    setSaved(false);
    onConfigChange?.(hasRequiredConfigForEffective(agent, fields, getDraftEffectiveConfig(agent, loaded)));
  };

  const handleClear = () => {
    clearAgentConfig(agent.id);
    setValues({});
    setDirty(false);
    setSaved(false);
    onConfigChange?.(hasRequiredConfigForEffective(agent, fields, getDraftEffectiveConfig(agent, {})));
    onSaved?.();
  };

  const toggleShow = (key: string) => {
    setShowSecrets(prev => ({ ...prev, [key]: !prev[key] }));
  };

  const llmBundledFields = displayFields.filter((f) => isLlmBundledConfigKey(f.key));
  const llmProviderField = llmBundledFields.find((f) => f.key === 'LLM_PROVIDER');
  const llmNestedFields = llmBundledFields.filter((f) => f.key !== 'LLM_PROVIDER');
  const outsideFields = displayFields.filter((f) => !isLlmBundledConfigKey(f.key));
  const requiredFields = outsideFields.filter((f) => f.required);
  const optionalFields = outsideFields.filter((f) => !f.required);
  const missingRequired = getMissingRequiredFieldsForEffective(agent, fields, draftEffective);
  const allRequiredSet = missingRequired.length === 0;

  const bannerPad = compact ? 'p-2' : 'pl-4 pr-3 py-3.5 sm:pl-5 sm:pr-4 sm:py-4';

  const fieldGridClass =
    workflowEmbed && compact
      ? 'grid gap-2 sm:grid-cols-2 sm:gap-2.5'
      : compact
        ? 'space-y-2'
        : 'space-y-2.5';

  return (
    <div className={compact && workflowEmbed ? 'space-y-2' : compact ? 'space-y-2' : 'space-y-4'}>
      {!compact && hasAnyAdminDefaults && allRequiredSet && (
        <div
          className={`relative overflow-hidden rounded-2xl border border-sky-200/70 bg-sky-50/90 shadow-sm shadow-sky-900/[0.04] backdrop-blur-sm dark:border-sky-500/20 dark:bg-sky-950/35 dark:shadow-black/20 ${bannerPad}`}
        >
          <div
            className="pointer-events-none absolute inset-y-2 left-0 w-1 rounded-full bg-gradient-to-b from-sky-400 to-blue-500 opacity-90 dark:from-sky-400/90 dark:to-blue-500/80"
            aria-hidden
          />
          <div className="relative flex items-start gap-3 sm:gap-3.5">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-sky-500/15 ring-1 ring-sky-500/20 dark:bg-sky-400/10 dark:ring-sky-400/25">
              <ShieldAlert className="h-5 w-5 text-sky-600 dark:text-sky-300" />
            </div>
            <div className="min-w-0 pt-0.5">
              <p className="font-body text-xs font-semibold tracking-tight text-sky-950 dark:text-sky-100">
                Pre-configured by admin
              </p>
              <p className="font-body mt-1 text-[11px] leading-relaxed text-sky-800/90 dark:text-sky-300/85">
                Defaults are set by your administrator. Override any field below when you need to.
              </p>
            </div>
          </div>
        </div>
      )}

      {!compact && !allRequiredSet && (
        <div
          className={`relative overflow-hidden rounded-2xl border border-amber-200/80 bg-amber-50/90 shadow-sm shadow-amber-900/[0.05] backdrop-blur-sm dark:border-amber-500/25 dark:bg-amber-950/40 dark:shadow-black/25 ${bannerPad}`}
        >
          <div
            className="pointer-events-none absolute inset-y-2 left-0 w-1 rounded-full bg-gradient-to-b from-amber-400 to-orange-500 opacity-90 dark:from-amber-400/85 dark:to-orange-500/75"
            aria-hidden
          />
          <div className="relative flex items-start gap-3 sm:gap-3.5">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-amber-500/15 ring-1 ring-amber-500/25 dark:bg-amber-400/12 dark:ring-amber-400/30">
              <AlertTriangle className="h-5 w-5 text-amber-600 dark:text-amber-300" />
            </div>
            <div className="min-w-0 pt-0.5">
              <p className="font-body text-xs font-semibold tracking-tight text-amber-950 dark:text-amber-100">
                Configuration required
              </p>
              <p className="font-body mt-1 text-[11px] leading-relaxed text-amber-900/85 dark:text-amber-200/80">
                {missingRequired.length} required {missingRequired.length === 1 ? 'field is' : 'fields are'} missing. Finish setup before chatting.
              </p>
            </div>
          </div>
        </div>
      )}

      {compact && !allRequiredSet && !workflowEmbed && (
        <p className="text-[10px] text-amber-400/90 font-body leading-snug">
          <AlertTriangle className="w-3 h-3 inline-block mr-1 align-text-bottom" />
          {missingRequired.length} required {missingRequired.length === 1 ? 'field' : 'fields'} missing.
        </p>
      )}

      {!compact && allRequiredSet && !hasAnyAdminDefaults && (
        <div
          className={`relative overflow-hidden rounded-2xl border border-emerald-200/75 bg-emerald-50/90 shadow-sm shadow-emerald-900/[0.04] backdrop-blur-sm dark:border-emerald-500/22 dark:bg-emerald-950/35 dark:shadow-black/20 ${bannerPad}`}
        >
          <div
            className="pointer-events-none absolute inset-y-2 left-0 w-1 rounded-full bg-gradient-to-b from-emerald-400 to-teal-500 opacity-90 dark:from-emerald-400/90 dark:to-teal-500/80"
            aria-hidden
          />
          <div className="relative flex items-start gap-3 sm:gap-3.5">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-500/15 ring-1 ring-emerald-500/20 dark:bg-emerald-400/12 dark:ring-emerald-400/25">
              <CheckCircle2 className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
            </div>
            <div className="min-w-0 pt-0.5">
              <p className="font-body text-xs font-semibold tracking-tight text-emerald-950 dark:text-emerald-100">
                Configured
              </p>
              <p className="font-body mt-1 text-[11px] leading-relaxed text-emerald-900/85 dark:text-emerald-200/80">
                Required settings are available from this browser or the server.
              </p>
            </div>
          </div>
        </div>
      )}

      {hasFileConfig && fileConfigMeta && (
        <div
          className={
            workflowEmbed
              ? 'rounded-xl border border-white/[0.08] bg-white/[0.03] p-3'
              : compact
                ? 'rounded-xl border border-gray-200/80 bg-gray-50/70 p-3 dark:border-white/[0.06] dark:bg-zinc-900/40'
                : 'overflow-hidden rounded-2xl border border-gray-200/85 bg-gradient-to-b from-white via-white to-gray-50/90 p-4 shadow-sm shadow-gray-900/[0.04] ring-1 ring-black/[0.02] dark:border-white/[0.08] dark:from-zinc-900/90 dark:via-zinc-950/95 dark:to-[#08090d] dark:shadow-black/30 dark:ring-white/[0.04]'
          }
        >
          <div className="flex items-start gap-3">
            <div className={`flex ${compact ? 'h-8 w-8' : 'h-10 w-10'} shrink-0 items-center justify-center rounded-xl bg-indigo-500/12 text-indigo-600 ring-1 ring-indigo-500/20 dark:bg-indigo-500/15 dark:text-indigo-300 dark:ring-indigo-400/25`}>
              <Paperclip className={compact ? 'h-4 w-4' : 'h-5 w-5'} aria-hidden />
            </div>
            <div className="min-w-0 flex-1 pt-0.5">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <h3 className={`font-body font-semibold tracking-tight ${compact ? 'text-[11px]' : 'text-sm'} ${workflowEmbed ? 'text-white' : 'text-gray-900 dark:text-white'}`}>
                    {fileConfigMeta.label}
                  </h3>
                  <p className={`font-body mt-0.5 leading-relaxed ${compact ? 'text-[10px]' : 'text-xs'} ${workflowEmbed ? 'text-gray-400' : 'text-gray-600 dark:text-zinc-400'}`}>
                    {fileConfigMeta.description}
                  </p>
                </div>
                {files.length > 0 && (
                  <button
                    type="button"
                    onClick={handleClearAllFiles}
                    className={`shrink-0 rounded-md border px-2 py-1 text-[10px] font-semibold transition ${
                      workflowEmbed
                        ? 'border-rose-400/30 bg-rose-500/10 text-rose-300 hover:bg-rose-500/20'
                        : 'border-red-200/70 bg-red-50/90 text-red-700 hover:bg-red-100 dark:border-red-500/25 dark:bg-red-950/40 dark:text-red-300'
                    }`}
                    title="Remove all uploaded files"
                  >
                    Clear all
                  </button>
                )}
              </div>

              <input
                ref={fileInputRef}
                type="file"
                accept={fileConfigMeta.accept}
                multiple={fileConfigMeta.maxCount > 1}
                onChange={(e) => handleFilesPicked(e.target.files)}
                className="hidden"
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className={`mt-2 flex items-center gap-2 rounded-lg border border-dashed px-3 py-2 font-semibold transition ${compact ? 'text-[11px]' : 'text-xs'} ${
                  workflowEmbed
                    ? 'border-indigo-400/35 bg-indigo-500/10 text-indigo-200 hover:bg-indigo-500/20'
                    : 'border-indigo-300 bg-indigo-50/80 text-indigo-700 hover:bg-indigo-100 dark:border-indigo-500/35 dark:bg-indigo-950/35 dark:text-indigo-200 dark:hover:bg-indigo-950/55'
                }`}
              >
                <Upload className={compact ? 'h-3 w-3' : 'h-3.5 w-3.5'} />
                {files.length > 0 ? 'Add more files' : 'Upload file(s)'}
              </button>

              {fileError && (
                <p className="mt-2 text-[11px] text-rose-500 dark:text-rose-300">{fileError}</p>
              )}

              {files.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {files.map((f) => (
                    <li
                      key={f.file_name}
                      className={`flex items-center justify-between gap-2 rounded-md px-2 py-1.5 ${
                        workflowEmbed
                          ? 'bg-white/[0.05] ring-1 ring-white/[0.06]'
                          : 'bg-white/90 ring-1 ring-gray-200/70 dark:bg-zinc-900/50 dark:ring-white/[0.06]'
                      }`}
                    >
                      <div className="flex min-w-0 items-center gap-2">
                        <FileText className={`shrink-0 ${workflowEmbed ? 'text-indigo-300' : 'text-indigo-600 dark:text-indigo-300'} h-3.5 w-3.5`} />
                        <span className={`truncate font-body ${compact ? 'text-[10px]' : 'text-[11px]'} ${workflowEmbed ? 'text-gray-200' : 'text-gray-800 dark:text-zinc-200'}`}>
                          {f.file_name}
                        </span>
                        {typeof f.size === 'number' && (
                          <span className={`shrink-0 font-body ${compact ? 'text-[9px]' : 'text-[10px]'} ${workflowEmbed ? 'text-gray-500' : 'text-gray-500 dark:text-zinc-500'}`}>
                            {(f.size / 1024).toFixed(1)} KB
                          </span>
                        )}
                      </div>
                      <button
                        type="button"
                        onClick={() => handleRemoveFile(f.file_name)}
                        className={`shrink-0 rounded p-1 transition ${
                          workflowEmbed
                            ? 'text-gray-400 hover:bg-white/[0.05] hover:text-rose-300'
                            : 'text-gray-500 hover:bg-gray-100 hover:text-rose-600 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-rose-300'
                        }`}
                        aria-label={`Remove ${f.file_name}`}
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      )}

      {llmProviderField && (
        <ConfigField
          key={llmProviderField.key}
          field={llmProviderField}
          value={values[llmProviderField.key] || ''}
          adminDefault={adminDefaults[llmProviderField.key]}
          isSecret={isSecretField(llmProviderField.key)}
          showSecret={showSecrets[llmProviderField.key] || false}
          onChange={handleLlmProviderChange}
          onToggleShow={() => toggleShow(llmProviderField.key)}
          resolvedLlmProvider={getEffectiveLlmProvider(fields, draftEffective)}
          ollamaCloudApiToken={draftEffective['ON_PREM_CLOUD_ACCESS_TOKEN'] ?? ''}
          compact={compact}
          workflowEmbed={workflowEmbed}
          embedBelow={
            llmNestedFields.length > 0 ? (
              <div className="space-y-3">
                {llmNestedFields.map((field) => (
                  <ConfigField
                    key={field.key}
                    field={field}
                    value={values[field.key] || ''}
                    adminDefault={adminDefaults[field.key]}
                    isSecret={isSecretField(field.key)}
                    showSecret={showSecrets[field.key] || false}
                    onChange={(v) => handleChange(field.key, v)}
                    onToggleShow={() => toggleShow(field.key)}
                    ollamaCloudApiToken={draftEffective['ON_PREM_CLOUD_ACCESS_TOKEN'] ?? ''}
                    compact={compact}
                    workflowEmbed={workflowEmbed}
                    insideLlmCard={workflowEmbed}
                  />
                ))}
              </div>
            ) : undefined
          }
        />
      )}

      {requiredFields.length > 0 && (
        <div
          className={
            !workflowEmbed && !compact
              ? 'overflow-hidden rounded-2xl border border-gray-200/85 bg-gradient-to-b from-white via-white to-gray-50/90 shadow-sm shadow-gray-900/[0.04] ring-1 ring-black/[0.02] dark:border-white/[0.08] dark:from-zinc-900/90 dark:via-zinc-950/95 dark:to-[#08090d] dark:shadow-black/30 dark:ring-white/[0.04]'
              : undefined
          }
        >
          {!workflowEmbed && !compact && (
            <div className="border-b border-gray-100/95 bg-gradient-to-r from-rose-500/[0.06] via-transparent to-amber-500/[0.04] px-4 py-3.5 sm:px-5 sm:py-4 dark:border-white/[0.06] dark:from-rose-500/10 dark:to-amber-500/[0.06]">
              <div className="flex items-start gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-rose-500/10 text-rose-600 ring-1 ring-rose-500/15 dark:bg-rose-500/15 dark:text-rose-300 dark:ring-rose-400/25">
                  <KeyRound className="h-5 w-5" aria-hidden />
                </div>
                <div className="min-w-0 pt-0.5">
                  <h3 className="font-body text-sm font-semibold tracking-tight text-gray-900 dark:text-white">
                    Required credentials
                  </h3>
                  <p className="font-body mt-0.5 text-xs leading-relaxed text-gray-600 dark:text-zinc-400">
                    {requiredFields.length} {requiredFields.length === 1 ? 'value' : 'values'} needed before you can run this agent.
                  </p>
                </div>
              </div>
            </div>
          )}
          {!workflowEmbed && compact && (
            <h3
              className={`font-body mb-2.5 flex items-center gap-2 font-semibold uppercase tracking-[0.14em] text-gray-500 dark:text-zinc-400 ${compact ? 'text-[9px]' : 'text-[10px]'}`}
            >
              <span className="h-px flex-1 max-w-[2rem] rounded-full bg-gradient-to-r from-red-400/60 to-transparent dark:from-red-400/40" aria-hidden />
              <Settings className={`shrink-0 text-red-500/90 dark:text-red-400/90 ${compact ? 'w-2.5 h-2.5' : 'w-3 h-3'}`} />
              Required
              <span className="h-px flex-1 rounded-full bg-gradient-to-l from-gray-200/90 to-transparent dark:from-white/[0.08]" aria-hidden />
            </h3>
          )}
          {workflowEmbed && compact && (
            <div className="mb-2 h-px w-full bg-gradient-to-r from-white/10 via-white/5 to-transparent" aria-hidden />
          )}
          <div
            className={
              !workflowEmbed && !compact ? 'space-y-4 p-4 sm:p-5 sm:pt-4' : fieldGridClass
            }
          >
            {requiredFields.map((field) => (
              <ConfigField
                key={field.key}
                field={field}
                value={values[field.key] || ''}
                adminDefault={adminDefaults[field.key]}
                isSecret={isSecretField(field.key)}
                showSecret={showSecrets[field.key] || false}
                onChange={(v) => handleChange(field.key, v)}
                onToggleShow={() => toggleShow(field.key)}
                ollamaCloudApiToken={draftEffective['ON_PREM_CLOUD_ACCESS_TOKEN'] ?? ''}
                compact={compact}
                workflowEmbed={workflowEmbed}
              />
            ))}
          </div>
        </div>
      )}

      {agent.id === 'claude_code' && (
        <div className={workflowEmbed ? 'my-3' : compact ? 'mt-3' : 'mt-1'}>
          <ClaudeCodeModelPicker
            onModelSaved={(modelId) => {
              setValues((prev) => {
                const next = { ...prev };
                if (!modelId.trim()) delete next.CLAUDE_CODE_MODEL;
                else next.CLAUDE_CODE_MODEL = modelId;
                return next;
              });
              // Picker persists to disk; refresh Studio step badges etc.
              onSaved?.();
            }}
          />
        </div>
      )}

      {optionalFields.length > 0 && (
        <div
          className={
            !workflowEmbed && !compact
              ? 'overflow-hidden rounded-2xl border border-gray-200/85 bg-gradient-to-b from-white to-gray-50/80 shadow-sm shadow-gray-900/[0.03] ring-1 ring-black/[0.02] dark:border-white/[0.08] dark:from-zinc-900/85 dark:to-zinc-950/95 dark:shadow-black/25 dark:ring-white/[0.04]'
              : undefined
          }
        >
          {!workflowEmbed && !compact && (
            <div className="border-b border-gray-100/95 bg-gradient-to-r from-slate-500/[0.05] via-transparent to-zinc-500/[0.04] px-4 py-3 sm:px-5 sm:py-3.5 dark:border-white/[0.06] dark:from-slate-400/8 dark:to-zinc-500/8">
              <div className="flex items-center gap-2.5">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-500/10 text-slate-600 ring-1 ring-slate-500/12 dark:bg-zinc-700/40 dark:text-zinc-300 dark:ring-white/[0.08]">
                  <Settings className="h-4 w-4" aria-hidden />
                </div>
                <div className="min-w-0">
                  <h3 className="font-body text-sm font-semibold tracking-tight text-gray-900 dark:text-white">
                    Optional settings
                  </h3>
                  <p className="font-body text-[11px] text-gray-600 dark:text-zinc-500">
                    Tune behavior when you need more control.
                  </p>
                </div>
              </div>
            </div>
          )}
          {!workflowEmbed && compact && (
            <h3
              className={`font-body mb-2.5 flex items-center gap-2 font-semibold uppercase tracking-[0.14em] text-gray-500 dark:text-zinc-400 ${compact ? 'text-[9px]' : 'text-[10px]'}`}
            >
              <span className="h-px flex-1 max-w-[2rem] rounded-full bg-gradient-to-r from-gray-400/50 to-transparent dark:from-zinc-500/40" aria-hidden />
              <Settings className={`shrink-0 text-gray-500 dark:text-zinc-500 ${compact ? 'w-2.5 h-2.5' : 'w-3 h-3'}`} />
              Optional
              <span className="h-px flex-1 rounded-full bg-gradient-to-l from-gray-200/90 to-transparent dark:from-white/[0.08]" aria-hidden />
            </h3>
          )}
          {workflowEmbed && compact && optionalFields.length > 0 && (
            <p className="mb-2 text-[9px] font-medium uppercase tracking-[0.2em] text-gray-500">Optional</p>
          )}
          <div
            className={
              !workflowEmbed && !compact ? 'space-y-4 p-4 sm:p-5 sm:pt-4' : fieldGridClass
            }
          >
            {optionalFields.map((field) => (
              <ConfigField
                key={field.key}
                field={field}
                value={values[field.key] || ''}
                adminDefault={adminDefaults[field.key]}
                isSecret={isSecretField(field.key)}
                showSecret={showSecrets[field.key] || false}
                onChange={(v) => handleChange(field.key, v)}
                onToggleShow={() => toggleShow(field.key)}
                ollamaCloudApiToken={draftEffective['ON_PREM_CLOUD_ACCESS_TOKEN'] ?? ''}
                compact={compact}
                workflowEmbed={workflowEmbed}
              />
            ))}
          </div>
        </div>
      )}

      <div
        className={`flex items-center gap-1.5 ${
          compact
            ? workflowEmbed
              ? 'pt-0.5'
              : 'pt-1'
            : 'rounded-2xl border border-gray-200/90 bg-white/70 p-1.5 shadow-sm shadow-gray-900/[0.03] backdrop-blur-sm dark:border-white/[0.08] dark:bg-zinc-900/55 dark:shadow-black/30 pt-3'
        }`}
      >
        <button
          onClick={handleSave}
          disabled={!dirty}
          className={`flex flex-1 items-center justify-center gap-1.5 font-semibold transition-all ${
            compact
              ? workflowEmbed
                ? 'rounded-lg px-2 py-1.5 text-[10px]'
                : 'rounded-lg px-2.5 py-1.5 text-[11px]'
              : 'rounded-xl px-3 py-2.5 text-xs'
          } ${
            workflowEmbed
              ? saved
                ? 'bg-emerald-600 text-white shadow-lg shadow-emerald-900/30'
                : dirty
                  ? 'bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white shadow-lg shadow-black/20'
                  : 'cursor-not-allowed border border-white/[0.06] bg-white/[0.06] text-gray-500'
              : saved
                ? 'bg-gradient-to-r from-emerald-600 to-teal-600 text-white shadow-md shadow-emerald-900/20'
                : dirty
                  ? 'bg-gradient-to-r from-primary-600 to-primary-700 text-white shadow-md shadow-primary-900/25 hover:from-primary-500 hover:to-primary-600'
                  : 'cursor-not-allowed bg-gray-100 text-gray-400 dark:bg-zinc-800 dark:text-zinc-500'
          }`}
        >
          {saved ? <CheckCircle2 className={workflowEmbed ? 'w-3 h-3' : 'w-3.5 h-3.5'} /> : <Save className={workflowEmbed ? 'w-3 h-3' : 'w-3.5 h-3.5'} />}
          {saved ? 'Saved' : 'Save'}
        </button>
        <button
          type="button"
          onClick={handleCancel}
          disabled={!dirty}
          title="Discard unsaved edits and reload last saved configuration"
          className={`flex shrink-0 items-center justify-center gap-1 font-semibold transition-all ${
            compact
              ? workflowEmbed
                ? 'rounded-lg px-2 py-1.5 text-[10px]'
                : 'rounded-lg px-2.5 py-1.5 text-[11px]'
              : 'rounded-xl border px-3 py-2.5 text-xs'
          } ${
            workflowEmbed
              ? !dirty
                ? 'cursor-not-allowed border-white/[0.04] bg-white/[0.02] text-gray-500'
                : 'border-white/[0.12] bg-white/[0.06] text-gray-200 hover:bg-white/[0.1]'
              : compact
                ? !dirty
                  ? 'cursor-not-allowed border-gray-200/80 bg-gray-50 text-gray-400 dark:border-gray-700/50 dark:bg-gray-900/40 dark:text-gray-500'
                  : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800/80 dark:text-gray-200 dark:hover:bg-gray-800'
                : !dirty
                  ? 'cursor-not-allowed border-gray-200/90 bg-gray-50 text-gray-400 dark:border-white/[0.06] dark:bg-zinc-900/40 dark:text-zinc-500'
                  : 'border-gray-200/90 bg-white text-gray-800 shadow-sm hover:bg-gray-50 dark:border-white/[0.08] dark:bg-zinc-800/90 dark:text-zinc-100 dark:hover:bg-zinc-800'
          }`}
        >
          <X className={workflowEmbed ? 'w-3 h-3' : compact ? 'w-3 h-3' : 'w-3.5 h-3.5'} />
          Cancel
        </button>
        <button
          onClick={handleClear}
          className={`flex items-center justify-center gap-1.5 font-semibold transition-all ${
            workflowEmbed
              ? 'rounded-lg border border-rose-500/20 bg-rose-500/10 px-2 py-1.5 text-rose-300 hover:bg-rose-500/20'
              : compact
                ? 'rounded-lg border border-red-200/60 bg-red-50 px-2 py-1.5 text-red-600 hover:bg-red-100 dark:border-red-800/35 dark:bg-red-950/30 dark:text-red-400 dark:hover:bg-red-950/50'
                : 'rounded-xl border border-red-200/70 bg-red-50/90 px-3 py-2.5 text-xs text-red-700 shadow-sm hover:bg-red-100 dark:border-red-500/25 dark:bg-red-950/40 dark:text-red-300 dark:hover:bg-red-950/55'
          }`}
          title="Clear all saved configuration"
        >
          <Trash2 className={workflowEmbed ? 'w-3 h-3' : compact ? 'w-3 h-3' : 'w-3.5 h-3.5'} />
        </button>
      </div>

      {!(compact && workflowEmbed) && (
        <p className={`text-gray-400 dark:text-gray-500 font-body leading-relaxed ${compact ? 'text-[9px]' : 'text-[10px]'}`}>
          {hasAnyAdminDefaults
            ? 'Admin defaults apply until you type your own value. Clearing a field and saving removes that value (including the admin default) for your session.'
            : 'Configuration is stored locally in your browser and sent with each chat request. Empty fields after save are treated as cleared — they do not fall back to server environment variables for those keys.'}
        </p>
      )}
    </div>
  );
}

/** Present config keys as short titles (e.g. JIRA_API_TOKEN → Jira API Token). */
function humanizeConfigKey(key: string): string {
  if (key === 'KB_CHUNK_STRATEGY') return 'Chunking strategy';
  return key
    .split('_')
    .map((segment) => {
      const upper = segment.toUpperCase();
      if (upper === 'API' || upper === 'URL' || upper === 'LLM' || upper === 'ID' || upper === 'UI') return upper;
      return segment.charAt(0).toUpperCase() + segment.slice(1).toLowerCase();
    })
    .join(' ');
}

/** FastAPI may return JSON-shaped strings in ``detail``; show the inner ``error`` when present. */
function formatOllamaProxyError(message: string): string {
  const m = message.trim();
  if (m.startsWith('{') && m.includes('"error"')) {
    try {
      const o = JSON.parse(m) as { error?: unknown };
      if (typeof o.error === 'string' && o.error.trim()) return o.error.trim();
    } catch {
      /* keep original */
    }
  }
  return m;
}

function OllamaCloudModelControl({
  value,
  onChange,
  apiToken,
  compact,
  workflowEmbed,
  hasAdminValue,
  adminDefault,
  field,
  inputClassName,
}: {
  value: string;
  onChange: (v: string) => void;
  apiToken: string;
  compact: boolean;
  workflowEmbed: boolean;
  hasAdminValue: boolean;
  adminDefault?: string;
  field: AgentConfigField;
  inputClassName: string;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const filterInputRef = useRef<HTMLInputElement>(null);
  const listboxId = useId();
  const trimmedTok = apiToken.trim();
  const [tagModels, setTagModels] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(0);
  /** Filter text inside the dropdown only — never written to ``ON_PREM_CLOUD_MODEL`` (avoids saving partial e.g. ``de``). */
  const [listFilter, setListFilter] = useState('');

  const filteredModels = useMemo(() => {
    const q = listFilter.trim().toLowerCase();
    if (!q) return tagModels;
    return tagModels.filter((m) => m.toLowerCase().includes(q));
  }, [tagModels, listFilter]);

  const showPicker = trimmedTok && !loading && tagModels.length > 0 && !err;

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    setListFilter('');
    requestAnimationFrame(() => filterInputRef.current?.focus());
  }, [open]);

  useEffect(() => {
    if (!open) return;
    setHighlighted(0);
  }, [open, listFilter]);

  useEffect(() => {
    if (!open || filteredModels.length === 0) return;
    setHighlighted((h) => Math.min(h, filteredModels.length - 1));
  }, [filteredModels.length, open]);

  useEffect(() => {
    if (!open) return;
    const el = rootRef.current?.querySelector(`[data-ollama-model-idx="${highlighted}"]`);
    el?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [highlighted, open, filteredModels]);

  useEffect(() => {
    if (!trimmedTok) {
      setTagModels([]);
      setErr(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setErr(null);
    fetch('/api/ollama-cloud/tags', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: trimmedTok }),
    })
      .then(async (res) => {
        const data = (await res.json().catch(() => ({}))) as {
          models?: unknown;
          detail?: unknown;
        };
        if (!res.ok) {
          let msg = `Request failed (${res.status})`;
          if (typeof data?.detail === 'string') msg = formatOllamaProxyError(data.detail);
          else if (Array.isArray(data?.detail) && data.detail[0] && typeof (data.detail[0] as { msg?: string }).msg === 'string') {
            msg = (data.detail[0] as { msg: string }).msg;
          }
          throw new Error(msg);
        }
        const raw = data?.models;
        const names = Array.isArray(raw)
          ? raw.filter((x): x is string => typeof x === 'string' && x.trim().length > 0)
          : [];
        if (!cancelled) {
          setTagModels(names);
          setLoading(false);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setTagModels([]);
          setLoading(false);
          setErr(e instanceof Error ? e.message : 'Failed to load models');
        }
      });
    return () => {
      cancelled = true;
    };
  }, [trimmedTok]);

  const placeholder =
    hasAdminValue && adminDefault
      ? `Admin default: ${adminDefault.slice(0, 30)}${adminDefault.length > 30 ? '…' : ''}`
      : field.example || field.default ||
          (field.key === 'ON_PREM_CLOUD_ACCESS_TOKEN'
            ? 'Enter ON_PREM_CLOUD_ACCESS_TOKEN'
            : `Enter ${field.key}`);

  const hintClass = `font-body text-gray-500 dark:text-gray-400 ${workflowEmbed ? 'text-[8px] leading-tight' : compact ? 'text-[9px] leading-snug' : 'text-[10px]'}`;

  const pickModel = (m: string) => {
    onChange(m);
    setOpen(false);
    setListFilter('');
  };

  const openPicker = () => {
    if (showPicker) setOpen(true);
  };

  const onMainInputKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (!showPicker) return;
    if (!open && e.key === 'ArrowDown') {
      e.preventDefault();
      openPicker();
    }
  };

  const onFilterKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      setOpen(false);
      setListFilter('');
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHighlighted((h) => (filteredModels.length ? (h + 1) % filteredModels.length : 0));
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlighted((h) =>
        filteredModels.length ? (h - 1 + filteredModels.length) % filteredModels.length : 0,
      );
      return;
    }
    if (e.key === 'Enter' && filteredModels.length > 0) {
      e.preventDefault();
      pickModel(filteredModels[highlighted] ?? filteredModels[0]);
    }
  };

  const panelSurface = workflowEmbed
    ? 'border-violet-400/35 bg-zinc-950/98 shadow-2xl shadow-black/50 ring-1 ring-violet-500/15'
    : 'border-violet-200/90 bg-white/98 shadow-xl shadow-violet-900/[0.08] ring-1 ring-violet-500/[0.06] dark:border-violet-500/30 dark:bg-zinc-900/98 dark:shadow-black/40 dark:ring-white/[0.06]';

  const optionRow = (active: boolean) =>
    workflowEmbed
      ? active
        ? 'bg-violet-500/25 text-violet-50'
        : 'text-gray-200 hover:bg-white/[0.06]'
      : active
        ? 'bg-violet-100 text-violet-950 dark:bg-violet-500/20 dark:text-violet-100'
        : 'text-gray-900 hover:bg-violet-50/90 dark:text-gray-100 dark:hover:bg-violet-500/10';

  return (
    <div className="space-y-1.5">
      {!trimmedTok ? (
        <p className={`font-body text-amber-700 dark:text-amber-400/90 ${workflowEmbed ? 'text-[8px]' : compact ? 'text-[9px]' : 'text-[10px]'}`}>
          Enter your Ollama Cloud API token above, then model names from{' '}
          <code className="font-mono text-[0.9em]">ollama.com/api/tags</code> appear in the picker below.
        </p>
      ) : loading ? (
        <p className={hintClass}>Loading models…</p>
      ) : err ? (
        <div
          className={`font-body text-amber-700 dark:text-amber-400/90 ${workflowEmbed ? 'text-[8px]' : compact ? 'text-[9px]' : 'text-[10px]'}`}
        >
          <p>{err}</p>
          {/unauthorized/i.test(err) ? (
            <p className="mt-1 text-gray-600 dark:text-gray-400">
              Ollama Cloud did not accept your API key. Use a current key from{' '}
              <a
                href="https://ollama.com/"
                target="_blank"
                rel="noopener noreferrer"
                className="underline text-violet-700 dark:text-violet-300"
              >
                ollama.com
              </a>
              , paste it into <code className="font-mono text-[0.95em]">ON_PREM_CLOUD_ACCESS_TOKEN</code> (key only—
              <code className="font-mono text-[0.95em]">Bearer</code> is added automatically), then Save.
            </p>
          ) : null}
        </div>
      ) : null}
      <div ref={rootRef} className={`relative ${open ? 'z-50' : ''}`}>
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          readOnly={open}
          title={
            open
              ? 'Close the picker (chevron or click outside) to edit this field, or use Filter in the menu.'
              : undefined
          }
          onKeyDown={onMainInputKeyDown}
          placeholder={placeholder}
          className={`${inputClassName} ${showPicker ? 'pr-10' : ''} ${open ? 'cursor-default opacity-90' : ''}`}
          aria-label="On-prem Cloud model name"
          aria-expanded={showPicker ? open : undefined}
          aria-haspopup={showPicker ? 'listbox' : undefined}
          aria-controls={showPicker && open ? listboxId : undefined}
          aria-readonly={open || undefined}
          role={showPicker ? 'combobox' : undefined}
          autoComplete="off"
        />
        {showPicker ? (
          <button
            type="button"
            tabIndex={-1}
            aria-label={open ? 'Close model list' : 'Open model list'}
            onClick={() => setOpen((o) => !o)}
            className={`absolute right-1 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-lg transition-colors ${
              workflowEmbed
                ? 'text-violet-200/80 hover:bg-violet-500/20 hover:text-violet-100'
                : 'text-violet-600/80 hover:bg-violet-100 dark:text-violet-300/90 dark:hover:bg-violet-500/15'
            }`}
          >
            <ChevronDown
              className={`h-4 w-4 transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
            />
          </button>
        ) : null}
        {showPicker && open ? (
          <div
            id={listboxId}
            role="listbox"
            aria-label="On-prem Cloud models"
            className={`absolute left-0 right-0 top-[calc(100%+6px)] z-[200] overflow-hidden rounded-xl border backdrop-blur-md ${panelSurface}`}
          >
            <div
              className={`flex items-center gap-2 border-b px-2 py-2 ${
                workflowEmbed ? 'border-violet-500/20' : 'border-violet-200/80 dark:border-violet-500/20'
              }`}
            >
              <Search
                className={`h-3.5 w-3.5 shrink-0 ${workflowEmbed ? 'text-violet-300/70' : 'text-violet-500/70'}`}
                aria-hidden
              />
              <input
                ref={filterInputRef}
                type="text"
                value={listFilter}
                onChange={(e) => setListFilter(e.target.value)}
                onKeyDown={onFilterKeyDown}
                placeholder="Filter models…"
                className={`min-w-0 flex-1 rounded-lg border bg-transparent px-2 py-1.5 font-mono text-xs outline-none focus:ring-2 ${
                  workflowEmbed
                    ? 'border-violet-400/30 text-gray-100 placeholder:text-gray-600 focus:ring-violet-500/30'
                    : 'border-violet-200/80 text-gray-900 placeholder:text-gray-400 focus:ring-violet-400/40 dark:border-violet-500/30 dark:text-white dark:placeholder:text-gray-500 dark:focus:ring-violet-500/30'
                }`}
                aria-label="Filter model list"
                autoComplete="off"
              />
            </div>
            <div
              className="max-h-52 overflow-y-auto overscroll-y-contain py-1 [scrollbar-color:rgba(139,92,246,0.35)_transparent] [scrollbar-width:thin]"
            >
              {filteredModels.length === 0 ? (
                <p
                  className={`px-3 py-2.5 text-center font-body text-xs ${
                    workflowEmbed ? 'text-gray-500' : 'text-gray-500 dark:text-gray-400'
                  }`}
                >
                  No models match “{listFilter.trim() || '…'}”. Clear the filter or pick from the full list.
                </p>
              ) : (
                filteredModels.map((m, i) => (
                  <button
                    key={m}
                    type="button"
                    role="option"
                    aria-selected={value === m}
                    data-ollama-model-idx={i}
                    onMouseEnter={() => setHighlighted(i)}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => pickModel(m)}
                    className={`flex w-full px-3 py-2 text-left font-mono text-xs transition-colors ${optionRow(i === highlighted)}`}
                  >
                    <span className="min-w-0 flex-1 truncate">{m}</span>
                  </button>
                ))
              )}
            </div>
          </div>
        ) : null}
      </div>
      {trimmedTok && !loading && tagModels.length === 0 && !err ? (
        <p className={hintClass}>
          No models returned from <code className="font-mono text-[0.95em]">/api/tags</code>. Type a model name (e.g. gemma3:27b-cloud) or check your account.
        </p>
      ) : trimmedTok && tagModels.length > 0 && !err ? (
        <p className={hintClass}>
          Use the ↑ menu to filter and scroll models. Type in the model field only when the menu is closed so partial search text is not saved as the model name.
        </p>
      ) : null}
    </div>
  );
}

function ConfigField({
  field,
  value,
  adminDefault,
  isSecret,
  showSecret,
  onChange,
  onToggleShow,
  compact = false,
  workflowEmbed = false,
  embedBelow,
  insideLlmCard = false,
  resolvedLlmProvider,
  ollamaCloudApiToken = '',
}: {
  field: AgentConfigField;
  value: string;
  adminDefault?: string;
  isSecret: boolean;
  showSecret: boolean;
  onChange: (v: string) => void;
  onToggleShow: () => void;
  compact?: boolean;
  workflowEmbed?: boolean;
  /** Rendered inside the LLM provider card under the provider hint */
  embedBelow?: ReactNode;
  /** Compact styling when nested inside the LLM provider card */
  insideLlmCard?: boolean;
  /** Matches getEffectiveLlmProvider (legacy USE_LOCAL_LLM + defaults); keeps segments in sync with nested fields */
  resolvedLlmProvider?: LlmProviderChoice;
  /** Effective Ollama Cloud bearer token (user + admin default); used to populate ON_PREM_CLOUD_MODEL from /api/tags */
  ollamaCloudApiToken?: string;
}) {
  const inputId = useId();
  const plainModern = !compact && !workflowEmbed && !insideLlmCard;
  const plainFieldShell =
    'rounded-xl border border-gray-200/75 bg-white/95 p-3.5 sm:p-4 shadow-[0_1px_2px_rgba(15,23,42,0.04)] ring-1 ring-black/[0.02] transition-[box-shadow,border-color] focus-within:border-primary-400/45 focus-within:shadow-[0_4px_14px_rgba(15,23,42,0.06)] focus-within:ring-primary-500/12 dark:border-white/[0.08] dark:bg-zinc-950/45 dark:ring-white/[0.03] dark:focus-within:border-primary-500/40 dark:focus-within:shadow-black/35 dark:focus-within:ring-primary-400/12';

  const hasAdminValue = !!adminDefault?.trim();
  const hasUserValue = !!value.trim();
  const isFilled = hasUserValue || hasAdminValue;

  const boolFrom = (s: string | undefined) => {
    const t = (s ?? '').trim().toLowerCase();
    return t === 'true' || t === '1' || t === 'yes';
  };

  if (field.control === 'select' && field.options?.length) {
    const fallback = (field.default ?? field.options[0]?.value ?? '').trim();
    const raw = value.trim() || fallback;
    const selected = field.options.some((o) => o.value === raw) ? raw : fallback;

    const selectClassName = `w-full font-body focus:outline-none transition-all ${
      compact
        ? workflowEmbed
          ? 'rounded-md px-2 py-1.5 text-[10px]'
          : 'rounded-md px-2.5 py-2 text-[11px]'
        : plainModern
          ? 'rounded-xl px-3.5 py-2.5 text-sm'
          : 'rounded-md px-3 py-2 text-xs'
    } ${
      insideLlmCard && workflowEmbed
        ? `text-gray-100 bg-black/20 border border-violet-400/25 focus:border-violet-400/50 focus:ring-1 focus:ring-violet-500/30 ${
            hasAdminValue && !hasUserValue ? 'border-sky-500/35' : ''
          }`
        : insideLlmCard
          ? `border rounded-lg bg-white/90 dark:bg-zinc-900/55 text-gray-900 dark:text-white focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400/55 ${
              hasAdminValue && !hasUserValue ? 'border-sky-300 dark:border-sky-500/40' : 'border-violet-200/80 dark:border-violet-500/30'
            }`
          : workflowEmbed
            ? `text-gray-100 bg-black/25 border border-white/[0.08] focus:border-emerald-500/40 focus:ring-1 focus:ring-emerald-500/20 ${
                hasAdminValue && !hasUserValue ? 'border-sky-500/30' : ''
              }`
            : plainModern
              ? `border border-gray-200/90 bg-white text-gray-900 shadow-sm focus:border-primary-500/55 focus:ring-2 focus:ring-primary-500/20 dark:border-white/[0.1] dark:bg-zinc-900/70 dark:text-white dark:focus:border-primary-400/50 dark:focus:ring-primary-400/15 ${
                  hasAdminValue && !hasUserValue ? 'border-sky-300 dark:border-sky-500/45' : ''
                }`
              : `bg-gray-50 dark:bg-gray-800/70 border rounded-lg text-gray-900 dark:text-white focus:ring-2 focus:ring-primary-500/30 focus:border-primary-500/50 ${
                  hasAdminValue && !hasUserValue ? 'border-blue-200 dark:border-blue-800/50' : 'border-gray-200 dark:border-gray-700'
                }`
    }`;

    return (
      <div
        className={
          workflowEmbed
            ? insideLlmCard
              ? 'rounded-lg border border-violet-400/20 bg-violet-500/[0.06] p-2 sm:p-2.5 shadow-inner shadow-black/10 backdrop-blur-sm'
              : 'rounded-lg border border-white/[0.06] bg-white/[0.03] p-2 sm:p-2.5 shadow-inner shadow-black/20 backdrop-blur-sm'
            : insideLlmCard
              ? 'rounded-lg border border-violet-200/50 dark:border-violet-500/25 bg-white/50 dark:bg-zinc-900/35 p-2 sm:p-2.5'
              : plainModern
                ? plainFieldShell
                : 'group'
        }
      >
        {plainModern ? (
          <div className="mb-2 space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <label htmlFor={inputId} className="font-body text-sm font-semibold tracking-tight text-gray-900 dark:text-white">
                {humanizeConfigKey(field.key)}
              </label>
              <code className="rounded-md bg-gray-100/90 px-1.5 py-0.5 font-mono text-[10px] font-medium text-gray-500 ring-1 ring-gray-200/80 dark:bg-white/[0.06] dark:text-gray-400 dark:ring-white/[0.08]">
                {field.key}
              </code>
              {field.required && (
                <span className="rounded-full bg-rose-500/10 px-2 py-0.5 font-body text-[10px] font-semibold uppercase tracking-wide text-rose-700 ring-1 ring-rose-500/15 dark:bg-rose-500/15 dark:text-rose-300 dark:ring-rose-400/25">
                  Required
                </span>
              )}
              {isFilled && <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" aria-hidden />}
              {hasAdminValue && !hasUserValue && (
                <span className="rounded-full bg-sky-500/10 px-2 py-0.5 font-body text-[10px] font-semibold text-sky-700 ring-1 ring-sky-500/15 dark:bg-sky-500/15 dark:text-sky-300 dark:ring-sky-400/25">
                  Admin default
                </span>
              )}
            </div>
            <p className="font-body text-xs leading-relaxed text-gray-600 dark:text-zinc-400">{field.description}</p>
          </div>
        ) : (
          <>
            <div className="mb-1 flex items-center justify-between">
              <label className={`font-body font-semibold text-gray-700 dark:text-gray-300 flex flex-wrap items-center gap-1.5 ${compact ? 'text-[10px]' : 'text-xs'}`}>
                <code
                  className={
                    insideLlmCard && workflowEmbed
                      ? 'text-[10px] text-violet-200/95 bg-violet-500/15 px-1.5 py-0.5 rounded-md font-mono ring-1 ring-violet-400/25'
                      : insideLlmCard
                        ? `text-violet-700 dark:text-violet-300 bg-violet-100/80 dark:bg-violet-500/15 px-1.5 py-0.5 rounded-md font-mono ring-1 ring-violet-200/80 dark:ring-violet-500/25 ${compact ? 'text-[10px]' : 'text-[11px]'}`
                        : workflowEmbed
                          ? 'text-[10px] text-emerald-400/90 bg-emerald-500/10 px-1.5 py-0.5 rounded-md font-mono ring-1 ring-emerald-500/15'
                          : `text-primary-600 dark:text-primary-400 bg-primary-50 dark:bg-primary-900/15 px-1.5 py-0.5 rounded ${compact ? 'text-[10px]' : 'text-[11px]'}`
                  }
                >
                  {field.key}
                </code>
                {field.required && <span className="text-[9px] font-bold text-red-500">*</span>}
                {isFilled && <CheckCircle2 className="h-3 w-3 text-green-500" />}
                {hasAdminValue && !hasUserValue && (
                  <span className="rounded-full bg-blue-100 px-1.5 py-0.5 text-[9px] font-bold text-blue-600 dark:bg-blue-900/20 dark:text-blue-400">
                    ADMIN DEFAULT
                  </span>
                )}
              </label>
            </div>
            <p
              className={`font-body text-gray-500 dark:text-gray-400 ${workflowEmbed ? 'mb-1 text-[8px] leading-tight' : compact ? 'mb-1.5 text-[9px] leading-snug' : 'mb-1.5 text-[10px]'}`}
            >
              {field.description}
            </p>
          </>
        )}
        <select
          id={plainModern ? inputId : undefined}
          value={selected}
          onChange={(e) => onChange(e.target.value)}
          className={selectClassName}
          aria-label={field.key}
        >
          {field.options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
    );
  }

  if (field.control === 'choice' && field.options?.length) {
    const isLlmProviderChoice = field.key === 'LLM_PROVIDER';
    const fallbackBase = field.default?.trim()
      ? field.default.trim()
      : isLlmProviderChoice
        ? 'pwc_genai'
        : (field.options[0]?.value ?? '').trim();
    const fallback = fallbackBase || (isLlmProviderChoice ? 'pwc_genai' : '');
    const raw = value.trim() || fallback;
    const selected =
      isLlmProviderChoice && resolvedLlmProvider && field.options.some((o) => o.value === resolvedLlmProvider)
        ? resolvedLlmProvider
        : field.options.some((o) => o.value === raw)
          ? raw
          : fallback;

    const choiceGroupLabel = isLlmProviderChoice
      ? 'LLM provider'
      : field.key.endsWith('_WEB_SEARCH_PROVIDER')
        ? 'Web search provider'
        : humanizeConfigKey(field.key);

    const llmIcon = (val: string) => {
      if (val === 'local_llm') return <Laptop2 className={compact ? 'h-3 w-3' : 'h-3.5 w-3.5'} />;
      if (val === 'ollama_cloud') return <Sparkles className={compact ? 'h-3 w-3' : 'h-3.5 w-3.5'} />;
      return <Cloud className={compact ? 'h-3 w-3' : 'h-3.5 w-3.5'} />;
    };

    /** Icons for catalog `choice` fields other than LLM_PROVIDER (e.g. web search backend). */
    const genericChoiceIcon = (val: string) => {
      if (field.key.endsWith('_WEB_SEARCH_PROVIDER')) {
        const v = val.toLowerCase();
        if (v === 'perplexity') return <Sparkles className={compact ? 'h-3 w-3' : 'h-3.5 w-3.5'} />;
        if (v.includes('duck') || v === 'free_duckduckgo') return <Search className={compact ? 'h-3 w-3' : 'h-3.5 w-3.5'} />;
        return <Globe className={compact ? 'h-3 w-3' : 'h-3.5 w-3.5'} />;
      }
      return <Search className={compact ? 'h-3 w-3' : 'h-3.5 w-3.5'} />;
    };

    const segmentIcon = (val: string) => (isLlmProviderChoice ? llmIcon(val) : genericChoiceIcon(val));

    const hint =
      !isLlmProviderChoice
        ? ''
        : selected === 'pwc_genai'
          ? 'PwC GenAI credentials and related options are in this card when applicable.'
          : selected === 'local_llm'
            ? 'Runs against your local server (default http://127.0.0.1:4099). PwC and Ollama Cloud keys stay hidden. Optional tuning fields appear in this card when listed.'
            : selected === 'ollama_cloud'
              ? 'On-prem Cloud API token, model, and optional endpoint fields are in this card. Keys from other backends stay hidden.'
              : '';

    const segmentBtn = (opt: { value: string; label: string }) => {
      const on = selected === opt.value;
      return (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={`flex min-w-0 flex-1 items-center justify-center gap-1 rounded-lg font-body font-semibold transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/50 ${
            compact ? 'px-1.5 py-1.5 text-[9px]' : 'px-2 py-2 text-[10px] sm:text-xs'
          } ${
            workflowEmbed
              ? on
                ? 'bg-violet-500/25 text-violet-100 ring-1 ring-violet-400/35'
                : 'bg-white/[0.04] text-gray-400 hover:bg-white/[0.07]'
              : on
                ? 'bg-white text-violet-700 shadow-sm ring-1 ring-violet-200/90 dark:bg-violet-500 dark:text-white dark:ring-violet-400/40 dark:shadow-violet-950/40'
                : 'text-gray-600 hover:bg-white/80 hover:text-gray-900 dark:text-zinc-400 dark:hover:bg-white/[0.07] dark:hover:text-zinc-200'
          }`}
        >
          {segmentIcon(opt.value)}
          <span className="truncate">{opt.label}</span>
        </button>
      );
    };

    const embedBlock = embedBelow != null ? (
        <div
          className={
            workflowEmbed
              ? 'mt-3 border-t border-violet-400/25 pt-3'
              : `mt-4 border-t border-violet-200/70 pt-4 dark:border-violet-500/25 ${compact ? 'mt-3 pt-3' : ''}`
          }
        >
          {embedBelow}
        </div>
      )
    : null;

    if (workflowEmbed) {
      return (
        <div className="rounded-xl border border-violet-500/25 bg-gradient-to-br from-violet-500/[0.08] via-white/[0.03] to-sky-500/[0.05] p-2.5 sm:p-3 shadow-inner shadow-black/20 backdrop-blur-sm">
          <p className="font-body text-[11px] font-semibold text-gray-100">{choiceGroupLabel}</p>
          <p className="font-body mt-1 text-[9px] leading-snug text-gray-400">{field.description}</p>
          <div className="mt-2 flex flex-col gap-1.5 sm:flex-row">{field.options.map(segmentBtn)}</div>
          {hint ? <p className="font-body mt-2 text-[8px] leading-snug text-gray-500">{hint}</p> : null}
          {embedBlock}
        </div>
      );
    }

    return (
      <div className="relative overflow-visible rounded-2xl border border-violet-200/70 bg-gradient-to-br from-violet-50/90 via-white to-sky-50/40 shadow-lg shadow-violet-900/[0.07] ring-1 ring-violet-500/[0.07] backdrop-blur-[2px] dark:border-violet-500/30 dark:from-violet-950/50 dark:via-zinc-900/92 dark:to-slate-950/75 dark:shadow-black/35 dark:ring-white/[0.06]">
        <div
          className="pointer-events-none absolute -right-12 -top-12 z-0 h-32 w-32 rounded-full bg-violet-400/18 blur-2xl dark:bg-violet-500/12"
          aria-hidden
        />
        <div
          className="pointer-events-none absolute -left-8 bottom-0 z-0 h-24 w-24 rounded-full bg-sky-400/10 blur-2xl dark:bg-sky-500/8"
          aria-hidden
        />
        <div className={`relative z-[1] ${compact ? 'p-3.5' : 'p-4 sm:p-5'}`}>
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center rounded-full border border-violet-200/80 bg-violet-100/60 px-2 py-0.5 font-body text-[9px] font-bold uppercase tracking-wider text-violet-700 dark:border-violet-500/30 dark:bg-violet-500/15 dark:text-violet-200">
              {isLlmProviderChoice ? 'Backend' : 'Setting'}
            </span>
            <p
              className={`font-body font-semibold tracking-tight text-gray-900 dark:text-white ${compact ? 'text-xs' : 'text-sm'}`}
            >
              {choiceGroupLabel}
            </p>
            <code className="rounded-md bg-gray-100/90 px-1.5 py-0.5 font-mono text-[9px] font-medium text-gray-500 ring-1 ring-gray-200/80 dark:bg-white/[0.06] dark:text-gray-400 dark:ring-white/[0.08]">
              {field.key}
            </code>
          </div>
          <p
            className={`font-body mt-2 leading-relaxed text-gray-600 dark:text-gray-400 ${compact ? 'text-[10px]' : 'text-xs'}`}
          >
            {field.description}
          </p>
          <div
            className={`mt-3.5 rounded-xl border border-violet-200/60 bg-gray-100/80 p-1 dark:border-violet-500/20 dark:bg-black/25 ${compact ? 'mt-2.5' : ''}`}
            role="radiogroup"
            aria-label={choiceGroupLabel}
          >
            <div className="flex flex-col gap-1 sm:flex-row sm:gap-1">{field.options.map(segmentBtn)}</div>
          </div>
          {hint ? (
            <p
              className={`font-body text-gray-500 dark:text-gray-500 ${compact ? 'mt-2 text-[9px]' : 'mt-3 text-[10px]'}`}
            >
              {hint}
            </p>
          ) : null}
          {embedBlock}
        </div>
      </div>
    );
  }

  if (field.control === 'boolean') {
    const effectiveOn = boolFrom(value) || (!value.trim() && boolFrom(field.default));

    return (
      <div
        className={
          workflowEmbed
            ? insideLlmCard
              ? 'rounded-lg border border-violet-400/20 bg-violet-500/[0.06] p-2 sm:p-2.5 shadow-inner shadow-black/10 backdrop-blur-sm'
              : 'rounded-lg border border-white/[0.06] bg-white/[0.03] p-2 sm:p-2.5 shadow-inner shadow-black/20 backdrop-blur-sm'
            : insideLlmCard
              ? 'rounded-lg border border-violet-200/50 dark:border-violet-500/25 bg-white/50 dark:bg-zinc-900/35 p-2 sm:p-2.5'
              : plainModern
                ? plainFieldShell
                : 'group'
        }
      >
        <div className={`flex items-center justify-between gap-3 ${plainModern ? 'mb-2' : 'mb-1'}`}>
          {plainModern ? (
            <div className="min-w-0 flex flex-wrap items-center gap-2">
              <span className="font-body text-sm font-semibold tracking-tight text-gray-900 dark:text-white">
                {humanizeConfigKey(field.key)}
              </span>
              <code className="rounded-md bg-gray-100/90 px-1.5 py-0.5 font-mono text-[10px] font-medium text-gray-500 ring-1 ring-gray-200/80 dark:bg-white/[0.06] dark:text-gray-400 dark:ring-white/[0.08]">
                {field.key}
              </code>
              <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-500" aria-hidden />
            </div>
          ) : (
            <label className={`font-body font-semibold text-gray-700 dark:text-gray-300 flex items-center gap-1.5 flex-wrap min-w-0 ${compact ? 'text-[10px]' : 'text-xs'}`}>
              <code
                className={
                  insideLlmCard && workflowEmbed
                    ? 'text-[10px] text-violet-200/95 bg-violet-500/15 px-1.5 py-0.5 rounded-md font-mono ring-1 ring-violet-400/25'
                    : insideLlmCard
                      ? `text-violet-700 dark:text-violet-300 bg-violet-100/80 dark:bg-violet-500/15 px-1.5 py-0.5 rounded-md font-mono ring-1 ring-violet-200/80 dark:ring-violet-500/25 ${compact ? 'text-[10px]' : 'text-[11px]'}`
                      : workflowEmbed
                        ? 'text-[10px] text-emerald-400/90 bg-emerald-500/10 px-1.5 py-0.5 rounded-md font-mono ring-1 ring-emerald-500/15'
                        : `text-primary-600 dark:text-primary-400 bg-primary-50 dark:bg-primary-900/15 px-1.5 py-0.5 rounded ${compact ? 'text-[10px]' : 'text-[11px]'}`
                }
              >
                {field.key}
              </code>
              <CheckCircle2 className="w-3 h-3 text-green-500 shrink-0" />
            </label>
          )}
          <button
            type="button"
            role="switch"
            aria-checked={effectiveOn}
            onClick={() => onChange(effectiveOn ? 'false' : 'true')}
            className={`relative shrink-0 h-6 w-11 rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500/50 ${
              effectiveOn
                ? 'bg-primary-600'
                : workflowEmbed
                  ? 'bg-white/15'
                  : 'bg-gray-300 dark:bg-gray-600'
            }`}
          >
            <span
              className={`absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${
                effectiveOn ? 'translate-x-5' : 'translate-x-0'
              }`}
            />
          </button>
        </div>
        <p
          className={`font-body text-gray-500 dark:text-gray-400 ${
            plainModern
              ? 'text-xs leading-relaxed text-gray-600 dark:text-zinc-400'
              : workflowEmbed
                ? 'mb-0 text-[8px] leading-tight'
                : compact
                  ? 'mb-0 text-[9px] leading-snug'
                  : 'mb-0 text-[10px]'
          }`}
        >
          {field.description}
        </p>
        <p className={`font-body mt-1.5 ${workflowEmbed ? 'text-[8px] text-gray-500' : 'text-[10px] text-gray-500 dark:text-gray-400'}`}>
          {effectiveOn ? 'Enabled' : 'Disabled'}
        </p>
      </div>
    );
  }

  return (
    <div
      className={
        workflowEmbed
          ? insideLlmCard
            ? 'rounded-lg border border-violet-400/20 bg-violet-500/[0.06] p-2 sm:p-2.5 shadow-inner shadow-black/10 backdrop-blur-sm'
            : 'rounded-lg border border-white/[0.06] bg-white/[0.03] p-2 sm:p-2.5 shadow-inner shadow-black/20 backdrop-blur-sm'
          : insideLlmCard
            ? 'rounded-lg border border-violet-200/50 dark:border-violet-500/25 bg-white/50 dark:bg-zinc-900/35 p-2 sm:p-2.5'
            : plainModern
              ? plainFieldShell
              : 'group'
      }
    >
      {plainModern ? (
        <div className="mb-2 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor={inputId} className="font-body text-sm font-semibold tracking-tight text-gray-900 dark:text-white">
              {humanizeConfigKey(field.key)}
            </label>
            <code className="rounded-md bg-gray-100/90 px-1.5 py-0.5 font-mono text-[10px] font-medium text-gray-500 ring-1 ring-gray-200/80 dark:bg-white/[0.06] dark:text-gray-400 dark:ring-white/[0.08]">
              {field.key}
            </code>
            {field.required && (
              <span className="rounded-full bg-rose-500/10 px-2 py-0.5 font-body text-[10px] font-semibold uppercase tracking-wide text-rose-700 ring-1 ring-rose-500/15 dark:bg-rose-500/15 dark:text-rose-300 dark:ring-rose-400/25">
                Required
              </span>
            )}
            {isFilled && <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" aria-hidden />}
            {hasAdminValue && !hasUserValue && (
              <span className="rounded-full bg-sky-500/10 px-2 py-0.5 font-body text-[10px] font-semibold text-sky-700 ring-1 ring-sky-500/15 dark:bg-sky-500/15 dark:text-sky-300 dark:ring-sky-400/25">
                Admin default
              </span>
            )}
          </div>
          <p className="font-body text-xs leading-relaxed text-gray-600 dark:text-zinc-400">{field.description}</p>
        </div>
      ) : (
        <>
          <div className="flex items-center justify-between mb-1">
            <label className={`font-body font-semibold text-gray-700 dark:text-gray-300 flex items-center gap-1.5 flex-wrap ${compact ? 'text-[10px]' : 'text-xs'}`}>
              <code
                className={
                  insideLlmCard && workflowEmbed
                    ? 'text-[10px] text-violet-200/95 bg-violet-500/15 px-1.5 py-0.5 rounded-md font-mono ring-1 ring-violet-400/25'
                    : insideLlmCard
                      ? `text-violet-700 dark:text-violet-300 bg-violet-100/80 dark:bg-violet-500/15 px-1.5 py-0.5 rounded-md font-mono ring-1 ring-violet-200/80 dark:ring-violet-500/25 ${compact ? 'text-[10px]' : 'text-[11px]'}`
                      : workflowEmbed
                        ? 'text-[10px] text-emerald-400/90 bg-emerald-500/10 px-1.5 py-0.5 rounded-md font-mono ring-1 ring-emerald-500/15'
                        : `text-primary-600 dark:text-primary-400 bg-primary-50 dark:bg-primary-900/15 px-1.5 py-0.5 rounded ${compact ? 'text-[10px]' : 'text-[11px]'}`
                }
              >
                {field.key}
              </code>
              {field.required && (
                <span className="text-[9px] text-red-500 font-bold">*</span>
              )}
              {isFilled && (
                <CheckCircle2 className="w-3 h-3 text-green-500" />
              )}
              {hasAdminValue && !hasUserValue && (
                <span className="text-[9px] bg-blue-100 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 px-1.5 py-0.5 rounded-full font-bold">
                  ADMIN DEFAULT
                </span>
              )}
            </label>
          </div>
          <p
            className={`font-body text-gray-500 dark:text-gray-400 ${workflowEmbed ? 'mb-1 text-[8px] leading-tight' : compact ? 'mb-1.5 text-[9px] leading-snug' : 'mb-1.5 text-[10px]'}`}
          >
            {field.description}
          </p>
        </>
      )}
      {field.key === 'ON_PREM_CLOUD_MODEL' ? (
        <OllamaCloudModelControl
          value={value}
          onChange={onChange}
          apiToken={ollamaCloudApiToken}
          compact={compact}
          workflowEmbed={workflowEmbed}
          hasAdminValue={hasAdminValue}
          adminDefault={adminDefault}
          field={field}
          inputClassName={`w-full font-mono focus:outline-none transition-all ${
            compact
              ? workflowEmbed
                ? 'rounded-md px-2 py-1.5 text-[10px]'
                : 'rounded-md px-2.5 py-2 text-[11px]'
              : plainModern
                ? 'rounded-xl px-3.5 py-2.5 text-sm'
                : 'rounded-md px-3 py-2 text-xs'
          } ${
            insideLlmCard && workflowEmbed
              ? `text-gray-100 placeholder:text-gray-600 bg-black/20 border border-violet-400/25 focus:border-violet-400/50 focus:ring-1 focus:ring-violet-500/30 ${
                  hasAdminValue && !hasUserValue ? 'border-sky-500/35' : ''
                }`
              : insideLlmCard
                ? `border rounded-lg bg-white/90 dark:bg-zinc-900/55 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400/55 ${
                    hasAdminValue && !hasUserValue ? 'border-sky-300 dark:border-sky-500/40' : 'border-violet-200/80 dark:border-violet-500/30'
                  }`
                : workflowEmbed
                  ? `text-gray-100 placeholder:text-gray-600 bg-black/25 border border-white/[0.08] focus:border-emerald-500/40 focus:ring-1 focus:ring-emerald-500/20 ${
                      hasAdminValue && !hasUserValue ? 'border-sky-500/30' : ''
                    }`
                  : plainModern
                    ? `border border-gray-200/90 bg-white text-gray-900 shadow-sm placeholder:text-gray-400 focus:border-primary-500/55 focus:ring-2 focus:ring-primary-500/20 dark:border-white/[0.1] dark:bg-zinc-900/70 dark:text-white dark:placeholder:text-zinc-500 dark:focus:border-primary-400/50 dark:focus:ring-primary-400/15 ${
                        hasAdminValue && !hasUserValue ? 'border-sky-300 dark:border-sky-500/45' : ''
                      }`
                    : `bg-gray-50 dark:bg-gray-800/70 border rounded-lg text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-primary-500/30 focus:border-primary-500/50 ${
                        hasAdminValue && !hasUserValue ? 'border-blue-200 dark:border-blue-800/50' : 'border-gray-200 dark:border-gray-700'
                      }`
          }`}
        />
      ) : (
        <div className="relative">
          <input
            id={plainModern ? inputId : undefined}
            type={isSecret && !showSecret ? 'password' : 'text'}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={
              hasAdminValue
                ? (isSecret ? 'Using admin default (••••••)' : `Admin default: ${adminDefault!.slice(0, 30)}${adminDefault!.length > 30 ? '…' : ''}`)
                : field.example || field.default ||
                    (field.key === 'ON_PREM_CLOUD_ACCESS_TOKEN'
                      ? 'Enter ON_PREM_CLOUD_ACCESS_TOKEN'
                      : `Enter ${field.key}`)
            }
            className={`w-full font-mono focus:outline-none transition-all pr-9 ${
              compact
                ? workflowEmbed
                  ? 'rounded-md px-2 py-1.5 text-[10px]'
                  : 'rounded-md px-2.5 py-2 text-[11px]'
                : plainModern
                  ? 'rounded-xl px-3.5 py-2.5 text-sm'
                  : 'rounded-md px-3 py-2 text-xs'
            } ${
              insideLlmCard && workflowEmbed
                ? `text-gray-100 placeholder:text-gray-600 bg-black/20 border border-violet-400/25 focus:border-violet-400/50 focus:ring-1 focus:ring-violet-500/30 ${
                    hasAdminValue && !hasUserValue ? 'border-sky-500/35' : ''
                  }`
                : insideLlmCard
                  ? `border rounded-lg bg-white/90 dark:bg-zinc-900/55 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400/55 ${
                      hasAdminValue && !hasUserValue ? 'border-sky-300 dark:border-sky-500/40' : 'border-violet-200/80 dark:border-violet-500/30'
                    }`
                  : workflowEmbed
                    ? `text-gray-100 placeholder:text-gray-600 bg-black/25 border border-white/[0.08] focus:border-emerald-500/40 focus:ring-1 focus:ring-emerald-500/20 ${
                        hasAdminValue && !hasUserValue ? 'border-sky-500/30' : ''
                      }`
                    : plainModern
                      ? `border border-gray-200/90 bg-white text-gray-900 shadow-sm placeholder:text-gray-400 focus:border-primary-500/55 focus:ring-2 focus:ring-primary-500/20 dark:border-white/[0.1] dark:bg-zinc-900/70 dark:text-white dark:placeholder:text-zinc-500 dark:focus:border-primary-400/50 dark:focus:ring-primary-400/15 ${
                          hasAdminValue && !hasUserValue ? 'border-sky-300 dark:border-sky-500/45' : ''
                        }`
                      : `bg-gray-50 dark:bg-gray-800/70 border rounded-lg text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-primary-500/30 focus:border-primary-500/50 ${
                          hasAdminValue && !hasUserValue ? 'border-blue-200 dark:border-blue-800/50' : 'border-gray-200 dark:border-gray-700'
                        }`
            }`}
          />
          {isSecret && (
            <button
              type="button"
              onClick={onToggleShow}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
            >
              {showSecret ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
