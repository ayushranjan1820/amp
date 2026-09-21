import { useState, useEffect, useMemo, Fragment } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import {
  Bot, MessageSquare, Settings,
  ChevronRight, User, Activity, Zap,
  Clock, Shield, ExternalLink, Plus, AlertCircle,
  CheckCircle, Loader2, Eye, EyeOff, Key, Trash2, Search,
  Edit2, Save, X, ChevronDown, ChevronUp, ChevronLeft, RefreshCw,
  DollarSign, TrendingUp, TrendingDown, BarChart3, Hash,
  Globe, MapPin, Monitor, Network, AlertTriangle, Database,
  Calendar, Sparkles, SlidersHorizontal, LayoutGrid, History
} from 'lucide-react';
import { getCatalog, updateCatalog, getCostSummary, getUsageSummary, getUsageLogs, getMaintenanceStatus, setMaintenanceMode, type Agent, type AgentsCatalog as CatalogData, type CostSummary, type UsageSummary, type UsageLog } from '../services/api';
import { Link } from 'react-router-dom';
import KnowledgeBaseTab from '../components/KnowledgeBaseTab';
import UserManagementTab from '../components/UserManagementTab';
import AdminLayout from '../layouts/AdminLayout';
import { getTabFromPath, type AdminTab } from '../admin/adminNav';
import { WorkflowsTab } from '../components/WorkflowsTab';
import ReviewQueueTab from '../components/ReviewQueueTab';
import UsageWorldMap from '../components/UsageWorldMap';
import { LoadingProvider, useLoading } from '../context/LoadingContext';
import { getConfigFields } from '../utils/agentConfigStorage';
import {
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ComposedChart,
  Line,
  Legend,
} from 'recharts';

interface ChatSession {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count?: number;
}

function getAutonomyColor(quotient: number): string {
  if (quotient >= 80) return '#10b981';
  if (quotient >= 60) return '#f59e0b';
  return '#f97316';
}

function getStatusStyle(status: string) {
  switch (status) {
    case 'active':
      return 'bg-green-500/10 text-green-400 border-green-500/20';
    case 'inactive':
      return 'bg-gray-500/10 text-gray-600 dark:text-gray-400 border-gray-500/20';
    case 'development':
      return 'bg-amber-500/10 text-amber-400 border-amber-500/20';
    default:
      return 'bg-gray-500/10 text-gray-600 dark:text-gray-400 border-gray-500/20';
  }
}

function formatDate(dateStr: string) {
  const d = new Date(dateStr);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function formatTime(dateStr: string) {
  const d = new Date(dateStr);
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
}

function formatRelativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '—';
  const sec = Math.round((Date.now() - then) / 1000);
  const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });
  if (sec < 45) return rtf.format(-sec, 'second');
  const min = Math.round(sec / 60);
  if (min < 60) return rtf.format(-min, 'minute');
  const hr = Math.round(min / 60);
  if (hr < 36) return rtf.format(-hr, 'hour');
  const day = Math.round(hr / 24);
  if (day < 30) return rtf.format(-day, 'day');
  const month = Math.round(day / 30);
  if (month < 24) return rtf.format(-month, 'month');
  const year = Math.round(month / 12);
  return rtf.format(-year, 'year');
}

function shortAgentId(id: string, max = 10): string {
  if (!id) return '';
  return id.length <= max ? id : `${id.slice(0, max)}…`;
}

export default function AdminDashboard() {
  const { username, role } = useAuth();
  const location = useLocation();
  const isAdmin = role === 'admin' || role === 'super_admin';
  const activeTab: AdminTab = getTabFromPath(location.pathname);

  return (
    <LoadingProvider>
      <AdminLayout>
        {activeTab === 'overview' && <OverviewTab />}
        {activeTab === 'agents' && <AgentsTab />}
        {activeTab === 'sessions' && <SessionsTab />}
        {activeTab === 'costs' && <CostsTab />}
        {activeTab === 'usage' && <UsageTrackerTab />}
        {activeTab === 'agent-studio' && <WorkflowsTab />}
        {activeTab === 'knowledge-base' && <KnowledgeBaseTab />}
        {activeTab === 'review-queue' && isAdmin && <ReviewQueueTab />}
        {activeTab === 'settings' && <SettingsTab username={username} />}
        {activeTab === 'users' && isAdmin && <UserManagementTab />}
      </AdminLayout>
    </LoadingProvider>
  );
}

function OverviewTab() {
  const navigate = useNavigate();
  const { username } = useAuth();
  const [catalogData, setCatalogData] = useState<CatalogData | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [health, setHealth] = useState<any>(null);
  const [maintenanceEnabled, setMaintenanceEnabled] = useState(false);
  const [maintenanceMsg, setMaintenanceMsg] = useState("We're performing scheduled maintenance. Please check back shortly.");
  const [editingMsg, setEditingMsg] = useState(false);
  const [tempMsg, setTempMsg] = useState('');
  const [maintenanceLoading, setMaintenanceLoading] = useState(false);
  const { withLoader } = useLoading();

  useEffect(() => {
    const loadSessionsForOverview = async () => {
      const res = await fetch('/api/chat/sessions');
      if (!res.ok) throw new Error(`Failed to fetch sessions: ${res.status}`);

      const data = await res.json();
      if (Array.isArray(data)) {
        setSessions(data);
        return;
      }

      // Be tolerant of wrapped API responses to prevent UI crashes.
      if (data && Array.isArray(data.sessions)) {
        setSessions(data.sessions);
        return;
      }

      setSessions([]);
    };

    withLoader('Loading dashboard overview...', () =>
      Promise.all([
        getCatalog().then(setCatalogData).catch(() => {}),
        loadSessionsForOverview().catch(() => setSessions([])),
        fetch('/api/health').then(r => r.json()).then(setHealth).catch(() => {}),
        getMaintenanceStatus().then((data) => {
          setMaintenanceEnabled(data.enabled);
          setMaintenanceMsg(data.message);
        }).catch(() => {}),
      ])
    ).finally(() => setIsLoading(false));
  }, []);

  const handleMaintenanceToggle = async () => {
    setMaintenanceLoading(true);
    try {
      const result = await withLoader('Updating maintenance mode...', () => setMaintenanceMode(!maintenanceEnabled, maintenanceMsg));
      setMaintenanceEnabled(result.enabled);
    } catch (e) {}
    setMaintenanceLoading(false);
  };

  const handleMsgSave = async () => {
    setMaintenanceLoading(true);
    try {
      const result = await withLoader('Saving maintenance message...', () => setMaintenanceMode(maintenanceEnabled, tempMsg));
      setMaintenanceMsg(result.message);
      setEditingMsg(false);
    } catch (e) {}
    setMaintenanceLoading(false);
  };

  const activeCount = catalogData?.agents.filter(a => a.status === 'active').length || 0;
  const devCount = catalogData?.agents.filter(a => a.status === 'development').length || 0;
  const totalAgents = catalogData?.metadata.total_agents || 0;
  const avgAutonomy = catalogData?.agents.length
    ? Math.round(catalogData.agents.reduce((sum, a) => sum + (a.autonomy_quotient || 0), 0) / catalogData.agents.length)
    : 0;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full min-h-[400px]">
        <div className="text-center">
          <div className="relative w-14 h-14 mx-auto mb-4">
            <div className="absolute inset-0 rounded-full border-2 border-gray-200 dark:border-white/[0.06]" />
            <div className="absolute inset-0 rounded-full border-2 border-transparent border-t-primary-500 animate-spin" />
          </div>
          <p className="font-body text-sm text-zinc-500">Loading overview…</p>
        </div>
      </div>
    );
  }

  const hour = new Date().getHours();
  const greet =
    hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';

  const quickLinks: { label: string; path: string; icon: React.ReactNode; accent: string }[] = [
    { label: 'Agents', path: '/admin/agents', icon: <Bot className="w-4 h-4" />, accent: 'from-primary-500/20 to-transparent' },
    { label: 'Sessions', path: '/admin/sessions', icon: <MessageSquare className="w-4 h-4" />, accent: 'from-sky-500/20 to-transparent' },
    { label: 'Costs', path: '/admin/costs', icon: <DollarSign className="w-4 h-4" />, accent: 'from-emerald-500/20 to-transparent' },
    { label: 'Usage', path: '/admin/usage', icon: <Globe className="w-4 h-4" />, accent: 'from-violet-500/20 to-transparent' },
    { label: 'Studio', path: '/admin/agent-studio', icon: <Activity className="w-4 h-4" />, accent: 'from-amber-500/20 to-transparent' },
    { label: 'Knowledge', path: '/admin/knowledge-base', icon: <Database className="w-4 h-4" />, accent: 'from-cyan-500/20 to-transparent' },
  ];

  return (
    <div className="p-5 sm:p-8 lg:p-10 max-w-7xl mx-auto w-full">
      <header className="mb-8 lg:mb-10 flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="font-body text-xs font-medium uppercase tracking-[0.2em] text-zinc-500 mb-2">Control center</p>
          <h1 className="font-heading text-3xl sm:text-4xl font-semibold tracking-tight text-gray-900 dark:text-white">
            {greet}
            {username ? `, ${username}` : ''}
          </h1>
          <p className="font-body text-sm text-gray-600 dark:text-zinc-400 mt-2 max-w-xl leading-relaxed">
            Live snapshot of agents, sessions, and platform health. Jump to any area below.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => navigate('/chat')}
            className="inline-flex items-center gap-2 rounded-xl bg-primary-600 px-4 py-2.5 text-sm font-medium text-gray-900 dark:text-white shadow-lg shadow-primary-600/25 ring-1 ring-gray-200 dark:ring-white/10 transition hover:bg-primary-500"
          >
            <Zap className="w-4 h-4" />
            Open chat
          </button>
          <button
            type="button"
            onClick={() => navigate('/admin/agents')}
            className="inline-flex items-center gap-2 rounded-xl border border-gray-200 dark:border-white/[0.08] bg-gray-100 dark:bg-white/[0.04] px-4 py-2.5 text-sm font-medium text-gray-800 dark:text-zinc-200 backdrop-blur-sm transition hover:bg-gray-100 dark:hover:bg-white/[0.07] hover:text-gray-900 dark:hover:text-white"
          >
            <LayoutGrid className="w-4 h-4 text-gray-600 dark:text-zinc-400" />
            Manage agents
          </button>
        </div>
      </header>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4 mb-8">
        {[
          { label: 'Total agents', value: totalAgents, sub: 'Registered', icon: <Bot className="w-5 h-5" />, ring: 'ring-primary-500/20', iconBg: 'bg-primary-500/15 text-primary-300' },
          { label: 'Active', value: activeCount, sub: 'Production', icon: <Activity className="w-5 h-5" />, ring: 'ring-emerald-500/20', iconBg: 'bg-emerald-500/15 text-emerald-300' },
          { label: 'Sessions', value: sessions.length, sub: 'Chat threads', icon: <MessageSquare className="w-5 h-5" />, ring: 'ring-sky-500/20', iconBg: 'bg-sky-500/15 text-sky-300' },
          { label: 'Avg. autonomy', value: `${avgAutonomy}%`, sub: 'Quotient', icon: <Sparkles className="w-5 h-5" />, ring: 'ring-amber-500/20', iconBg: 'bg-amber-500/15 text-amber-300' },
        ].map((card) => (
          <div
            key={card.label}
            className={`group relative overflow-hidden rounded-2xl border border-gray-200 dark:border-white/[0.06] bg-white dark:bg-zinc-900/40 p-4 sm:p-5 backdrop-blur-sm ring-1 ${card.ring} transition hover:border-gray-300 dark:hover:border-white/[0.1] hover:bg-gray-100 dark:hover:bg-zinc-900/55`}
          >
            <div className={`mb-4 inline-flex rounded-xl p-2.5 ${card.iconBg}`}>{card.icon}</div>
            <p className="font-body text-[11px] font-medium uppercase tracking-wider text-zinc-500">{card.label}</p>
            <p className="font-heading mt-1 text-2xl sm:text-3xl font-semibold tabular-nums text-gray-900 dark:text-white tracking-tight">{card.value}</p>
            <p className="font-body mt-0.5 text-xs text-zinc-500">{card.sub}</p>
          </div>
        ))}
      </div>

      <div className="mb-8">
        <h2 className="font-heading text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-3">Shortcuts</h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 sm:gap-3">
          {quickLinks.map((q) => (
            <button
              key={q.path}
              type="button"
              onClick={() => navigate(q.path)}
              className={`group relative flex flex-col items-start gap-2 overflow-hidden rounded-2xl border border-gray-200 dark:border-white/[0.06] bg-gradient-to-br ${q.accent} bg-white dark:bg-zinc-900/30 p-3 sm:p-4 text-left backdrop-blur-sm transition hover:border-gray-300 dark:hover:border-white/[0.12] hover:bg-gray-100 dark:hover:bg-zinc-900/45`}
            >
              <span className="rounded-lg bg-gray-100 dark:bg-white/[0.06] p-2 text-gray-700 dark:text-zinc-300 ring-1 ring-gray-200 dark:ring-white/[0.06] group-hover:text-gray-900 dark:hover:text-white">{q.icon}</span>
              <span className="font-body text-sm font-medium text-gray-800 dark:text-zinc-200 group-hover:text-gray-900 dark:hover:text-white">{q.label}</span>
              <ExternalLink className="absolute right-2.5 top-2.5 h-3.5 w-3.5 text-zinc-600 opacity-0 transition group-hover:opacity-100" />
            </button>
          ))}
        </div>
      </div>

      <div className={`mb-8 rounded-2xl border p-5 sm:p-6 backdrop-blur-sm transition-all ${
        maintenanceEnabled
          ? 'border-amber-500/25 bg-gradient-to-br from-amber-500/[0.08] to-amber-50 dark:to-zinc-900/40 ring-1 ring-amber-500/15'
          : 'border-gray-200 dark:border-white/[0.06] bg-white dark:bg-zinc-900/35 ring-1 ring-gray-200 dark:ring-white/[0.04]'
      }`}>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3 sm:items-center">
            <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${maintenanceEnabled ? 'bg-amber-500/20 text-amber-300' : 'bg-gray-100 dark:bg-white/[0.06] text-zinc-500'}`}>
              <AlertTriangle className="h-5 w-5" />
            </div>
            <div>
              <h3 className="font-heading text-base font-semibold text-gray-900 dark:text-white">Maintenance mode</h3>
              <p className="font-body text-sm text-gray-600 dark:text-zinc-400 mt-0.5">
                {maintenanceEnabled ? 'User-facing pages are paused until you turn this off.' : 'Users can access the app normally.'}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={handleMaintenanceToggle}
            disabled={maintenanceLoading}
            className={`relative mx-auto sm:mx-0 inline-flex h-8 w-[3.25rem] shrink-0 items-center rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500/50 ${
              maintenanceEnabled ? 'bg-amber-500' : 'bg-zinc-700'
            } ${maintenanceLoading ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}`}
            aria-pressed={maintenanceEnabled}
          >
            <span
              className={`inline-block h-6 w-6 rounded-full bg-white shadow-md transition-transform duration-200 ${
                maintenanceEnabled ? 'translate-x-[1.35rem]' : 'translate-x-1'
              }`}
            />
          </button>
        </div>
        {maintenanceEnabled && (
          <div className="mt-5 border-t border-amber-500/15 pt-5">
            <div className="mb-2 flex items-center justify-between">
              <span className="font-body text-[11px] font-medium uppercase tracking-wider text-zinc-500">Message shown to users</span>
              {!editingMsg && (
                <button
                  type="button"
                  onClick={() => { setTempMsg(maintenanceMsg); setEditingMsg(true); }}
                  className="font-body text-xs text-primary-400 hover:text-primary-300 flex items-center gap-1"
                >
                  <Edit2 className="w-3 h-3" /> Edit
                </button>
              )}
            </div>
            {editingMsg ? (
              <div className="space-y-2">
                <textarea
                  value={tempMsg}
                  onChange={(e) => setTempMsg(e.target.value)}
                  rows={2}
                  className="w-full rounded-xl border border-gray-200 dark:border-white/[0.08] bg-white dark:bg-zinc-950/60 px-3 py-2.5 text-sm text-gray-800 dark:text-zinc-200 font-body placeholder:text-zinc-600 focus:border-primary-500/50 focus:outline-none focus:ring-1 focus:ring-primary-500/30 resize-none"
                />
                <div className="flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setEditingMsg(false)}
                    className="rounded-lg border border-gray-200 dark:border-white/[0.08] px-3 py-1.5 text-xs font-body text-gray-600 dark:text-zinc-400 transition hover:border-gray-300 dark:hover:border-white/[0.12] hover:text-gray-900 dark:hover:text-white"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={handleMsgSave}
                    disabled={maintenanceLoading}
                    className="rounded-lg bg-primary-600 px-3 py-1.5 text-xs font-body text-gray-900 dark:text-white transition hover:bg-primary-500 disabled:opacity-50"
                  >
                    Save
                  </button>
                </div>
              </div>
            ) : (
              <p className="font-body text-sm leading-relaxed text-gray-700 dark:text-zinc-300 rounded-xl border border-gray-200 dark:border-white/[0.06] bg-white dark:bg-zinc-950/40 px-4 py-3">{maintenanceMsg}</p>
            )}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2 lg:gap-6">
        <div className="rounded-2xl border border-gray-200 dark:border-white/[0.06] bg-white dark:bg-zinc-900/35 p-5 sm:p-6 backdrop-blur-sm ring-1 ring-gray-200 dark:ring-white/[0.04]">
          <div className="mb-5 flex items-center justify-between">
            <h3 className="font-heading text-sm font-semibold text-gray-900 dark:text-white flex items-center gap-2">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary-500/15 text-primary-300">
                <Bot className="w-4 h-4" />
              </span>
              Agent mix
            </h3>
          </div>
          <div className="space-y-4">
            {[
              { label: 'Active', count: activeCount, pct: totalAgents ? (activeCount / totalAgents) * 100 : 0, bar: 'bg-emerald-500', text: 'text-emerald-400' },
              { label: 'Development', count: devCount, pct: totalAgents ? (devCount / totalAgents) * 100 : 0, bar: 'bg-amber-500', text: 'text-amber-400' },
              { label: 'Inactive', count: totalAgents - activeCount - devCount, pct: totalAgents ? ((totalAgents - activeCount - devCount) / totalAgents) * 100 : 0, bar: 'bg-zinc-500', text: 'text-gray-600 dark:text-zinc-400' },
            ].map((row) => (
              <div key={row.label} className="flex items-center justify-between gap-3">
                <span className="font-body text-sm text-gray-600 dark:text-zinc-400 shrink-0">{row.label}</span>
                <div className="flex min-w-0 flex-1 items-center gap-3">
                  <div className="h-2 flex-1 max-w-[200px] overflow-hidden rounded-full bg-gray-100 dark:bg-zinc-800/80">
                    <div className={`h-full rounded-full ${row.bar} transition-all`} style={{ width: `${row.pct}%` }} />
                  </div>
                  <span className={`font-body text-xs font-semibold tabular-nums w-7 text-right ${row.text}`}>{row.count}</span>
                </div>
              </div>
            ))}
          </div>

          {catalogData && catalogData.categories.length > 0 && (
            <div className="mt-6 border-t border-gray-200 dark:border-white/[0.06] pt-5">
              <h4 className="font-body text-[11px] font-medium uppercase tracking-wider text-zinc-500 mb-3">Categories</h4>
              <div className="flex flex-wrap gap-2">
                {catalogData.categories.map((cat) => {
                  const count = catalogData.agents.filter((a) => a.category === cat.id).length;
                  return (
                    <span
                      key={cat.id}
                      className="rounded-lg border border-gray-200 dark:border-white/[0.06] bg-gray-100 dark:bg-white/[0.04] px-2.5 py-1 text-xs font-medium text-gray-700 dark:text-zinc-300"
                    >
                      {cat.name}{' '}
                      <span className="text-zinc-500">({count})</span>
                    </span>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        <div className="rounded-2xl border border-gray-200 dark:border-white/[0.06] bg-white dark:bg-zinc-900/35 p-5 sm:p-6 backdrop-blur-sm ring-1 ring-gray-200 dark:ring-white/[0.04]">
          <div className="mb-5 flex items-center justify-between">
            <h3 className="font-heading text-sm font-semibold text-gray-900 dark:text-white flex items-center gap-2">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-sky-500/15 text-sky-300">
                <Clock className="w-4 h-4" />
              </span>
              Recent sessions
            </h3>
            {sessions.length > 0 && (
              <button
                type="button"
                onClick={() => navigate('/admin/sessions')}
                className="font-body text-xs font-medium text-primary-400 hover:text-primary-300"
              >
                View all
              </button>
            )}
          </div>
          {sessions.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-gray-200 dark:border-white/[0.08] bg-white dark:bg-zinc-950/30 py-12 text-center">
              <MessageSquare className="mb-3 h-10 w-10 text-zinc-600" />
              <p className="font-body text-sm text-zinc-500">No sessions yet</p>
              <p className="font-body mt-1 text-xs text-zinc-600">Conversations will show up here.</p>
            </div>
          ) : (
            <div className="space-y-2">
              {sessions.slice(0, 5).map((session) => (
                <div
                  key={session.id}
                  className="flex items-center gap-3 rounded-xl border border-gray-200 dark:border-white/[0.05] bg-white dark:bg-zinc-950/25 p-3 transition hover:border-gray-300 dark:hover:border-white/[0.1] hover:bg-gray-100 dark:hover:bg-zinc-950/40"
                >
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gray-100 dark:bg-white/[0.05] text-zinc-500">
                    <MessageSquare className="h-4 w-4" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-body text-sm text-gray-800 dark:text-zinc-200">{session.title || 'Untitled session'}</p>
                    <p className="font-body text-xs text-zinc-500">
                      {formatDate(session.created_at)} · {formatTime(session.created_at)}
                    </p>
                  </div>
                </div>
              ))}
              {sessions.length > 5 && (
                <p className="pt-1 text-center font-body text-xs text-zinc-500">+{sessions.length - 5} more</p>
              )}
            </div>
          )}
        </div>
      </div>

      {health && (
        <div className="mt-6 rounded-2xl border border-gray-200 dark:border-white/[0.06] bg-white dark:bg-zinc-900/35 p-5 sm:p-6 backdrop-blur-sm ring-1 ring-gray-200 dark:ring-white/[0.04]">
          <h3 className="font-heading text-sm font-semibold text-gray-900 dark:text-white flex items-center gap-2 mb-5">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-300">
              <Activity className="w-4 h-4" />
            </span>
            System status
          </h3>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {[
              { k: 'API', v: (health.status || 'healthy') as string, highlight: true },
              { k: 'Catalog version', v: catalogData?.metadata.version || '—' },
              { k: 'Last catalog update', v: catalogData?.metadata.last_updated || '—' },
              { k: 'Categories', v: String(catalogData?.categories.length ?? 0) },
            ].map((cell) => (
              <div
                key={cell.k}
                className="rounded-xl border border-gray-200 dark:border-white/[0.05] bg-white dark:bg-zinc-950/30 p-3 sm:p-4"
              >
                <span className="font-body text-[10px] font-medium uppercase tracking-wider text-zinc-500">{cell.k}</span>
                <p
                  className={`font-body mt-1.5 text-sm font-medium ${
                    cell.highlight ? 'capitalize text-emerald-400' : 'text-gray-800 dark:text-zinc-200'
                  }`}
                >
                  {cell.v}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function AgentsTab() {
  const [catalogData, setCatalogData] = useState<CatalogData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [editingAgent, setEditingAgent] = useState<Agent | null>(null);
  const [isAddingNew, setIsAddingNew] = useState(false);
  const [expandedAgents, setExpandedAgents] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState('');
  const [filterCategory, setFilterCategory] = useState('all');
  const [curlInput, setCurlInput] = useState('');
  const [curlParseError, setCurlParseError] = useState<string | null>(null);
  const [externalConfigMode, setExternalConfigMode] = useState<'curl' | 'manual'>('curl');
  const { withLoader } = useLoading();

  const parseCurlCommand = (curl: string) => {
    setCurlParseError(null);
    if (!curl.trim()) return;

    try {
      const normalized = curl.replace(/\\\s*\n/g, ' ').replace(/\s+/g, ' ').trim();

      if (!normalized.toLowerCase().startsWith('curl')) {
        setCurlParseError('Input must start with "curl"');
        return;
      }

      let url = '';
      let method = 'POST';
      let payloadFormat: 'json' | 'form_data' = 'json';
      const headers: Record<string, string> = {};
      let bodyData = '';

      const contentTypeMatch = normalized.match(/(?:-H|--header)\s+["']Content-Type:\s*([^"']+)["']/i);
      if (contentTypeMatch && /multipart\/form-data|application\/x-www-form-urlencoded/i.test(contentTypeMatch[1])) {
        payloadFormat = 'form_data';
      }

      const urlMatch = normalized.match(/curl\s+(?:-[^"'\s]*\s+)*["']?(https?:\/\/[^\s"']+)["']?/) ||
                        normalized.match(/["'](https?:\/\/[^\s"']+)["']/);
      if (urlMatch) url = urlMatch[1];

      const methodMatch = normalized.match(/(?:-X|--request)\s+(\w+)/);
      if (methodMatch) method = methodMatch[1].toUpperCase();

      const headerRegex = /(?:-H|--header)\s+["']([^"']+)["']/g;
      let hMatch;
      while ((hMatch = headerRegex.exec(normalized)) !== null) {
        const colonIdx = hMatch[1].indexOf(':');
        if (colonIdx > 0) {
          const key = hMatch[1].substring(0, colonIdx).trim();
          const val = hMatch[1].substring(colonIdx + 1).trim();
          if (key.toLowerCase() !== 'content-type') {
            headers[key] = val;
          }
        }
      }

      const cookieRegex = /(?:-b|--cookie)\s+["']([^"']+)["']/g;
      let cMatch;
      while ((cMatch = cookieRegex.exec(normalized)) !== null) {
        headers['Cookie'] = cMatch[1];
      }

      const dataMatch = normalized.match(/(?:-d|--data|--data-raw|--data-binary)\s+'([^']+)'/) ||
                         normalized.match(/(?:-d|--data|--data-raw|--data-binary)\s+"([^"]+)"/);
      if (dataMatch) {
        bodyData = dataMatch[1];
      }

      const formFields: Record<string, any> = {};
      const formFieldRegex = /(?:-F|--form)\s+["']([^"']+)["']/g;
      let formMatch;
      while ((formMatch = formFieldRegex.exec(normalized)) !== null) {
        const separator = formMatch[1].indexOf('=');
        if (separator > 0) {
          const key = formMatch[1].substring(0, separator).trim();
          const value = formMatch[1].substring(separator + 1);
          const lower = key.toLowerCase();
          formFields[key] = lower.includes('prompt') || lower.includes('query') || lower.includes('message') || lower.includes('input') || lower.includes('question')
            ? '{{query}}'
            : lower.includes('session') ? '{{session_id}}' : value;
        }
      }
      if (Object.keys(formFields).length > 0) {
        payloadFormat = 'form_data';
        bodyData = JSON.stringify(formFields);
      }

      if (!url) {
        setCurlParseError('Could not extract URL from cURL command');
        return;
      }

      let payloadTemplate = '';
      if (bodyData) {
        try {
          let parsed: any;
          try {
            parsed = JSON.parse(bodyData);
          } catch {
            if (payloadFormat === 'form_data') {
              parsed = Object.fromEntries(new URLSearchParams(bodyData).entries());
            } else {
              throw new Error('Payload is not valid JSON');
            }
          }
          const templateObj: Record<string, any> = {};
          for (const [k, v] of Object.entries(parsed)) {
            if (typeof v === 'string') {
              const lower = k.toLowerCase();
              if (lower.includes('prompt') || lower.includes('query') || lower.includes('message') || lower.includes('input') || lower.includes('question')) {
                templateObj[k] = '{{query}}';
              } else if (lower.includes('session')) {
                templateObj[k] = '{{session_id}}';
              } else {
                templateObj[k] = v;
              }
            } else {
              templateObj[k] = v;
            }
          }
          payloadTemplate = JSON.stringify(templateObj, null, 2);
        } catch {
          payloadTemplate = bodyData;
        }
      }

      if (editingAgent) {
        setEditingAgent({
          ...editingAgent,
          external_api_url: url,
          external_method: method,
          external_payload_format: payloadFormat,
          external_headers: Object.keys(headers).length > 0 ? headers : undefined,
          external_payload_template: payloadTemplate || undefined,
        });
        setCurlParseError(null);
      }
    } catch (err: any) {
      setCurlParseError(`Failed to parse cURL: ${err.message}`);
    }
  };

  useEffect(() => {
    fetchCatalog();
  }, []);

  const fetchCatalog = async () => {
    try {
      setIsLoading(true);
      const data = await withLoader('Loading agent catalog...', () => getCatalog());
      setCatalogData(data);
      setError(null);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  };

  const saveCatalog = async (updatedData: CatalogData) => {
    try {
      await withLoader('Saving agent catalog...', () => updateCatalog(updatedData));
      setCatalogData(updatedData);
      setSuccessMessage('Catalog saved successfully!');
      setTimeout(() => setSuccessMessage(null), 3000);
      return true;
    } catch (err: any) {
      setError(err.message);
      return false;
    }
  };

  const handleAddAgent = () => {
    const newAgent: Agent = {
      id: `agent_${Date.now()}`,
      name: 'New Agent',
      type: 'AI Agent',
      category: 'general',
      status: 'active',
      admin_only: false,
      autonomy_quotient: 50,
      description: 'Description of the new agent',
      logo: '',
      version: '1.0.0',
      path: 'agents/New_Agent',
      capabilities: [],
      tools: [],
      llm_providers: [],
      usage: {
        entry_point: 'agent.py',
        class_name: 'NewAgent',
        api_endpoint: '/api/new-agent',
        example_prompts: []
      }
    };
    setEditingAgent(newAgent);
    setIsAddingNew(true);
  };

  const handleSaveAgent = async () => {
    if (!editingAgent || !catalogData) return;

    let updatedAgents: Agent[];
    if (isAddingNew) {
      updatedAgents = [...catalogData.agents, editingAgent];
    } else {
      updatedAgents = catalogData.agents.map(a =>
        a.id === editingAgent.id ? editingAgent : a
      );
    }

    const updatedData: CatalogData = {
      ...catalogData,
      agents: updatedAgents,
      metadata: {
        ...catalogData.metadata,
        total_agents: updatedAgents.length,
        last_updated: new Date().toISOString().split('T')[0],
      },
    };

    const success = await saveCatalog(updatedData);
    if (success) {
      setEditingAgent(null);
      setIsAddingNew(false);
    }
  };

  const toggleExpanded = (agentId: string) => {
    const newExpanded = new Set(expandedAgents);
    if (newExpanded.has(agentId)) {
      newExpanded.delete(agentId);
    } else {
      newExpanded.add(agentId);
    }
    setExpandedAgents(newExpanded);
  };

  const filteredAgents = catalogData?.agents.filter((agent) => {
    const matchesSearch = !searchQuery ||
      agent.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      agent.description.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesCategory = filterCategory === 'all' || agent.category === filterCategory;
    return matchesSearch && matchesCategory;
  }) || [];

  const agentStats = useMemo(() => {
    const agents = catalogData?.agents ?? [];
    return {
      total: agents.length,
      active: agents.filter((a) => a.status === 'active').length,
      development: agents.filter((a) => a.status === 'development').length,
    };
  }, [catalogData?.agents]);

  if (isLoading) {
    return (
      <div className="relative min-h-[420px] flex items-center justify-center overflow-hidden">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_80%_50%_at_50%_-20%,rgba(99,102,241,0.18),transparent)]" />
        <div className="relative text-center">
          <div className="relative w-14 h-14 mx-auto mb-4">
            <div className="absolute inset-0 rounded-2xl bg-primary-500/10 blur-xl animate-pulse" />
            <div className="relative w-14 h-14 rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900/80 flex items-center justify-center">
              <Loader2 className="w-7 h-7 text-primary-400 animate-spin" />
            </div>
          </div>
          <p className="font-body text-sm text-gray-600 dark:text-gray-400">Loading catalog…</p>
          <p className="font-body text-xs text-gray-600 mt-1">Fetching agents and metadata</p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative min-h-full">
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -top-32 left-1/2 h-[420px] w-[min(100%,720px)] -translate-x-1/2 rounded-full bg-primary-500/[0.07] blur-3xl" />
        <div className="absolute top-40 right-0 h-64 w-64 rounded-full bg-violet-600/[0.06] blur-3xl" />
        <div className="absolute bottom-0 left-0 h-48 w-48 rounded-full bg-cyan-500/[0.04] blur-3xl" />
      </div>

      <div className="relative z-10 mx-auto max-w-7xl px-5 py-8 lg:px-10 lg:py-10">
        <div className="mb-8 flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-3">
            <div className="inline-flex items-center gap-2 rounded-full border border-gray-200 dark:border-gray-800/80 bg-white dark:bg-gray-900/50 px-3 py-1 font-body text-[11px] font-medium uppercase tracking-widest text-gray-500 backdrop-blur-sm">
              <LayoutGrid className="h-3.5 w-3.5 text-primary-400" />
              Catalog
            </div>
            <h1 className="font-heading text-3xl font-bold tracking-tight text-gray-900 dark:text-white sm:text-4xl">
              Agents
            </h1>
            <p className="max-w-xl font-body text-sm leading-relaxed text-gray-600 dark:text-gray-400">
              Browse, filter, and configure every agent in your marketplace. Open an agent for the full experience or expand a card for technical details.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => fetchCatalog()}
              className="inline-flex items-center gap-2 rounded-2xl border border-gray-200 dark:border-gray-700/80 bg-white dark:bg-gray-900/60 px-4 py-2.5 font-body text-sm font-medium text-gray-700 dark:text-gray-300 backdrop-blur-sm transition-all hover:border-gray-300 dark:hover:border-gray-600 hover:bg-gray-100 dark:hover:bg-gray-800/80 hover:text-gray-900 dark:hover:text-white"
            >
              <RefreshCw className="h-4 w-4 text-gray-500" />
              Refresh
            </button>
            <button
              type="button"
              onClick={handleAddAgent}
              className="inline-flex items-center gap-2 rounded-2xl bg-gradient-to-r from-primary-600 to-primary-500 px-5 py-2.5 font-body text-sm font-semibold text-gray-900 dark:text-white shadow-lg shadow-primary-500/25 transition-all hover:from-primary-500 hover:to-primary-400 hover:shadow-primary-500/35"
            >
              <Plus className="h-4 w-4" />
              Add agent
            </button>
          </div>
        </div>

        <div className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:gap-4">
          {[
            { label: 'Total', value: agentStats.total, accent: 'from-slate-500/20 to-transparent', icon: Bot },
            { label: 'Active', value: agentStats.active, accent: 'from-emerald-500/15 to-transparent', icon: CheckCircle },
            { label: 'In development', value: agentStats.development, accent: 'from-amber-500/15 to-transparent', icon: Zap },
            { label: 'Showing', value: filteredAgents.length, accent: 'from-primary-500/15 to-transparent', icon: Sparkles },
          ].map(({ label, value, accent, icon: Icon }) => (
            <div
              key={label}
              className="group relative overflow-hidden rounded-2xl border border-gray-200 dark:border-gray-800/70 bg-white dark:bg-gray-900/40 p-4 backdrop-blur-sm transition-all hover:border-gray-300 dark:hover:border-gray-700/90"
            >
              <div className={`pointer-events-none absolute inset-0 bg-gradient-to-br ${accent} opacity-80`} />
              <div className="relative flex items-start justify-between gap-2">
                <div>
                  <p className="font-body text-[11px] font-medium uppercase tracking-wider text-gray-500">{label}</p>
                  <p className="mt-1 font-heading text-2xl font-bold tabular-nums text-gray-900 dark:text-white">{value}</p>
                </div>
                <div className="rounded-xl border border-gray-200 dark:border-gray-800/80 bg-white dark:bg-gray-950/50 p-2 text-gray-500 transition-colors group-hover:border-primary-500/20 group-hover:text-primary-400">
                  <Icon className="h-4 w-4" />
                </div>
              </div>
            </div>
          ))}
        </div>

        {successMessage && (
          <div className="mb-6 flex items-center gap-3 rounded-2xl border border-emerald-500/25 bg-emerald-500/[0.08] p-4 backdrop-blur-sm animate-fadeIn">
            <CheckCircle className="h-5 w-5 shrink-0 text-emerald-400" />
            <p className="font-body text-sm text-emerald-200">{successMessage}</p>
          </div>
        )}

        {error && (
          <div className="mb-6 flex items-center gap-3 rounded-2xl border border-red-500/25 bg-red-500/[0.08] p-4 backdrop-blur-sm animate-fadeIn">
            <AlertCircle className="h-5 w-5 shrink-0 text-red-400" />
            <p className="font-body text-sm text-red-200">{error}</p>
          </div>
        )}

        <div className="mb-8 rounded-2xl border border-gray-200 dark:border-gray-800/80 bg-white dark:bg-gray-900/35 p-2 backdrop-blur-md sm:p-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-stretch">
            <div className="relative min-h-[44px] flex-1">
              <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
              <input
                type="text"
                placeholder="Search by name or description…"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="h-full w-full rounded-xl border border-transparent bg-white dark:bg-gray-950/50 py-3 pl-11 pr-4 font-body text-sm text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-600 transition-all focus:border-primary-500/40 focus:outline-none focus:ring-2 focus:ring-primary-500/20"
              />
            </div>
            <div className="relative flex min-h-[44px] items-center sm:min-w-[200px]">
              <SlidersHorizontal className="pointer-events-none absolute left-4 top-1/2 z-[1] h-4 w-4 -translate-y-1/2 text-gray-500 sm:left-3" />
              <select
                value={filterCategory}
                onChange={(e) => setFilterCategory(e.target.value)}
                className="h-full w-full cursor-pointer appearance-none rounded-xl border border-transparent bg-white dark:bg-gray-950/50 py-3 pl-11 pr-10 font-body text-sm text-gray-800 dark:text-gray-200 transition-all focus:border-primary-500/40 focus:outline-none focus:ring-2 focus:ring-primary-500/20 sm:pl-10"
              >
                <option value="all">All categories</option>
                {catalogData?.categories.map((cat) => (
                  <option key={cat.id} value={cat.id}>
                    {cat.name}
                  </option>
                ))}
              </select>
              <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {filteredAgents.map((agent, index) => {
            const isExpanded = expandedAgents.has(agent.id);
            const autonomy = agent.autonomy_quotient || 0;
            const barColor = getAutonomyColor(autonomy);

            return (
              <div
                key={agent.id}
                className={`group/card animate-fadeIn overflow-hidden rounded-2xl border border-gray-200 dark:border-gray-800/70 bg-gradient-to-b from-white to-gray-50 dark:from-gray-900/90 dark:to-gray-950/95 shadow-xl shadow-black/5 dark:shadow-black/20 backdrop-blur-sm transition-all duration-300 hover:border-primary-500/25 hover:shadow-primary-500/[0.07] ${isExpanded ? 'xl:col-span-2' : ''}`}
                style={{ animationDelay: `${Math.min(index, 12) * 40}ms` }}
              >
                <div className="relative p-5 lg:p-6">
                  <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(105deg,transparent_40%,rgba(99,102,241,0.03)_100%)] opacity-0 transition-opacity duration-300 group-hover/card:opacity-100" />
                  <div className="relative flex flex-col gap-4 sm:flex-row sm:items-start">
                    <div className="flex shrink-0 items-start gap-4">
                      <div className="relative flex h-14 w-14 items-center justify-center overflow-hidden rounded-2xl border border-gray-200 dark:border-gray-700/50 bg-gradient-to-br from-gray-800 to-gray-900 shadow-inner">
                        {agent.logo && (agent.logo.startsWith('/') || agent.logo.startsWith('http')) ? (
                          <img src={agent.logo} alt="" className="h-9 w-9 object-contain" />
                        ) : (
                          <Bot className="h-7 w-7 text-gray-500" />
                        )}
                      </div>
                    </div>

                    <div className="min-w-0 flex-1">
                      <div className="mb-2 flex flex-wrap items-center gap-2">
                        <h3 className="font-heading text-lg font-semibold tracking-tight text-gray-900 dark:text-white">{agent.name}</h3>
                        <span className={`rounded-lg border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${getStatusStyle(agent.status)}`}>
                          {agent.status}
                        </span>
                        {agent.admin_only && (
                          <span className="inline-flex items-center gap-1 rounded-lg border border-purple-500/25 bg-purple-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-purple-300">
                            <Shield className="h-2.5 w-2.5" />
                            Admin
                          </span>
                        )}
                        {agent.external_api_url && (
                          <span className="inline-flex items-center gap-1 rounded-lg border border-sky-500/25 bg-sky-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-sky-300">
                            <ExternalLink className="h-2.5 w-2.5" />
                            External
                          </span>
                        )}
                        <span className="rounded-lg border border-gray-200 dark:border-gray-700/60 bg-white dark:bg-gray-950/40 px-2 py-0.5 font-mono text-[10px] font-medium text-gray-500">
                          v{agent.version}
                        </span>
                      </div>
                      <p className="mb-4 line-clamp-2 font-body text-sm leading-relaxed text-gray-600 dark:text-gray-400">{agent.description}</p>
                      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
                        <div>
                          <span className="font-body text-[10px] font-medium uppercase tracking-wider text-gray-600">Type</span>
                          <p className="font-body text-xs text-gray-700 dark:text-gray-300">{agent.type}</p>
                        </div>
                        <div>
                          <span className="font-body text-[10px] font-medium uppercase tracking-wider text-gray-600">Category</span>
                          <p className="font-body text-xs capitalize text-gray-700 dark:text-gray-300">{agent.category}</p>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="font-body text-[10px] font-medium uppercase tracking-wider text-gray-600">Autonomy</span>
                          <div className="flex items-center gap-2">
                            <div className="h-1.5 w-20 overflow-hidden rounded-full bg-gray-100 dark:bg-gray-800">
                              <div
                                className="h-full rounded-full transition-all duration-500"
                                style={{ width: `${autonomy}%`, backgroundColor: barColor }}
                              />
                            </div>
                            <span className="font-body text-xs font-semibold tabular-nums" style={{ color: barColor }}>
                              {autonomy}%
                            </span>
                          </div>
                        </div>
                        <div className="flex items-center gap-1.5 text-gray-500">
                          <Zap className="h-3.5 w-3.5" />
                          <span className="font-body text-xs text-gray-600 dark:text-gray-400">{agent.capabilities.length} capabilities</span>
                        </div>
                      </div>
                    </div>

                    <div className="flex shrink-0 items-center gap-0.5 self-end sm:flex-col sm:self-start sm:gap-1">
                      <Link
                        to={`/agent/${agent.id}`}
                        className="rounded-xl p-2.5 text-gray-500 transition-all hover:bg-primary-500/10 hover:text-primary-400"
                        title="Open in marketplace"
                      >
                        <ExternalLink className="h-4 w-4" />
                      </Link>
                      <button
                        type="button"
                        onClick={() => toggleExpanded(agent.id)}
                        className="rounded-xl p-2.5 text-gray-500 transition-all hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-white"
                        title={isExpanded ? 'Collapse' : 'Expand details'}
                      >
                        {isExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                      </button>
                      <button
                        type="button"
                        onClick={() => setEditingAgent(agent)}
                        className="rounded-xl p-2.5 text-gray-500 transition-all hover:bg-blue-500/10 hover:text-blue-400"
                        title="Edit"
                      >
                        <Edit2 className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                </div>

                {isExpanded && (
                  <div className="border-t border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-950/40 px-5 py-5 lg:px-6 lg:py-6 animate-fadeIn">
                    <div className="grid grid-cols-1 gap-8 md:grid-cols-2">
                      <div>
                        <div className="mb-3 flex items-center gap-2">
                          <div className="rounded-lg bg-primary-500/10 p-1.5">
                            <Zap className="h-3.5 w-3.5 text-primary-400" />
                          </div>
                          <h4 className="font-heading text-sm font-semibold text-gray-900 dark:text-white">Capabilities</h4>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {agent.capabilities.map((cap, idx) => (
                            <span
                              key={idx}
                              className="rounded-lg border border-gray-200 dark:border-gray-700/50 bg-white dark:bg-gray-900/60 px-2.5 py-1 font-body text-[11px] font-medium text-gray-700 dark:text-gray-300"
                            >
                              {cap}
                            </span>
                          ))}
                          {agent.capabilities.length === 0 && (
                            <span className="font-body text-xs italic text-gray-500">No capabilities defined</span>
                          )}
                        </div>
                      </div>
                      <div>
                        <div className="mb-3 flex items-center gap-2">
                          <div className="rounded-lg bg-blue-500/10 p-1.5">
                            <Settings className="h-3.5 w-3.5 text-blue-400" />
                          </div>
                          <h4 className="font-heading text-sm font-semibold text-gray-900 dark:text-white">Tools</h4>
                        </div>
                        <div className="space-y-2">
                          {agent.tools.map((tool, idx) => (
                            <div key={idx} className="rounded-xl border border-gray-200 dark:border-gray-800/80 bg-white dark:bg-gray-900/50 p-3">
                              <span className="font-body text-xs font-semibold text-gray-800 dark:text-gray-200">{tool.name}</span>
                              <p className="mt-1 font-body text-[11px] leading-relaxed text-gray-500">{tool.description}</p>
                            </div>
                          ))}
                          {agent.tools.length === 0 && (
                            <span className="font-body text-xs italic text-gray-500">No tools defined</span>
                          )}
                        </div>
                      </div>
                    </div>
                    {agent.usage && (
                      <div className="mt-6 border-t border-gray-200 dark:border-gray-800/50 pt-6">
                        <div className="mb-3 flex items-center gap-2">
                          <div className="rounded-lg bg-emerald-500/10 p-1.5">
                            <Settings className="h-3.5 w-3.5 text-emerald-400" />
                          </div>
                          <h4 className="font-heading text-sm font-semibold text-gray-900 dark:text-white">Runtime configuration</h4>
                        </div>
                        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                          <div className="rounded-xl border border-gray-200 dark:border-gray-800/80 bg-white dark:bg-gray-900/50 p-3">
                            <span className="font-body text-[10px] font-medium uppercase tracking-wider text-gray-500">Endpoint</span>
                            <p className="mt-1 break-all font-body text-xs font-mono text-gray-800 dark:text-gray-200">{agent.usage.api_endpoint}</p>
                          </div>
                          <div className="rounded-xl border border-gray-200 dark:border-gray-800/80 bg-white dark:bg-gray-900/50 p-3">
                            <span className="font-body text-[10px] font-medium uppercase tracking-wider text-gray-500">Entry point</span>
                            <p className="mt-1 font-body text-xs font-mono text-gray-800 dark:text-gray-200">{agent.usage.entry_point}</p>
                          </div>
                          <div className="rounded-xl border border-gray-200 dark:border-gray-800/80 bg-white dark:bg-gray-900/50 p-3">
                            <span className="font-body text-[10px] font-medium uppercase tracking-wider text-gray-500">Class</span>
                            <p className="mt-1 font-body text-xs font-mono text-gray-800 dark:text-gray-200">{agent.usage.class_name}</p>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {filteredAgents.length === 0 && (
          <div className="relative mt-4 overflow-hidden rounded-2xl border border-dashed border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900/30 py-20 text-center backdrop-blur-sm">
            <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(99,102,241,0.06),transparent_65%)]" />
            <div className="relative mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950/80">
              <Search className="h-7 w-7 text-gray-600" />
            </div>
            <p className="relative font-body text-base font-medium text-gray-700 dark:text-gray-300">No agents match your filters</p>
            <p className="relative mt-1 font-body text-sm text-gray-500">Try another search term or pick a different category</p>
            <button
              type="button"
              onClick={() => {
                setSearchQuery('');
                setFilterCategory('all');
              }}
              className="relative mt-6 inline-flex items-center rounded-xl border border-primary-500/30 bg-primary-500/10 px-4 py-2 font-body text-sm font-semibold text-primary-300 transition-all hover:bg-primary-500/20"
            >
              Clear filters
            </button>
          </div>
        )}
      </div>

      {editingAgent && (
        <div className="fixed inset-0 bg-gray-900/40 dark:bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4 overflow-y-auto">
          <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-2xl max-w-4xl w-full max-h-[90vh] overflow-y-auto shadow-2xl">
            <div className="sticky top-0 bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 p-5 lg:p-6 flex items-center justify-between z-10">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 bg-primary-500/10 rounded-lg flex items-center justify-center">
                  {isAddingNew ? <Plus className="w-4 h-4 text-primary-400" /> : <Edit2 className="w-4 h-4 text-primary-400" />}
                </div>
                <h2 className="font-heading text-xl font-bold text-gray-900 dark:text-white">
                  {isAddingNew ? 'Add New Agent' : 'Edit Agent'}
                </h2>
              </div>
              <button
                onClick={() => { setEditingAgent(null); setIsAddingNew(false); }}
                className="p-2 text-gray-500 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-all"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-5 lg:p-6 space-y-5">
              <div>
                <h3 className="font-heading text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3 flex items-center gap-2">
                  <Bot className="w-4 h-4 text-primary-400" />
                  Basic Information
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div>
                    <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">ID</label>
                    <input type="text" value={editingAgent.id} onChange={(e) => setEditingAgent({ ...editingAgent, id: e.target.value })} className="w-full px-3.5 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body placeholder-gray-400 dark:placeholder-gray-500 disabled:opacity-50" disabled={!isAddingNew} />
                  </div>
                  <div>
                    <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">Name</label>
                    <input type="text" value={editingAgent.name} onChange={(e) => setEditingAgent({ ...editingAgent, name: e.target.value })} className="w-full px-3.5 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body placeholder-gray-400 dark:placeholder-gray-500" />
                  </div>
                  <div>
                    <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">Type</label>
                    <input type="text" value={editingAgent.type} onChange={(e) => setEditingAgent({ ...editingAgent, type: e.target.value })} className="w-full px-3.5 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body placeholder-gray-400 dark:placeholder-gray-500" />
                  </div>
                  <div>
                    <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">Category</label>
                    <select value={editingAgent.category} onChange={(e) => setEditingAgent({ ...editingAgent, category: e.target.value })} className="w-full px-3.5 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body cursor-pointer">
                      {catalogData?.categories.map(cat => (
                        <option key={cat.id} value={cat.id}>{cat.name}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">Status</label>
                    <select value={editingAgent.status} onChange={(e) => setEditingAgent({ ...editingAgent, status: e.target.value })} className="w-full px-3.5 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body cursor-pointer">
                      <option value="active">Active</option>
                      <option value="inactive">Inactive</option>
                      <option value="development">Development</option>
                    </select>
                  </div>
                  <div>
                    <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">Autonomy Quotient</label>
                    <input type="number" min="0" max="100" value={editingAgent.autonomy_quotient} onChange={(e) => setEditingAgent({ ...editingAgent, autonomy_quotient: parseInt(e.target.value) })} className="w-full px-3.5 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body" />
                  </div>
                  <div>
                    <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">Logo</label>
                    <input type="text" value={editingAgent.logo} onChange={(e) => setEditingAgent({ ...editingAgent, logo: e.target.value })} className="w-full px-3.5 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body placeholder-gray-400 dark:placeholder-gray-500" placeholder="/images/logo.png" />
                  </div>
                  <div>
                    <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">Version</label>
                    <input type="text" value={editingAgent.version} onChange={(e) => setEditingAgent({ ...editingAgent, version: e.target.value })} className="w-full px-3.5 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body placeholder-gray-400 dark:placeholder-gray-500" />
                  </div>
                  <div>
                    <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">Path</label>
                    <input type="text" value={editingAgent.path} onChange={(e) => setEditingAgent({ ...editingAgent, path: e.target.value })} className="w-full px-3.5 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body placeholder-gray-400 dark:placeholder-gray-500" />
                  </div>
                  <div className="flex items-end pb-1">
                    <label className="flex items-center gap-2.5 cursor-pointer">
                      <input type="checkbox" checked={editingAgent.admin_only} onChange={(e) => setEditingAgent({ ...editingAgent, admin_only: e.target.checked })} className="w-4 h-4 rounded border-gray-600 bg-gray-100 dark:bg-gray-800 text-primary-500 focus:ring-primary-500/30" />
                      <span className="font-body text-sm text-gray-700 dark:text-gray-300">Admin Only</span>
                    </label>
                  </div>
                </div>
              </div>

              <div>
                <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">Description</label>
                <textarea value={editingAgent.description} onChange={(e) => setEditingAgent({ ...editingAgent, description: e.target.value })} rows={3} className="w-full px-3.5 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body placeholder-gray-400 dark:placeholder-gray-500 resize-none" />
              </div>

              <div>
                <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">Capabilities (comma-separated)</label>
                <textarea value={editingAgent.capabilities.join(', ')} onChange={(e) => setEditingAgent({ ...editingAgent, capabilities: e.target.value.split(',').map(s => s.trim()).filter(s => s) })} rows={3} className="w-full px-3.5 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body placeholder-gray-400 dark:placeholder-gray-500 resize-none" />
              </div>

              {/* Default Configuration Values (admin-set) */}
              {(() => {
                const cfgFields = getConfigFields(editingAgent);
                if (cfgFields.length === 0) return null;
                const dc = editingAgent.default_config || {};
                return (
                  <div className="border-t border-gray-200 dark:border-gray-800 pt-4 mt-2">
                    <div className="flex items-center gap-2 mb-1">
                      <Key className="w-4 h-4 text-amber-400" />
                      <h4 className="font-heading text-sm font-semibold text-gray-900 dark:text-white">Default Configuration</h4>
                      <span className="text-xs text-gray-500 font-body">(Pre-fill so users don't need to configure)</span>
                    </div>
                    <p className="text-[11px] text-gray-500 font-body mb-3">
                      Values set here will be used automatically. Users will only be asked to configure if you leave required fields empty.
                    </p>
                    <div className="space-y-2.5">
                      {cfgFields.map((field) => (
                        <div key={field.key}>
                          <label className="flex items-center gap-1.5 font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                            <code className="text-[11px] text-primary-400 bg-primary-900/20 px-1.5 py-0.5 rounded">{field.key}</code>
                            {field.required && <span className="text-[9px] text-red-400 font-bold">REQUIRED</span>}
                            {dc[field.key] && <CheckCircle className="w-3 h-3 text-green-400" />}
                          </label>
                          <p className="text-[10px] text-gray-500 mb-1">{field.description}</p>
                          <input
                            type={field.key.toLowerCase().includes('token') || field.key.toLowerCase().includes('key') || field.key.toLowerCase().includes('secret') || field.key.toLowerCase().includes('password') ? 'password' : 'text'}
                            value={dc[field.key] || ''}
                            onChange={(e) => {
                              const updated = { ...dc, [field.key]: e.target.value };
                              if (!e.target.value) delete updated[field.key];
                              setEditingAgent({
                                ...editingAgent,
                                default_config: Object.keys(updated).length > 0 ? updated : undefined,
                              });
                            }}
                            placeholder={
                              field.example || field.default ||
                                (field.key === 'ON_PREM_CLOUD_ACCESS_TOKEN'
                                  ? 'Enter ON_PREM_CLOUD_ACCESS_TOKEN'
                                  : `Enter ${field.key}`)
                            }
                            className="w-full px-3.5 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body font-mono placeholder-gray-400 dark:placeholder-gray-500"
                          />
                        </div>
                      ))}
                    </div>
                    {editingAgent.default_config && Object.keys(editingAgent.default_config).length > 0 && (
                      <div className="mt-3 flex justify-end">
                        <button
                          type="button"
                          onClick={() => setEditingAgent({ ...editingAgent, default_config: undefined })}
                          className="px-3 py-1.5 text-xs text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded-lg transition-all"
                        >
                          Clear All Defaults
                        </button>
                      </div>
                    )}
                  </div>
                );
              })()}

              <div className="border-t border-gray-200 dark:border-gray-800 pt-4 mt-2">
                <div className="flex items-center gap-2 mb-3">
                  <Globe className="w-4 h-4 text-blue-400" />
                  <h4 className="font-heading text-sm font-semibold text-gray-900 dark:text-white">External Agent Configuration</h4>
                  <span className="text-xs text-gray-500 font-body">(Optional — for agents hosted outside this platform)</span>
                </div>

                <div className="flex gap-1 mb-3 bg-gray-100 dark:bg-gray-800/50 rounded-lg p-1">
                  <button type="button" onClick={() => setExternalConfigMode('curl')} className={`flex-1 px-3 py-1.5 text-xs font-medium rounded-md transition-all ${externalConfigMode === 'curl' ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30' : 'text-gray-600 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'}`}>
                    Paste cURL
                  </button>
                  <button type="button" onClick={() => setExternalConfigMode('manual')} className={`flex-1 px-3 py-1.5 text-xs font-medium rounded-md transition-all ${externalConfigMode === 'manual' ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30' : 'text-gray-600 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'}`}>
                    Manual Config
                  </button>
                </div>

                {externalConfigMode === 'curl' && (
                  <div className="space-y-3">
                    <div>
                      <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">Paste cURL Command</label>
                      <textarea
                        value={curlInput}
                        onChange={(e) => setCurlInput(e.target.value)}
                        rows={6}
                        placeholder={`curl \\\n  -X POST \\\n  "https://api.example.com/agent/chat" \\\n  -b "session=YOUR_COOKIE" \\\n  -H "Content-Type: application/json" \\\n  -d '{"prompt": "Hello", "session_id": "uuid"}'`}
                        className="w-full px-3.5 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body font-mono placeholder-gray-400 dark:placeholder-gray-500 resize-none"
                      />
                      <div className="flex items-center gap-2 mt-2">
                        <button type="button" onClick={() => parseCurlCommand(curlInput)} className="px-4 py-1.5 bg-blue-600/20 text-blue-400 border border-blue-500/30 text-xs font-semibold rounded-lg hover:bg-blue-600/30 transition-all">
                          Parse cURL
                        </button>
                        {curlParseError && (
                          <span className="text-xs text-red-400 flex items-center gap-1">
                            <AlertCircle className="w-3 h-3" /> {curlParseError}
                          </span>
                        )}
                        {!curlParseError && editingAgent.external_api_url && curlInput && (
                          <span className="text-xs text-green-400 flex items-center gap-1">
                            <CheckCircle className="w-3 h-3" /> Parsed successfully
                          </span>
                        )}
                      </div>
                    </div>
                    {editingAgent.external_api_url && (
                      <div className="bg-gray-100 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-700/50 rounded-xl p-3 space-y-2">
                        <p className="text-xs text-gray-600 dark:text-gray-400 font-body font-semibold uppercase tracking-wider">Parsed Configuration</p>
                        <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-xs">
                          <span className="text-gray-500">Method:</span>
                          <span className="text-gray-900 dark:text-white font-mono">{editingAgent.external_method || 'POST'}</span>
                           <span className="text-gray-500">Body:</span>
                           <span className="text-gray-900 dark:text-white font-mono">{editingAgent.external_payload_format === 'form_data' ? 'Form data (multipart)' : 'JSON'}</span>
                          <span className="text-gray-500">URL:</span>
                          <span className="text-blue-400 font-mono truncate">{editingAgent.external_api_url}</span>
                          {editingAgent.external_headers && Object.keys(editingAgent.external_headers).length > 0 && (
                            <>
                              <span className="text-gray-500">Headers:</span>
                              <div className="space-y-0.5">
                                {Object.entries(editingAgent.external_headers).map(([k, v]) => (
                                  <div key={k} className="font-mono">
                                    <span className="text-gray-700 dark:text-gray-300">{k}:</span>{' '}
                                    <span className="text-gray-600 dark:text-gray-400">{v.length > 40 ? v.slice(0, 40) + '...' : v}</span>
                                  </div>
                                ))}
                              </div>
                            </>
                          )}
                          {editingAgent.external_payload_template && (
                            <>
                              <span className="text-gray-500">Payload:</span>
                              <pre className="text-gray-700 dark:text-gray-300 font-mono whitespace-pre-wrap text-[11px] max-h-24 overflow-auto">{editingAgent.external_payload_template}</pre>
                            </>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {externalConfigMode === 'manual' && (
                  <div className="space-y-3">
                    <div className="grid grid-cols-[100px_1fr] gap-3">
                      <div>
                        <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">Method</label>
                        <select value={editingAgent.external_method || 'POST'} onChange={(e) => setEditingAgent({ ...editingAgent, external_method: e.target.value })} className="w-full px-3 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body font-mono cursor-pointer">
                          <option value="POST">POST</option>
                          <option value="GET">GET</option>
                          <option value="PUT">PUT</option>
                        </select>
                      </div>
                      <div>
                        <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">External API URL</label>
                        <input type="text" value={editingAgent.external_api_url || ''} onChange={(e) => setEditingAgent({ ...editingAgent, external_api_url: e.target.value || undefined })} placeholder="https://api.example.com/agent/invoke" className="w-full px-3.5 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body placeholder-gray-400 dark:placeholder-gray-500" />
                      </div>
                    </div>
                     <div>
                       <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">Request Body Format</label>
                       <select
                         value={editingAgent.external_payload_format || 'json'}
                         onChange={(e) => setEditingAgent({ ...editingAgent, external_payload_format: e.target.value as 'json' | 'form_data' })}
                         className="w-full px-3 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body cursor-pointer"
                       >
                         <option value="json">JSON</option>
                         <option value="form_data">Form data (multipart/form-data)</option>
                       </select>
                       <p className="mt-1 text-xs text-gray-500 font-body">Form fields use the same JSON-shaped template, but are sent as multipart form fields.</p>
                     </div>
                    <div>
                      <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">Headers (JSON)</label>
                      <textarea value={editingAgent.external_headers ? JSON.stringify(editingAgent.external_headers, null, 2) : ''} onChange={(e) => { try { const h = e.target.value ? JSON.parse(e.target.value) : undefined; setEditingAgent({ ...editingAgent, external_headers: h }); } catch {} }} rows={3} placeholder={'{\n  "Authorization": "Bearer token",\n  "Cookie": "session=abc123"\n}'} className="w-full px-3.5 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body font-mono placeholder-gray-400 dark:placeholder-gray-500 resize-none" />
                    </div>
                    <div>
                       <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">{editingAgent.external_payload_format === 'form_data' ? 'Form Fields Template' : 'Payload JSON Template'}</label>
                      <textarea value={editingAgent.external_payload_template || ''} onChange={(e) => setEditingAgent({ ...editingAgent, external_payload_template: e.target.value || undefined })} rows={4} placeholder={'{\n  "message": "{{query}}",\n  "session": "{{session_id}}"\n}'} className="w-full px-3.5 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body font-mono placeholder-gray-400 dark:placeholder-gray-500 resize-none" />
                      <p className="mt-1 text-xs text-gray-500 font-body">Use <code className="text-blue-400">{"{{query}}"}</code> for user message and <code className="text-blue-400">{"{{session_id}}"}</code> for session ID.</p>
                    </div>
                  </div>
                )}

                {editingAgent.external_api_url && (
                  <div className="mt-3 flex justify-end">
                     <button type="button" onClick={() => { setEditingAgent({ ...editingAgent, external_api_url: undefined, external_payload_template: undefined, external_payload_format: undefined, external_headers: undefined, external_method: undefined }); setCurlInput(''); setCurlParseError(null); }} className="px-3 py-1.5 text-xs text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded-lg transition-all">
                      Clear External Config
                    </button>
                  </div>
                )}
              </div>
            </div>

            <div className="sticky bottom-0 bg-white dark:bg-gray-900 border-t border-gray-200 dark:border-gray-800 p-5 lg:p-6 flex justify-end gap-3">
              <button onClick={() => { setEditingAgent(null); setIsAddingNew(false); }} className="px-5 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300 text-sm font-medium rounded-xl hover:bg-gray-700 transition-all">
                Cancel
              </button>
              <button onClick={handleSaveAgent} className="flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-primary-600 to-primary-500 text-gray-900 dark:text-white text-sm font-semibold rounded-xl hover:from-primary-500 hover:to-primary-400 transition-all shadow-lg shadow-primary-500/20">
                <Save className="w-4 h-4" />
                Save Agent
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function SessionsTab() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedSession, setExpandedSession] = useState<string | null>(null);
  const [sessionMessages, setSessionMessages] = useState<any[]>([]);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const { withLoader } = useLoading();

  useEffect(() => {
    fetchSessions();
  }, []);

  const fetchSessions = async () => {
    try {
      setIsLoading(true);
      const data = await withLoader('Loading chat sessions...', async () => {
        const res = await fetch('/api/chat/sessions');
        if (!res.ok) throw new Error('Failed to fetch sessions');
        return res.json();
      });
      setSessions(data);
      setError(null);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  };

  const deleteSession = async (sessionId: string) => {
    if (!confirm('Are you sure you want to delete this session and all its messages?')) return;
    try {
      await withLoader('Deleting chat session...', async () => {
        const res = await fetch(`/api/chat/sessions/${sessionId}`, { method: 'DELETE' });
        if (!res.ok) throw new Error('Failed to delete session');
      });
      setSessions(prev => prev.filter(s => s.id !== sessionId));
      setSuccessMessage('Session deleted successfully');
      setTimeout(() => setSuccessMessage(null), 3000);
      if (expandedSession === sessionId) {
        setExpandedSession(null);
        setSessionMessages([]);
      }
    } catch (err: any) {
      setError(err.message);
    }
  };

  const viewMessages = async (sessionId: string) => {
    if (expandedSession === sessionId) {
      setExpandedSession(null);
      setSessionMessages([]);
      return;
    }
    try {
      setLoadingMessages(true);
      setExpandedSession(sessionId);
      const data = await withLoader('Loading session messages...', async () => {
        const res = await fetch(`/api/chat/sessions/${sessionId}/messages`);
        if (!res.ok) throw new Error('Failed to load messages');
        return res.json();
      });
      setSessionMessages(data);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoadingMessages(false);
    }
  };

  const filteredSessions = sessions.filter(s =>
    !searchQuery || (s.title || '').toLowerCase().includes(searchQuery.toLowerCase())
  );

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full min-h-[400px]">
        <div className="text-center">
          <div className="relative w-12 h-12 mx-auto mb-3">
            <div className="absolute inset-0 rounded-full border-2 border-gray-200 dark:border-gray-800"></div>
            <div className="absolute inset-0 rounded-full border-2 border-transparent border-t-primary-500 animate-spin"></div>
          </div>
          <p className="font-body text-sm text-gray-600 dark:text-gray-400">Loading sessions...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 lg:p-8 max-w-6xl">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
        <div>
          <h1 className="font-heading text-2xl font-bold text-gray-900 dark:text-white mb-1">Chat Sessions</h1>
          <p className="font-body text-sm text-gray-600 dark:text-gray-400">{sessions.length} total sessions</p>
        </div>
        <button
          onClick={fetchSessions}
          className="flex items-center gap-2 px-4 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300 text-sm font-medium rounded-xl hover:bg-gray-700 transition-all"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      {successMessage && (
        <div className="mb-4 bg-green-500/10 border border-green-500/20 rounded-xl p-4 flex items-center gap-3 animate-fadeIn">
          <CheckCircle className="w-5 h-5 text-green-400 shrink-0" />
          <p className="font-body text-sm text-green-300">{successMessage}</p>
        </div>
      )}

      {error && (
        <div className="mb-4 bg-red-500/10 border border-red-500/20 rounded-xl p-4 flex items-center gap-3 animate-fadeIn">
          <AlertCircle className="w-5 h-5 text-red-400 shrink-0" />
          <p className="font-body text-sm text-red-300">{error}</p>
          <button onClick={() => setError(null)} className="ml-auto text-red-400 hover:text-red-300"><X className="w-4 h-4" /></button>
        </div>
      )}

      {sessions.length > 0 && (
        <div className="relative mb-6">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
          <input
            type="text"
            placeholder="Search sessions..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-10 pr-4 py-2.5 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl text-sm text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 font-body focus:ring-2 focus:ring-primary-500/30 focus:border-primary-500/50 transition-all"
          />
        </div>
      )}

      {filteredSessions.length === 0 ? (
        <div className="text-center py-16">
          <div className="w-14 h-14 mx-auto mb-4 bg-gray-100 dark:bg-gray-800 rounded-xl flex items-center justify-center">
            <MessageSquare className="w-6 h-6 text-gray-500" />
          </div>
          <p className="font-body text-sm text-gray-600 dark:text-gray-400 mb-1">
            {sessions.length === 0 ? 'No chat sessions yet' : 'No matching sessions'}
          </p>
          <p className="font-body text-xs text-gray-500">
            {sessions.length === 0 ? 'Sessions from the Global Chat will appear here' : 'Try a different search term'}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {filteredSessions.map((session) => (
            <div key={session.id} className="bg-white dark:bg-gray-900/60 border border-gray-200 dark:border-gray-800/60 rounded-xl overflow-hidden hover:border-gray-300 dark:hover:border-gray-700/80 transition-all">
              <div className="p-4 flex items-center gap-4">
                <div className="w-10 h-10 shrink-0 bg-blue-500/10 rounded-xl flex items-center justify-center">
                  <MessageSquare className="w-5 h-5 text-blue-400" />
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="font-body text-sm font-semibold text-gray-900 dark:text-white truncate">{session.title || 'Untitled Session'}</h3>
                  <p className="font-body text-xs text-gray-500">{formatDate(session.created_at)} at {formatTime(session.created_at)}</p>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <button
                    onClick={() => viewMessages(session.id)}
                    className="p-2 text-gray-500 hover:text-blue-400 hover:bg-blue-500/10 rounded-lg transition-all"
                    title="View messages"
                  >
                    {expandedSession === session.id ? <ChevronUp className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                  <button
                    onClick={() => deleteSession(session.id)}
                    className="p-2 text-gray-500 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-all"
                    title="Delete session"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>

              {expandedSession === session.id && (
                <div className="border-t border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900/40 p-4 animate-fadeIn">
                  {loadingMessages ? (
                    <div className="flex items-center justify-center py-6">
                      <Loader2 className="w-5 h-5 text-gray-600 dark:text-gray-400 animate-spin" />
                    </div>
                  ) : sessionMessages.length === 0 ? (
                    <p className="font-body text-sm text-gray-500 text-center py-4">No messages in this session</p>
                  ) : (
                    <div className="space-y-3 max-h-96 overflow-y-auto">
                      {sessionMessages.map((msg: any, idx: number) => (
                        <div key={idx} className={`flex gap-3 ${msg.role === 'user' ? '' : ''}`}>
                          <div className={`w-7 h-7 shrink-0 rounded-lg flex items-center justify-center text-xs font-bold ${
                            msg.role === 'user' ? 'bg-primary-500/10 text-primary-400' : 'bg-blue-500/10 text-blue-400'
                          }`}>
                            {msg.role === 'user' ? <User className="w-3.5 h-3.5" /> : <Bot className="w-3.5 h-3.5" />}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1">
                              <span className="font-body text-xs font-semibold text-gray-700 dark:text-gray-300 capitalize">{msg.role}</span>
                              {msg.timestamp && <span className="font-body text-[10px] text-gray-600">{formatTime(msg.timestamp)}</span>}
                            </div>
                            <p className="font-body text-sm text-gray-600 dark:text-gray-400 whitespace-pre-wrap break-words line-clamp-6">{msg.content}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const COST_EVENT_HEX: Record<string, string> = {
  llm_call: '#60a5fa',
  perplexity_search: '#c084fc',
  web_search: '#4ade80',
  email_send: '#fbbf24',
};

function CostsTab() {
  const [costData, setCostData] = useState<CostSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [viewMode, setViewMode] = useState<'today' | 'all'>('all');
  const { withLoader } = useLoading();

  const fetchCosts = async () => {
    const token = localStorage.getItem('admin_token');
    if (!token) return;
    setLoading(true);
    setError('');
    try {
      const data = await withLoader('Loading cost analytics...', () => getCostSummary(token));
      setCostData(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load cost data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCosts();
  }, []);

  const formatCost = (cost: number) => `$${cost.toFixed(4)}`;
  const formatTokens = (tokens: number) =>
    tokens >= 1000000 ? `${(tokens / 1000000).toFixed(1)}M` : tokens >= 1000 ? `${(tokens / 1000).toFixed(1)}K` : tokens.toString();
  const eventTypeLabel = (t: string) => {
    const labels: Record<string, string> = {
      llm_call: 'LLM Calls',
      perplexity_search: 'Perplexity Search',
      web_search: 'Web Search',
      email_send: 'Email Sends',
    };
    return labels[t] || t;
  };
  const sortedTrendAsc = useMemo(() => {
    if (!costData?.daily_trend?.length) return [];
    return [...costData.daily_trend].sort((a, b) => a.date.localeCompare(b.date));
  }, [costData?.daily_trend]);

  const costTrendChartData = useMemo(() => {
    return sortedTrendAsc.map((day, i) => {
      const parts = day.date.split('-').map(Number);
      const y = parts[0] ?? 0;
      const m = parts[1] ?? 1;
      const d = parts[2] ?? 1;
      const dt = new Date(y, m - 1, d);
      const start = Math.max(0, i - 6);
      const slice = sortedTrendAsc.slice(start, i + 1);
      const ma7 = slice.reduce((s, x) => s + x.cost, 0) / slice.length;
      return {
        ...day,
        label: dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
        ma7: Math.round(ma7 * 1000000) / 1000000,
      };
    });
  }, [sortedTrendAsc]);

  const peakDayCost = useMemo(
    () => (costTrendChartData.length ? Math.max(...costTrendChartData.map((x) => x.cost), 0) : 0),
    [costTrendChartData],
  );

  const costWindowKpis = useMemo(() => {
    const dc = costTrendChartData;
    if (!dc.length) return { wow: null as number | null, avgDaily: 0 };
    const windowSum = dc.reduce((s, d) => s + d.cost, 0);
    const avgDaily = windowSum / dc.length;
    const last7 = dc.slice(-7);
    const prev7 = dc.slice(-14, -7);
    const last7Sum = last7.reduce((s, d) => s + d.cost, 0);
    const prev7Sum = prev7.reduce((s, d) => s + d.cost, 0);
    const wow =
      prev7.length >= 1 && prev7Sum > 0
        ? Math.round(((last7Sum - prev7Sum) / prev7Sum) * 1000) / 10
        : null;
    return { wow, avgDaily };
  }, [costTrendChartData]);

  const eventTypeBadgeClass = (t: string) => {
    const map: Record<string, string> = {
      llm_call: 'bg-sky-500/15 text-sky-200 ring-sky-500/30',
      perplexity_search: 'bg-violet-500/15 text-violet-200 ring-violet-500/30',
      web_search: 'bg-emerald-500/15 text-emerald-200 ring-emerald-500/30',
      email_send: 'bg-amber-500/15 text-amber-200 ring-amber-500/30',
    };
    return map[t] || 'bg-zinc-500/15 text-gray-700 dark:text-zinc-300 ring-zinc-500/25';
  };

  if (loading) {
    return (
      <div className="flex min-h-[40vh] flex-col items-center justify-center gap-4 p-8">
        <div className="relative flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-500/20 to-teal-600/10 ring-1 ring-emerald-500/25 shadow-lg shadow-emerald-500/10">
          <div className="absolute inset-0 rounded-2xl bg-[linear-gradient(rgba(255,255,255,.06)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,.06)_1px,transparent_1px)] bg-[size:8px_8px] opacity-60" />
          <Loader2 className="relative h-7 w-7 animate-spin text-emerald-400" />
        </div>
        <p className="text-sm font-medium text-gray-600 dark:text-zinc-400">Loading cost analytics…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 lg:p-8">
        <div className="flex max-w-2xl items-center gap-4 rounded-2xl border border-red-500/25 bg-red-500/10 p-5 ring-1 ring-red-500/10">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-red-500/20">
            <AlertCircle className="h-6 w-6 text-red-400" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="font-semibold text-red-200">Could not load cost data</p>
            <p className="mt-1 text-sm text-red-300/80">{error}</p>
          </div>
          <button
            type="button"
            onClick={fetchCosts}
            className="flex shrink-0 items-center gap-2 rounded-xl bg-gray-100 dark:bg-white/10 px-4 py-2.5 text-sm font-medium text-gray-900 dark:text-white ring-1 ring-white/15 transition-colors hover:bg-white/15"
          >
            <RefreshCw className="h-4 w-4" />
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!costData) return null;

  const stats = viewMode === 'today' ? costData.today : costData.totals;
  const byType = viewMode === 'today' ? costData.today_by_type : costData.by_type;
  const byAgent = viewMode === 'today' ? costData.today_by_agent : costData.by_agent;

  const typeChartData = [...byType]
    .sort((a, b) => b.cost - a.cost)
    .map((item) => ({
      name: eventTypeLabel(item.event_type),
      shortName: eventTypeLabel(item.event_type).length > 22 ? `${eventTypeLabel(item.event_type).slice(0, 20)}…` : eventTypeLabel(item.event_type),
      cost: item.cost,
      count: item.count,
      tokens: item.tokens,
      event_type: item.event_type,
      fill: COST_EVENT_HEX[item.event_type] || '#71717a',
    }));

  const agentChartData = [...byAgent]
    .sort((a, b) => b.cost - a.cost)
    .slice(0, 14)
    .map((a) => ({
      name: a.agent_name.length > 30 ? `${a.agent_name.slice(0, 28)}…` : a.agent_name,
      fullName: a.agent_name,
      cost: a.cost,
      count: a.count,
      tokens: a.tokens,
    }));

  const todaySharePct =
    viewMode === 'all' && costData.totals.total_cost > 0
      ? Math.round((costData.today.total_cost / costData.totals.total_cost) * 1000) / 10
      : null;

  return (
    <div className="relative mx-auto max-w-7xl space-y-8 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 -top-24 h-80 bg-[radial-gradient(ellipse_70%_60%_at_50%_0%,rgba(52,211,153,0.14),transparent_65%)]"
      />

      <div className="relative overflow-hidden rounded-3xl border border-white/[0.09] bg-white dark:bg-zinc-950/80 p-6 shadow-2xl shadow-black/40 backdrop-blur-xl ring-1 ring-gray-200 dark:ring-white/[0.06] sm:p-8">
        <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(255,255,255,.04)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,.04)_1px,transparent_1px)] bg-[size:48px_48px] opacity-50" />
        <div className="pointer-events-none absolute -right-24 -top-28 h-72 w-72 rounded-full bg-emerald-500/[0.12] blur-3xl" />
        <div className="pointer-events-none absolute -bottom-32 -left-20 h-64 w-64 rounded-full bg-cyan-500/[0.1] blur-3xl" />
        <div className="relative flex flex-col gap-8 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0 flex-1 space-y-4">
            <div className="inline-flex items-center gap-2 rounded-full border border-emerald-500/25 bg-emerald-500/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-emerald-300/95">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 shadow-[0_0_10px_rgba(52,211,153,0.8)]" />
              Finance
            </div>
            <div>
              <h2 className="font-heading text-3xl font-bold tracking-tight text-gray-900 dark:text-white sm:text-4xl">Cost analytics</h2>
              <p className="mt-3 max-w-2xl text-sm leading-relaxed text-gray-600 dark:text-zinc-400 sm:text-[15px]">
                Live view of LLM spend, search tools, and token volume. Toggle today vs all-time to compare run-rate against total burn.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {viewMode === 'all' && todaySharePct != null && (
                <span className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 dark:border-white/[0.08] bg-gray-100 dark:bg-white/[0.04] px-3 py-1.5 text-xs text-gray-700 dark:text-zinc-300 ring-1 ring-gray-200 dark:ring-white/[0.04]">
                  <span className="text-zinc-500">Today vs all-time</span>
                  <span className="font-semibold tabular-nums text-emerald-300">{todaySharePct}%</span>
                </span>
              )}
              {costWindowKpis.avgDaily > 0 && (
                <span className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 dark:border-white/[0.08] bg-gray-100 dark:bg-white/[0.04] px-3 py-1.5 text-xs text-gray-700 dark:text-zinc-300 ring-1 ring-gray-200 dark:ring-white/[0.04]">
                  <span className="text-zinc-500">Avg / day in chart</span>
                  <span className="font-semibold tabular-nums text-gray-900 dark:text-white">{formatCost(costWindowKpis.avgDaily)}</span>
                </span>
              )}
              {costWindowKpis.wow != null && (
                <span
                  className={`inline-flex items-center gap-1 rounded-full px-3 py-1.5 text-xs font-semibold ring-1 ${
                    costWindowKpis.wow >= 0
                      ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-200 ring-emerald-500/25'
                      : 'border-red-500/20 bg-red-500/10 text-red-200 ring-red-500/20'
                  }`}
                >
                  {costWindowKpis.wow >= 0 ? <TrendingUp className="h-3.5 w-3.5" /> : <TrendingDown className="h-3.5 w-3.5" />}
                  Last 7d vs prior: {costWindowKpis.wow >= 0 ? '+' : ''}
                  {costWindowKpis.wow}%
                </span>
              )}
            </div>
          </div>
          <div className="flex shrink-0 flex-col gap-3 sm:flex-row sm:items-center lg:flex-col lg:items-stretch xl:flex-row xl:items-center">
            <div className="inline-flex rounded-full border border-gray-200 dark:border-white/[0.08] bg-gray-900/30 dark:bg-black/40 p-1 ring-1 ring-white/[0.05]">
              <button
                type="button"
                onClick={() => setViewMode('today')}
                className={`rounded-full px-5 py-2.5 text-sm font-semibold transition-all ${
                  viewMode === 'today'
                    ? 'bg-gradient-to-b from-emerald-500/35 to-emerald-600/20 text-gray-900 dark:text-white shadow-lg shadow-emerald-500/15 ring-1 ring-emerald-400/30'
                    : 'text-zinc-500 hover:text-gray-800 dark:hover:text-zinc-200'
                }`}
              >
                Today
              </button>
              <button
                type="button"
                onClick={() => setViewMode('all')}
                className={`rounded-full px-5 py-2.5 text-sm font-semibold transition-all ${
                  viewMode === 'all'
                    ? 'bg-gradient-to-b from-emerald-500/35 to-emerald-600/20 text-gray-900 dark:text-white shadow-lg shadow-emerald-500/15 ring-1 ring-emerald-400/30'
                    : 'text-zinc-500 hover:text-gray-800 dark:hover:text-zinc-200'
                }`}
              >
                All time
              </button>
            </div>
            <button
              type="button"
              onClick={fetchCosts}
              className="inline-flex items-center justify-center gap-2 rounded-2xl border border-gray-200 dark:border-white/[0.1] bg-gray-100 dark:bg-white/[0.05] px-5 py-2.5 text-sm font-semibold text-gray-900 dark:text-zinc-100 shadow-sm transition-all hover:border-white/[0.14] hover:bg-gray-100 dark:hover:bg-white/[0.08] active:scale-[0.98]"
            >
              <RefreshCw className="h-4 w-4" />
              Refresh
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[
          {
            label: 'Estimated spend',
            value: formatCost(stats.total_cost),
            hint:
              viewMode === 'today'
                ? 'Charges attributed to the current UTC day.'
                : 'Cumulative estimated cost from tracked events.',
            icon: <DollarSign className="h-5 w-5 text-emerald-400" />,
            iconWrap: 'from-emerald-500/25 to-teal-600/10 ring-emerald-500/30',
            accent: 'from-emerald-500/80 to-teal-400',
          },
          {
            label: 'Billable events',
            value: stats.total_events.toLocaleString(),
            hint: 'LLM calls, searches, and other metered actions in this window.',
            icon: <Hash className="h-5 w-5 text-sky-400" />,
            iconWrap: 'from-sky-500/25 to-blue-600/10 ring-sky-500/30',
            accent: 'from-sky-500 to-blue-400',
          },
          {
            label: 'Tokens',
            value: formatTokens(stats.total_tokens),
            hint: 'Prompt + completion tokens associated with billed usage.',
            icon: <Sparkles className="h-5 w-5 text-violet-400" />,
            iconWrap: 'from-violet-500/25 to-fuchsia-600/10 ring-violet-500/30',
            accent: 'from-violet-500 to-fuchsia-400',
          },
          {
            label: 'Avg / event',
            value: stats.total_events > 0 ? formatCost(stats.total_cost / stats.total_events) : '$0.0000',
            hint: 'Mean estimated cost per event — useful for anomaly checks.',
            icon: <BarChart3 className="h-5 w-5 text-amber-400" />,
            iconWrap: 'from-amber-500/25 to-orange-600/10 ring-amber-500/30',
            accent: 'from-amber-500 to-orange-400',
          },
        ].map((card) => (
          <div
            key={card.label}
            className="group relative overflow-hidden rounded-2xl border border-white/[0.07] bg-white dark:bg-zinc-900/40 p-5 shadow-lg shadow-black/20 ring-1 ring-gray-200 dark:ring-white/[0.04] transition-all duration-300 hover:-translate-y-0.5 hover:border-white/[0.11] hover:shadow-xl hover:shadow-emerald-500/[0.04] backdrop-blur-sm"
          >
            <div
              className={`pointer-events-none absolute left-0 top-0 h-0.5 w-full bg-gradient-to-r ${card.accent} opacity-90`}
            />
            <div className="flex items-start gap-4">
              <div
                className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br ${card.iconWrap} ring-1 transition-transform duration-300 group-hover:scale-105`}
              >
                {card.icon}
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-zinc-500">{card.label}</p>
                <p className="mt-1.5 text-2xl font-bold tabular-nums tracking-tight text-gray-900 dark:text-white">{card.value}</p>
                <p className="mt-2 text-xs leading-relaxed text-zinc-500">{card.hint}</p>
              </div>
            </div>
          </div>
        ))}
      </div>

      {costTrendChartData.length > 0 && (
        <div className="overflow-hidden rounded-3xl border border-gray-200 dark:border-white/[0.08] bg-white dark:bg-zinc-950/70 shadow-2xl shadow-black/35 ring-1 ring-white/[0.05] backdrop-blur-md sm:p-1">
          <div className="relative p-5 sm:p-7">
            <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-emerald-500/[0.06] via-transparent to-cyan-500/[0.04]" />
            <div className="relative mb-5 flex flex-wrap items-end justify-between gap-4">
              <div className="flex items-start gap-4">
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-400/30 to-teal-600/20 ring-1 ring-emerald-400/25 shadow-lg shadow-emerald-500/10">
                  <TrendingUp className="h-6 w-6 text-emerald-200" />
                </div>
                <div>
                  <h3 className="text-xl font-semibold tracking-tight text-gray-900 dark:text-white">Daily spend trend</h3>
                  <p className="mt-1 max-w-xl text-xs leading-relaxed text-zinc-500 sm:text-[13px]">
                    Bars show estimated cost per day; the line is a 7-day moving average. Range{' '}
                    <span className="font-mono text-gray-600 dark:text-zinc-400">
                      {costTrendChartData[0]?.date} → {costTrendChartData[costTrendChartData.length - 1]?.date}
                    </span>
                    .
                  </p>
                </div>
              </div>
              {peakDayCost > 0 && (
                <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/[0.12] px-4 py-3 ring-1 ring-emerald-500/20">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-emerald-300/90">Peak day</p>
                  <p className="mt-0.5 text-lg font-bold tabular-nums text-emerald-50">{formatCost(peakDayCost)}</p>
                </div>
              )}
            </div>
            <div className="relative h-[min(340px,50vh)] w-full min-h-[240px] overflow-hidden rounded-2xl border border-gray-200 dark:border-white/[0.06] bg-gradient-to-b from-zinc-900/80 to-black/50 px-1 pt-4 pb-2 sm:px-3">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={costTrendChartData} margin={{ top: 8, right: 12, left: 4, bottom: 4 }}>
                  <defs>
                    <linearGradient id="costDailyBar" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#6ee7b7" stopOpacity={1} />
                      <stop offset="100%" stopColor="#059669" stopOpacity={0.85} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="4 8" stroke="rgba(255,255,255,0.05)" vertical={false} />
                  <XAxis
                    dataKey="label"
                    tick={{ fill: '#a1a1aa', fontSize: 10 }}
                    tickLine={false}
                    axisLine={{ stroke: 'rgba(255,255,255,0.1)' }}
                    interval="preserveStartEnd"
                    minTickGap={8}
                  />
                  <YAxis
                    tick={{ fill: '#a1a1aa', fontSize: 11 }}
                    tickLine={false}
                    axisLine={false}
                    width={52}
                    tickFormatter={(v) => `$${Number(v).toFixed(2)}`}
                  />
                  <Tooltip
                    cursor={{ fill: 'rgba(52, 211, 153, 0.07)' }}
                    contentStyle={{
                      backgroundColor: 'rgba(9, 9, 11, 0.94)',
                      border: '1px solid rgba(255, 255, 255, 0.12)',
                      borderRadius: '14px',
                      padding: '12px 14px',
                      boxShadow: '0 20px 50px rgba(0,0,0,0.65)',
                    }}
                    labelStyle={{ color: '#fafafa', fontWeight: 600, marginBottom: 6 }}
                    formatter={(value: number | undefined, name: string | undefined) => {
                      const v = value ?? 0;
                      const n = name ?? '';
                      if (n === '7-day avg cost') return [formatCost(v), n];
                      return [formatCost(v), 'Daily cost'];
                    }}
                    labelFormatter={(_, payload) => {
                      const row = payload?.[0]?.payload as { date?: string; label?: string } | undefined;
                      return row?.date ?? row?.label ?? '';
                    }}
                  />
                  <Legend
                    wrapperStyle={{ paddingTop: 14, fontSize: 12 }}
                    formatter={(value) => <span className="text-gray-600 dark:text-zinc-400">{value}</span>}
                  />
                  <Bar
                    name="Daily cost"
                    dataKey="cost"
                    fill="url(#costDailyBar)"
                    radius={[8, 8, 0, 0]}
                    maxBarSize={44}
                  />
                  <Line
                    type="monotone"
                    name="7-day avg cost"
                    dataKey="ma7"
                    stroke="#5eead4"
                    strokeWidth={2.5}
                    dot={false}
                    activeDot={{ r: 5, fill: '#5eead4', stroke: '#0f766e', strokeWidth: 1.5 }}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="group/card min-w-0 overflow-hidden rounded-3xl border border-white/[0.07] bg-white dark:bg-zinc-950/60 shadow-xl shadow-black/25 ring-1 ring-gray-200 dark:ring-white/[0.04] backdrop-blur-sm transition-shadow hover:shadow-emerald-500/[0.04]">
          <div className="h-1 bg-gradient-to-r from-emerald-500 via-teal-400 to-cyan-400 opacity-90" />
          <div className="p-5 sm:p-6">
            <div className="mb-5 flex items-start justify-between gap-3">
              <div>
                <h3 className="flex items-center gap-2.5 text-lg font-semibold tracking-tight text-gray-900 dark:text-white">
                  <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-500/15 ring-1 ring-emerald-500/25">
                    <BarChart3 className="h-5 w-5 text-emerald-400" />
                  </span>
                  Spend by event type
                </h3>
                <p className="mt-2 text-xs leading-relaxed text-zinc-500 sm:text-[13px]">
                  Where spend concentrates — LLM vs search vs other metered actions.
                </p>
              </div>
            </div>
          {typeChartData.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-gray-200 dark:border-white/10 bg-black/20 py-16 text-center">
              <DollarSign className="h-11 w-11 text-zinc-600" />
              <p className="text-sm text-zinc-500">No cost data for this window yet.</p>
            </div>
          ) : (
            <div className="h-[min(320px,50vh)] w-full min-h-[200px] rounded-2xl border border-gray-200 dark:border-white/[0.05] bg-black/25 px-1 py-2">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart layout="vertical" data={typeChartData} margin={{ top: 4, right: 16, left: 8, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="4 6" stroke="rgba(255,255,255,0.06)" horizontal={false} />
                  <XAxis
                    type="number"
                    tick={{ fill: '#a1a1aa', fontSize: 11 }}
                    tickFormatter={(v) => `$${Number(v).toFixed(2)}`}
                  />
                  <YAxis
                    type="category"
                    dataKey="shortName"
                    width={108}
                    tick={{ fill: '#d4d4d8', fontSize: 10 }}
                    tickLine={false}
                    axisLine={false}
                  />
                  <Tooltip
                    cursor={{ fill: 'rgba(52, 211, 153, 0.06)' }}
                    contentStyle={{
                      backgroundColor: 'rgba(24, 24, 27, 0.96)',
                      border: '1px solid rgba(255, 255, 255, 0.1)',
                      borderRadius: '10px',
                      padding: '10px 12px',
                      boxShadow: '0 16px 48px rgba(0,0,0,0.55)',
                    }}
                    formatter={(value: number | undefined, _n, item) => {
                      const v = value ?? 0;
                      const row = item?.payload as { count?: number; tokens?: number };
                      const parts = [`${row?.count ?? 0} events`];
                      if (row?.tokens) parts.push(`${formatTokens(row.tokens)} tokens`);
                      return [`${formatCost(v)} · ${parts.join(' · ')}`, 'Estimated cost'];
                    }}
                    labelFormatter={(_, payload) => (payload?.[0]?.payload as { name?: string })?.name ?? ''}
                  />
                  <Bar dataKey="cost" radius={[0, 6, 6, 0]} maxBarSize={28}>
                    {typeChartData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.fill} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
          </div>
        </div>

        <div className="group/card min-w-0 overflow-hidden rounded-3xl border border-white/[0.07] bg-white dark:bg-zinc-950/60 shadow-xl shadow-black/25 ring-1 ring-gray-200 dark:ring-white/[0.04] backdrop-blur-sm transition-shadow hover:shadow-teal-500/[0.04]">
          <div className="h-1 bg-gradient-to-r from-teal-500 via-emerald-400 to-sky-400 opacity-90" />
          <div className="p-5 sm:p-6">
            <div className="mb-5">
              <h3 className="flex items-center gap-2.5 text-lg font-semibold tracking-tight text-gray-900 dark:text-white">
                <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-teal-500/15 ring-1 ring-teal-500/25">
                  <Bot className="h-5 w-5 text-teal-400" />
                </span>
                Spend by agent
              </h3>
              <p className="mt-2 text-xs leading-relaxed text-zinc-500 sm:text-[13px]">
                Top agents by estimated cost in the selected window (up to 14).
              </p>
            </div>
          {agentChartData.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-gray-200 dark:border-white/10 bg-black/20 py-16 text-center">
              <Bot className="h-11 w-11 text-zinc-600" />
              <p className="text-sm text-zinc-500">No agent-level cost yet.</p>
            </div>
          ) : (
            <div className="h-[min(360px,55vh)] w-full min-h-[220px] rounded-2xl border border-gray-200 dark:border-white/[0.05] bg-black/25 px-1 py-2">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart layout="vertical" data={agentChartData} margin={{ top: 4, right: 12, left: 8, bottom: 4 }}>
                  <defs>
                    <linearGradient id="costAgentBar" x1="0" y1="0" x2="1" y2="0">
                      <stop offset="0%" stopColor="#0f766e" stopOpacity={0.9} />
                      <stop offset="100%" stopColor="#34d399" stopOpacity={1} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="4 6" stroke="rgba(255,255,255,0.06)" horizontal={false} />
                  <XAxis type="number" tick={{ fill: '#a1a1aa', fontSize: 11 }} tickFormatter={(v) => `$${Number(v).toFixed(2)}`} />
                  <YAxis
                    type="category"
                    dataKey="name"
                    width={124}
                    tick={{ fill: '#d4d4d8', fontSize: 10 }}
                    tickLine={false}
                    axisLine={false}
                  />
                  <Tooltip
                    cursor={{ fill: 'rgba(45, 212, 191, 0.06)' }}
                    contentStyle={{
                      backgroundColor: 'rgba(24, 24, 27, 0.96)',
                      border: '1px solid rgba(255, 255, 255, 0.1)',
                      borderRadius: '10px',
                      padding: '10px 12px',
                      boxShadow: '0 16px 48px rgba(0,0,0,0.55)',
                    }}
                    labelFormatter={(_, payload) =>
                      (payload?.[0]?.payload as { fullName?: string })?.fullName ?? 'Agent'
                    }
                    formatter={(value, _n, item) => {
                      const v = typeof value === 'number' ? value : Number(value) || 0;
                      const row = item?.payload as { count?: number; tokens?: number };
                      const tok = row?.tokens ? ` · ${formatTokens(row.tokens)} tok` : '';
                      return [`${formatCost(v)} · ${row?.count ?? 0} events${tok}`, 'Spend'];
                    }}
                  />
                  <Bar dataKey="cost" fill="url(#costAgentBar)" radius={[0, 6, 6, 0]} maxBarSize={26} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
          </div>
        </div>
      </div>

      <div className="overflow-hidden rounded-3xl border border-gray-200 dark:border-white/[0.08] bg-white dark:bg-zinc-950/70 shadow-2xl shadow-black/30 ring-1 ring-white/[0.05] backdrop-blur-md">
        <div className="relative border-b border-gray-200 dark:border-white/[0.06] bg-gradient-to-r from-zinc-900/80 via-zinc-950/50 to-zinc-900/80 px-5 py-5 sm:px-7">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h3 className="text-xl font-semibold tracking-tight text-gray-900 dark:text-white">Recent events</h3>
              <p className="mt-1 text-xs text-zinc-500 sm:text-[13px]">Latest 20 billable events across the platform.</p>
            </div>
            <span className="rounded-full border border-gray-200 dark:border-white/[0.08] bg-gray-100 dark:bg-white/[0.04] px-3 py-1 text-[11px] font-medium uppercase tracking-wide text-gray-600 dark:text-zinc-400 ring-1 ring-gray-200 dark:ring-white/[0.04]">
              Live feed
            </span>
          </div>
        </div>
        {costData.recent_events.length === 0 ? (
          <div className="px-5 py-16 text-center sm:px-7">
            <Activity className="mx-auto h-12 w-12 text-zinc-600 opacity-80" />
            <p className="mt-4 text-sm text-zinc-500">No events recorded yet. Usage will show up as agents run.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[680px] text-sm">
              <thead className="sticky top-0 z-10">
                <tr className="border-b border-gray-200 dark:border-white/[0.06] bg-white dark:bg-zinc-950/95 text-left text-[11px] font-semibold uppercase tracking-wider text-zinc-500 backdrop-blur-md">
                  <th className="px-5 py-3.5 sm:px-7">Time</th>
                  <th className="px-3 py-3.5">Type</th>
                  <th className="px-3 py-3.5">Agent</th>
                  <th className="px-3 py-3.5">Model</th>
                  <th className="px-3 py-3.5 text-right tabular-nums">Tokens</th>
                  <th className="px-5 py-3.5 text-right tabular-nums sm:pr-7">Cost</th>
                </tr>
              </thead>
              <tbody>
                {costData.recent_events.slice(0, 20).map((event, idx) => (
                  <tr
                    key={event.id}
                    className={`border-b border-gray-200 dark:border-white/[0.04] transition-colors hover:bg-gray-100 dark:hover:bg-white/[0.04] ${
                      idx % 2 === 0 ? 'bg-black/[0.12]' : 'bg-transparent'
                    }`}
                  >
                    <td className="whitespace-nowrap px-5 py-3.5 font-mono text-xs text-gray-600 dark:text-zinc-400 sm:px-7">
                      {event.created_at
                        ? new Date(event.created_at).toLocaleString('en-US', {
                            month: 'short',
                            day: 'numeric',
                            hour: '2-digit',
                            minute: '2-digit',
                          })
                        : '—'}
                    </td>
                    <td className="px-3 py-3.5">
                      <span
                        className={`inline-flex max-w-[160px] truncate rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${eventTypeBadgeClass(event.event_type)}`}
                        title={eventTypeLabel(event.event_type)}
                      >
                        {eventTypeLabel(event.event_type)}
                      </span>
                    </td>
                    <td className="max-w-[200px] truncate px-3 py-3.5 font-medium text-gray-800 dark:text-zinc-200" title={event.agent_name}>
                      {event.agent_name}
                    </td>
                    <td className="max-w-[160px] truncate px-3 py-3.5 font-mono text-[11px] text-zinc-500" title={event.model || ''}>
                      {event.model || '—'}
                    </td>
                    <td className="px-3 py-3.5 text-right tabular-nums text-gray-600 dark:text-zinc-400">
                      {event.total_tokens > 0 ? formatTokens(event.total_tokens) : '—'}
                    </td>
                    <td className="px-5 py-3.5 text-right sm:pr-7">
                      <span className="inline-block rounded-lg bg-emerald-500/10 px-2.5 py-1 font-semibold tabular-nums text-emerald-100 ring-1 ring-emerald-500/20">
                        {formatCost(event.estimated_cost)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function SettingsTab({ username }: { username: string | null }) {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showCurrentPassword, setShowCurrentPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const { withLoader } = useLoading();

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);

    if (!currentPassword || !newPassword) {
      setError('Please fill in all password fields');
      return;
    }
    if (newPassword.length < 6) {
      setError('New password must be at least 6 characters');
      return;
    }
    if (newPassword !== confirmPassword) {
      setError('New passwords do not match');
      return;
    }

    setIsSubmitting(true);
    try {
      await withLoader('Changing password...', async () => {
        const token = localStorage.getItem('admin_token');
        const res = await fetch('/api/admin/change-password', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            current_password: currentPassword,
            new_password: newPassword,
          }),
        });

        if (!res.ok) {
          const data = await res.json();
          throw new Error(data.detail || 'Password change failed');
        }
      });

      setSuccess('Password changed successfully!');
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
      setTimeout(() => setSuccess(null), 5000);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="p-6 lg:p-8 max-w-2xl">
      <div className="mb-8">
        <h1 className="font-heading text-2xl font-bold text-gray-900 dark:text-white mb-1">Settings</h1>
        <p className="font-body text-sm text-gray-600 dark:text-gray-400">Manage your admin account</p>
      </div>

      <div className="bg-white dark:bg-gray-900/60 border border-gray-200 dark:border-gray-800/60 rounded-xl p-5 mb-6">
        <div className="flex items-center gap-2 mb-4">
          <User className="w-4 h-4 text-primary-400" />
          <h3 className="font-heading text-sm font-semibold text-gray-900 dark:text-white">Profile</h3>
        </div>
        <div className="bg-gray-100 dark:bg-gray-800/50 rounded-lg p-4 border border-gray-200 dark:border-gray-700/30 flex items-center gap-4">
          <div className="w-12 h-12 bg-primary-500/10 rounded-xl flex items-center justify-center">
            <User className="w-6 h-6 text-primary-400" />
          </div>
          <div>
            <p className="font-body text-sm font-semibold text-gray-900 dark:text-white">{username || 'Admin'}</p>
            <p className="font-body text-xs text-gray-500">Administrator</p>
          </div>
        </div>
      </div>

      <div className="bg-white dark:bg-gray-900/60 border border-gray-200 dark:border-gray-800/60 rounded-xl p-5">
        <div className="flex items-center gap-2 mb-4">
          <Key className="w-4 h-4 text-amber-400" />
          <h3 className="font-heading text-sm font-semibold text-gray-900 dark:text-white">Change Password</h3>
        </div>

        {error && (
          <div className="mb-4 bg-red-500/10 border border-red-500/20 rounded-xl p-3.5 flex items-center gap-3 animate-fadeIn">
            <AlertCircle className="w-4 h-4 text-red-400 shrink-0" />
            <p className="font-body text-sm text-red-300">{error}</p>
          </div>
        )}

        {success && (
          <div className="mb-4 bg-green-500/10 border border-green-500/20 rounded-xl p-3.5 flex items-center gap-3 animate-fadeIn">
            <CheckCircle className="w-4 h-4 text-green-400 shrink-0" />
            <p className="font-body text-sm text-green-300">{success}</p>
          </div>
        )}

        <form onSubmit={handleChangePassword} className="space-y-4">
          <div>
            <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">Current Password</label>
            <div className="relative">
              <input
                type={showCurrentPassword ? 'text' : 'password'}
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                className="w-full px-4 py-2.5 pr-11 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-primary-500/30 focus:border-primary-500/50 transition-all"
                placeholder="Enter current password"
              />
              <button type="button" onClick={() => setShowCurrentPassword(!showCurrentPassword)} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition-colors">
                {showCurrentPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          <div>
            <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">New Password</label>
            <div className="relative">
              <input
                type={showNewPassword ? 'text' : 'password'}
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                className="w-full px-4 py-2.5 pr-11 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-primary-500/30 focus:border-primary-500/50 transition-all"
                placeholder="Enter new password (min 6 characters)"
              />
              <button type="button" onClick={() => setShowNewPassword(!showNewPassword)} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition-colors">
                {showNewPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          <div>
            <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">Confirm New Password</label>
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="w-full px-4 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-primary-500/30 focus:border-primary-500/50 transition-all"
              placeholder="Confirm new password"
            />
          </div>

          <button
            type="submit"
            disabled={isSubmitting}
            className="flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-primary-600 to-primary-500 text-gray-900 dark:text-white text-sm font-semibold rounded-xl hover:from-primary-500 hover:to-primary-400 transition-all shadow-lg shadow-primary-500/20 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isSubmitting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Changing...
              </>
            ) : (
              <>
                <Key className="w-4 h-4" />
                Change Password
              </>
            )}
          </button>
        </form>
      </div>
    </div>
  );
}

const USAGE_LOG_PAGE_SIZES = [25, 50, 100] as const;

function UsageTrackerTab() {
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [logs, setLogs] = useState<UsageLog[]>([]);
  const [logsTotal, setLogsTotal] = useState(0);
  const [logsPage, setLogsPage] = useState(0);
  const [logsPageSize, setLogsPageSize] = useState(25);
  const [loading, setLoading] = useState(true);
  const [logsLoading, setLogsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [agentFilter, setAgentFilter] = useState('');
  const [expandedLog, setExpandedLog] = useState<number | null>(null);
  const { withLoader } = useLoading();

  const getToken = () => localStorage.getItem('admin_token') || '';

  const loadUsageLogs = async (page: number, pageSize: number, agentFilterValue: string) => {
    const token = getToken();
    if (!token) return;
    try {
      setLogsLoading(true);
      setError(null);
      const agent = agentFilterValue.trim() || undefined;
      const label = agent ? 'Filtering usage logs…' : 'Loading usage logs…';
      const logsData = await withLoader(label, () =>
        getUsageLogs(token, pageSize, page * pageSize, agent)
      );
      setLogs(logsData.logs);
      setLogsTotal(logsData.total);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLogsLoading(false);
    }
  };

  const fetchData = async () => {
    const token = getToken();
    if (!token) {
      setLoading(false);
      return;
    }
    try {
      setLoading(true);
      setError(null);
      const agent = agentFilter.trim() || undefined;
      const [summaryData, logsData] = await withLoader('Loading usage data...', () =>
        Promise.all([
          getUsageSummary(token),
          getUsageLogs(token, logsPageSize, logsPage * logsPageSize, agent),
        ])
      );
      setSummary(summaryData);
      setLogs(logsData.logs);
      setLogsTotal(logsData.total);
    } catch (err: any) {
      setError(err.message || 'Failed to load usage data');
    } finally {
      setLoading(false);
    }
  };

  const applyActivityFilter = () => {
    setLogsPage(0);
    void loadUsageLogs(0, logsPageSize, agentFilter);
  };
  const clearActivityFilter = () => {
    setAgentFilter('');
    setLogsPage(0);
    void loadUsageLogs(0, logsPageSize, '');
  };

  const goToLogsPage = (nextPage: number) => {
    const maxPage = Math.max(0, Math.ceil(logsTotal / logsPageSize) - 1);
    const p = Math.max(0, Math.min(nextPage, maxPage));
    setLogsPage(p);
    void loadUsageLogs(p, logsPageSize, agentFilter);
  };

  const changeLogsPageSize = (nextSize: number) => {
    setLogsPageSize(nextSize);
    setLogsPage(0);
    void loadUsageLogs(0, nextSize, agentFilter);
  };

  useEffect(() => { fetchData(); }, []);

  const sortedDailyAsc = useMemo(() => {
    if (!summary?.daily_trend?.length) return [];
    return [...summary.daily_trend].sort((a, b) => a.date.localeCompare(b.date));
  }, [summary?.daily_trend]);

  const dailyChartData = useMemo(() => {
    return sortedDailyAsc.map((day, i) => {
      const parts = day.date.split('-').map(Number);
      const y = parts[0] ?? 0;
      const m = parts[1] ?? 1;
      const d = parts[2] ?? 1;
      const dt = new Date(y, m - 1, d);
      const start = Math.max(0, i - 6);
      const slice = sortedDailyAsc.slice(start, i + 1);
      const ma7 = Math.round((slice.reduce((s, x) => s + x.count, 0) / slice.length) * 10) / 10;
      return {
        ...day,
        label: dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
        ma7,
      };
    });
  }, [sortedDailyAsc]);

  const agentBars = useMemo(() => {
    if (!summary?.by_agent?.length) return [];
    const t = summary.total_requests || 1;
    return summary.by_agent.slice(0, 15).map((a) => {
      const full = a.agent_name;
      const name = full.length > 34 ? `${full.slice(0, 32)}…` : full;
      return {
        name,
        fullName: full,
        count: a.count,
        pct: Math.round((a.count / t) * 1000) / 10,
      };
    });
  }, [summary]);

  const kpis = useMemo(() => {
    if (!summary) {
      return {
        windowSum: 0,
        windowDays: 0,
        avgDaily: 0,
        wow: null as number | null,
        topCountry: null as { country: string; count: number } | null,
        topCountryPctOfTotal: 0,
        todayVsAvgPct: null as number | null,
        activeAgents: 0,
      };
    }
    const dc = dailyChartData;
    const windowSum = dc.reduce((s, d) => s + d.count, 0);
    const windowDays = dc.length || 1;
    const avgDaily = windowSum / windowDays;
    const last7 = dc.slice(-7);
    const prev7 = dc.slice(-14, -7);
    const last7Sum = last7.reduce((s, d) => s + d.count, 0);
    const prev7Sum = prev7.reduce((s, d) => s + d.count, 0);
    const wow =
      prev7.length >= 1 && prev7Sum > 0
        ? Math.round(((last7Sum - prev7Sum) / prev7Sum) * 1000) / 10
        : null;
    const topCountry = summary.by_country[0] ?? null;
    const topCountryPctOfTotal =
      topCountry && summary.total_requests > 0
        ? Math.round((topCountry.count / summary.total_requests) * 1000) / 10
        : 0;
    const todayVsAvgPct =
      summary.today_requests != null && avgDaily > 0
        ? Math.round(((summary.today_requests / avgDaily - 1) * 1000)) / 10
        : null;
    return {
      windowSum,
      windowDays,
      avgDaily,
      wow,
      topCountry,
      topCountryPctOfTotal,
      todayVsAvgPct,
      activeAgents: summary.by_agent.length,
    };
  }, [summary, dailyChartData]);

  const peakDaily = useMemo(
    () => (dailyChartData.length ? Math.max(...dailyChartData.map((x) => x.count), 0) : 0),
    [dailyChartData],
  );

  const activityInsights = useMemo(() => {
    const uniqueAgents = new Set(logs.map((l) => l.agent_name).filter(Boolean)).size;
    const latest = logs[0]?.created_at;
    return {
      uniqueAgents,
      latestRelative: latest ? formatRelativeTime(latest) : null,
    };
  }, [logs]);

  const logTotalPages = Math.max(1, Math.ceil(logsTotal / logsPageSize) || 1);
  const logRangeStart =
    logsTotal === 0 || logs.length === 0 ? 0 : logsPage * logsPageSize + 1;
  const logRangeEnd =
    logsTotal === 0 || logs.length === 0 ? 0 : logsPage * logsPageSize + logs.length;

  if (loading) {
    return (
      <div className="flex min-h-[40vh] flex-col items-center justify-center gap-4 p-8">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-orange-500/10 ring-1 ring-orange-500/20">
          <Loader2 className="h-7 w-7 animate-spin text-orange-400" />
        </div>
        <p className="text-sm text-zinc-500">Loading usage analytics…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 lg:p-8">
        <div className="flex max-w-2xl items-center gap-4 rounded-2xl border border-red-500/25 bg-red-500/10 p-5 ring-1 ring-red-500/10">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-red-500/20">
            <AlertCircle className="h-6 w-6 text-red-400" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="font-semibold text-red-200">Could not load usage data</p>
            <p className="mt-1 text-sm text-red-300/80">{error}</p>
          </div>
          <button
            type="button"
            onClick={fetchData}
            className="flex shrink-0 items-center gap-2 rounded-xl bg-gray-100 dark:bg-white/10 px-4 py-2.5 text-sm font-medium text-gray-900 dark:text-white ring-1 ring-white/15 transition-colors hover:bg-white/15"
          >
            <RefreshCw className="h-4 w-4" />
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!summary) {
    return (
      <div className="flex min-h-[40vh] flex-col items-center justify-center gap-4 p-8 text-center">
        <BarChart3 className="h-12 w-12 text-zinc-600" />
        <p className="max-w-sm text-sm text-zinc-500">No usage summary available. Sign in as an admin and refresh.</p>
        <button
          type="button"
          onClick={fetchData}
          className="flex items-center gap-2 rounded-xl bg-orange-500/20 px-4 py-2 text-sm font-medium text-orange-200 ring-1 ring-orange-500/30 hover:bg-orange-500/30"
        >
          <RefreshCw className="h-4 w-4" />
          Try again
        </button>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl space-y-8 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
      <div className="relative overflow-hidden rounded-2xl border border-gray-200 dark:border-white/[0.08] bg-gradient-to-br from-zinc-900/90 via-zinc-950/80 to-zinc-950 p-6 shadow-xl shadow-black/25 ring-1 ring-white/[0.05] sm:p-8">
        <div className="pointer-events-none absolute -right-20 -top-20 h-64 w-64 rounded-full bg-orange-500/10 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-24 -left-24 h-56 w-56 rounded-full bg-sky-500/10 blur-3xl" />
        <div className="relative flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-orange-400/90">Operations</p>
            <h2 className="mt-2 font-heading text-2xl font-bold tracking-tight text-gray-900 dark:text-white sm:text-3xl">Usage &amp; demand</h2>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-gray-600 dark:text-zinc-400">
              Volume, run-rate, and geographic mix for agent traffic. Use the trend and concentration metrics for capacity planning and product prioritization.
            </p>
          </div>
          <button
            type="button"
            onClick={fetchData}
            className="inline-flex shrink-0 items-center gap-2 rounded-xl bg-gray-100 dark:bg-white/[0.06] px-4 py-2.5 text-sm font-semibold text-gray-800 dark:text-zinc-200 ring-1 ring-gray-200 dark:ring-white/10 transition-colors hover:bg-white/[0.1]"
          >
            <RefreshCw className="h-4 w-4" />
            Refresh data
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-xl border border-gray-200 dark:border-white/[0.06] bg-white dark:bg-zinc-900/50 p-5 ring-1 ring-gray-200 dark:ring-white/[0.04]">
          <div className="flex items-start gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-500/15 ring-1 ring-blue-500/20">
              <Activity className="h-5 w-5 text-blue-400" />
            </div>
            <div className="min-w-0">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-zinc-500">Total volume</p>
              <p className="mt-1 text-2xl font-bold tabular-nums text-gray-900 dark:text-white">{summary.total_requests.toLocaleString()}</p>
              <p className="mt-2 text-xs leading-snug text-zinc-500">All-time logged agent invocations across the platform.</p>
            </div>
          </div>
        </div>
        <div className="rounded-xl border border-gray-200 dark:border-white/[0.06] bg-white dark:bg-zinc-900/50 p-5 ring-1 ring-gray-200 dark:ring-white/[0.04]">
          <div className="flex items-start gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-emerald-500/15 ring-1 ring-emerald-500/20">
              <Calendar className="h-5 w-5 text-emerald-400" />
            </div>
            <div className="min-w-0">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-zinc-500">Today</p>
              <p className="mt-1 text-2xl font-bold tabular-nums text-gray-900 dark:text-white">{summary.today_requests.toLocaleString()}</p>
              <p className="mt-2 text-xs leading-snug text-zinc-500">
                {kpis.todayVsAvgPct != null
                  ? `${kpis.todayVsAvgPct >= 0 ? '+' : ''}${kpis.todayVsAvgPct}% vs average daily in the chart window`
                  : 'Compared to the trailing daily average when history exists.'}
              </p>
            </div>
          </div>
        </div>
        <div className="rounded-xl border border-gray-200 dark:border-white/[0.06] bg-white dark:bg-zinc-900/50 p-5 ring-1 ring-gray-200 dark:ring-white/[0.04]">
          <div className="flex items-start gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-amber-500/15 ring-1 ring-amber-500/20">
              <Hash className="h-5 w-5 text-amber-400" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-zinc-500">Run rate</p>
              <p className="mt-1 text-2xl font-bold tabular-nums text-gray-900 dark:text-white">
                {kpis.windowDays > 0 ? (Math.round(kpis.avgDaily * 10) / 10).toLocaleString() : '—'}
                <span className="ml-1 text-sm font-medium text-zinc-500">/day</span>
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <p className="text-xs leading-snug text-zinc-500">
                  Mean over {kpis.windowDays} day{kpis.windowDays !== 1 ? 's' : ''} in view ({kpis.windowSum.toLocaleString()} in window).
                </p>
                {kpis.wow != null && (
                  <span
                    className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-semibold ring-1 ${
                      kpis.wow >= 0
                        ? 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/25'
                        : 'bg-red-500/10 text-red-300 ring-red-500/20'
                    }`}
                  >
                    {kpis.wow >= 0 ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
                    Last 7d vs prior 7d: {kpis.wow >= 0 ? '+' : ''}
                    {kpis.wow}%
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>
        <div className="rounded-xl border border-gray-200 dark:border-white/[0.06] bg-white dark:bg-zinc-900/50 p-5 ring-1 ring-gray-200 dark:ring-white/[0.04]">
          <div className="flex items-start gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-violet-500/15 ring-1 ring-violet-500/20">
              <Globe className="h-5 w-5 text-violet-400" />
            </div>
            <div className="min-w-0">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-zinc-500">Geographic mix</p>
              <p className="mt-1 text-2xl font-bold tabular-nums text-gray-900 dark:text-white">{summary.by_country.length}</p>
              <p className="mt-2 text-xs leading-snug text-zinc-500">
                {kpis.topCountry
                  ? `Top market: ${kpis.topCountry.country || 'Unknown'} · ${kpis.topCountryPctOfTotal}% of all requests`
                  : 'Country inferred from client IP; enrich data to compare regions.'}
              </p>
              <p className="mt-1 text-[11px] text-zinc-600">{kpis.activeAgents} agent{kpis.activeAgents !== 1 ? 's' : ''} with traffic</p>
            </div>
          </div>
        </div>
      </div>

      {dailyChartData.length > 0 && (
        <div className="rounded-xl border border-gray-200 dark:border-white/[0.08] bg-gradient-to-br from-zinc-900/90 via-zinc-900/70 to-zinc-950/90 p-5 shadow-xl shadow-black/30 ring-1 ring-white/[0.05] sm:p-6">
          <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-orange-500/25 to-amber-600/15 ring-1 ring-orange-500/25">
                <BarChart3 className="h-5 w-5 text-orange-400" />
              </div>
              <div>
                <h3 className="text-lg font-semibold tracking-tight text-gray-900 dark:text-white">Daily demand trend</h3>
                <p className="mt-0.5 max-w-xl text-xs leading-relaxed text-zinc-500">
                  Bars = raw daily volume. Line = 7-day moving average — use it to see sustained lift or dips without noise from single-day spikes (
                  {dailyChartData[0]?.date} → {dailyChartData[dailyChartData.length - 1]?.date}).
                </p>
              </div>
            </div>
            {peakDaily > 0 && (
              <div className="rounded-lg bg-orange-500/15 px-3 py-2 ring-1 ring-orange-500/25">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-orange-400/90">Peak day (in view)</p>
                <p className="text-sm font-bold tabular-nums text-orange-100">{peakDaily.toLocaleString()} requests</p>
              </div>
            )}
          </div>
          <div className="h-[min(340px,52vh)] w-full min-h-[240px] rounded-xl border border-gray-200 dark:border-white/[0.06] bg-black/30 px-1 pt-3 pb-2 sm:px-2">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={dailyChartData} margin={{ top: 8, right: 12, left: 4, bottom: 4 }}>
                <defs>
                  <linearGradient id="usageDailyBar" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#fb923c" stopOpacity={1} />
                    <stop offset="100%" stopColor="#c2410c" stopOpacity={0.92} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="4 6" stroke="rgba(255,255,255,0.06)" vertical={false} />
                <XAxis
                  dataKey="label"
                  tick={{ fill: '#a1a1aa', fontSize: 10 }}
                  tickLine={false}
                  axisLine={{ stroke: 'rgba(255,255,255,0.12)' }}
                  interval="preserveStartEnd"
                  minTickGap={8}
                />
                <YAxis
                  tick={{ fill: '#a1a1aa', fontSize: 11 }}
                  tickLine={false}
                  axisLine={false}
                  allowDecimals={false}
                  width={40}
                />
                <Tooltip
                  cursor={{ fill: 'rgba(251, 146, 60, 0.06)' }}
                  contentStyle={{
                    backgroundColor: 'rgba(24, 24, 27, 0.96)',
                    border: '1px solid rgba(255, 255, 255, 0.1)',
                    borderRadius: '10px',
                    padding: '10px 12px',
                    boxShadow: '0 16px 48px rgba(0,0,0,0.55)',
                  }}
                  labelStyle={{ color: '#fafafa', fontWeight: 600, marginBottom: 4 }}
                  formatter={(value: number | undefined, name: string | undefined) => {
                    const v = value ?? 0;
                    const n = name ?? '';
                    if (n === '7-day average') return [`${v.toLocaleString()} / day`, n];
                    return [`${v.toLocaleString()} requests`, 'Daily volume'];
                  }}
                  labelFormatter={(_, payload) => {
                    const row = payload?.[0]?.payload as { date?: string; label?: string } | undefined;
                    return row?.date ?? row?.label ?? '';
                  }}
                />
                <Legend
                  wrapperStyle={{ paddingTop: 12, fontSize: 12 }}
                  formatter={(value) => <span className="text-gray-600 dark:text-zinc-400">{value}</span>}
                />
                <Bar
                  name="Daily volume"
                  dataKey="count"
                  fill="url(#usageDailyBar)"
                  radius={[6, 6, 0, 0]}
                  maxBarSize={48}
                />
                <Line
                  type="monotone"
                  name="7-day average"
                  dataKey="ma7"
                  stroke="#38bdf8"
                  strokeWidth={2.25}
                  dot={false}
                  activeDot={{ r: 4, fill: '#38bdf8', stroke: '#0c4a6e', strokeWidth: 1 }}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {agentBars.length > 0 && (
          <div
            className={`min-w-0 rounded-xl border border-gray-200 dark:border-white/[0.06] bg-white dark:bg-zinc-900/40 p-5 ring-1 ring-gray-200 dark:ring-white/[0.04] sm:p-6 ${
              summary.by_ip.length === 0 ? 'lg:col-span-2' : ''
            }`}
          >
            <div className="mb-4">
              <h3 className="flex items-center gap-2 text-lg font-semibold tracking-tight text-gray-900 dark:text-white">
                <Bot className="h-5 w-5 shrink-0 text-orange-400" />
                Agent workload mix
              </h3>
              <p className="mt-1 text-xs leading-relaxed text-zinc-500">
                Each bar is volume and <span className="text-gray-600 dark:text-zinc-400">% of all requests</span> — useful for roadmap, SLAs, and cost focus on the busiest agents.
              </p>
            </div>
            <div className="h-[min(440px,65vh)] w-full min-h-[260px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart layout="vertical" data={agentBars} margin={{ top: 4, right: 20, left: 8, bottom: 4 }}>
                  <defs>
                    <linearGradient id="usageAgentBar" x1="0" y1="0" x2="1" y2="0">
                      <stop offset="0%" stopColor="#c2410c" stopOpacity={0.85} />
                      <stop offset="100%" stopColor="#fb923c" stopOpacity={1} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="4 6" stroke="rgba(255,255,255,0.06)" horizontal={false} />
                  <XAxis type="number" tick={{ fill: '#a1a1aa', fontSize: 11 }} allowDecimals={false} />
                  <YAxis
                    type="category"
                    dataKey="name"
                    width={118}
                    tick={{ fill: '#d4d4d8', fontSize: 10 }}
                    tickLine={false}
                    axisLine={false}
                  />
                  <Tooltip
                    cursor={{ fill: 'rgba(251, 146, 60, 0.06)' }}
                    contentStyle={{
                      backgroundColor: 'rgba(24, 24, 27, 0.96)',
                      border: '1px solid rgba(255, 255, 255, 0.1)',
                      borderRadius: '10px',
                      padding: '10px 12px',
                      boxShadow: '0 16px 48px rgba(0,0,0,0.55)',
                    }}
                    formatter={(value: number | undefined, _n, item) => {
                      const v = value ?? 0;
                      const pct = (item?.payload as { pct?: number })?.pct ?? 0;
                      return [`${v.toLocaleString()} requests · ${pct}% of all traffic`, 'Volume'];
                    }}
                    labelFormatter={(_, payload) => (payload?.[0]?.payload as { fullName?: string })?.fullName ?? ''}
                  />
                  <Bar dataKey="count" fill="url(#usageAgentBar)" radius={[0, 8, 8, 0]} barSize={16} name="Requests" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}

        {summary.by_ip.length > 0 &&
          (() => {
            const ipSlice = summary.by_ip.slice(0, 10);
            const maxInList = Math.max(...ipSlice.map((r) => r.count), 1);
            return (
              <div
                className={`relative min-w-0 overflow-hidden rounded-2xl border border-gray-200 dark:border-white/[0.07] bg-gradient-to-br from-white via-gray-50 to-gray-100 dark:from-zinc-900/95 dark:via-zinc-900/70 dark:to-zinc-950/95 p-5 shadow-lg shadow-black/25 ring-1 ring-white/[0.05] sm:p-6 ${
                  agentBars.length === 0 ? 'lg:col-span-2' : ''
                }`}
              >
                <div className="pointer-events-none absolute -right-16 -top-12 h-40 w-40 rounded-full bg-emerald-500/10 blur-3xl" />
                <div className="pointer-events-none absolute -bottom-16 -left-10 h-36 w-36 rounded-full bg-teal-500/5 blur-3xl" />
                <div className="relative mb-5 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="flex gap-3">
                    <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500/25 to-teal-600/15 ring-1 ring-emerald-500/25">
                      <Network className="h-5 w-5 text-emerald-400" />
                    </div>
                    <div>
                      <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-emerald-400/90">Sources</p>
                      <h3 className="mt-0.5 flex flex-wrap items-center gap-2 text-lg font-semibold tracking-tight text-gray-900 dark:text-white">
                        Heaviest client endpoints
                        <span className="rounded-md bg-gray-100 dark:bg-white/[0.06] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-gray-600 dark:text-zinc-400 ring-1 ring-gray-200 dark:ring-white/[0.08]">
                          Top {ipSlice.length}
                        </span>
                      </h3>
                      <p className="mt-1 max-w-xl text-xs leading-relaxed text-zinc-500">
                        Ranked by request volume. <span className="text-gray-600 dark:text-zinc-400">Platform share</span> is % of all logged
                        traffic; bar compares each row to the heaviest IP in this list.
                      </p>
                    </div>
                  </div>
                </div>
                <div className="relative max-h-[min(520px,58vh)] space-y-2.5 overflow-y-auto overflow-x-hidden pr-1">
                  {ipSlice.map((ip, i) => {
                    const share =
                      summary.total_requests > 0
                        ? Math.round((ip.count / summary.total_requests) * 1000) / 10
                        : 0;
                    const loc = [ip.city, ip.region, ip.country].filter(Boolean).join(' · ') || 'Location unknown';
                    const net = [ip.isp, ip.org].filter(Boolean).join(' · ') || '—';
                    const loadPct = Math.round((ip.count / maxInList) * 1000) / 10;
                    return (
                      <div
                        key={`${ip.ip_address}-${i}`}
                        className="group rounded-xl border border-gray-200 dark:border-white/[0.06] bg-black/30 p-3.5 ring-1 ring-white/[0.03] transition-all duration-200 hover:border-emerald-500/20 hover:bg-gray-100 dark:hover:bg-white/[0.04] hover:shadow-md hover:shadow-emerald-950/20 sm:p-4"
                      >
                        <div className="flex gap-3 sm:gap-4">
                          <div
                            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-zinc-800 to-zinc-900 text-xs font-bold tabular-nums text-emerald-400 ring-1 ring-gray-200 dark:ring-white/[0.08] sm:h-10 sm:w-10 sm:text-sm"
                            aria-hidden
                          >
                            {i + 1}
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                              <span className="break-all font-mono text-[13px] font-medium tracking-tight text-orange-200/95 sm:text-sm">
                                {ip.ip_address}
                              </span>
                              <span className="inline-flex items-center gap-1 rounded-md bg-emerald-500/12 px-1.5 py-0.5 text-[10px] font-semibold tabular-nums text-emerald-300/95 ring-1 ring-emerald-500/20">
                                {share}% total
                              </span>
                            </div>
                            <div className="mt-2 flex flex-wrap items-center gap-1.5">
                              <span className="inline-flex max-w-full items-center gap-1 rounded-md bg-gray-100 dark:bg-white/[0.04] px-2 py-0.5 text-[10px] text-gray-600 dark:text-zinc-400 ring-1 ring-gray-200 dark:ring-white/[0.06]">
                                <MapPin className="h-3 w-3 shrink-0 text-zinc-600" aria-hidden />
                                <span className="truncate">{loc}</span>
                              </span>
                              <span className="inline-flex max-w-full items-center gap-1 rounded-md bg-gray-50 dark:bg-white/[0.03] px-2 py-0.5 text-[10px] text-zinc-500 ring-1 ring-white/[0.05]">
                                <Monitor className="h-3 w-3 shrink-0 text-zinc-600" aria-hidden />
                                <span className="truncate" title={net}>
                                  {net}
                                </span>
                              </span>
                            </div>
                            <div className="mt-3">
                              <div className="mb-1 flex items-center justify-between text-[10px] text-zinc-600">
                                <span>Relative load</span>
                                <span className="tabular-nums text-zinc-500">{loadPct}% vs #1</span>
                              </div>
                              <div className="h-1.5 overflow-hidden rounded-full bg-gray-100 dark:bg-zinc-800/90 ring-1 ring-gray-200 dark:ring-white/[0.04]">
                                <div
                                  className="h-full rounded-full bg-gradient-to-r from-emerald-600/90 to-teal-400/85 transition-all duration-300"
                                  style={{ width: `${loadPct}%` }}
                                />
                              </div>
                            </div>
                          </div>
                          <div className="shrink-0 text-right">
                            <p className="text-[10px] font-medium uppercase tracking-wide text-zinc-600">Requests</p>
                            <p className="text-lg font-bold tabular-nums leading-tight text-gray-900 dark:text-white sm:text-xl">
                              {ip.count.toLocaleString()}
                            </p>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })()}

        {summary.by_country.length > 0 && (
          <div className="col-span-1 rounded-xl border border-gray-200 dark:border-white/[0.06] bg-white dark:bg-zinc-900/40 p-5 ring-1 ring-gray-200 dark:ring-white/[0.04] sm:p-6 lg:col-span-2">
            <div className="mb-4">
              <h3 className="flex items-center gap-2 text-lg font-semibold tracking-tight text-gray-900 dark:text-white">
                <MapPin className="h-5 w-5 shrink-0 text-sky-400" />
                World map · regional demand
              </h3>
              <p className="mt-1 text-xs leading-relaxed text-zinc-500">
                Countries are shaded by request volume (IP geolocation). Amber dots mark centroid of markets with traffic; hover a country for exact counts and share of all requests.
              </p>
            </div>
            <UsageWorldMap byCountry={summary.by_country} totalRequests={summary.total_requests} />
          </div>
        )}
      </div>

      <div className="relative overflow-hidden rounded-2xl border border-gray-200 dark:border-white/[0.07] bg-gradient-to-br from-white via-gray-50 to-gray-100 dark:from-zinc-900/95 dark:via-zinc-900/70 dark:to-zinc-950/95 p-5 shadow-lg shadow-black/25 ring-1 ring-white/[0.05] sm:p-6">
        <div className="pointer-events-none absolute -right-16 -top-12 h-40 w-40 rounded-full bg-orange-500/10 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-16 -left-10 h-36 w-36 rounded-full bg-sky-500/10 blur-3xl" />
        <div className="relative space-y-5">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="flex min-w-0 gap-3">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-orange-500/25 to-amber-600/15 ring-1 ring-orange-500/25">
                <History className="h-5 w-5 text-orange-400" aria-hidden />
              </div>
              <div className="min-w-0">
                <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-orange-400/90">Live trail</p>
                <h3 className="mt-0.5 text-lg font-semibold tracking-tight text-gray-900 dark:text-white sm:text-xl">Recent activity</h3>
                <p className="mt-1 max-w-2xl text-xs leading-relaxed text-zinc-500">
                  Newest invocations first: prompt preview, geography, and client details on expand. Filter uses the{' '}
                  <span className="text-gray-600 dark:text-zinc-400">exact catalog display name</span> (case-sensitive) to narrow support and audit investigations.
                </p>
              </div>
            </div>
            {logsTotal > 0 && (
              <div className="flex flex-wrap gap-2 lg:justify-end">
                <span className="inline-flex items-center gap-1.5 rounded-lg bg-gray-100 dark:bg-white/[0.06] px-2.5 py-1.5 text-[11px] font-medium tabular-nums text-gray-700 dark:text-zinc-300 ring-1 ring-gray-200 dark:ring-white/[0.08]">
                  <Activity className="h-3.5 w-3.5 shrink-0 text-orange-400/90" aria-hidden />
                  {logsTotal.toLocaleString()} total
                  <span className="text-zinc-600">
                    · page {logsPage + 1}/{logTotalPages}
                  </span>
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-lg bg-gray-100 dark:bg-white/[0.06] px-2.5 py-1.5 text-[11px] font-medium text-gray-700 dark:text-zinc-300 ring-1 ring-gray-200 dark:ring-white/[0.08]">
                  <Bot className="h-3.5 w-3.5 shrink-0 text-zinc-500" aria-hidden />
                  {activityInsights.uniqueAgents} agent{activityInsights.uniqueAgents !== 1 ? 's' : ''}
                </span>
                {activityInsights.latestRelative && (
                  <span
                    className="inline-flex items-center gap-1.5 rounded-lg bg-gray-100 dark:bg-white/[0.06] px-2.5 py-1.5 text-[11px] font-medium text-gray-600 dark:text-zinc-400 ring-1 ring-gray-200 dark:ring-white/[0.08]"
                    title="Timestamp of the newest row in this list"
                  >
                    <Clock className="h-3.5 w-3.5 shrink-0 text-sky-400/90" aria-hidden />
                    Latest {activityInsights.latestRelative}
                  </span>
                )}
                {agentFilter.trim() ? (
                  <span className="inline-flex items-center gap-1.5 rounded-lg bg-orange-500/15 px-2.5 py-1.5 text-[11px] font-semibold text-orange-200 ring-1 ring-orange-500/25">
                    Filter on
                  </span>
                ) : null}
              </div>
            )}
          </div>

          <div className="flex flex-col gap-3 border-t border-gray-200 dark:border-white/[0.06] pt-5 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-[11px] leading-relaxed text-zinc-600 sm:max-w-md">
              Press Enter in the field to apply. Clearing resets the filter and returns to page 1. Rows load in pages so the dashboard stays responsive.
            </p>
            <div className="flex w-full flex-col gap-2 sm:w-auto sm:min-w-[min(100%,420px)] sm:flex-row sm:items-center sm:justify-end">
              <div className="relative min-w-0 flex-1 sm:min-w-[240px] sm:flex-1 sm:max-w-md">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-600" aria-hidden />
                <input
                  type="text"
                  placeholder="Exact agent name…"
                  value={agentFilter}
                  onChange={(e) => setAgentFilter(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && applyActivityFilter()}
                  aria-label="Filter by exact agent name"
                  className="w-full rounded-xl border border-gray-200 dark:border-white/[0.08] bg-black/35 py-2.5 pl-9 pr-3 text-sm text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-zinc-600 ring-1 ring-gray-200 dark:ring-white/[0.04] transition-colors focus:border-orange-500/40 focus:outline-none focus:ring-2 focus:ring-orange-500/15"
                />
              </div>
              <div className="flex shrink-0 gap-2">
                <button
                  type="button"
                  onClick={applyActivityFilter}
                  disabled={logsLoading}
                  className="inline-flex flex-1 items-center justify-center gap-2 rounded-xl bg-orange-500/20 px-4 py-2.5 text-sm font-semibold text-orange-100 ring-1 ring-orange-500/30 transition-colors hover:bg-orange-500/30 disabled:cursor-not-allowed disabled:opacity-50 sm:flex-initial"
                >
                  {logsLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                  Apply
                </button>
                {agentFilter.trim() ? (
                  <button
                    type="button"
                    onClick={clearActivityFilter}
                    disabled={logsLoading}
                    className="inline-flex items-center justify-center rounded-xl bg-gray-100 dark:bg-white/[0.06] px-4 py-2.5 text-sm font-medium text-gray-700 dark:text-zinc-300 ring-1 ring-gray-200 dark:ring-white/10 transition-colors hover:bg-white/[0.1] disabled:opacity-50"
                  >
                    Clear
                  </button>
                ) : null}
              </div>
            </div>
          </div>

          <div className="space-y-4">
            {logs.length === 0 && !logsLoading ? (
              <div className="rounded-xl border border-dashed border-gray-200 dark:border-white/[0.1] bg-black/20 py-14 text-center ring-1 ring-gray-200 dark:ring-white/[0.04]">
                <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-gray-100 dark:bg-zinc-800/80 ring-1 ring-gray-200 dark:ring-white/[0.06]">
                  <History className="h-6 w-6 text-zinc-600" aria-hidden />
                </div>
                <p className="mt-4 text-sm font-medium text-gray-600 dark:text-zinc-400">No events in this view</p>
                <p className="mx-auto mt-1 max-w-sm px-4 text-xs leading-relaxed text-zinc-600">
                  {agentFilter.trim()
                    ? 'No rows matched that exact agent name. Check spelling and copy the name from the agent catalog.'
                    : 'Usage rows appear when end users invoke agents. Refresh above if you expect traffic already.'}
                </p>
              </div>
            ) : null}

            {logs.length > 0 ? (
              <div className="overflow-hidden rounded-xl border border-gray-200 dark:border-white/[0.06] ring-1 ring-gray-200 dark:ring-white/[0.04]">
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[640px] border-collapse text-left text-sm">
                    <thead>
                      <tr className="border-b border-gray-200 dark:border-white/[0.08] bg-black/30 text-[11px] font-semibold uppercase tracking-wide text-zinc-500">
                        <th className="w-10 px-2 py-3 sm:px-3" scope="col">
                          <span className="sr-only">Expand</span>
                        </th>
                        <th className="whitespace-nowrap px-2 py-3 sm:px-3" scope="col">
                          When
                        </th>
                        <th className="min-w-[140px] px-2 py-3 sm:px-3" scope="col">
                          Agent
                        </th>
                        <th className="hidden min-w-[200px] px-2 py-3 md:table-cell sm:px-3" scope="col">
                          Preview
                        </th>
                        <th className="hidden min-w-[120px] px-2 py-3 lg:table-cell sm:px-3" scope="col">
                          Location
                        </th>
                        <th className="hidden min-w-[110px] px-2 py-3 sm:table-cell sm:px-3" scope="col">
                          IP
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-200 dark:divide-white/[0.06]">
                      {logs.map((log) => {
                        const loc = [log.city, log.region].filter(Boolean).join(' · ') || null;
                        const when = new Date(log.created_at);
                        const abs = Number.isNaN(when.getTime()) ? '—' : when.toLocaleString();
                        const rel = formatRelativeTime(log.created_at);
                        const initial = ((log.agent_name?.trim() ?? '').charAt(0) || '?').toUpperCase();
                        const expanded = expandedLog === log.id;
                        return (
                          <Fragment key={log.id}>
                            <tr className="bg-black/20 transition-colors hover:bg-gray-100 dark:hover:bg-white/[0.04]">
                              <td className="align-middle px-2 py-2 sm:px-3">
                                <button
                                  type="button"
                                  onClick={() => setExpandedLog(expanded ? null : log.id)}
                                  className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-zinc-800 to-zinc-900 text-sm font-bold text-orange-300 ring-1 ring-gray-200 dark:ring-white/[0.08] transition-colors hover:ring-orange-500/30"
                                  aria-expanded={expanded}
                                  aria-label={expanded ? 'Collapse row details' : 'Expand row details'}
                                >
                                  {initial}
                                </button>
                              </td>
                              <td className="align-middle whitespace-nowrap px-2 py-2 sm:px-3">
                                <p className="text-xs font-semibold tabular-nums text-gray-800 dark:text-zinc-200" title={abs}>
                                  {rel}
                                </p>
                                <p className="text-[10px] tabular-nums text-zinc-600">{abs}</p>
                              </td>
                              <td className="align-middle px-2 py-2 sm:px-3">
                                <span className="inline-flex max-w-full rounded-md bg-orange-500/15 px-2 py-0.5 text-xs font-semibold text-orange-200 ring-1 ring-orange-500/25">
                                  <span className="truncate">{log.agent_name}</span>
                                </span>
                                {log.agent_id ? (
                                  <p
                                    className="mt-1 max-w-[200px] truncate font-mono text-[10px] text-zinc-500"
                                    title={log.agent_id}
                                  >
                                    id · {shortAgentId(log.agent_id, 12)}
                                  </p>
                                ) : null}
                                <p className="mt-1 line-clamp-2 text-xs leading-snug text-gray-600 dark:text-zinc-400 md:hidden">
                                  {log.query_preview?.trim() || (
                                    <span className="italic text-zinc-600">No prompt preview.</span>
                                  )}
                                </p>
                              </td>
                              <td className="hidden align-middle px-2 py-2 text-gray-600 dark:text-zinc-400 md:table-cell sm:px-3">
                                <p className="line-clamp-2 max-w-md text-xs leading-snug">
                                  {log.query_preview?.trim() || (
                                    <span className="italic text-zinc-600">No prompt preview.</span>
                                  )}
                                </p>
                              </td>
                              <td className="hidden align-middle px-2 py-2 lg:table-cell sm:px-3">
                                <div className="flex flex-col gap-1">
                                  {log.country ? (
                                    <span className="inline-flex max-w-[180px] items-center gap-1 truncate text-[11px] text-gray-600 dark:text-zinc-400">
                                      <Globe className="h-3 w-3 shrink-0 text-zinc-600" aria-hidden />
                                      {log.country}
                                    </span>
                                  ) : null}
                                  {loc ? (
                                    <span className="inline-flex max-w-[180px] items-center gap-1 truncate text-[11px] text-zinc-500">
                                      <MapPin className="h-3 w-3 shrink-0 text-zinc-600" aria-hidden />
                                      {loc}
                                    </span>
                                  ) : null}
                                  {!log.country && !loc ? (
                                    <span className="text-[11px] text-zinc-600">—</span>
                                  ) : null}
                                </div>
                              </td>
                              <td className="hidden align-middle px-2 py-2 sm:table-cell sm:px-3">
                                <span className="inline-flex max-w-[140px] items-center gap-1 truncate font-mono text-[11px] text-gray-600 dark:text-zinc-400">
                                  <Network className="h-3 w-3 shrink-0 text-zinc-600" aria-hidden />
                                  {log.ip_address || '—'}
                                </span>
                                <button
                                  type="button"
                                  onClick={() => setExpandedLog(expanded ? null : log.id)}
                                  className="mt-1 flex items-center gap-1 text-[10px] font-medium text-zinc-500 hover:text-gray-700 dark:hover:text-zinc-300"
                                  aria-expanded={expanded}
                                >
                                  {expanded ? (
                                    <>
                                      <ChevronUp className="h-3.5 w-3.5" aria-hidden />
                                      Less
                                    </>
                                  ) : (
                                    <>
                                      <ChevronDown className="h-3.5 w-3.5" aria-hidden />
                                      More
                                    </>
                                  )}
                                </button>
                              </td>
                            </tr>
                            {expanded ? (
                              <tr className="bg-black/35">
                                <td colSpan={6} className="border-t border-gray-200 dark:border-white/[0.06] px-3 py-4 sm:px-4">
                                  <div className="grid grid-cols-2 gap-3 text-xs md:grid-cols-4">
                                    <div>
                                      <span className="text-zinc-600">Agent id</span>
                                      <p className="mt-0.5 break-all font-mono text-gray-700 dark:text-zinc-300">{log.agent_id || '—'}</p>
                                    </div>
                                    <div>
                                      <span className="text-zinc-600">IP</span>
                                      <p className="mt-0.5 font-mono text-gray-700 dark:text-zinc-300">{log.ip_address}</p>
                                    </div>
                                    <div>
                                      <span className="text-zinc-600">City / region</span>
                                      <p className="mt-0.5 text-gray-700 dark:text-zinc-300">
                                        {[log.city, log.region].filter(Boolean).join(' · ') || '—'}
                                      </p>
                                    </div>
                                    <div>
                                      <span className="text-zinc-600">Country</span>
                                      <p className="mt-0.5 text-gray-700 dark:text-zinc-300">{log.country || '—'}</p>
                                    </div>
                                    <div>
                                      <span className="text-zinc-600">Coordinates</span>
                                      <p className="mt-0.5 font-mono text-gray-700 dark:text-zinc-300">
                                        {log.latitude != null && log.longitude != null
                                          ? `${log.latitude.toFixed(4)}, ${log.longitude.toFixed(4)}`
                                          : '—'}
                                      </p>
                                    </div>
                                    <div>
                                      <span className="text-zinc-600">Timezone</span>
                                      <p className="mt-0.5 text-gray-700 dark:text-zinc-300">{log.timezone || '—'}</p>
                                    </div>
                                    <div>
                                      <span className="text-zinc-600">ISP</span>
                                      <p className="mt-0.5 text-gray-700 dark:text-zinc-300">{log.isp || '—'}</p>
                                    </div>
                                    <div className="col-span-2 md:col-span-2">
                                      <span className="text-zinc-600">Organization</span>
                                      <p className="mt-0.5 text-gray-700 dark:text-zinc-300">{log.org || '—'}</p>
                                    </div>
                                    <div className="col-span-2 md:col-span-4">
                                      <span className="text-zinc-600">Full prompt preview</span>
                                      <p className="mt-0.5 whitespace-pre-wrap break-words text-gray-600 dark:text-zinc-400">
                                        {log.query_preview || '—'}
                                      </p>
                                    </div>
                                    <div className="col-span-2 md:col-span-4">
                                      <span className="text-zinc-600">Session</span>
                                      <p className="mt-0.5 break-all font-mono text-gray-700 dark:text-zinc-300">{log.session_id || '—'}</p>
                                    </div>
                                    <div className="col-span-2 md:col-span-4">
                                      <span className="text-zinc-600">User agent</span>
                                      <p className="mt-0.5 break-all text-gray-600 dark:text-zinc-400">{log.user_agent || '—'}</p>
                                    </div>
                                  </div>
                                </td>
                              </tr>
                            ) : null}
                          </Fragment>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : null}

            {logsTotal > 0 ? (
              <div className="flex flex-col gap-3 border-t border-gray-200 dark:border-white/[0.06] pt-4 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
                <p className="text-[11px] tabular-nums text-zinc-500">
                  Showing{' '}
                  <span className="font-medium text-gray-700 dark:text-zinc-300">
                    {logRangeStart.toLocaleString()}–{logRangeEnd.toLocaleString()}
                  </span>{' '}
                  of <span className="font-medium text-gray-700 dark:text-zinc-300">{logsTotal.toLocaleString()}</span>
                </p>
                <div className="flex flex-wrap items-center gap-2 sm:gap-3">
                  <label className="flex items-center gap-2 text-[11px] text-zinc-500">
                    <span className="shrink-0">Rows per page</span>
                    <select
                      value={logsPageSize}
                      onChange={(e) => changeLogsPageSize(Number(e.target.value))}
                      disabled={logsLoading}
                      className="rounded-lg border border-gray-200 dark:border-white/[0.1] bg-gray-900/30 dark:bg-black/40 py-1.5 pl-2 pr-8 text-xs font-medium text-gray-800 dark:text-zinc-200 ring-1 ring-white/[0.05] focus:border-orange-500/40 focus:outline-none focus:ring-2 focus:ring-orange-500/15 disabled:opacity-50"
                    >
                      {USAGE_LOG_PAGE_SIZES.map((n) => (
                        <option key={n} value={n}>
                          {n}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      onClick={() => goToLogsPage(logsPage - 1)}
                      disabled={logsLoading || logsPage <= 0}
                      className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-gray-100 dark:bg-white/[0.06] text-gray-700 dark:text-zinc-300 ring-1 ring-gray-200 dark:ring-white/10 transition-colors hover:bg-white/[0.1] disabled:cursor-not-allowed disabled:opacity-40"
                      aria-label="Previous page"
                    >
                      <ChevronLeft className="h-4 w-4" aria-hidden />
                    </button>
                    <button
                      type="button"
                      onClick={() => goToLogsPage(logsPage + 1)}
                      disabled={logsLoading || logsPage >= logTotalPages - 1}
                      className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-gray-100 dark:bg-white/[0.06] text-gray-700 dark:text-zinc-300 ring-1 ring-gray-200 dark:ring-white/10 transition-colors hover:bg-white/[0.1] disabled:cursor-not-allowed disabled:opacity-40"
                      aria-label="Next page"
                    >
                      <ChevronRight className="h-4 w-4" aria-hidden />
                    </button>
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
