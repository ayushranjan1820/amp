import { useEffect, useMemo, useState } from 'react';
import { Database, RefreshCw, Loader2, Folder, Clock, FileCode, ChevronDown, ChevronRight, ExternalLink } from 'lucide-react';
import { getAgentsMarketplaceApiBase } from '../utils/agentsApiBase';

interface RunNote {
  at: string;
  summary: string;
  changed_files: string[];
  cost_usd: number;
  duration_seconds: number;
}

interface MemoryRecord {
  repo_url: string;
  repo_name: string;
  language: string;
  file_tree?: string;
  key_files_text?: string;
  refreshed_at: string;
  run_notes?: RunNote[];
}

interface MemorySummary {
  repo_url: string;
  repo_name: string;
  language: string;
  refreshed_at: string;
  run_notes_count: number;
  last_run_at: string;
  last_run_summary: string;
  last_run_changed_files: string[];
}

function formatTimestamp(iso: string): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

export default function ClaudeCodeMemoryView() {
  const [items, setItems] = useState<MemorySummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [details, setDetails] = useState<Record<string, MemoryRecord>>({});
  const [detailsLoading, setDetailsLoading] = useState<Record<string, boolean>>({});

  const apiBase = useMemo(() => getAgentsMarketplaceApiBase(), []);

  const fetchList = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase}/api/claude-code/memory`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setItems(data.memories || []);
    } catch (e: any) {
      setError(e?.message || 'Failed to load memory');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggle = async (repoUrl: string) => {
    const key = repoUrl;
    const isOpen = !!expanded[key];
    setExpanded((prev) => ({ ...prev, [key]: !isOpen }));
    if (!isOpen && !details[key]) {
      setDetailsLoading((prev) => ({ ...prev, [key]: true }));
      try {
        const res = await fetch(
          `${apiBase}/api/claude-code/memory?repo_url=${encodeURIComponent(repoUrl)}`,
        );
        if (res.ok) {
          const data = await res.json();
          if (data?.memory) {
            setDetails((prev) => ({ ...prev, [key]: data.memory }));
          }
        }
      } catch {
        /* ignore — keep summary view */
      } finally {
        setDetailsLoading((prev) => ({ ...prev, [key]: false }));
      }
    }
  };

  return (
    <section className="rounded-2xl border border-gray-200/70 bg-white/75 p-4 shadow-sm shadow-gray-900/[0.02] ring-1 ring-black/[0.02] backdrop-blur-sm dark:border-white/[0.07] dark:bg-zinc-900/40 dark:shadow-black/25 dark:ring-white/[0.04]">
      <div className="mb-4 flex items-start justify-between gap-3">
        <h3 className="flex items-center gap-2.5 font-body">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500/12 to-primary-500/10 ring-1 ring-violet-500/15 dark:from-violet-400/15 dark:to-primary-400/10 dark:ring-violet-400/20">
            <Database className="h-4 w-4 text-violet-600 dark:text-violet-400" aria-hidden />
          </span>
          <span className="min-w-0">
            <span className="block text-[11px] font-bold uppercase tracking-[0.14em] text-gray-500 dark:text-zinc-400">
              Saved Memory
            </span>
            <span className="mt-0.5 block text-[10px] font-medium leading-tight text-gray-400 dark:text-zinc-500">
              Adaptive per-repo memory the agent injects into CLAUDE.md
            </span>
          </span>
        </h3>
        <button
          type="button"
          onClick={fetchList}
          disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200/80 bg-white px-2.5 py-1.5 font-body text-[11px] font-semibold text-gray-700 shadow-sm transition hover:bg-gray-50 disabled:opacity-60 dark:border-white/[0.08] dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
        >
          {loading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" />
          )}
          Refresh
        </button>
      </div>

      {error && (
        <div className="mb-3 rounded-xl border border-red-200/80 bg-red-50/70 px-3 py-2 font-body text-[11px] text-red-700 dark:border-red-500/30 dark:bg-red-950/30 dark:text-red-300">
          {error}
        </div>
      )}

      {loading && !items && (
        <div className="flex items-center justify-center py-10 text-gray-500 dark:text-zinc-500">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          <span className="font-body text-xs">Loading memory…</span>
        </div>
      )}

      {items && items.length === 0 && !loading && (
        <p className="rounded-xl border border-dashed border-gray-200/90 bg-gray-50/60 px-4 py-8 text-center font-body text-xs text-gray-500 dark:border-white/[0.1] dark:bg-zinc-950/40 dark:text-zinc-500">
          No saved memory yet. Run the Claude Code Agent against a repo and its memory will appear here.
        </p>
      )}

      {items && items.length > 0 && (
        <ul className="space-y-3">
          {items.map((it) => {
            const isOpen = !!expanded[it.repo_url];
            const detail = details[it.repo_url];
            const isLoadingDetail = !!detailsLoading[it.repo_url];
            return (
              <li
                key={it.repo_url}
                className="overflow-hidden rounded-2xl border border-gray-200/65 bg-gradient-to-br from-white to-gray-50/90 transition-all dark:border-white/[0.07] dark:from-zinc-900/85 dark:to-zinc-950/95"
              >
                <button
                  type="button"
                  onClick={() => toggle(it.repo_url)}
                  className="flex w-full items-start gap-3 p-3.5 text-left hover:bg-gray-50/60 dark:hover:bg-zinc-900/60"
                >
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary-500/12 to-zinc-500/5 ring-1 ring-primary-500/12 dark:from-primary-400/18 dark:to-zinc-900 dark:ring-primary-400/15">
                    <Folder className="h-4 w-4 text-primary-600 dark:text-primary-400" aria-hidden />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h4 className="truncate font-body text-sm font-semibold tracking-tight text-gray-900 dark:text-white">
                        {it.repo_name || '(unknown repo)'}
                      </h4>
                      <span className="rounded-md bg-violet-100 px-1.5 py-0.5 font-body text-[9px] font-bold uppercase tracking-wide text-violet-700 dark:bg-violet-500/20 dark:text-violet-200">
                        {it.language || 'unknown'}
                      </span>
                      <span className="inline-flex items-center gap-1 rounded-md bg-gray-100 px-1.5 py-0.5 font-body text-[9px] font-medium text-gray-600 dark:bg-zinc-800 dark:text-zinc-300">
                        <FileCode className="h-3 w-3" />
                        {it.run_notes_count} run{it.run_notes_count === 1 ? '' : 's'}
                      </span>
                    </div>
                    <p className="mt-1 truncate font-mono text-[10.5px] text-gray-500 dark:text-zinc-400">
                      {it.repo_url}
                    </p>
                    <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 font-body text-[10.5px] text-gray-500 dark:text-zinc-500">
                      <span className="inline-flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        Refreshed {formatTimestamp(it.refreshed_at)}
                      </span>
                      {it.last_run_at && (
                        <span className="inline-flex items-center gap-1">
                          Last run {formatTimestamp(it.last_run_at)}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex h-9 w-7 shrink-0 items-center justify-center text-gray-400 dark:text-zinc-500">
                    {isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                  </div>
                </button>

                {isOpen && (
                  <div className="border-t border-gray-200/70 bg-gray-50/40 p-3.5 dark:border-white/[0.06] dark:bg-zinc-950/40">
                    {isLoadingDetail && !detail && (
                      <div className="flex items-center justify-center py-6 text-gray-500 dark:text-zinc-500">
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        <span className="font-body text-xs">Loading details…</span>
                      </div>
                    )}

                    {detail && (
                      <div className="space-y-4">
                        <div className="flex flex-wrap items-center gap-2">
                          <a
                            href={it.repo_url}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1 rounded-md bg-white px-2 py-1 font-body text-[10.5px] font-medium text-primary-700 ring-1 ring-gray-200 hover:bg-primary-50 dark:bg-zinc-900 dark:text-primary-300 dark:ring-white/[0.08] dark:hover:bg-zinc-800"
                          >
                            <ExternalLink className="h-3 w-3" />
                            Open repository
                          </a>
                        </div>

                        {detail.file_tree && (
                          <div>
                            <h5 className="mb-1.5 font-body text-[10px] font-bold uppercase tracking-[0.14em] text-gray-500 dark:text-zinc-400">
                              File tree
                            </h5>
                            <pre className="max-h-72 overflow-auto rounded-lg border border-gray-200/80 bg-white p-2.5 font-mono text-[10.5px] leading-relaxed text-gray-800 dark:border-white/[0.07] dark:bg-zinc-950 dark:text-zinc-200">
{detail.file_tree}
                            </pre>
                          </div>
                        )}

                        {detail.key_files_text && (
                          <div>
                            <h5 className="mb-1.5 font-body text-[10px] font-bold uppercase tracking-[0.14em] text-gray-500 dark:text-zinc-400">
                              Key files
                            </h5>
                            <pre className="max-h-72 overflow-auto rounded-lg border border-gray-200/80 bg-white p-2.5 font-mono text-[10.5px] leading-relaxed text-gray-800 dark:border-white/[0.07] dark:bg-zinc-950 dark:text-zinc-200">
{detail.key_files_text}
                            </pre>
                          </div>
                        )}

                        {detail.run_notes && detail.run_notes.length > 0 && (
                          <div>
                            <h5 className="mb-1.5 font-body text-[10px] font-bold uppercase tracking-[0.14em] text-gray-500 dark:text-zinc-400">
                              Recent runs ({detail.run_notes.length})
                            </h5>
                            <ul className="space-y-2">
                              {[...detail.run_notes].reverse().map((note, idx) => (
                                <li
                                  key={idx}
                                  className="rounded-lg border border-gray-200/80 bg-white p-2.5 dark:border-white/[0.07] dark:bg-zinc-950"
                                >
                                  <div className="mb-1 flex flex-wrap items-center gap-x-3 gap-y-1 font-body text-[10.5px] text-gray-500 dark:text-zinc-400">
                                    <span className="inline-flex items-center gap-1">
                                      <Clock className="h-3 w-3" />
                                      {formatTimestamp(note.at)}
                                    </span>
                                    <span>${(note.cost_usd ?? 0).toFixed(4)}</span>
                                    <span>{note.duration_seconds ?? 0}s</span>
                                    <span>{(note.changed_files || []).length} file(s)</span>
                                  </div>
                                  {note.summary && (
                                    <p className="mb-1.5 whitespace-pre-wrap font-body text-[11px] text-gray-700 dark:text-zinc-300">
                                      {note.summary}
                                    </p>
                                  )}
                                  {(note.changed_files || []).length > 0 && (
                                    <ul className="flex flex-wrap gap-1">
                                      {note.changed_files.map((f, i) => (
                                        <li
                                          key={i}
                                          className="rounded-md bg-gray-100 px-1.5 py-0.5 font-mono text-[10px] text-gray-700 dark:bg-zinc-800 dark:text-zinc-300"
                                        >
                                          {f}
                                        </li>
                                      ))}
                                    </ul>
                                  )}
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    )}

                    {!detail && !isLoadingDetail && it.last_run_summary && (
                      <div>
                        <h5 className="mb-1.5 font-body text-[10px] font-bold uppercase tracking-[0.14em] text-gray-500 dark:text-zinc-400">
                          Latest run
                        </h5>
                        <p className="whitespace-pre-wrap font-body text-[11px] text-gray-700 dark:text-zinc-300">
                          {it.last_run_summary}
                        </p>
                      </div>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
