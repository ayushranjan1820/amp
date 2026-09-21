import { useEffect, useState } from 'react';
import { Activity, AlertCircle, BarChart3, Clock, Loader2, Zap } from 'lucide-react';
import { getAgentStats, type AgentUsageStats } from '../../services/agentBuilder';

interface Props {
  agentId: string | null;
}

const WINDOW_OPTIONS: { label: string; days: number }[] = [
  { label: '24h', days: 1 },
  { label: '7d', days: 7 },
  { label: '30d', days: 30 },
  { label: '90d', days: 90 },
];

function formatNumber(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'k';
  return String(n);
}

function formatMs(ms: number): string {
  if (!ms || ms < 0) return '—';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function Sparkline({ values, color }: { values: number[]; color: string }) {
  if (!values.length) {
    return <div className="h-8 text-[10px] text-gray-400 dark:text-gray-600 flex items-center">No data</div>;
  }
  const max = Math.max(1, ...values);
  const W = 200;
  const H = 32;
  const stepX = values.length > 1 ? W / (values.length - 1) : W;
  const points = values
    .map((v, i) => `${(i * stepX).toFixed(1)},${(H - (v / max) * H).toFixed(1)}`)
    .join(' ');
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="w-full h-8">
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.5" />
    </svg>
  );
}

export default function UsagePanel({ agentId }: Props) {
  const [stats, setStats] = useState<AgentUsageStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [days, setDays] = useState(30);

  useEffect(() => {
    if (!agentId) return;
    let cancelled = false;
    setLoading(true);
    setError('');
    getAgentStats(agentId, days)
      .then(({ stats: s }) => {
        if (!cancelled) setStats(s);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message || 'Failed to load stats');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [agentId, days]);

  if (!agentId) return null;

  const callsSeries = (stats?.series || []).map((s) => s.calls);
  const tokensSeries = (stats?.series || []).map((s) => s.tokens);
  const errorRate =
    stats && stats.totals.calls > 0 ? (stats.totals.errors / stats.totals.calls) * 100 : 0;

  return (
    <div className="rounded-xl border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-white/[0.02] p-5">
      <div className="flex items-center justify-between mb-4">
        <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 flex items-center gap-2">
          <BarChart3 className="w-4 h-4" /> Usage
        </h4>
        <div className="flex items-center gap-1 rounded-lg bg-gray-100 dark:bg-white/[0.04] p-0.5">
          {WINDOW_OPTIONS.map((opt) => (
            <button
              key={opt.days}
              onClick={() => setDays(opt.days)}
              className={`px-2.5 py-1 rounded text-[11px] font-medium transition-colors ${
                days === opt.days
                  ? 'bg-violet-600 text-gray-900 dark:text-white'
                  : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-6 text-gray-500 text-sm">
          <Loader2 className="w-4 h-4 animate-spin mr-2" /> Loading stats…
        </div>
      )}

      {error && !loading && (
        <div className="flex items-center gap-2 text-sm text-red-400 py-3">
          <AlertCircle className="w-4 h-4" /> {error}
        </div>
      )}

      {stats && !loading && !error && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Metric
              icon={<Activity className="w-3.5 h-3.5" />}
              label="Calls"
              value={formatNumber(stats.totals.calls || 0)}
            />
            <Metric
              icon={<Zap className="w-3.5 h-3.5" />}
              label="Tokens"
              value={formatNumber((stats.totals.input_tokens || 0) + (stats.totals.output_tokens || 0))}
            />
            <Metric
              icon={<Clock className="w-3.5 h-3.5" />}
              label="p95"
              value={formatMs(Number(stats.totals.p95_duration_ms) || 0)}
            />
            <Metric
              icon={<AlertCircle className="w-3.5 h-3.5" />}
              label="Errors"
              value={`${errorRate.toFixed(1)}%`}
              tone={errorRate > 5 ? 'danger' : 'normal'}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-[10px] uppercase tracking-wide text-gray-500 font-semibold">Calls / day</span>
                <span className="text-[10px] text-gray-400 dark:text-gray-600">peak {formatNumber(Math.max(0, ...callsSeries))}</span>
              </div>
              <Sparkline values={callsSeries} color="#a78bfa" />
            </div>
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-[10px] uppercase tracking-wide text-gray-500 font-semibold">Tokens / day</span>
                <span className="text-[10px] text-gray-400 dark:text-gray-600">peak {formatNumber(Math.max(0, ...tokensSeries))}</span>
              </div>
              <Sparkline values={tokensSeries} color="#34d399" />
            </div>
          </div>

          {stats.totals.calls === 0 && (
            <p className="text-xs text-gray-400 dark:text-gray-600 text-center py-2">
              No calls in this window yet. Try the agent in the playground or via the API.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function Metric({
  icon,
  label,
  value,
  tone = 'normal',
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  tone?: 'normal' | 'danger';
}) {
  return (
    <div className="rounded-lg bg-gray-50 dark:bg-white/[0.02] border border-gray-200 dark:border-white/[0.04] p-3">
      <div className="flex items-center gap-1 text-gray-500 text-[10px] font-medium uppercase tracking-wide">
        {icon} {label}
      </div>
      <div className={`mt-1 text-lg font-bold tabular-nums ${tone === 'danger' ? 'text-red-400' : 'text-gray-900 dark:text-white'}`}>
        {value}
      </div>
    </div>
  );
}
