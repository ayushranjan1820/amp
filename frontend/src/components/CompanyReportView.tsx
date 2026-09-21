import { useState, useEffect, useRef, useCallback, useMemo, Component, type ReactNode } from 'react';
import { Copy, Check, Building2, TrendingUp, TrendingDown, DollarSign, BarChart3, PieChart as PieChartIcon, Users, Scale, ChevronDown, ChevronRight, Loader2, Activity, Percent } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { linkifySourceCitations } from '../utils/linkifyMarkdownSources';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell,
  PieChart, Pie, Legend, LabelList
} from 'recharts';

class ChartErrorBoundary extends Component<{ children: ReactNode; fallback?: ReactNode }, { hasError: boolean }> {
  constructor(props: any) {
    super(props);
    this.state = { hasError: false };
  }
  static getDerivedStateFromError() {
    return { hasError: true };
  }
  componentDidCatch(error: any) {
    console.warn('Chart render error:', error?.message);
  }
  render() {
    if (this.state.hasError) {
      return this.props.fallback || (
        <div className="flex items-center justify-center py-8 text-gray-500 text-xs">
          <BarChart3 className="w-4 h-4 mr-2 opacity-40" />
          Chart unavailable
        </div>
      );
    }
    return this.props.children;
  }
}

function useContainerWidth(ref: React.RefObject<HTMLDivElement | null>) {
  const [width, setWidth] = useState(500);
  useEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver(entries => {
      for (const entry of entries) {
        setWidth(entry.contentRect.width);
      }
    });
    observer.observe(ref.current);
    setWidth(ref.current.clientWidth);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}

interface ChartData {
  quarterly: { quarter: string; revenue: number | null; net_profit: number | null; ebitda: number | null; operating_margin: number | null; eps: number | null }[];
  annual: { year: string; revenue: number | null; net_profit: number | null; total_assets: number | null; market_cap: number | null }[];
  revenue_segments: { name: string; percentage: number }[];
  key_metrics: {
    market_cap: string;
    latest_revenue: string;
    latest_profit: string;
    operating_margin: string;
    employees: string;
    debt_equity: string;
    currency: string;
  };
  balance_sheet: {
    total_assets: number | null;
    total_liabilities: number | null;
    equity: number | null;
    cash: number | null;
    debt: number | null;
  };
  company_type?: string;
}

const CHART_COLORS = {
  revenue: '#D85604',
  revenueFaded: '#D8560440',
  profit: '#10b981',
  profitFaded: '#10b98140',
  ebitda: '#3b82f6',
  ebitdaFaded: '#3b82f640',
  assets: '#06b6d4',
  margin: ['#8b5cf6', '#a78bfa', '#c4b5fd', '#ddd6fe'],
  pie: ['#D85604', '#10b981', '#3b82f6', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16', '#f43f5e', '#14b8a6'],
};

function formatAxisValue(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(value >= 10_000 ? 0 : 1)}K`;
  return value.toFixed(value % 1 === 0 ? 0 : 1);
}

function formatCurrency(value: number, currency?: string): string {
  const prefix = currency?.includes('INR') || currency?.includes('₹') ? '₹' : currency?.includes('USD') || currency?.includes('$') ? '$' : '';
  if (value >= 1_00_000) return `${prefix}${(value / 1_000).toFixed(0).replace(/\B(?=(\d{2})+(?!\d))/g, ',')} Cr`;
  if (value >= 1_000) return `${prefix}${value.toLocaleString('en-IN')}`;
  return `${prefix}${value.toLocaleString()}`;
}

function calcGrowth(data: { revenue: number | null }[]): string | null {
  if (data.length < 2) return null;
  const latest = data[data.length - 1]?.revenue;
  const prev = data[data.length - 2]?.revenue;
  if (!latest || !prev || prev === 0) return null;
  const pct = ((latest - prev) / prev * 100).toFixed(1);
  return `${Number(pct) >= 0 ? '+' : ''}${pct}%`;
}

function EnhancedTooltip({ active, payload, label, currency }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white/95 dark:bg-gray-950/95 backdrop-blur-xl border border-gray-200 dark:border-gray-700/60 rounded-xl px-4 py-3 shadow-2xl shadow-black/10 dark:shadow-black/40">
      <p className="text-gray-600 dark:text-gray-400 text-[10px] font-semibold uppercase tracking-wider mb-2 pb-1.5 border-b border-gray-200 dark:border-gray-800">{label}</p>
      {payload.map((entry: any, i: number) => (
        <div key={i} className="flex items-center justify-between gap-6 py-0.5">
          <span className="flex items-center gap-2 text-xs text-gray-400 dark:text-gray-400">
            <span className="w-2 h-2 rounded-sm" style={{ backgroundColor: entry.color }} />
            {entry.name}
          </span>
          <span className="text-gray-900 dark:text-white text-xs font-bold tabular-nums">
            {typeof entry.value === 'number'
              ? entry.name?.toLowerCase().includes('margin') || entry.name?.toLowerCase().includes('%')
                ? `${entry.value.toFixed(1)}%`
                : formatCurrency(entry.value, currency)
              : entry.value}
          </span>
        </div>
      ))}
    </div>
  );
}

function PieTooltipEnhanced({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white/95 dark:bg-gray-950/95 backdrop-blur-xl border border-gray-200 dark:border-gray-700/60 rounded-xl px-4 py-3 shadow-2xl shadow-black/10 dark:shadow-black/40">
      <div className="flex items-center gap-2">
        <span className="w-3 h-3 rounded" style={{ backgroundColor: payload[0].payload?.fill }} />
        <span className="text-gray-900 dark:text-white text-sm font-semibold">{payload[0].name}</span>
      </div>
      <p className="text-[#D85604] text-lg font-bold mt-1">{payload[0].value}%</p>
    </div>
  );
}

function MetricCard({ label, value, icon, trend, accentColor = '#D85604' }: { label: string; value: string; icon: React.ReactNode; trend?: 'up' | 'down' | null; accentColor?: string }) {
  return (
    <div className="bg-gradient-to-br from-gray-800/80 to-gray-900/80 border border-gray-700/30 rounded-xl p-3.5 relative overflow-hidden group hover:border-gray-600/50 transition-all duration-300 hover:shadow-lg hover:shadow-black/20">
      <div className="absolute -top-6 -right-6 w-20 h-20 rounded-full opacity-[0.04]" style={{ backgroundColor: accentColor }} />
      <div className="absolute bottom-0 left-0 w-full h-[2px] opacity-0 group-hover:opacity-100 transition-opacity" style={{ background: `linear-gradient(90deg, ${accentColor}00, ${accentColor}, ${accentColor}00)` }} />
      <div className="flex items-center gap-1.5 text-gray-500 text-[9px] font-bold uppercase tracking-[0.1em] mb-1">
        {icon}
        {label}
      </div>
      <div className="text-gray-900 dark:text-white text-[15px] font-bold flex items-center gap-1.5 tabular-nums">
        {value}
        {trend === 'up' && <TrendingUp className="w-3 h-3 text-emerald-400" />}
        {trend === 'down' && <TrendingDown className="w-3 h-3 text-red-400" />}
      </div>
    </div>
  );
}

function ChartCard({ children, title, subtitle, icon, badge, className = '' }: {
  children: React.ReactNode;
  title: string;
  subtitle?: string;
  icon: React.ReactNode;
  badge?: string | null;
  className?: string;
}) {
  return (
    <div className={`bg-gradient-to-b from-gray-800/50 to-gray-900/30 border border-gray-700/30 rounded-xl overflow-hidden ${className}`}>
      <div className="px-4 pt-4 pb-2 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-gray-700/40 flex items-center justify-center">
            {icon}
          </div>
          <div>
            <h4 className="text-gray-900 dark:text-white text-[13px] font-semibold leading-tight">{title}</h4>
            {subtitle && <p className="text-gray-500 text-[10px] mt-0.5">{subtitle}</p>}
          </div>
        </div>
        {badge && (
          <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
            badge.startsWith('+') ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' :
            badge.startsWith('-') ? 'bg-red-500/10 text-red-400 border border-red-500/20' :
            'bg-gray-700/40 text-gray-400 dark:text-gray-400 border border-gray-600/20'
          }`}>
            {badge}
          </span>
        )}
      </div>
      <div className="px-2 pb-3">
        {children}
      </div>
    </div>
  );
}

function renderCustomBarLabel(props: any) {
  const { x, y, width, value } = props;
  if (value === null || value === undefined) return null;
  return (
    <text x={x + width / 2} y={y - 6} fill="#9ca3af" textAnchor="middle" fontSize={9} fontWeight={600}>
      {formatAxisValue(value)}
    </text>
  );
}

function renderPieLabel({ cx, cy, midAngle, outerRadius, name, percentage }: any) {
  const RADIAN = Math.PI / 180;
  const radius = outerRadius + 25;
  const x = cx + radius * Math.cos(-midAngle * RADIAN);
  const y = cy + radius * Math.sin(-midAngle * RADIAN);
  if (percentage < 5) return null;
  return (
    <text x={x} y={y} fill="#d1d5db" textAnchor={x > cx ? 'start' : 'end'} fontSize={10} fontWeight={500}>
      {`${name} ${percentage}%`}
    </text>
  );
}

export function isCompanyResearchReport(content: string): boolean {
  const markers = [
    'Company Overview & Business Profile',
    'Financial Performance Analysis',
    'Balance Sheet Analysis',
    'Sales Pitch Focus Areas',
  ];
  return markers.filter(m => content.includes(m)).length >= 3;
}

export interface NewsCardData {
  title: string;
  url: string;
  date?: string | null;
  snippet: string;
  source: string;
  image_url?: string | null;
}

/** Same “Latest News” card grid as Company Research Agent; reusable for Meeting Prep, etc. */
export function LatestNewsCardsSection({ newsCards }: { newsCards: NewsCardData[] }) {
  const [expanded, setExpanded] = useState(true);
  if (!newsCards?.length) return null;
  return (
    <div className="border border-gray-200 dark:border-gray-700/50 rounded-lg overflow-hidden bg-gray-50 dark:bg-gray-900/30">
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="w-full flex items-center justify-between px-5 py-3 bg-gray-100 dark:bg-gray-800/50 hover:bg-gray-200 dark:hover:bg-gray-800/70 transition-colors"
      >
        <span className="text-sm font-semibold text-gray-800 dark:text-gray-200 flex items-center gap-2">
          <svg className="w-4 h-4 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z" /></svg>
          Latest News
        </span>
        {expanded ? <ChevronDown className="w-4 h-4 text-gray-400 dark:text-gray-400" /> : <ChevronRight className="w-4 h-4 text-gray-400 dark:text-gray-400" />}
      </button>
      {expanded && (
        <div className="p-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {newsCards.map((card, idx) => (
            <a
              key={idx}
              href={card.url}
              target="_blank"
              rel="noopener noreferrer"
              className="group block border border-gray-200 dark:border-gray-700/50 rounded-lg overflow-hidden bg-white dark:bg-gray-800/40 hover:bg-gray-50 dark:hover:bg-gray-800/70 hover:border-gray-300 dark:hover:border-gray-600 transition-all duration-200"
            >
              <div className="w-full h-36 overflow-hidden bg-gray-100 dark:bg-gray-900/80 relative">
                {card.image_url ? (
                  <img
                    src={card.image_url}
                    alt={card.title}
                    className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                    onError={(e) => {
                      const el = e.target as HTMLImageElement;
                      el.style.display = 'none';
                      const fb = el.parentElement?.querySelector('.news-card-fallback') as HTMLElement;
                      if (fb) fb.style.display = 'flex';
                    }}
                  />
                ) : null}
                <div
                  className="news-card-fallback absolute inset-0 items-center justify-center"
                  style={{
                    display: card.image_url ? 'none' : 'flex',
                    background: `linear-gradient(135deg, ${['#1e3a5f','#2d1b4e','#1a3c34','#3b1c32','#1c2d3f','#2e2a1a'][idx % 6]} 0%, #111827 100%)`
                  }}
                >
                  <div className="text-center px-4">
                    <div className="w-10 h-10 rounded-full bg-white/10 flex items-center justify-center mx-auto mb-2">
                      <svg className="w-5 h-5 text-gray-400 dark:text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z" /></svg>
                    </div>
                    <span className="text-xs text-gray-400 dark:text-gray-400 font-medium">{card.source}</span>
                  </div>
                </div>
              </div>
              <div className="p-3">
                <h4 className="text-sm font-medium text-gray-200 group-hover:text-blue-400 transition-colors line-clamp-2 mb-1.5 leading-snug">
                  {card.title}
                </h4>
                <p className="text-xs text-gray-400 dark:text-gray-400 line-clamp-2 mb-2">{card.snippet}</p>
                <div className="flex items-center justify-between text-xs text-gray-500">
                  <span className="font-medium text-gray-400 dark:text-gray-400">{card.source}</span>
                  {card.date && <span>{card.date}</span>}
                </div>
              </div>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

function stripAllChartData(text: string): string {
  let result = text;
  result = result.replace(/```\s*chartdata\s*\n[\s\S]*?\n\s*```/g, '');
  result = result.replace(/```chartdata[\s\S]*?```/g, '');
  result = result.replace(/```\s*chartdata[\s\S]*?```/g, '');
  const jsonPattern = /\n?\{"\s*quarterly"\s*:\s*\[.*\]\s*,\s*"annual"\s*:\s*\[.*\]\s*,\s*"revenue_segments"\s*:\s*\[.*\]\s*,\s*"key_metrics"\s*:\s*\{.*\}\s*,\s*"balance_sheet"\s*:\s*\{[^}]*\}(?:\s*,\s*"company_type"\s*:\s*"[^"]*")?\s*\}/g;
  result = result.replace(jsonPattern, '');
  return result.replace(/\n{3,}/g, '\n\n').trim();
}

function parseEmbeddedChartData(reportText: string): ChartData | null {
  try {
    const patterns = [
      /```chartdata\s*\n([\s\S]*?)\n```/,
      /```\s*chartdata\s*\n?([\s\S]*?)\n?```/,
      /```chartdata\s*([\s\S]*?)```/,
    ];
    for (const pat of patterns) {
      const match = reportText.match(pat);
      if (match) {
        let jsonStr = match[1].trim();
        if (jsonStr.startsWith('{')) {
          const parsed = JSON.parse(jsonStr);
          if (parsed && (parsed.quarterly || parsed.annual || parsed.revenue_segments || parsed.balance_sheet)) {
            return parsed as ChartData;
          }
        }
      }
    }
    const jsonMatch = reportText.match(/\{"quarterly"\s*:\s*\[[\s\S]*?"balance_sheet"\s*:\s*\{[^}]*\}\s*\}/);
    if (jsonMatch) {
      const parsed = JSON.parse(jsonMatch[0]);
      if (parsed && (parsed.quarterly || parsed.annual)) return parsed as ChartData;
    }
    return null;
  } catch {
    return null;
  }
}

async function fetchChartDataFromAPI(reportText: string): Promise<ChartData | null> {
  try {
    const cleaned = stripAllChartData(reportText);
    const res = await fetch('/api/company-research/extract-charts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ report_text: cleaned }),
    });
    const data = await res.json();
    if (data.success && data.chart_data) return data.chart_data;
    return null;
  } catch {
    return null;
  }
}

function hasSubstantiveData(data: ChartData): boolean {
  const hasQ = data.quarterly && data.quarterly.some(q => q.revenue !== null || q.net_profit !== null);
  const hasA = data.annual && data.annual.some(a => a.revenue !== null || a.net_profit !== null);
  const hasS = data.revenue_segments && data.revenue_segments.length > 0;
  const hasBS = data.balance_sheet && (data.balance_sheet.total_assets || data.balance_sheet.equity);
  return !!(hasQ || hasA || hasS || hasBS);
}

function getChartData(reportText: string): { data: ChartData | null; needsFetch: boolean } {
  const embedded = parseEmbeddedChartData(reportText);
  if (embedded && hasSubstantiveData(embedded)) return { data: embedded, needsFetch: false };
  return { data: null, needsFetch: true };
}

function stripTableMarkdown(text: string): string {
  const lines = text.split('\n');
  const filtered: string[] = [];
  let skipTable = false;
  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith('|')) {
      skipTable = true;
      continue;
    }
    if (skipTable && trimmed === '') {
      skipTable = false;
      continue;
    }
    skipTable = false;
    if (/^###\s*(Quarterly Performance|Annual Performance)/i.test(trimmed)) continue;
    if (/^Trend:/i.test(trimmed)) continue;
    filtered.push(line);
  }
  return filtered.join('\n').replace(/\n{3,}/g, '\n\n').trim();
}

function splitReportSections(markdown: string) {
  const cleaned = stripAllChartData(markdown);
  const financialStart = cleaned.indexOf('## Financial Performance Analysis');
  const balanceStart = cleaned.indexOf('## Balance Sheet Analysis');
  const focusStart = cleaned.indexOf('## Current Focus Areas');
  const newsStart = cleaned.indexOf('## Relevant News');
  if (financialStart === -1) return { before: cleaned, financial: '', afterFinancial: '' };
  const before = cleaned.substring(0, financialStart).trim();
  const financialEnd = balanceStart !== -1 ? balanceStart : focusStart !== -1 ? focusStart : newsStart !== -1 ? newsStart : cleaned.length;
  const rawFinancial = cleaned.substring(financialStart, financialEnd).trim();
  const financial = stripTableMarkdown(rawFinancial);
  const afterFinancial = cleaned.substring(financialEnd).trim();
  return { before, financial, afterFinancial };
}

export default function CompanyReportView({ content, newsCards }: { content: string; newsCards?: NewsCardData[] }) {
  const [copied, setCopied] = useState(false);
  const [chartData, setChartData] = useState<ChartData | null>(null);
  const [chartsLoading, setChartsLoading] = useState(true);
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    overview: true, financial: true, charts: true, rest: true
  });
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartWidth = useContainerWidth(chartContainerRef);
  const halfWidth = Math.max(280, Math.floor((chartWidth - 16) / 2));

  const linkedContent = useMemo(() => linkifySourceCitations(content), [content]);
  const { before, financial, afterFinancial } = splitReportSections(linkedContent);
  const currency = chartData?.key_metrics?.currency || '';

  useEffect(() => {
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    const { data } = getChartData(content);
    if (data) {
      console.log('[Charts] Embedded chart data found and valid');
      setChartData(data);
      setChartsLoading(false);
      return;
    }

    console.log('[Charts] No embedded data found, calling extraction API...');
    setChartsLoading(true);

    fetchChartDataFromAPI(content).then(fetched => {
      if (cancelled) return;
      if (fetched && hasSubstantiveData(fetched)) {
        console.log('[Charts] API extraction succeeded');
        setChartData(fetched);
        setChartsLoading(false);
      } else {
        console.log('[Charts] API extraction returned no data, retrying in 2s...');
        retryTimer = setTimeout(() => {
          if (cancelled) return;
          fetchChartDataFromAPI(content).then(retry => {
            if (cancelled) return;
            if (retry && hasSubstantiveData(retry)) {
              console.log('[Charts] Retry succeeded');
              setChartData(retry);
            } else {
              console.log('[Charts] Charts unavailable after retry');
              setChartData(fetched || retry || null);
            }
            setChartsLoading(false);
          });
        }, 2000);
      }
    }).catch(() => {
      if (!cancelled) setChartsLoading(false);
    });

    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, [content]);

  const handleCopy = useCallback(async () => {
    try {
      const cleaned = stripAllChartData(linkedContent);
      await navigator.clipboard.writeText(cleaned);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {}
  }, [linkedContent]);

  const toggleSection = (key: string) => {
    setExpandedSections(prev => ({ ...prev, [key]: !prev[key] }));
  };

  const validQuarterly = chartData?.quarterly?.filter(q => q.revenue !== null || q.net_profit !== null) || [];
  const validAnnual = chartData?.annual?.filter(a => a.revenue !== null || a.net_profit !== null) || [];
  const validSegments = (chartData?.revenue_segments || [])
    .map((s: any) => ({
      ...s,
      percentage: s.percentage > 0 ? s.percentage : (s.value > 0 ? s.value : 0)
    }))
    .filter((s: any) => s.percentage > 0);
  const km = chartData?.key_metrics;
  const bs = chartData?.balance_sheet;
  const isBank = chartData?.company_type === 'bank';

  const qGrowth = calcGrowth(validQuarterly);
  const aGrowth = calcGrowth(validAnnual);

  const hasBSData = bs && (bs.total_assets || bs.total_liabilities || bs.equity || bs.cash);
  const bsPieData = hasBSData ? [
    bs.equity ? { name: 'Equity', value: bs.equity } : null,
    bs.total_liabilities ? { name: 'Liabilities', value: bs.total_liabilities } : null,
    bs.cash ? { name: 'Cash & Equiv.', value: bs.cash } : null,
    bs.debt ? { name: 'Debt', value: bs.debt } : null,
  ].filter(Boolean) as { name: string; value: number }[] : [];

  const marginData = validQuarterly.filter(q => q.operating_margin !== null).map(q => ({
    quarter: q.quarter,
    operating_margin: q.operating_margin,
  }));

  const formatCellContent = (text: string) => {
    if (!text || typeof text !== 'string') return text;
    const trimmed = text.trim();
    const growthMatch = trimmed.match(/^([+-]?\d+\.?\d*)%$/);
    if (growthMatch) {
      const val = parseFloat(growthMatch[1]);
      if (val > 0) return <span className="inline-flex items-center gap-0.5 text-emerald-400 font-semibold"><TrendingUp className="w-3 h-3" />{trimmed}</span>;
      if (val < 0) return <span className="inline-flex items-center gap-0.5 text-red-400 font-semibold"><TrendingDown className="w-3 h-3" />{trimmed}</span>;
      return <span className="text-gray-400 dark:text-gray-400 font-medium">{trimmed}</span>;
    }
    if (/^-?\d{1,3}(,\d{3})*(\.\d+)?$/.test(trimmed) || /^₹/.test(trimmed) || /^\$/.test(trimmed)) {
      return <span className="font-mono text-gray-100 font-medium">{trimmed}</span>;
    }
    if (/not available|n\/a|nil/i.test(trimmed)) {
      return <span className="text-gray-400 dark:text-gray-600 italic text-[10px]">—</span>;
    }
    return text;
  };

  const markdownComponents = {
    table: ({ children }: any) => (
      <div className="overflow-x-auto my-4 rounded-xl border border-gray-200 dark:border-gray-700/40 bg-white dark:bg-gray-900/50 shadow-lg shadow-black/5 dark:shadow-black/20">
        <table className="w-full text-xs border-collapse">{children}</table>
      </div>
    ),
    thead: ({ children }: any) => (
      <thead className="bg-gradient-to-r from-gray-100 to-gray-50 dark:from-gray-800/80 dark:to-gray-800/60 border-b border-gray-200 dark:border-gray-600/50">{children}</thead>
    ),
    th: ({ children }: any) => {
      const text = typeof children === 'string' ? children : Array.isArray(children) ? children.map((c: any) => typeof c === 'string' ? c : '').join('') : '';
      const isMetricCol = /metric|quarter|year|source/i.test(text);
      return (
        <th className={`px-3 py-2.5 text-[10px] font-bold uppercase tracking-wider text-gray-700 dark:text-gray-300 align-top break-words whitespace-normal ${isMetricCol ? 'text-left' : 'text-right'}`}>
          {children}
        </th>
      );
    },
    td: ({ children }: any) => {
      const raw = typeof children === 'string' ? children : Array.isArray(children) ? children.map((c: any) => {
        if (typeof c === 'string') return c;
        if (c?.props?.children) return typeof c.props.children === 'string' ? c.props.children : '';
        return '';
      }).join('') : '';
      const trimmed = raw.trim();
      const isLabel = /^[A-Z]/.test(trimmed) && !/^\d/.test(trimmed) && !/^[+-]/.test(trimmed) && !/^₹/.test(trimmed) && !/^\$/.test(trimmed);
      const isGrowthRow = /qoq growth|yoy growth/i.test(trimmed);
      const formatted = formatCellContent(trimmed);
      return (
        <td className={`px-3 py-2 border-t border-gray-200 dark:border-gray-800/50 align-top break-words whitespace-normal min-w-0 ${isLabel || isGrowthRow ? 'text-left font-semibold text-gray-800 dark:text-gray-200' : 'text-right text-gray-700 dark:text-gray-300'} ${isGrowthRow ? 'bg-gray-100 dark:bg-gray-800/30 text-[10px] italic' : ''}`}>
          {formatted !== raw ? formatted : children}
        </td>
      );
    },
    tr: ({ children, ...props }: any) => {
      const isInThead = props?.node?.parentNode?.tagName === 'thead';
      return (
        <tr className={isInThead ? '' : 'hover:bg-gray-100 dark:hover:bg-gray-800/30 transition-colors even:bg-gray-50 dark:even:bg-gray-800/10'}>
          {children}
        </tr>
      );
    },
    pre: ({ children }: any) => {
      const extractText = (node: any): string => {
        if (typeof node === 'string') return node;
        if (node?.props?.children) return extractText(node.props.children);
        if (Array.isArray(node)) return node.map(extractText).join('');
        return '';
      };
      const text = extractText(children);
      if (text.includes('"quarterly"') || text.includes('"revenue"') || text.includes('chartdata')) return null;
      return <pre className="bg-gray-100 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-700/40 rounded-lg p-3 my-2 overflow-x-auto text-xs text-gray-700 dark:text-gray-300">{children}</pre>;
    },
    code: ({ children, className }: any) => {
      const text = typeof children === 'string' ? children : Array.isArray(children) ? children.join('') : '';
      if (text.includes('"quarterly"') || text.includes('"revenue"') || text.includes('chartdata')) return null;
      if (className?.includes('chartdata')) return null;
      if (className) {
        return <code className="bg-gray-100 dark:bg-gray-900/50 text-gray-700 dark:text-gray-300 text-xs">{children}</code>;
      }
      return <code className="bg-gray-100 dark:bg-gray-800/60 text-[#D85604] px-1 py-0.5 rounded text-xs">{children}</code>;
    },
    a: ({ href, children }: any) => (
      <a href={href} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:text-blue-300 underline decoration-blue-400/30 hover:decoration-blue-300/50 transition-colors">{children}</a>
    ),
    h2: ({ children }: any) => (
      <h2 className="text-[15px] font-bold text-gray-900 dark:text-white mt-6 mb-3 pb-2 border-b border-gray-700/50 flex items-center gap-2">
        <span className="w-1 h-5 bg-[#D85604] rounded-full" />
        {children}
      </h2>
    ),
    h3: ({ children }: any) => (
      <h3 className="text-[13px] font-semibold text-gray-200 mt-4 mb-2">{children}</h3>
    ),
    strong: ({ children }: any) => (
      <strong className="text-[#D85604] font-semibold">{children}</strong>
    ),
    p: ({ children }: any) => {
      const text = typeof children === 'string' ? children : Array.isArray(children) ? children.map((c: any) => typeof c === 'string' ? c : '').join('') : '';
      if (text.includes('"quarterly"') && text.includes('"revenue"')) return null;
      if (/^\s*\{.*"quarterly"\s*:/.test(text)) return null;
      if (/^Trend:/i.test(text.trim())) {
        return (
          <div className="flex items-start gap-2 my-3 px-3 py-2.5 bg-gradient-to-r from-amber-500/10 to-transparent border border-amber-500/20 rounded-lg">
            <Activity className="w-3.5 h-3.5 text-amber-400 mt-0.5 shrink-0" />
            <p className="text-xs text-amber-200/90 font-medium leading-relaxed">{children}</p>
          </div>
        );
      }
      return <p className="text-xs text-gray-700 dark:text-gray-300 leading-relaxed my-1.5">{children}</p>;
    },
  };

  return (
    <div className="w-full space-y-4">
      <div className="relative bg-gradient-to-r from-[#1e3a5f] via-[#264a72] to-[#2c5f8a] rounded-xl px-5 py-5 overflow-hidden">
        <div className="absolute inset-0 bg-[url('data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNDAiIGhlaWdodD0iNDAiIHZpZXdCb3g9IjAgMCA0MCA0MCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48Y2lyY2xlIGN4PSIyMCIgY3k9IjIwIiByPSIxIiBmaWxsPSJyZ2JhKDI1NSwyNTUsMjU1LDAuMDUpIi8+PC9zdmc+')] opacity-50" />
        <div className="relative flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-white/10 backdrop-blur rounded-xl flex items-center justify-center border border-gray-200 dark:border-white/10">
              <Building2 className="w-5 h-5 text-gray-900 dark:text-white" />
            </div>
            <div>
              <h2 className="text-gray-900 dark:text-white font-bold text-lg tracking-tight">Company Research Report</h2>
              <p className="text-blue-200/70 text-xs">Executive Summary & Financial Analysis</p>
            </div>
          </div>
          <button
            onClick={handleCopy}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-white/10 hover:bg-white/20 text-gray-900 dark:text-white text-xs rounded-lg transition-colors backdrop-blur border border-gray-200 dark:border-white/10"
          >
            {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
            {copied ? 'Copied' : 'Copy Report'}
          </button>
        </div>
      </div>

      {km && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
          {km.market_cap && km.market_cap !== 'N/A' && (
            <MetricCard label="Market Cap" value={km.market_cap} icon={<DollarSign className="w-3 h-3" />} accentColor="#f59e0b" />
          )}
          {km.latest_revenue && km.latest_revenue !== 'N/A' && (
            <MetricCard label={isBank ? "Total Income" : "Revenue"} value={km.latest_revenue} icon={<BarChart3 className="w-3 h-3" />} trend="up" accentColor="#D85604" />
          )}
          {km.latest_profit && km.latest_profit !== 'N/A' && (
            <MetricCard label="Net Profit" value={km.latest_profit} icon={<TrendingUp className="w-3 h-3" />} accentColor="#10b981" />
          )}
          {km.operating_margin && km.operating_margin !== 'N/A' && (
            <MetricCard label={isBank ? "NIM" : "Op. Margin"} value={km.operating_margin} icon={<Percent className="w-3 h-3" />} accentColor="#8b5cf6" />
          )}
          {km.employees && km.employees !== 'N/A' && (
            <MetricCard label="Employees" value={km.employees} icon={<Users className="w-3 h-3" />} accentColor="#06b6d4" />
          )}
          {km.debt_equity && km.debt_equity !== 'N/A' && (
            <MetricCard label="Debt/Equity" value={km.debt_equity} icon={<Scale className="w-3 h-3" />} accentColor="#ec4899" />
          )}
        </div>
      )}

      {before && (
        <div className="bg-gray-50 dark:bg-gray-800/30 border border-gray-200 dark:border-gray-700/40 rounded-xl overflow-hidden">
          <button onClick={() => toggleSection('overview')} className="w-full flex items-center justify-between px-5 py-3 bg-gray-100 dark:bg-gray-800/50 hover:bg-gray-200 dark:hover:bg-gray-800/70 transition-colors">
            <span className="text-gray-900 dark:text-white text-sm font-semibold flex items-center gap-2">
              <Building2 className="w-4 h-4 text-[#D85604]" />
              Company Overview
            </span>
            {expandedSections.overview ? <ChevronDown className="w-4 h-4 text-gray-400 dark:text-gray-400" /> : <ChevronRight className="w-4 h-4 text-gray-400 dark:text-gray-400" />}
          </button>
          {expandedSections.overview && (
            <div className="px-5 py-4 prose prose-sm prose-invert max-w-none prose-p:text-gray-300 prose-p:text-sm prose-p:leading-relaxed prose-li:text-gray-300 prose-li:text-sm">
              <ReactMarkdown components={markdownComponents}>{before}</ReactMarkdown>
            </div>
          )}
        </div>
      )}

      <div className="bg-gray-50 dark:bg-gray-800/30 border border-gray-200 dark:border-gray-700/40 rounded-xl overflow-hidden">
        <button onClick={() => toggleSection('financial')} className="w-full flex items-center justify-between px-5 py-3 bg-gray-100 dark:bg-gray-800/50 hover:bg-gray-200 dark:hover:bg-gray-800/70 transition-colors">
          <span className="text-gray-900 dark:text-white text-sm font-semibold flex items-center gap-2">
            <BarChart3 className="w-4 h-4 text-[#D85604]" />
            Financial Performance & Charts
          </span>
          {expandedSections.financial ? <ChevronDown className="w-4 h-4 text-gray-400 dark:text-gray-400" /> : <ChevronRight className="w-4 h-4 text-gray-400 dark:text-gray-400" />}
        </button>

        {expandedSections.financial && (
          <div className="px-5 py-4">
            {validQuarterly.length > 0 && (
              <div className="mb-5">
                <div className="flex items-center gap-2 mb-3">
                  <BarChart3 className="w-4 h-4 text-[#D85604]" />
                  <h3 className="text-sm font-bold text-gray-900 dark:text-white">Quarterly Performance (Last {validQuarterly.length} Quarters)</h3>
                  {qGrowth && (
                    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${Number(qGrowth.replace('%','')) >= 0 ? 'bg-emerald-500/15 text-emerald-400' : 'bg-red-500/15 text-red-400'}`}>
                      {qGrowth} QoQ
                    </span>
                  )}
                </div>
                <div className="bg-white dark:bg-gray-900/60 border border-gray-200 dark:border-gray-700/40 rounded-xl overflow-hidden">
                  <div className="grid grid-cols-1 divide-y divide-gray-200 dark:divide-gray-800/60">
                    <div className={`grid gap-0 text-[10px] font-bold uppercase tracking-wider text-gray-600 dark:text-gray-400 bg-gray-100 dark:bg-gray-800/60`} style={{ gridTemplateColumns: `140px repeat(${validQuarterly.length}, 1fr) repeat(${Math.max(validQuarterly.length - 1, 0)}, 100px)` }}>
                      <div className="px-3 py-2.5">Metric</div>
                      {validQuarterly.map((q, i) => <div key={i} className="px-3 py-2.5 text-right">{q.quarter}</div>)}
                      {validQuarterly.slice(1).map((_, i) => <div key={`g${i}`} className="px-3 py-2.5 text-right text-gray-500">QoQ</div>)}
                    </div>
                    {[
                      { label: isBank ? 'Total Income' : 'Revenue', key: 'revenue' as const, format: (v: number | null) => v !== null ? formatCurrency(v, currency) : '—' },
                      { label: 'Net Profit', key: 'net_profit' as const, format: (v: number | null) => v !== null ? formatCurrency(v, currency) : '—' },
                      { label: isBank ? 'Operating Profit' : 'EBITDA', key: 'ebitda' as const, format: (v: number | null) => v !== null ? formatCurrency(v, currency) : '—' },
                      { label: isBank ? 'NIM' : 'Op. Margin', key: 'operating_margin' as const, format: (v: number | null) => v !== null ? `${v}%` : '—' },
                      { label: 'EPS', key: 'eps' as const, format: (v: number | null) => v !== null ? `₹${v}` : '—' },
                    ].filter(metric => validQuarterly.some(q => (q as any)[metric.key] !== null && (q as any)[metric.key] !== undefined)).map((metric, mi) => (
                      <div key={mi} className={`grid gap-0 text-xs ${mi % 2 === 0 ? 'bg-gray-50 dark:bg-gray-800/10' : ''} hover:bg-gray-100 dark:hover:bg-gray-100 dark:hover:bg-gray-800/30 transition-colors`} style={{ gridTemplateColumns: `140px repeat(${validQuarterly.length}, 1fr) repeat(${Math.max(validQuarterly.length - 1, 0)}, 100px)` }}>
                        <div className="px-3 py-2 font-semibold text-gray-800 dark:text-gray-200">{metric.label}</div>
                        {validQuarterly.map((q, i) => (
                          <div key={i} className="px-3 py-2 text-right font-mono text-gray-900 dark:text-gray-100 font-medium">
                            {metric.format((q as any)[metric.key])}
                          </div>
                        ))}
                        {validQuarterly.slice(1).map((q, i) => {
                          const curr = (q as any)[metric.key];
                          const prev = (validQuarterly[i] as any)[metric.key];
                          if (curr === null || prev === null || prev === 0) return <div key={`g${i}`} className="px-3 py-2 text-right text-gray-400 dark:text-gray-600">—</div>;
                          const pct = metric.key === 'operating_margin' ? (curr - prev).toFixed(1) + 'pp' : ((curr - prev) / prev * 100).toFixed(1) + '%';
                          const isPositive = metric.key === 'operating_margin' ? curr - prev >= 0 : ((curr - prev) / prev) >= 0;
                          return (
                            <div key={`g${i}`} className={`px-3 py-2 text-right text-[11px] font-semibold flex items-center justify-end gap-0.5 ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
                              {isPositive ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                              {isPositive && !pct.startsWith('-') ? '+' : ''}{pct}
                            </div>
                          );
                        })}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {validAnnual.length > 0 && (
              <div className="mb-5">
                <div className="flex items-center gap-2 mb-3">
                  <TrendingUp className="w-4 h-4 text-emerald-400" />
                  <h3 className="text-sm font-bold text-gray-900 dark:text-white">Annual Performance (Last {validAnnual.length} Years)</h3>
                  {aGrowth && (
                    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${Number(aGrowth.replace('%','')) >= 0 ? 'bg-emerald-500/15 text-emerald-400' : 'bg-red-500/15 text-red-400'}`}>
                      {aGrowth} YoY
                    </span>
                  )}
                </div>
                <div className="bg-white dark:bg-gray-900/60 border border-gray-200 dark:border-gray-700/40 rounded-xl overflow-hidden">
                  <div className="grid grid-cols-1 divide-y divide-gray-200 dark:divide-gray-800/60">
                    <div className={`grid gap-0 text-[10px] font-bold uppercase tracking-wider text-gray-600 dark:text-gray-400 bg-gray-100 dark:bg-gray-800/60`} style={{ gridTemplateColumns: `140px repeat(${validAnnual.length}, 1fr) repeat(${Math.max(validAnnual.length - 1, 0)}, 100px)` }}>
                      <div className="px-3 py-2.5">Metric</div>
                      {validAnnual.map((a, i) => <div key={i} className="px-3 py-2.5 text-right">{a.year}</div>)}
                      {validAnnual.slice(1).map((_, i) => <div key={`g${i}`} className="px-3 py-2.5 text-right text-gray-500">YoY</div>)}
                    </div>
                    {[
                      { label: isBank ? 'Total Income' : 'Revenue', key: 'revenue' as const, format: (v: number | null) => v !== null ? formatCurrency(v, currency) : '—' },
                      { label: 'Net Profit', key: 'net_profit' as const, format: (v: number | null) => v !== null ? formatCurrency(v, currency) : '—' },
                      { label: 'Total Assets', key: 'total_assets' as const, format: (v: number | null) => v !== null ? formatCurrency(v, currency) : '—' },
                      { label: 'Market Cap', key: 'market_cap' as const, format: (v: number | null) => v !== null ? formatCurrency(v, currency) : '—' },
                    ].filter(metric => validAnnual.some(a => (a as any)[metric.key] !== null && (a as any)[metric.key] !== undefined)).map((metric, mi) => (
                      <div key={mi} className={`grid gap-0 text-xs ${mi % 2 === 0 ? 'bg-gray-50 dark:bg-gray-800/10' : ''} hover:bg-gray-100 dark:hover:bg-gray-800/30 transition-colors`} style={{ gridTemplateColumns: `140px repeat(${validAnnual.length}, 1fr) repeat(${Math.max(validAnnual.length - 1, 0)}, 100px)` }}>
                        <div className="px-3 py-2 font-semibold text-gray-200">{metric.label}</div>
                        {validAnnual.map((a, i) => (
                          <div key={i} className="px-3 py-2 text-right font-mono text-gray-100 font-medium">
                            {metric.format((a as any)[metric.key])}
                          </div>
                        ))}
                        {validAnnual.slice(1).map((a, i) => {
                          const curr = (a as any)[metric.key];
                          const prev = (validAnnual[i] as any)[metric.key];
                          if (curr === null || prev === null || prev === 0) return <div key={`g${i}`} className="px-3 py-2 text-right text-gray-400 dark:text-gray-600">—</div>;
                          const pct = ((curr - prev) / prev * 100).toFixed(1);
                          const isPositive = Number(pct) >= 0;
                          return (
                            <div key={`g${i}`} className={`px-3 py-2 text-right text-[11px] font-semibold flex items-center justify-end gap-0.5 ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
                              {isPositive ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                              {isPositive ? '+' : ''}{pct}%
                            </div>
                          );
                        })}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {financial && (
              <div className="prose prose-sm prose-invert max-w-none prose-p:text-gray-300 prose-p:text-sm prose-p:leading-relaxed prose-li:text-gray-300 prose-li:text-sm mb-6">
                <ReactMarkdown components={markdownComponents}>{financial}</ReactMarkdown>
              </div>
            )}

            {chartsLoading ? (
              <div className="flex flex-col items-center justify-center py-16 gap-3">
                <div className="relative">
                  <div className="w-12 h-12 rounded-full border-2 border-gray-700/50 flex items-center justify-center">
                    <Loader2 className="w-6 h-6 animate-spin text-[#D85604]" />
                  </div>
                </div>
                <span className="text-gray-400 dark:text-gray-400 text-sm font-medium">Generating interactive charts...</span>
                <span className="text-gray-400 dark:text-gray-600 text-xs">Analyzing financial data from the report</span>
              </div>
            ) : (
              <div className="space-y-4" ref={chartContainerRef}>
                {validQuarterly.length > 0 && (
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    <ChartCard
                      title={isBank ? "Quarterly Income & Profit" : "Quarterly Revenue & Profit"}
                      subtitle={currency ? `Values in ${currency}` : 'Comparative analysis'}
                      icon={<BarChart3 className="w-3.5 h-3.5 text-[#D85604]" />}
                      badge={qGrowth ? `${qGrowth} QoQ` : null}
                    >
                      <ChartErrorBoundary>
                        <div className="overflow-hidden">
                          <BarChart width={halfWidth} height={280} data={validQuarterly} margin={{ top: 20, right: 12, left: -5, bottom: 5 }}>
                            <defs>
                              <linearGradient id="revGrad" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stopColor="#D85604" stopOpacity={1} />
                                <stop offset="100%" stopColor="#D85604" stopOpacity={0.7} />
                              </linearGradient>
                              <linearGradient id="profitGrad" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stopColor="#10b981" stopOpacity={1} />
                                <stop offset="100%" stopColor="#10b981" stopOpacity={0.7} />
                              </linearGradient>
                              <linearGradient id="ebitdaGrad" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stopColor="#3b82f6" stopOpacity={1} />
                                <stop offset="100%" stopColor="#3b82f6" stopOpacity={0.7} />
                              </linearGradient>
                            </defs>
                            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" vertical={false} />
                            <XAxis dataKey="quarter" tick={{ fill: '#6b7280', fontSize: 10, fontWeight: 500 }} axisLine={false} tickLine={false} dy={8} />
                            <YAxis tick={{ fill: '#6b7280', fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={formatAxisValue} dx={-5} />
                            <Tooltip content={<EnhancedTooltip currency={currency} />} cursor={{ fill: 'rgba(255,255,255,0.03)' }} />
                            <Bar dataKey="revenue" name={isBank ? "Total Income" : "Revenue"} fill="url(#revGrad)" radius={[6, 6, 0, 0]} barSize={20}>
                              <LabelList dataKey="revenue" content={renderCustomBarLabel} />
                            </Bar>
                            <Bar dataKey="net_profit" name="Net Profit" fill="url(#profitGrad)" radius={[6, 6, 0, 0]} barSize={20} />
                            <Bar dataKey="ebitda" name={isBank ? "Operating Profit" : "EBITDA"} fill="url(#ebitdaGrad)" radius={[6, 6, 0, 0]} barSize={20} />
                            <Legend
                              iconType="circle"
                              iconSize={8}
                              wrapperStyle={{ fontSize: '10px', paddingTop: '12px' }}
                              formatter={(v: string) => <span style={{ color: '#9ca3af', fontSize: '10px', marginLeft: '2px' }}>{v}</span>}
                            />
                          </BarChart>
                        </div>
                      </ChartErrorBoundary>
                    </ChartCard>

                    {marginData.length > 0 && (
                      <ChartCard
                        title={isBank ? "Net Interest Margin Trend" : "Operating Margin Trend"}
                        subtitle={isBank ? "NIM trend (%)" : "Profitability efficiency (%)"}
                        icon={<Activity className="w-3.5 h-3.5 text-purple-400" />}
                        badge={marginData.length >= 2 ? `${(((marginData[marginData.length-1]?.operating_margin || 0) - (marginData[0]?.operating_margin || 0))).toFixed(1)}pp` : null}
                      >
                        <ChartErrorBoundary>
                          <div className="overflow-hidden">
                            <BarChart width={halfWidth} height={280} data={marginData} margin={{ top: 20, right: 12, left: -5, bottom: 5 }}>
                              <defs>
                                <linearGradient id="marginGrad" x1="0" y1="0" x2="0" y2="1">
                                  <stop offset="0%" stopColor="#8b5cf6" stopOpacity={1} />
                                  <stop offset="100%" stopColor="#8b5cf6" stopOpacity={0.6} />
                                </linearGradient>
                              </defs>
                              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" vertical={false} />
                              <XAxis dataKey="quarter" tick={{ fill: '#6b7280', fontSize: 10, fontWeight: 500 }} axisLine={false} tickLine={false} dy={8} />
                              <YAxis tick={{ fill: '#6b7280', fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${v}%`} dx={-5} domain={[0, 'auto']} />
                              <Tooltip content={<EnhancedTooltip />} cursor={{ fill: 'rgba(255,255,255,0.03)' }} />
                              <Bar dataKey="operating_margin" name={isBank ? "NIM %" : "Op. Margin %"} fill="url(#marginGrad)" radius={[6, 6, 0, 0]} barSize={36}>
                                {marginData.map((_, i) => (
                                  <Cell key={i} fill={CHART_COLORS.margin[i % CHART_COLORS.margin.length]} />
                                ))}
                                <LabelList dataKey="operating_margin" position="top" formatter={(v: any) => `${v}%`} style={{ fill: '#c4b5fd', fontSize: 10, fontWeight: 600 }} offset={8} />
                              </Bar>
                            </BarChart>
                          </div>
                        </ChartErrorBoundary>
                      </ChartCard>
                    )}
                  </div>
                )}

                {(validAnnual.length > 0 || validSegments.length > 0 || bsPieData.length > 0) && (
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    {validAnnual.length > 0 && (
                      <ChartCard
                        title="Annual Performance"
                        subtitle={currency ? `Values in ${currency}` : 'Year-over-Year comparison'}
                        icon={<TrendingUp className="w-3.5 h-3.5 text-emerald-400" />}
                        badge={aGrowth ? `${aGrowth} YoY` : null}
                      >
                        <ChartErrorBoundary>
                          <div className="overflow-hidden">
                            <BarChart width={halfWidth} height={280} data={validAnnual} margin={{ top: 20, right: 12, left: -5, bottom: 5 }}>
                              <defs>
                                <linearGradient id="revGradA" x1="0" y1="0" x2="0" y2="1">
                                  <stop offset="0%" stopColor="#D85604" stopOpacity={1} />
                                  <stop offset="100%" stopColor="#D85604" stopOpacity={0.7} />
                                </linearGradient>
                                <linearGradient id="profitGradA" x1="0" y1="0" x2="0" y2="1">
                                  <stop offset="0%" stopColor="#10b981" stopOpacity={1} />
                                  <stop offset="100%" stopColor="#10b981" stopOpacity={0.7} />
                                </linearGradient>
                              </defs>
                              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" vertical={false} />
                              <XAxis dataKey="year" tick={{ fill: '#6b7280', fontSize: 10, fontWeight: 500 }} axisLine={false} tickLine={false} dy={8} />
                              <YAxis tick={{ fill: '#6b7280', fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={formatAxisValue} dx={-5} />
                              <Tooltip content={<EnhancedTooltip currency={currency} />} cursor={{ fill: 'rgba(255,255,255,0.03)' }} />
                              <Bar dataKey="revenue" name={isBank ? "Total Income" : "Revenue"} fill="url(#revGradA)" radius={[6, 6, 0, 0]} barSize={24}>
                                <LabelList dataKey="revenue" content={renderCustomBarLabel} />
                              </Bar>
                              <Bar dataKey="net_profit" name="Net Profit" fill="url(#profitGradA)" radius={[6, 6, 0, 0]} barSize={24} />
                              {validAnnual.some(a => a.total_assets) && (
                                <Bar dataKey="total_assets" name="Total Assets" fill="#06b6d4" radius={[6, 6, 0, 0]} barSize={24} opacity={0.7} />
                              )}
                              <Legend
                                iconType="circle"
                                iconSize={8}
                                wrapperStyle={{ fontSize: '10px', paddingTop: '12px' }}
                                formatter={(v: string) => <span style={{ color: '#9ca3af', fontSize: '10px', marginLeft: '2px' }}>{v}</span>}
                              />
                            </BarChart>
                          </div>
                        </ChartErrorBoundary>
                      </ChartCard>
                    )}

                    {validSegments.length > 0 && (
                      <ChartCard
                        title={isBank ? "Income Segments" : "Revenue Segments"}
                        subtitle={isBank ? "Business line breakdown" : "Business / Geography breakdown"}
                        icon={<PieChartIcon className="w-3.5 h-3.5 text-[#D85604]" />}
                      >
                        <ChartErrorBoundary>
                        <div className="overflow-hidden flex items-center justify-center">
                          <PieChart width={halfWidth} height={280}>
                            <Pie
                              data={validSegments}
                              cx="50%"
                              cy="45%"
                              innerRadius={60}
                              outerRadius={95}
                              paddingAngle={2}
                              dataKey="percentage"
                              nameKey="name"
                              stroke="rgba(0,0,0,0.3)"
                              strokeWidth={1}
                              label={renderPieLabel}
                              labelLine={{ stroke: '#4b5563', strokeWidth: 1 }}
                            >
                              {validSegments.map((_, i) => (
                                <Cell key={i} fill={CHART_COLORS.pie[i % CHART_COLORS.pie.length]} />
                              ))}
                            </Pie>
                            <Tooltip content={<PieTooltipEnhanced />} />
                            <Legend
                              iconType="circle"
                              iconSize={7}
                              layout="horizontal"
                              verticalAlign="bottom"
                              align="center"
                              wrapperStyle={{ fontSize: '10px', paddingTop: '4px' }}
                              formatter={(v: string) => <span style={{ color: '#9ca3af', fontSize: '10px', marginLeft: '2px' }}>{v}</span>}
                            />
                          </PieChart>
                        </div>
                        </ChartErrorBoundary>
                      </ChartCard>
                    )}

                    {bsPieData.length > 0 && !validSegments.length && (
                      <ChartCard
                        title="Balance Sheet Composition"
                        subtitle="Capital structure breakdown"
                        icon={<Scale className="w-3.5 h-3.5 text-blue-400" />}
                      >
                        <ChartErrorBoundary>
                        <div className="overflow-hidden flex items-center justify-center">
                          <PieChart width={halfWidth} height={280}>
                            <Pie
                              data={bsPieData}
                              cx="50%"
                              cy="45%"
                              innerRadius={60}
                              outerRadius={95}
                              paddingAngle={2}
                              dataKey="value"
                              nameKey="name"
                              stroke="rgba(0,0,0,0.3)"
                              strokeWidth={1}
                            >
                              {bsPieData.map((_, i) => (
                                <Cell key={i} fill={CHART_COLORS.pie[i % CHART_COLORS.pie.length]} />
                              ))}
                            </Pie>
                            <Tooltip content={<EnhancedTooltip currency={currency} />} />
                            <Legend
                              iconType="circle"
                              iconSize={7}
                              layout="horizontal"
                              verticalAlign="bottom"
                              align="center"
                              wrapperStyle={{ fontSize: '10px', paddingTop: '4px' }}
                              formatter={(v: string) => <span style={{ color: '#9ca3af', fontSize: '10px', marginLeft: '2px' }}>{v}</span>}
                            />
                          </PieChart>
                        </div>
                        </ChartErrorBoundary>
                      </ChartCard>
                    )}
                  </div>
                )}

                {validQuarterly.length === 0 && validAnnual.length === 0 && validSegments.length === 0 && (
                  <div className="text-center py-8 text-gray-500 text-sm">
                    <BarChart3 className="w-8 h-8 mx-auto mb-2 opacity-30" />
                    <p>Chart data could not be extracted from this report</p>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {afterFinancial && (
        <div className="bg-gray-50 dark:bg-gray-800/30 border border-gray-200 dark:border-gray-700/40 rounded-xl overflow-hidden">
          <button onClick={() => toggleSection('rest')} className="w-full flex items-center justify-between px-5 py-3 bg-gray-100 dark:bg-gray-800/50 hover:bg-gray-200 dark:hover:bg-gray-800/70 transition-colors">
            <span className="text-gray-900 dark:text-white text-sm font-semibold flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-[#D85604]" />
              Strategy, News & Sales Pitch
            </span>
            {expandedSections.rest ? <ChevronDown className="w-4 h-4 text-gray-400 dark:text-gray-400" /> : <ChevronRight className="w-4 h-4 text-gray-400 dark:text-gray-400" />}
          </button>
          {expandedSections.rest && (
            <div className="px-5 py-4 prose prose-sm prose-invert max-w-none prose-p:text-gray-300 prose-p:text-sm prose-p:leading-relaxed prose-li:text-gray-300 prose-li:text-sm prose-table:text-xs prose-th:text-gray-700 dark:prose-th:text-gray-300 prose-th:bg-gray-100 dark:prose-th:bg-gray-800/80 prose-th:px-3 prose-th:py-2 prose-th:border-gray-200 dark:prose-th:border-gray-700 prose-td:text-gray-600 dark:prose-td:text-gray-400 prose-td:px-3 prose-td:py-2 prose-td:border-gray-200 dark:prose-td:border-gray-700">
              <ReactMarkdown components={markdownComponents}>{afterFinancial}</ReactMarkdown>
            </div>
          )}
        </div>
      )}

      {newsCards && newsCards.length > 0 && <LatestNewsCardsSection newsCards={newsCards} />}
    </div>
  );
}
