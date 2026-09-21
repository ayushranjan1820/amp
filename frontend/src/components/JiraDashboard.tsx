import { useState, Component, type ReactNode } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell,
  PieChart, Pie, Legend, Line, Area, AreaChart,
  ResponsiveContainer,
} from 'recharts';
import {
  BarChart3, PieChart as PieChartIcon, TrendingDown, Activity,
  Users, AlertTriangle, CheckCircle2, Clock, ChevronDown, ChevronRight,
} from 'lucide-react';

class ChartErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean }> {
  constructor(props: any) {
    super(props);
    this.state = { hasError: false };
  }
  static getDerivedStateFromError() {
    return { hasError: true };
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="flex items-center justify-center py-8 text-gray-500 text-xs">
          <BarChart3 className="w-4 h-4 mr-2 opacity-40" />
          Chart unavailable
        </div>
      );
    }
    return this.props.children;
  }
}

export interface JiraChartData {
  status_distribution: { name: string; value: number }[];
  priority_distribution: { name: string; value: number }[];
  type_distribution: { name: string; value: number }[];
  assignee_distribution: { name: string; value: number }[];
  creation_trend: { date: string; count: number }[];
  burndown_data: { date: string; remaining: number; ideal: number }[];
  summary: {
    total: number;
    open: number;
    in_progress: number;
    done: number;
    unassigned: number;
  };
}

const STATUS_COLORS: Record<string, string> = {
  'To Do': '#6366f1',
  'Open': '#6366f1',
  'Backlog': '#94a3b8',
  'In Progress': '#f59e0b',
  'In Review': '#f97316',
  'Done': '#22c55e',
  'Closed': '#16a34a',
  'Resolved': '#10b981',
};

const PRIORITY_COLORS: Record<string, string> = {
  'Highest': '#ef4444',
  'High': '#f97316',
  'Medium': '#f59e0b',
  'Low': '#3b82f6',
  'Lowest': '#94a3b8',
};

const PIE_COLORS = ['#f97316', '#6366f1', '#22c55e', '#f59e0b', '#3b82f6', '#ec4899', '#8b5cf6', '#14b8a6', '#ef4444', '#64748b'];

function SummaryCards({ summary }: { summary: JiraChartData['summary'] }) {
  const cards = [
    { label: 'Total Issues', value: summary.total, icon: Activity, color: 'text-blue-500', bg: 'bg-blue-500/10' },
    { label: 'Open', value: summary.open, icon: AlertTriangle, color: 'text-indigo-500', bg: 'bg-indigo-500/10' },
    { label: 'In Progress', value: summary.in_progress, icon: Clock, color: 'text-amber-500', bg: 'bg-amber-500/10' },
    { label: 'Done', value: summary.done, icon: CheckCircle2, color: 'text-green-500', bg: 'bg-green-500/10' },
    { label: 'Unassigned', value: summary.unassigned, icon: Users, color: 'text-gray-500', bg: 'bg-gray-500/10' },
  ];
  return (
    <div className="grid grid-cols-5 gap-3 mb-5">
      {cards.map((c) => (
        <div key={c.label} className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-3 text-center">
          <div className={`inline-flex items-center justify-center w-8 h-8 rounded-lg ${c.bg} mb-1`}>
            <c.icon className={`w-4 h-4 ${c.color}`} />
          </div>
          <div className="text-xl font-bold text-gray-900 dark:text-white">{c.value}</div>
          <div className="text-[10px] text-gray-500 dark:text-gray-400 uppercase tracking-wide">{c.label}</div>
        </div>
      ))}
    </div>
  );
}

function ChartCard({ title, icon: Icon, children }: { title: string; icon: any; children: ReactNode }) {
  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-4">
      <div className="flex items-center gap-2 mb-3">
        <Icon className="w-4 h-4 text-orange-500" />
        <h4 className="text-sm font-semibold text-gray-900 dark:text-white">{title}</h4>
      </div>
      <ChartErrorBoundary>{children}</ChartErrorBoundary>
    </div>
  );
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-gray-900 dark:bg-gray-800 text-white text-xs rounded-lg px-3 py-2 shadow-xl border border-gray-700">
      <p className="font-medium mb-1">{label}</p>
      {payload.map((p: any, i: number) => (
        <p key={i} style={{ color: p.color || p.stroke }}>
          {p.name}: {p.value}
        </p>
      ))}
    </div>
  );
};

export default function JiraDashboard({ data }: { data: JiraChartData }) {
  const [expanded, setExpanded] = useState(true);

  if (!data || !data.summary) return null;

  const completionRate = data.summary.total > 0
    ? Math.round((data.summary.done / data.summary.total) * 100)
    : 0;

  return (
    <div className="mt-3 mb-2">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-white mb-3 hover:text-orange-500 transition-colors"
      >
        {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        <BarChart3 className="w-4 h-4 text-orange-500" />
        Project Analytics Dashboard
        <span className="text-xs font-normal text-gray-500 ml-2">({data.summary.total} issues &middot; {completionRate}% complete)</span>
      </button>

      {expanded && (
        <div className="space-y-4">
          <SummaryCards summary={data.summary} />

          <div className="grid grid-cols-2 gap-4">
            <ChartCard title="Status Distribution" icon={PieChartIcon}>
              <ResponsiveContainer width="100%" height={220}>
                <PieChart>
                  <Pie
                    data={data.status_distribution}
                    cx="50%"
                    cy="50%"
                    innerRadius={45}
                    outerRadius={80}
                    paddingAngle={2}
                    dataKey="value"
                    nameKey="name"
                  >
                    {data.status_distribution.map((entry, i) => (
                      <Cell key={i} fill={STATUS_COLORS[entry.name] || PIE_COLORS[i % PIE_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip content={<CustomTooltip />} />
                  <Legend
                    iconType="circle"
                    iconSize={8}
                    wrapperStyle={{ fontSize: '10px' }}
                  />
                </PieChart>
              </ResponsiveContainer>
            </ChartCard>

            <ChartCard title="Priority Breakdown" icon={AlertTriangle}>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={data.priority_distribution} layout="vertical" margin={{ left: 10, right: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
                  <XAxis type="number" tick={{ fontSize: 10 }} />
                  <YAxis type="category" dataKey="name" tick={{ fontSize: 10 }} width={55} />
                  <Tooltip content={<CustomTooltip />} />
                  <Bar dataKey="value" name="Issues" radius={[0, 4, 4, 0]} barSize={18}>
                    {data.priority_distribution.map((entry, i) => (
                      <Cell key={i} fill={PRIORITY_COLORS[entry.name] || PIE_COLORS[i % PIE_COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <ChartCard title="Issue Types" icon={BarChart3}>
              <ResponsiveContainer width="100%" height={220}>
                <PieChart>
                  <Pie
                    data={data.type_distribution}
                    cx="50%"
                    cy="50%"
                    innerRadius={45}
                    outerRadius={80}
                    paddingAngle={2}
                    dataKey="value"
                    nameKey="name"
                  >
                    {data.type_distribution.map((_, i) => (
                      <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip content={<CustomTooltip />} />
                  <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: '10px' }} />
                </PieChart>
              </ResponsiveContainer>
            </ChartCard>

            <ChartCard title="Top Assignees" icon={Users}>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={data.assignee_distribution} layout="vertical" margin={{ left: 10, right: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
                  <XAxis type="number" tick={{ fontSize: 10 }} />
                  <YAxis
                    type="category"
                    dataKey="name"
                    tick={{ fontSize: 9 }}
                    width={80}
                    tickFormatter={(v: string) => v.length > 12 ? v.slice(0, 12) + '...' : v}
                  />
                  <Tooltip content={<CustomTooltip />} />
                  <Bar dataKey="value" name="Issues" fill="#6366f1" radius={[0, 4, 4, 0]} barSize={14} />
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>
          </div>

          <ChartCard title="Burndown Chart (30 days)" icon={TrendingDown}>
            <ResponsiveContainer width="100%" height={240}>
              <AreaChart data={data.burndown_data} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                <defs>
                  <linearGradient id="burnRemaining" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#f97316" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#f97316" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 9 }}
                  tickFormatter={(v: string) => v.slice(5)}
                  interval={Math.max(0, Math.floor(data.burndown_data.length / 8))}
                />
                <YAxis tick={{ fontSize: 10 }} />
                <Tooltip content={<CustomTooltip />} />
                <Legend iconType="line" iconSize={12} wrapperStyle={{ fontSize: '11px' }} />
                <Area
                  type="monotone"
                  dataKey="remaining"
                  name="Remaining"
                  stroke="#f97316"
                  fill="url(#burnRemaining)"
                  strokeWidth={2}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="ideal"
                  name="Ideal"
                  stroke="#94a3b8"
                  strokeDasharray="5 5"
                  strokeWidth={1.5}
                  dot={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </ChartCard>

          <ChartCard title="Issue Creation Trend (30 days)" icon={Activity}>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={data.creation_trend} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 9 }}
                  tickFormatter={(v: string) => v.slice(5)}
                  interval={Math.max(0, Math.floor(data.creation_trend.length / 8))}
                />
                <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
                <Tooltip content={<CustomTooltip />} />
                <Bar dataKey="count" name="Created" fill="#6366f1" radius={[3, 3, 0, 0]} barSize={12} />
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>
        </div>
      )}
    </div>
  );
}
