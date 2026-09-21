import { useEffect, useState } from 'react';
import { X, Loader2, AlertCircle, RotateCcw } from 'lucide-react';
import { getVersionDiff, rollbackToVersion, type VersionDiffEntry } from '../../services/agentBuilder';

interface Props {
  agentId: string;
  version: string;
  onClose: () => void;
  onRollback?: () => void;
}

function formatValue(v: unknown): string {
  if (v == null) return '—';
  if (typeof v === 'string') return v;
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

export default function VersionDiffModal({ agentId, version, onClose, onRollback }: Props) {
  const [diff, setDiff] = useState<VersionDiffEntry[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [rollingBack, setRollingBack] = useState(false);
  const [rollbackError, setRollbackError] = useState('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    getVersionDiff(agentId, version)
      .then(({ diff: d }) => {
        if (!cancelled) setDiff(d);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message || 'Could not load diff');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [agentId, version]);

  const handleRollback = async () => {
    setRollingBack(true);
    setRollbackError('');
    try {
      await rollbackToVersion(agentId, version);
      onRollback?.();
      onClose();
    } catch (e) {
      setRollbackError((e as Error).message || 'Rollback failed');
    } finally {
      setRollingBack(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-gray-900/40 dark:bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-full max-w-3xl max-h-[85vh] flex flex-col rounded-2xl bg-white dark:bg-zinc-900 border border-gray-200 dark:border-white/[0.08] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between p-5 border-b border-gray-200 dark:border-white/[0.06]">
          <div>
            <h3 className="text-base font-semibold text-gray-900 dark:text-white">Compare with v{version}</h3>
            <p className="text-xs text-gray-500 mt-0.5">
              Differences between the saved snapshot and the current agent state.
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-white/[0.06] text-gray-500 hover:text-gray-700 dark:text-gray-300 transition-colors"
            aria-label="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-3">
          {loading && (
            <div className="flex items-center justify-center py-8 text-gray-500 text-sm">
              <Loader2 className="w-4 h-4 animate-spin mr-2" /> Loading diff…
            </div>
          )}

          {error && !loading && (
            <div className="flex items-center gap-2 text-sm text-red-400">
              <AlertCircle className="w-4 h-4" /> {error}
            </div>
          )}

          {!loading && !error && diff && diff.length === 0 && (
            <p className="text-sm text-gray-500 text-center py-8">
              No differences — current state matches v{version}.
            </p>
          )}

          {!loading && !error && diff && diff.length > 0 && (
            <div className="space-y-3">
              {diff.map((entry) => (
                <div key={entry.field} className="rounded-xl border border-gray-200 dark:border-white/[0.06] overflow-hidden">
                  <div className="px-4 py-2 bg-gray-50 dark:bg-white/[0.03] border-b border-gray-200 dark:border-white/[0.06]">
                    <span className="text-sm font-mono text-violet-400">{entry.field}</span>
                  </div>
                  <div className="grid sm:grid-cols-2 divide-y sm:divide-y-0 sm:divide-x divide-gray-200 dark:divide-white/[0.06]">
                    <div className="p-3">
                      <div className="text-[10px] uppercase tracking-wide text-amber-400 font-semibold mb-1">
                        v{version}
                      </div>
                      <pre className="text-[11px] font-mono text-amber-300/80 whitespace-pre-wrap break-words max-h-40 overflow-y-auto">
                        {formatValue(entry.old)}
                      </pre>
                    </div>
                    <div className="p-3">
                      <div className="text-[10px] uppercase tracking-wide text-emerald-400 font-semibold mb-1">
                        Current
                      </div>
                      <pre className="text-[11px] font-mono text-emerald-300/80 whitespace-pre-wrap break-words max-h-40 overflow-y-auto">
                        {formatValue(entry.new)}
                      </pre>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {!loading && diff && diff.length > 0 && (
          <div className="flex items-center justify-between gap-2 p-4 border-t border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-white/[0.02] rounded-b-2xl">
            {rollbackError && (
              <span className="text-xs text-red-400 flex items-center gap-1 mr-auto">
                <AlertCircle className="w-3.5 h-3.5" /> {rollbackError}
              </span>
            )}
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-xl border border-gray-200 dark:border-white/[0.08] text-sm font-medium text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:border-gray-300 dark:hover:border-white/[0.15] transition-colors"
            >
              Close
            </button>
            <button
              onClick={handleRollback}
              disabled={rollingBack}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-amber-600 hover:bg-amber-700 disabled:opacity-50 disabled:cursor-not-allowed text-gray-900 dark:text-white text-sm font-semibold transition-colors"
            >
              {rollingBack ? <Loader2 className="w-4 h-4 animate-spin" /> : <RotateCcw className="w-4 h-4" />}
              Roll back to v{version}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
