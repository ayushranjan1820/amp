import { useState, useMemo, useRef, useEffect, useLayoutEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { Search, ChevronDown, X, Check, Eye, EyeOff } from 'lucide-react';
import type { Agent } from '../services/api';
import { collectEnvKeysFromAgents, mcpEnvKeyMetaForKeys, type McpEnvKeyTier } from '../utils/catalogEnvKeys';

type Props = {
  agents: Agent[];
  selectedIds: string[];
  onSelectionChange: (ids: string[]) => void;
  disabled?: boolean;
  envKeys: string[];
  envValues: Record<string, string>;
  onEnvValueChange: (key: string, value: string) => void;
};

function isSensitiveEnvKey(key: string): boolean {
  return /TOKEN|SECRET|PASSWORD|API_KEY|BEARER|CREDENTIAL|AUTH|PAT|_KEY$/i.test(key);
}

export default function McpAgentEnvPicker({
  agents,
  selectedIds,
  onSelectionChange,
  disabled,
  envKeys,
  envValues,
  onEnvValueChange,
}: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  /** When a key is present, that secret field is shown as plain text. */
  const [revealedSecretKeys, setRevealedSecretKeys] = useState<Record<string, boolean>>({});
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [menuRect, setMenuRect] = useState<{ top: number; left: number; width: number; maxH: number } | null>(null);

  const updateMenuRect = useCallback(() => {
    const el = buttonRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const gap = 4;
    const maxH = Math.max(120, Math.min(320, window.innerHeight - r.bottom - gap - 12));
    setMenuRect({ top: r.bottom + gap, left: r.left, width: r.width, maxH });
  }, []);

  useLayoutEffect(() => {
    if (!open) {
      setMenuRect(null);
      return;
    }
    updateMenuRect();
    const ro = new ResizeObserver(updateMenuRect);
    if (buttonRef.current) ro.observe(buttonRef.current);
    window.addEventListener('scroll', updateMenuRect, true);
    window.addEventListener('resize', updateMenuRect);
    return () => {
      ro.disconnect();
      window.removeEventListener('scroll', updateMenuRect, true);
      window.removeEventListener('resize', updateMenuRect);
    };
  }, [open, updateMenuRect]);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      const t = e.target as Node;
      if (rootRef.current?.contains(t) || menuRef.current?.contains(t)) return;
      setOpen(false);
    }
    document.addEventListener('click', onDocClick);
    return () => document.removeEventListener('click', onDocClick);
  }, []);

  const selectable = useMemo(
    () => agents.filter((a) => a.status === 'active' && (a.configuration || a.usage?.api_endpoint)),
    [agents],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return selectable;
    return selectable.filter(
      (a) =>
        a.name.toLowerCase().includes(q) ||
        a.id.toLowerCase().includes(q) ||
        (a.description && a.description.toLowerCase().includes(q)),
    );
  }, [selectable, query]);

  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);

  const toggle = (id: string) => {
    if (selectedSet.has(id)) {
      onSelectionChange(selectedIds.filter((x) => x !== id));
    } else {
      onSelectionChange([...selectedIds, id]);
    }
  };

  const selectVisible = () => {
    const ids = new Set(selectedIds);
    filtered.forEach((a) => ids.add(a.id));
    onSelectionChange([...ids]);
  };

  const clearAll = () => onSelectionChange([]);

  const keyCount = collectEnvKeysFromAgents(selectable.filter((a) => selectedSet.has(a.id))).length;

  const selectedAgents = useMemo(
    () => agents.filter((a) => selectedIds.includes(a.id)),
    [agents, selectedIds],
  );

  const envKeyMeta = useMemo(() => mcpEnvKeyMetaForKeys(selectedAgents, envKeys), [selectedAgents, envKeys]);

  const sortedEnvKeys = useMemo(() => {
    const tierOrder: Record<McpEnvKeyTier, number> = { base: 0, required: 1, optional: 2 };
    return [...envKeys].sort((a, b) => {
      const ta = envKeyMeta[a]?.tier ?? 'optional';
      const tb = envKeyMeta[b]?.tier ?? 'optional';
      const d = tierOrder[ta] - tierOrder[tb];
      return d !== 0 ? d : a.localeCompare(b);
    });
  }, [envKeys, envKeyMeta]);

  const tierLabel: Record<McpEnvKeyTier, string> = {
    base: 'Core',
    required: 'Required',
    optional: 'Optional',
  };

  const tierRowClass: Record<McpEnvKeyTier, string> = {
    base:
      'border-gray-200/90 bg-primary-50/35 dark:border-gray-700/90 dark:bg-primary-950/20 border-l-[3px] border-l-primary-500',
    required:
      'border-gray-200/90 bg-amber-50/55 dark:border-gray-700/90 dark:bg-amber-950/25 border-l-[3px] border-l-amber-500 dark:border-l-amber-400',
    optional:
      'border-gray-200/85 bg-slate-50/70 dark:border-gray-700/85 dark:bg-slate-900/35 border-l-[3px] border-l-slate-400 dark:border-l-slate-500',
  };

  const tierBadgeClass: Record<McpEnvKeyTier, string> = {
    base: 'bg-primary-500/15 text-primary-800 dark:bg-primary-500/20 dark:text-primary-200',
    required: 'bg-amber-500/15 text-amber-900 dark:bg-amber-400/25 dark:text-amber-100',
    optional: 'bg-slate-500/10 text-slate-700 dark:bg-slate-400/15 dark:text-slate-300',
  };

  return (
    <div ref={rootRef} className="relative">
      <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-x-2 gap-y-0.5">
        <span className="font-heading text-xs font-semibold text-gray-800 dark:text-gray-200">Agents</span>
        <span className="font-body text-[10px] text-gray-500 dark:text-gray-400">Multi-select · keys merge into the header JSON</span>
      </div>
      <button
        ref={buttonRef}
        type="button"
        disabled={disabled}
        onClick={(e) => {
          e.stopPropagation();
          setOpen(!open);
        }}
        className="w-full flex items-center justify-between gap-2 rounded-lg border border-gray-200 bg-white px-2.5 py-2 text-left font-body text-sm text-gray-900 transition-colors hover:border-primary-400 disabled:opacity-50 dark:border-gray-700 dark:bg-gray-900 dark:text-white dark:hover:border-primary-600"
      >
        <span className="min-w-0 truncate">
          {selectedIds.length === 0 ? (
            <span className="text-gray-500 dark:text-gray-400">Select agents…</span>
          ) : (
            <>
              <span className="font-medium">{selectedIds.length} selected</span>
              <span className="font-normal text-gray-500 dark:text-gray-400"> · ~{keyCount} keys</span>
            </>
          )}
        </span>
        <ChevronDown className={`h-4 w-4 shrink-0 text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {selectedIds.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {selectedIds.map((id) => {
            const a = agents.find((x) => x.id === id);
            if (!a) return null;
            return (
              <span
                key={id}
                className="inline-flex max-w-full items-start gap-1 rounded-lg border border-neutral-700/90 bg-neutral-800 px-2 py-1 shadow-sm dark:border-neutral-500 dark:bg-neutral-700 dark:shadow-black/30"
              >
                <span className="min-w-0 max-w-full break-words font-body text-xs font-semibold leading-snug text-neutral-50">
                  {a.name}
                </span>
                <button
                  type="button"
                  onClick={() => toggle(id)}
                  className="mt-0.5 shrink-0 rounded p-0.5 text-neutral-500 dark:text-neutral-400 transition-colors hover:bg-gray-100 dark:hover:bg-white/15 hover:text-gray-900 dark:hover:text-white"
                  aria-label={`Remove ${a.name}`}
                >
                  <X className="h-3.5 w-3.5" strokeWidth={2.5} aria-hidden />
                </button>
              </span>
            );
          })}
          <button
            type="button"
            onClick={clearAll}
            className="self-center px-1.5 text-[11px] font-medium text-gray-500 hover:text-gray-800 dark:hover:text-gray-200"
          >
            Clear
          </button>
        </div>
      )}

      {envKeys.length > 0 && (
        <div className="mt-3 space-y-2 border-t border-gray-100 pt-3 dark:border-gray-800/80">
          <div className="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
            <div>
              <p className="font-heading text-xs font-semibold text-gray-800 dark:text-gray-200">Env values</p>
              <p className="font-body text-[10px] leading-snug text-gray-500 dark:text-gray-400">
                Each field becomes a property in the header JSON you copy below.
              </p>
            </div>
            <div className="flex flex-wrap gap-1.5 shrink-0">
              {(['base', 'required', 'optional'] as const).map((t) => (
                <span
                  key={t}
                  className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-body text-[9px] font-semibold uppercase tracking-wide ${tierBadgeClass[t]}`}
                >
                  <span
                    className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                      t === 'base'
                        ? 'bg-primary-500'
                        : t === 'required'
                          ? 'bg-amber-500'
                          : 'bg-slate-400 dark:bg-slate-500'
                    }`}
                    aria-hidden
                  />
                  {tierLabel[t]}
                </span>
              ))}
            </div>
          </div>
          <div className="space-y-1.5">
            {sortedEnvKeys.map((key) => {
              const tier = envKeyMeta[key]?.tier ?? 'optional';
              const description = envKeyMeta[key]?.description;
              const sensitive = isSensitiveEnvKey(key);
              const revealed = revealedSecretKeys[key] === true;
              return (
                <div
                  key={key}
                  className={`space-y-1 rounded-lg border py-2 pl-3 pr-2.5 shadow-sm ${tierRowClass[tier]}`}
                >
                  <div className="flex flex-wrap items-center gap-1.5">
                    <label
                      htmlFor={`mcp-env-${key}`}
                      className="font-mono text-[11px] font-semibold text-gray-900 dark:text-gray-100"
                    >
                      {key}
                    </label>
                    <span
                      className={`rounded px-1 py-px font-body text-[8px] font-bold uppercase tracking-wide ${tierBadgeClass[tier]}`}
                    >
                      {tierLabel[tier]}
                    </span>
                  </div>
                  {description ? (
                    <p className="font-body text-[10px] leading-snug text-gray-600 dark:text-gray-400">{description}</p>
                  ) : null}
                  <div className="relative">
                    <input
                      id={`mcp-env-${key}`}
                      type={sensitive && !revealed ? 'password' : 'text'}
                      autoComplete="off"
                      spellCheck={false}
                      disabled={disabled}
                      value={envValues[key] ?? ''}
                      onChange={(e) => onEnvValueChange(key, e.target.value)}
                      className={`w-full rounded-md border border-gray-200/90 bg-white py-1.5 font-mono text-[11px] text-black outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500/30 disabled:opacity-50 dark:border-gray-600 dark:bg-gray-950/80 dark:text-neutral-100 ${
                        sensitive ? 'pl-2.5 pr-9' : 'px-2.5'
                      }`}
                    />
                    {sensitive ? (
                      <button
                        type="button"
                        disabled={disabled}
                        onClick={() =>
                          setRevealedSecretKeys((prev) => ({
                            ...prev,
                            [key]: !prev[key],
                          }))
                        }
                        className="absolute right-1 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-md text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-800 disabled:pointer-events-none disabled:opacity-50 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200"
                        aria-label={revealed ? `Hide ${key}` : `Show ${key}`}
                        aria-pressed={revealed}
                      >
                        {revealed ? <EyeOff className="h-4 w-4" strokeWidth={2} aria-hidden /> : <Eye className="h-4 w-4" strokeWidth={2} aria-hidden />}
                      </button>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {open &&
        menuRect &&
        createPortal(
          <div
            ref={menuRef}
            role="listbox"
            aria-label="Select agents"
            className="fixed z-[500] flex flex-col overflow-hidden rounded-lg border border-gray-200 bg-white shadow-2xl ring-1 ring-black/5 dark:border-gray-700 dark:bg-gray-900 dark:ring-white/10"
            style={{
              top: menuRect.top,
              left: menuRect.left,
              width: menuRect.width,
              maxHeight: menuRect.maxH,
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="shrink-0 border-b border-gray-100 p-2 dark:border-gray-800">
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
                <input
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search agents…"
                  className="w-full rounded-md border border-gray-200 bg-gray-50 py-2 pl-9 pr-3 font-body text-sm text-gray-900 outline-none placeholder:text-gray-400 focus:border-primary-500 focus:ring-2 focus:ring-primary-500/25 dark:border-gray-700 dark:bg-gray-800/80 dark:text-white"
                  autoFocus
                />
              </div>
              <div className="mt-2 flex gap-2">
                <button
                  type="button"
                  onClick={selectVisible}
                  className="text-xs font-semibold text-primary-600 hover:underline dark:text-primary-400"
                >
                  Select all in list
                </button>
              </div>
            </div>
            <ul className="min-h-0 flex-1 overflow-y-auto p-1">
              {filtered.length === 0 ? (
                <li className="px-3 py-4 text-center text-sm text-gray-500">No matches</li>
              ) : (
                filtered.map((a) => {
                  const on = selectedSet.has(a.id);
                  return (
                    <li key={a.id}>
                      <button
                        type="button"
                        onClick={() => toggle(a.id)}
                        className={`flex w-full items-start gap-2 rounded-md px-2 py-2 text-left font-body text-sm transition-colors ${
                          on
                            ? 'bg-primary-50 text-primary-900 dark:bg-primary-900/20 dark:text-primary-100'
                            : 'text-gray-800 hover:bg-gray-50 dark:text-gray-200 dark:hover:bg-gray-800/80'
                        }`}
                      >
                        <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border border-gray-300 bg-white dark:border-gray-600 dark:bg-gray-900">
                          {on && <Check className="h-3 w-3 text-primary-600" />}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate font-semibold">{a.name}</span>
                          <span className="font-mono text-[11px] text-gray-500 dark:text-gray-400">{a.id}</span>
                        </span>
                      </button>
                    </li>
                  );
                })
              )}
            </ul>
          </div>,
          document.body,
        )}
    </div>
  );
}
