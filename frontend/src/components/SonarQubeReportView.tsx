import { useMemo, useState, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Shield,
  ShieldCheck,
  ShieldAlert,
  ExternalLink,
  FileCode,
  Rows3,
  Bug,
  AlertTriangle,
  Copy,
  Check,
  Download,
  ChevronDown,
  ChevronRight,
  ListChecks,
  Lightbulb,
  type LucideIcon,
} from 'lucide-react';
import PaginatedMarkdownTable from './PaginatedMarkdownTable';
import MarkdownCodeBlock from './MarkdownCodeBlock';

interface SonarQubeReportViewProps {
  content: string;
}

/** Legacy responses embedded literal `\n` instead of newlines — normalize so markdown parses correctly. */
export function normalizeSonarReportMarkdown(md: string): string {
  if (!md.includes('\\n')) return md;
  return md.replace(/\\r\\n/g, '\n').replace(/\\n/g, '\n').replace(/\\t/g, '\t');
}

export function isSonarQubeReport(content: string): boolean {
  const n = normalizeSonarReportMarkdown(content);
    return (
    /Sonar(?:qube|Cloud) Analysis Report/i.test(n) &&
    (/Quality Gate/i.test(n) || /Files scanned/i.test(n))
  );
}

type Parsed = {
  repoTitle: string;
  repoUrl: string | null;
  qualityGate: string;
  filesScanned: string | null;
  linesScanned: string | null;
  totalIssues: string | null;
  severityMd: string;
  typesMd: string;
  findingsMd: string;
  recommendationsMd: string;
};

function sliceAfterHeading(md: string, heading: string): string {
  const lines = md.split('\n');
  const idx = lines.findIndex((l) => l.trim() === `### ${heading}`);
  if (idx === -1) return '';
  const rest = lines.slice(idx + 1);
  const out: string[] = [];
  for (const line of rest) {
    if (/^###\s/.test(line.trim())) break;
    out.push(line);
  }
  return out.join('\n').trim();
}

/** Match summary bullets with optional markdown bold around labels (server emits `- **Files scanned:** 10`). */
function parseLeadingBullets(normalized: string): Omit<Parsed, 'severityMd' | 'typesMd' | 'findingsMd' | 'recommendationsMd'> | null {
  const titleMatch = normalized.match(/^##\s+Sonar(?:Qube|Cloud) Analysis Report:\s*(.+)$/im);
  if (!titleMatch) return null;
  const repoTitle = titleMatch[1].trim();

  const repoUrlMatch = normalized.match(/^-\s*\*{0,2}Repository\*{0,2}:\s*(\S+)/im);
  const gateMatch = normalized.match(/^-\s*\*{0,2}Quality Gate\*{0,2}:\s*(.+)$/im);
  let qualityGate = '—';
  if (gateMatch) {
    const raw = gateMatch[1].replace(/\*\*/g, '').trim();
    const status = raw.match(/\b(PASSED|FAILED|WARN|OK|ERROR|UNKNOWN)\b/i);
    if (status) {
      const g = status[1].toUpperCase();
      qualityGate = g === 'OK' ? 'PASSED' : g;
    } else {
      qualityGate = raw;
    }
  }

  const filesMatch = normalized.match(/^-\s*\*{0,2}Files scanned\*{0,2}:\s*([\d,]+)/im);
  const linesMatch = normalized.match(/^-\s*\*{0,2}Lines scanned\*{0,2}:\s*([\d,]+)/im);
  const issuesMatch = normalized.match(/^-\s*\*{0,2}Total issues\*{0,2}:\s*([\d,]+)/im);

  return {
    repoTitle,
    repoUrl: repoUrlMatch?.[1]?.trim() ?? null,
    qualityGate,
    filesScanned: filesMatch?.[1] ?? null,
    linesScanned: linesMatch?.[1] ?? null,
    totalIssues: issuesMatch?.[1] ?? null,
  };
}

function parseReport(normalized: string): Parsed | null {
  const base = parseLeadingBullets(normalized);
  if (!base) return null;
  return {
    ...base,
    severityMd: sliceAfterHeading(normalized, 'Severity Breakdown'),
    typesMd: sliceAfterHeading(normalized, 'Issue Type Breakdown'),
    findingsMd: sliceAfterHeading(normalized, 'Top Findings'),
    recommendationsMd: sliceAfterHeading(normalized, 'Recommended Actions'),
  };
}

function gateTone(gate: string): 'pass' | 'fail' | 'warn' | 'neutral' {
  const g = gate.toUpperCase();
  if (g.includes('PASS')) return 'pass';
  if (g.includes('FAIL')) return 'fail';
  if (g.includes('WARN')) return 'warn';
  return 'neutral';
}

const mdComponents = {
  a: ({ href, children }: { href?: string; children?: ReactNode }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" className="text-sky-700 underline decoration-sky-700/30 underline-offset-2 hover:text-sky-900 dark:text-sky-400 dark:hover:text-sky-300">
      {children}
    </a>
  ),
  ul: ({ children }: { children?: ReactNode }) => (
    <ul className="my-2 list-none space-y-2 pl-0">{children}</ul>
  ),
  ol: ({ children }: { children?: ReactNode }) => (
    <ol className="my-2 list-decimal space-y-2 pl-5 marker:text-slate-500">{children}</ol>
  ),
  li: ({ children }: { children?: ReactNode }) => (
    <li className="rounded-lg border border-slate-200/90 bg-white/80 px-3 py-2 text-[13px] leading-relaxed text-slate-800 shadow-[0_1px_2px_rgba(15,23,42,0.04)] dark:border-slate-700/90 dark:bg-slate-900/40 dark:text-slate-100">
      {children}
    </li>
  ),
  p: ({ children }: { children?: ReactNode }) => <p className="my-1.5 text-[13px] leading-relaxed text-slate-700 dark:text-slate-300">{children}</p>,
  strong: ({ children }: { children?: ReactNode }) => (
    <strong className="font-semibold text-slate-900 dark:text-white">{children}</strong>
  ),
  code: ({ children, className }: { children?: ReactNode; className?: string }) => {
    const isInline = !className;
    if (isInline) {
      return (
        <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[11px] text-slate-800 dark:bg-slate-800 dark:text-slate-200">
          {children}
        </code>
      );
    }
    const langMatch = /language-([\w-+]+)/.exec(className || '');
    const codeStr = String(children).replace(/\n$/, '');
    if (langMatch) {
      return <MarkdownCodeBlock language={langMatch[1]} code={codeStr} />;
    }
    return <code className={className}>{children}</code>;
  },
  pre: ({ children }: { children?: ReactNode }) => <>{children}</>,
  table: ({ children }: { children?: ReactNode }) => <PaginatedMarkdownTable>{children}</PaginatedMarkdownTable>,
};

/** Lists without heavy per-row cards — better for severity/type bullet counts. */
const compactMdComponents: typeof mdComponents = {
  ...mdComponents,
  ul: ({ children }: { children?: ReactNode }) => (
    <ul className="my-1 list-disc space-y-1 pl-5 text-[13px] leading-relaxed text-slate-700 marker:text-sky-600 dark:text-slate-300 dark:marker:text-sky-400">
      {children}
    </ul>
  ),
  ol: ({ children }: { children?: ReactNode }) => (
    <ol className="my-2 list-decimal space-y-2 pl-5 text-[13px] leading-relaxed text-slate-700 marker:text-sky-600 dark:text-slate-300 dark:marker:text-sky-400">
      {children}
    </ol>
  ),
  li: ({ children }: { children?: ReactNode }) => (
    <li className="py-0.5 pl-1">{children}</li>
  ),
};

function MetricTile({
  label,
  value,
  icon: Icon,
  accent,
}: {
  label: string;
  value: string | null;
  icon: LucideIcon;
  accent?: boolean;
}) {
  return (
    <div
      className={`rounded-xl border px-4 py-3 ${
        accent
          ? 'border-sky-200 bg-gradient-to-br from-sky-50 to-white dark:border-sky-900/60 dark:from-sky-950/40 dark:to-slate-900/80'
          : 'border-slate-200/90 bg-white dark:border-slate-700/90 dark:bg-slate-900/40'
      } shadow-[0_1px_2px_rgba(15,23,42,0.04)]`}
    >
      <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
        <Icon className="h-3.5 w-3.5" aria-hidden />
        {label}
      </div>
      <div className="mt-1 font-mono text-lg font-semibold tabular-nums text-slate-900 dark:text-white">{value ?? '—'}</div>
    </div>
  );
}

function BreakdownCard({
  title,
  icon: Icon,
  md,
  defaultOpen,
  markdownComponents,
}: {
  title: string;
  icon: LucideIcon;
  md: string;
  defaultOpen?: boolean;
  markdownComponents?: typeof mdComponents;
}) {
  const [open, setOpen] = useState(defaultOpen ?? true);
  if (!md.trim()) return null;
  return (
    <div className="rounded-xl border border-slate-200/90 bg-white dark:border-slate-700/90 dark:bg-slate-900/35 overflow-hidden shadow-sm">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left hover:bg-slate-50 dark:hover:bg-slate-800/60 transition-colors"
      >
        {open ? <ChevronDown className="h-4 w-4 shrink-0 text-slate-400" /> : <ChevronRight className="h-4 w-4 shrink-0 text-slate-400" />}
        <Icon className="h-4 w-4 shrink-0 text-sky-600 dark:text-sky-400" aria-hidden />
        <span className="text-sm font-semibold text-slate-900 dark:text-white">{title}</span>
      </button>
      {open && (
        <div className="border-t border-slate-100 px-4 py-3 dark:border-slate-800 prose prose-sm max-w-none dark:prose-invert prose-p:my-1 prose-li:my-0">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents ?? mdComponents}>
            {md}
          </ReactMarkdown>
        </div>
      )}
    </div>
  );
}

export default function SonarQubeReportView({ content }: SonarQubeReportViewProps) {
  const normalized = useMemo(() => normalizeSonarReportMarkdown(content), [content]);
  const parsed = useMemo(() => parseReport(normalized), [normalized]);
  const [copied, setCopied] = useState(false);

  const tone = parsed ? gateTone(parsed.qualityGate) : 'neutral';

  const badgeClass =
    tone === 'pass'
      ? 'bg-emerald-400/20 text-emerald-50 ring-emerald-200/35'
      : tone === 'fail'
        ? 'bg-rose-400/25 text-rose-50 ring-rose-200/35'
        : tone === 'warn'
          ? 'bg-amber-400/20 text-amber-50 ring-amber-200/35'
          : 'bg-white/15 text-white ring-white/25';

  const GateIcon = tone === 'pass' ? ShieldCheck : tone === 'fail' ? ShieldAlert : Shield;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(normalized);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (e) {
      console.error(e);
    }
  };

  const handleDownload = () => {
    const blob = new Blob([normalized], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `sonarqube-report-${Date.now()}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  if (!parsed) {
    return (
      <div className="rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3 dark:border-gray-800 dark:bg-gray-900">
        <div className="prose prose-sm dark:prose-invert max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
            {normalized}
          </ReactMarkdown>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full min-w-0">
      <div className="overflow-hidden rounded-2xl border border-slate-200/90 bg-white shadow-md shadow-slate-900/[0.06] dark:border-slate-700/90 dark:bg-slate-950 dark:shadow-black/25">
        <div className="relative bg-gradient-to-br from-sky-700 via-sky-600 to-blue-800 px-5 py-5">
          <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,rgba(255,255,255,0.12),transparent_55%)] pointer-events-none" />
          <div className="relative flex flex-wrap items-start justify-between gap-4">
            <div className="flex min-w-0 flex-1 items-start gap-3">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white/15 backdrop-blur-sm ring-1 ring-white/20">
                <Shield className="h-6 w-6 text-white" aria-hidden />
              </div>
              <div className="min-w-0">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-sky-100/90">Static analysis summary</p>
                <h2 className="mt-0.5 text-lg font-bold leading-snug text-white sm:text-xl">{parsed.repoTitle}</h2>
                {parsed.repoUrl ? (
                  <a
                    href={parsed.repoUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-2 inline-flex max-w-full items-center gap-1.5 rounded-lg bg-white/10 px-2.5 py-1 text-xs text-sky-50 backdrop-blur-sm hover:bg-white/20"
                  >
                    <span className="truncate font-mono">{parsed.repoUrl}</span>
                    <ExternalLink className="h-3 w-3 shrink-0 opacity-80" aria-hidden />
                  </a>
                ) : null}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold ring-1 backdrop-blur-sm ${badgeClass}`}
              >
                <GateIcon className="h-3.5 w-3.5" aria-hidden />
                Quality gate · {parsed.qualityGate}
              </span>
              <button
                type="button"
                onClick={handleDownload}
                className="inline-flex items-center gap-1.5 rounded-lg bg-white/15 px-2.5 py-1.5 text-[11px] font-medium text-white ring-1 ring-white/20 backdrop-blur-sm transition-colors hover:bg-white/25"
              >
                <Download className="h-3.5 w-3.5" aria-hidden />
                Markdown
              </button>
              <button
                type="button"
                onClick={handleCopy}
                className="inline-flex items-center gap-1.5 rounded-lg bg-white/15 px-2.5 py-1.5 text-[11px] font-medium text-white ring-1 ring-white/20 backdrop-blur-sm transition-colors hover:bg-white/25"
              >
                {copied ? <Check className="h-3.5 w-3.5" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
                {copied ? 'Copied' : 'Copy'}
              </button>
            </div>
          </div>
        </div>

        <div className="border-b border-slate-100 bg-slate-50/90 px-5 py-4 dark:border-slate-800 dark:bg-slate-900/50">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <MetricTile label="Files scanned" value={parsed.filesScanned} icon={FileCode} />
            <MetricTile label="Lines scanned" value={parsed.linesScanned} icon={Rows3} />
            <MetricTile label="Total issues" value={parsed.totalIssues} icon={Bug} accent />
          </div>
        </div>

        <div className="space-y-3 bg-gradient-to-b from-slate-50/80 to-white p-4 dark:from-slate-950 dark:to-slate-950/90">
          <div className="grid gap-3 md:grid-cols-2">
            <BreakdownCard title="Severity breakdown" icon={AlertTriangle} md={parsed.severityMd} markdownComponents={compactMdComponents} defaultOpen />
            <BreakdownCard title="Issue types" icon={ListChecks} md={parsed.typesMd} markdownComponents={compactMdComponents} defaultOpen />
          </div>
          <BreakdownCard title="Top findings" icon={Bug} md={parsed.findingsMd} defaultOpen />
          <BreakdownCard title="Recommended actions" icon={Lightbulb} md={parsed.recommendationsMd} markdownComponents={compactMdComponents} defaultOpen={false} />
        </div>
      </div>
    </div>
  );
}
