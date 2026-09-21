import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  BrainCircuit,
  AlertTriangle,
  Workflow,
  Clock3,
  ArrowRight,
  Sparkles,
  Target,
  ListTree,
  Link2,
  TrendingUp,
  Milestone,
  FileText,
  FileDown,
  Loader2,
} from 'lucide-react';
import { exportCompanyAiSolutionsDocx, exportCompanyAiSolutionsPdf } from '../utils/companyAiSolutionsExport';

/* eslint-disable react-refresh/only-export-components -- shared parse helpers + default view for WorkflowsTab */
export interface ParsedSolution {
  name: string;
  source?: string;
  type?: string;
  why?: string;
  plan?: string;
  dependencies?: string;
  impact?: string;
  horizon?: string;
}

export interface ParsedReport {
  executiveSummary: string[];
  keyProblems: string[];
  processAreas: string[];
  solutions: ParsedSolution[];
  roadmap: Array<{ title: string; items: string[] }>;
  risks: Array<{ risk: string; mitigation: string }>;
}

function safeJsonParse(text: string): unknown | null {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function extractJsonPayload(content: string): Record<string, unknown> | null {
  const trimmed = content.trim();
  const direct = safeJsonParse(trimmed);
  if (direct && typeof direct === 'object' && !Array.isArray(direct)) {
    return direct as Record<string, unknown>;
  }

  const fenced = content.match(/```json\s*([\s\S]*?)\s*```/i);
  if (fenced?.[1]) {
    const parsed = safeJsonParse(fenced[1].trim());
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
  }
  return null;
}

function toStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((x) => (typeof x === 'string' ? stripMdInline(x) : '')).filter(Boolean);
}

function toParsedSolutions(value: unknown): ParsedSolution[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((entry) => {
      if (!entry || typeof entry !== 'object' || Array.isArray(entry)) return null;
      const item = entry as Record<string, unknown>;
      const name = stripMdInline(String(item.solution_name ?? item.name ?? '').trim());
      if (!name) return null;
      return {
        name,
        source: String(item.source ?? '').trim(),
        type: String(item.type ?? '').trim(),
        why: String(item.why_relevant ?? item.why ?? '').trim(),
        plan: String(item.implementation_plan ?? item.plan ?? '').trim(),
        dependencies: String(item.dependencies ?? '').trim(),
        impact: String(item.expected_business_impact ?? item.impact ?? '').trim(),
        horizon: String(item.delivery_horizon ?? item.horizon ?? '').trim(),
      } as ParsedSolution;
    })
    .filter((x): x is ParsedSolution => Boolean(x));
}

function toParsedRoadmap(value: unknown): Array<{ title: string; items: string[] }> {
  if (!Array.isArray(value)) return [];
  return value
    .map((entry, idx) => {
      if (!entry || typeof entry !== 'object' || Array.isArray(entry)) return null;
      const item = entry as Record<string, unknown>;
      const title = stripMdInline(String(item.phase ?? item.title ?? `Phase ${idx + 1}`).trim());
      const actions = toStringArray(item.actions ?? item.items);
      return { title: title || `Phase ${idx + 1}`, items: actions };
    })
    .filter((x): x is { title: string; items: string[] } => Boolean(x));
}

function toParsedRisks(value: unknown): Array<{ risk: string; mitigation: string }> {
  if (!Array.isArray(value)) return [];
  return value
    .map((entry) => {
      if (!entry || typeof entry !== 'object' || Array.isArray(entry)) return null;
      const item = entry as Record<string, unknown>;
      const risk = stripMdInline(String(item.risk ?? '').trim());
      if (!risk) return null;
      const mitigation = stripMdInline(String(item.mitigation ?? '').trim()) || 'Define owner, controls, and monitoring checkpoints.';
      return { risk, mitigation };
    })
    .filter((x): x is { risk: string; mitigation: string } => Boolean(x));
}

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function phaseTimeWindow(title: string): string | null {
  const m = title.match(/\(([^)]+)\)\s*$/);
  return m?.[1]?.trim() ?? null;
}

function phaseHeading(title: string): string {
  const stripped = title.replace(/\s*\([^)]+\)\s*$/, '').trim();
  return stripped || title;
}

function stripMdInline(text: string): string {
  return text
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/\[([^\]]+)]\([^)]+\)/g, '$1')
    .trim();
}

function normalizeLabelLine(line: string): string {
  return line
    .replace(/^[-*]\s+/, '')
    .replace(/^\d+[.)]\s+/, '')
    .replace(/^#{1,6}\s+/, '')
    .replace(/^\*\*([^*]+)\*\*\s*[-:]?\s*/i, '$1: ')
    .replace(/^__([^_]+)__\s*[-:]?\s*/i, '$1: ')
    .trim();
}

function extractSection(markdown: string, headings: string[]): string {
  for (const heading of headings) {
    const re = new RegExp(
      `^#{1,3}\\s+${escapeRegex(heading)}\\s*$\\n([\\s\\S]*?)(?=^#{1,3}\\s+|\\Z)`,
      'im'
    );
    const m = markdown.match(re);
    if (m?.[1]) return m[1].trim();
  }
  return '';
}

function toBullets(section: string): string[] {
  if (!section) return [];
  const lines = section.split(/\r?\n/);
  const bullets: string[] = [];
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;
    if (/^[-*]\s+/.test(line) || /^\d+\.\s+/.test(line)) {
      bullets.push(stripMdInline(line.replace(/^[-*]\s+|^\d+\.\s+/, '')));
    }
  }
  return bullets;
}

function parseSolutions(section: string): ParsedSolution[] {
  if (!section) return [];

  const normalized = section
    .split(/\r?\n/)
    .map((line) => normalizeLabelLine(line))
    .join('\n');

  const splitBySolutionName = normalized
    .split(/\n(?=(?:\s*[-*]\s*)?Solution\s*Name\s*[-:])/i)
    .map((b) => b.trim())
    .filter((b) => /Solution\s*Name\s*[-:]/i.test(b));

  const splitByHeadings = normalized
    .split(/\n(?=#{2,6}\s*(?:\d+[.)]\s*)?[^\n]{3,80}$)/m)
    .map((b) => b.trim())
    .filter((b) => /^(#{2,6}\s*(?:\d+[.)]\s*)?[^\n]{3,80})\n/i.test(b));

  const blocks = splitBySolutionName.length > 0
    ? splitBySolutionName
    : splitByHeadings;

  return blocks
    .map((block) => {
      const getField = (label: string) => {
        const m = block.match(new RegExp(`${escapeRegex(label)}\\s*[-:]\\s*([\\s\\S]*?)(?=\\n(?:[-*]\\s*)?(?:\\*\\*)?[A-Za-z][^\\n]{1,80}(?:\\*\\*)?\\s*[-:]|$)`, 'i'));
        return m?.[1] ? stripMdInline(m[1].replace(/\n+/g, ' ').trim()) : '';
      };

      const headingName = (() => {
        const h = block.match(/^(?:#{2,6}\s*)(?:\d+[.)]\s*)?(.+)$/m);
        return h?.[1] ? stripMdInline(h[1]) : '';
      })();

      const inferredName = (() => {
        const firstLine = block.split('\n')[0]?.trim() || '';
        if (/^#{2,6}\s*/.test(firstLine)) return stripMdInline(firstLine.replace(/^#{2,6}\s*/, ''));
        return '';
      })();

      return {
        name: getField('Solution Name') || headingName || inferredName,
        source: getField('Source'),
        type: getField('Type'),
        why: getField('Why This Is Relevant For This Company'),
        plan: getField('High-Level Implementation Plan'),
        dependencies: getField('Data / System Dependencies'),
        impact: getField('Expected Business Impact (with measurable KPIs)') || getField('Expected Business Impact'),
        horizon: getField('Delivery Horizon (30/60/90 days or quarter-based)') || getField('Delivery Horizon'),
      };
    })
    .filter((s) => s.name);
}

function parseRoadmap(section: string): Array<{ title: string; items: string[] }> {
  const phases = [
    'Phase 1 (0-30 days)',
    'Phase 2 (31-90 days)',
    'Phase 3 (90+ days)',
  ];

  return phases.map((phase) => {
    const re = new RegExp(`${escapeRegex(phase)}\\s*[-:]?\\s*([\\s\\S]*?)(?=\\n\\s*Phase\\s*\\d|$)`, 'i');
    const m = section.match(re);
    const body = m?.[1]?.trim() || '';
    const items = toBullets(body);
    if (!items.length && body) items.push(stripMdInline(body));
    return { title: phase, items };
  });
}

function parseRisks(section: string): Array<{ risk: string; mitigation: string }> {
  const items = toBullets(section);
  return items.map((line) => {
    const parts = line.split(/\s*[-:]\s*/);
    if (parts.length >= 2) {
      return { risk: parts[0], mitigation: parts.slice(1).join(' - ') };
    }
    return { risk: line, mitigation: 'Define owner, controls, and monitoring checkpoints.' };
  });
}

export function parseReport(content: string): ParsedReport {
  const payload = extractJsonPayload(content);
  if (payload) {
    const executiveSummary = toStringArray(payload['executive_summary']);
    const keyProblems = toStringArray(payload['key_problems']);
    const processAreas = toStringArray(payload['process_improvement_areas']);
    const solutions = toParsedSolutions(payload['recommended_solutions']);
    const roadmap = toParsedRoadmap(payload['implementation_roadmap']);
    const risks = toParsedRisks(payload['risks_and_mitigations']);

    if (
      executiveSummary.length ||
      keyProblems.length ||
      processAreas.length ||
      solutions.length ||
      roadmap.length ||
      risks.length
    ) {
      return { executiveSummary, keyProblems, processAreas, solutions, roadmap, risks };
    }
  }

  const executiveSummary = toBullets(extractSection(content, ['Executive Summary']));
  const keyProblems = toBullets(extractSection(content, ['Key Problems The Company Is Facing']));
  const processAreas = toBullets(extractSection(content, ['Current Process Improvement Areas']));
  const solutions = parseSolutions(extractSection(content, ['Recommended AI and Agentic AI Solutions']));
  const roadmap = parseRoadmap(extractSection(content, ['Implementation Roadmap']));
  const risks = parseRisks(extractSection(content, ['Risks and Mitigations']));

  return { executiveSummary, keyProblems, processAreas, solutions, roadmap, risks };
}

export function isCompanyAiSolutionsReport(content: string): boolean {
  const jsonPayload = extractJsonPayload(content);
  if (jsonPayload) {
    const jsonMarkers = [
      'executive_summary',
      'key_problems',
      'process_improvement_areas',
      'recommended_solutions',
      'implementation_roadmap',
      'risks_and_mitigations',
    ];
    const hit = jsonMarkers.filter((k) => Object.prototype.hasOwnProperty.call(jsonPayload, k)).length;
    if (hit >= 4) return true;
  }

  const markers = [
    'Executive Summary',
    'Key Problems The Company Is Facing',
    'Current Process Improvement Areas',
    'Recommended AI and Agentic AI Solutions',
    'Implementation Roadmap',
    'Risks and Mitigations',
  ];
  return markers.filter((m) => content.includes(m)).length >= 4;
}

export default function CompanyAiSolutionsView({ content }: { content: string }) {
  const [activeTab, setActiveTab] = useState(0);
  const [exportBusy, setExportBusy] = useState<'docx' | 'pdf' | null>(null);

  const parsed = useMemo(() => parseReport(content), [content]);
  const roadmapActionsCount = useMemo(
    () => parsed.roadmap.reduce((acc, phase) => acc + phase.items.length, 0),
    [parsed.roadmap],
  );

  const selectedSolution = parsed.solutions[activeTab] || null;

  const sectionIndex = useMemo(() => {
    let n = 0;
    const next = () => String(++n).padStart(2, '0');
    const hasExec = parsed.executiveSummary.length > 0;
    if (hasExec) {
      return {
        executive: next(),
        context: next(),
        solutions: next(),
        roadmap: next(),
        risks: next(),
      };
    }
    return {
      executive: null,
      context: next(),
      solutions: next(),
      roadmap: next(),
      risks: next(),
    };
  }, [parsed.executiveSummary.length]);

  useEffect(() => {
    if (parsed.solutions.length === 0) {
      if (activeTab !== 0) setActiveTab(0);
      return;
    }
    if (activeTab > parsed.solutions.length - 1) {
      setActiveTab(0);
    }
  }, [activeTab, parsed.solutions.length]);

  const handleExportDocx = useCallback(async () => {
    setExportBusy('docx');
    try {
      await exportCompanyAiSolutionsDocx(content);
    } finally {
      setExportBusy(null);
    }
  }, [content]);

  const handleExportPdf = useCallback(async () => {
    setExportBusy('pdf');
    try {
      await exportCompanyAiSolutionsPdf(content);
    } finally {
      setExportBusy(null);
    }
  }, [content]);

  return (
    <article
      className="[color-scheme:light] w-full overflow-hidden rounded-xl border border-slate-200/70 bg-gradient-to-b from-slate-50 via-white to-slate-50/80 text-slate-800 shadow-[0_1px_2px_rgba(15,23,42,0.04),0_20px_50px_-24px_rgba(15,23,42,0.14),0_0_0_1px_rgba(15,23,42,0.02)_inset]"
      data-export-root="company-ai-blueprint"
    >
      <header className="relative border-b border-slate-200/60 bg-gradient-to-br from-slate-50/90 via-white to-indigo-50/30 px-5 py-7 sm:px-8 sm:py-8">
        <div
          className="absolute left-0 top-0 h-full w-1 bg-gradient-to-b from-indigo-600 via-indigo-500 to-slate-700"
          aria-hidden
        />
        <div className="pl-1 sm:pl-2">
          <div
            className="h-px w-14 bg-gradient-to-r from-indigo-600/80 to-transparent"
            aria-hidden
          />
          <div className="mt-6 flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
            <div className="min-w-0 max-w-3xl">
              <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-indigo-700/90">Strategic assessment</p>
              <h2 className="mt-2.5 text-balance text-xl font-semibold tracking-tight text-slate-900 sm:text-2xl">Company AI Solutions Blueprint</h2>
              <p className="mt-2.5 text-sm leading-relaxed text-slate-600">
                A structured view of opportunity areas, solution design, delivery phases, and risk posture—formatted for review and handoff.
              </p>
            </div>
            <div className="flex shrink-0 flex-col items-stretch gap-3 sm:items-end">
              <div className="flex flex-wrap gap-2 sm:justify-end">
                <button
                  type="button"
                  onClick={handleExportDocx}
                  disabled={exportBusy !== null}
                  className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-slate-200/90 bg-white/95 px-3 py-2 text-[11px] font-semibold text-slate-800 shadow-sm ring-1 ring-slate-900/[0.04] transition hover:border-indigo-200 hover:bg-white hover:text-indigo-950 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {exportBusy === 'docx' ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-indigo-600" aria-hidden />
                  ) : (
                    <FileText className="h-3.5 w-3.5 text-indigo-600" aria-hidden />
                  )}
                  Word
                </button>
                <button
                  type="button"
                  onClick={handleExportPdf}
                  disabled={exportBusy !== null}
                  className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-slate-200/90 bg-white/95 px-3 py-2 text-[11px] font-semibold text-slate-800 shadow-sm ring-1 ring-slate-900/[0.04] transition hover:border-indigo-200 hover:bg-white hover:text-indigo-950 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {exportBusy === 'pdf' ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-indigo-600" aria-hidden />
                  ) : (
                    <FileDown className="h-3.5 w-3.5 text-indigo-600" aria-hidden />
                  )}
                  PDF
                </button>
              </div>
              <dl className="grid grid-cols-3 gap-2 text-center sm:gap-2.5">
                {[
                  { k: 'Solutions', n: parsed.solutions.length },
                  { k: 'Roadmap', n: roadmapActionsCount },
                  { k: 'Risks', n: parsed.risks.length },
                ].map(({ k, n }) => (
                  <div
                    key={k}
                    className="min-w-[4.75rem] rounded-lg border border-slate-200/80 bg-white/90 px-3 py-3 shadow-sm ring-1 ring-slate-900/[0.03]"
                  >
                    <dt className="text-[9px] font-semibold uppercase tracking-wider text-slate-500">{k}</dt>
                    <dd className="mt-1 text-lg font-semibold tabular-nums text-indigo-950">{n}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </div>
        </div>
      </header>

      <div className="border-b border-slate-200/60 bg-slate-100/50 px-5 py-2.5 sm:px-8">
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-600">
          <div className="flex h-6 w-6 items-center justify-center rounded-md bg-indigo-100/90 text-indigo-700">
            <BrainCircuit className="h-3.5 w-3.5" aria-hidden />
          </div>
          <span className="font-medium">AI &amp; agentic solutions report</span>
        </div>
      </div>

      {parsed.executiveSummary.length > 0 && (
        <section className="relative overflow-hidden border-b border-slate-200/60 bg-gradient-to-b from-white via-slate-50/40 to-white">
          <div
            className="pointer-events-none absolute -right-24 top-0 h-64 w-64 rounded-full bg-gradient-to-br from-indigo-400/[0.14] via-violet-400/[0.08] to-transparent blur-3xl"
            aria-hidden
          />
          <div
            className="pointer-events-none absolute -left-20 bottom-0 h-48 w-48 rounded-full bg-gradient-to-tr from-cyan-400/[0.08] to-transparent blur-2xl"
            aria-hidden
          />
          <div className="relative px-5 py-8 sm:px-8 sm:py-9">
            <div className="mb-6 flex flex-col gap-5 sm:mb-7 sm:flex-row sm:items-end sm:justify-between">
              <div className="flex min-w-0 items-start gap-4">
                <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-600 to-violet-600 text-gray-900 dark:text-white shadow-lg shadow-indigo-500/25 ring-1 ring-white/25">
                  <Sparkles className="h-5 w-5" aria-hidden />
                </span>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="inline-flex items-center rounded-full bg-indigo-50 px-2.5 py-0.5 font-mono text-[10px] font-semibold tabular-nums text-indigo-700 ring-1 ring-indigo-200/70">
                      {sectionIndex.executive}
                    </span>
                    <span className="text-[10px] font-semibold uppercase tracking-[0.22em] text-indigo-600/85">At a glance</span>
                  </div>
                  <h3 className="mt-2 text-balance text-xl font-semibold tracking-tight text-slate-900 sm:text-2xl">Executive summary</h3>
                  <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-slate-600">
                    The headline narrative—what matters most before you dive into problems, solutions, and delivery.
                  </p>
                </div>
              </div>
            </div>
            <ul className="grid list-none gap-3 p-0 sm:grid-cols-2 sm:gap-4">
              {parsed.executiveSummary.map((item, idx) => (
                <li
                  key={idx}
                  className="group relative flex gap-4 rounded-2xl border border-slate-200/70 bg-white/85 p-4 shadow-[0_2px_12px_-4px_rgba(15,23,42,0.08)] ring-1 ring-slate-900/[0.03] backdrop-blur-[2px] transition duration-200 hover:border-indigo-200/80 hover:shadow-[0_8px_28px_-12px_rgba(99,102,241,0.18)] hover:ring-indigo-500/[0.06] sm:p-5"
                >
                  <span
                    className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-slate-100 to-white text-sm font-semibold tabular-nums text-indigo-600 shadow-sm ring-1 ring-slate-200/80 transition duration-200 group-hover:from-indigo-50 group-hover:to-violet-50/80 group-hover:text-indigo-700 group-hover:ring-indigo-200/60"
                    aria-hidden
                  >
                    {idx + 1}
                  </span>
                  <p className="min-w-0 flex-1 text-[13px] leading-relaxed text-slate-700">{item}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}

      <section className="border-b border-slate-200/60 bg-slate-50/90 px-5 py-7 sm:px-8">
        <div className="mb-4 flex items-baseline gap-3 border-b border-slate-200/80 pb-3">
          <span className="font-mono text-xs font-medium text-indigo-500/80 tabular-nums">{sectionIndex.context}</span>
          <h3 className="text-sm font-semibold uppercase tracking-[0.1em] text-slate-800">Context &amp; pressure points</h3>
        </div>
        <div className="grid gap-5 lg:grid-cols-2">
          <div className="rounded-xl border border-slate-200/70 bg-white p-4 shadow-[0_1px_3px_rgba(15,23,42,0.04)] ring-1 ring-slate-900/[0.03]">
            <div className="mb-3 flex items-center gap-2 border-b border-slate-100/90 pb-2.5">
              <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-amber-50 text-amber-800">
                <AlertTriangle className="h-3.5 w-3.5" />
              </span>
              <h4 className="text-xs font-semibold text-slate-800">Key problems</h4>
            </div>
            <ol className="list-decimal space-y-2.5 pl-4 text-[13px] leading-relaxed text-slate-700 marker:text-indigo-400/80">
              {parsed.keyProblems.length > 0
                ? parsed.keyProblems.map((p, idx) => <li key={idx}>{p}</li>)
                : <li className="list-none pl-0 text-slate-500">No problems extracted from the response.</li>}
            </ol>
          </div>
          <div className="rounded-xl border border-slate-200/70 bg-white p-4 shadow-[0_1px_3px_rgba(15,23,42,0.04)] ring-1 ring-slate-900/[0.03]">
            <div className="mb-3 flex items-center gap-2 border-b border-slate-100/90 pb-2.5">
              <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-indigo-50 text-indigo-800">
                <Workflow className="h-3.5 w-3.5" />
              </span>
              <h4 className="text-xs font-semibold text-slate-800">Process improvement areas</h4>
            </div>
            <ol className="list-decimal space-y-2.5 pl-4 text-[13px] leading-relaxed text-slate-700 marker:text-indigo-400/80">
              {parsed.processAreas.length > 0
                ? parsed.processAreas.map((p, idx) => <li key={idx}>{p}</li>)
                : <li className="list-none pl-0 text-slate-500">No process improvements extracted from the response.</li>}
            </ol>
          </div>
        </div>
      </section>

      <section className="border-b border-slate-200/60 bg-white px-5 py-7 sm:px-8">
        <div className="mb-4 flex items-baseline gap-3 border-b border-slate-200/80 pb-3">
          <span className="font-mono text-xs font-medium text-indigo-500/80 tabular-nums">{sectionIndex.solutions}</span>
          <h3 className="text-sm font-semibold uppercase tracking-[0.1em] text-slate-800">Recommended solutions</h3>
        </div>

        <div className="overflow-hidden rounded-2xl border border-slate-200/60 bg-gradient-to-b from-slate-50/80 via-white to-slate-50/50 shadow-[0_2px_16px_-4px_rgba(15,23,42,0.08),0_0_0_1px_rgba(15,23,42,0.02)_inset]">
          <div className="flex flex-col gap-2 border-b border-slate-200/50 bg-gradient-to-r from-slate-50/95 via-indigo-50/25 to-slate-50/90 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:py-3.5">
            <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">Choose a solution</p>
            <span className="inline-flex items-center gap-1.5 self-start rounded-full border border-slate-200/80 bg-white/80 px-2.5 py-0.5 text-[10px] font-medium tabular-nums text-slate-600 shadow-sm sm:self-auto">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 shadow-[0_0_0_2px_rgba(16,185,129,0.25)]" aria-hidden />
              {parsed.solutions.length} in scope
            </span>
          </div>

          <div
            className="relative border-b border-slate-200/40 bg-[radial-gradient(1200px_200px_at_50%_-40%,rgba(99,102,241,0.09),transparent)] px-3 py-3.5 sm:px-4 sm:py-4"
            role="tablist"
            aria-label="Recommended solutions"
          >
            <div className="flex max-h-[min(11rem,40vh)] flex-wrap gap-2 overflow-y-auto pr-0.5 [scrollbar-width:thin] [scrollbar-color:rgba(148,163,184,0.5)_transparent] sm:max-h-none sm:overflow-visible">
              {parsed.solutions.map((solution, idx) => (
                <button
                  key={idx}
                  type="button"
                  role="tab"
                  id={`company-ai-solution-tab-${idx}`}
                  aria-selected={idx === activeTab}
                  aria-controls="company-ai-solution-panel"
                  onClick={() => setActiveTab(idx)}
                  className={`group max-w-full rounded-full px-3.5 py-2 text-left text-[11px] font-medium leading-snug transition duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/50 focus-visible:ring-offset-2 focus-visible:ring-offset-white ${
                    idx === activeTab
                      ? 'bg-gradient-to-r from-indigo-600 to-violet-600 text-gray-900 dark:text-white shadow-md shadow-indigo-500/20 ring-1 ring-indigo-500/20'
                      : 'border border-slate-200/80 bg-white/90 text-slate-600 shadow-sm ring-1 ring-slate-900/[0.04] hover:border-indigo-200/90 hover:bg-white hover:text-slate-900 hover:shadow-md hover:shadow-slate-200/40'
                  }`}
                  title={solution.name}
                >
                  <span
                    className={`block max-w-[min(20rem,100%)] truncate sm:max-w-[22rem] ${idx === activeTab ? 'text-gray-900 dark:text-white' : 'group-hover:text-slate-900'}`}
                  >
                    {solution.name}
                  </span>
                </button>
              ))}
            </div>
            {parsed.solutions.length === 0 && <p className="w-full text-xs text-slate-500">No structured solution cards found in output.</p>}
          </div>

          {selectedSolution && (
            <div
              className="bg-gradient-to-b from-slate-50/40 to-white/80 p-3 sm:p-5"
              role="tabpanel"
              id="company-ai-solution-panel"
              aria-labelledby={parsed.solutions[activeTab] != null ? `company-ai-solution-tab-${activeTab}` : undefined}
            >
              <div className="group relative overflow-hidden rounded-2xl border border-slate-200/40 bg-white shadow-[0_8px_40px_-12px_rgba(15,23,42,0.15),0_0_0_1px_rgba(15,23,42,0.04)_inset] ring-1 ring-slate-900/[0.04]">
                <div
                  className="pointer-events-none absolute -right-16 -top-20 h-56 w-56 rounded-full bg-gradient-to-br from-indigo-500/[0.12] via-violet-500/[0.08] to-transparent blur-3xl"
                  aria-hidden
                />
                <div
                  className="pointer-events-none absolute -bottom-8 -left-8 h-40 w-40 rounded-full bg-gradient-to-tr from-cyan-500/[0.07] to-transparent blur-2xl"
                  aria-hidden
                />
                <div
                  className="pointer-events-none absolute right-1/3 top-0 h-px w-1/2 bg-gradient-to-r from-transparent via-indigo-400/30 to-transparent"
                  aria-hidden
                />

                <div className="relative border-b border-slate-200/50 bg-gradient-to-br from-slate-50/90 via-white to-indigo-50/35 px-5 py-5 sm:px-6 sm:py-6">
                  <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0 flex-1">
                      <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-indigo-600/90">Active solution</p>
                      <h4 className="mt-2 text-balance text-lg font-semibold leading-snug tracking-tight text-slate-900 sm:text-xl">
                        {selectedSolution.name}
                      </h4>
                    </div>
                    <div className="flex shrink-0 flex-wrap gap-2 sm:max-w-[min(100%,20rem)] sm:justify-end">
                      {selectedSolution.type && (
                        <span className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200/70 bg-white/90 px-2.5 py-1.5 text-[11px] font-medium text-slate-700 shadow-sm ring-1 ring-slate-900/[0.04]">
                          <Sparkles className="h-3.5 w-3.5 text-indigo-500" aria-hidden />
                          {selectedSolution.type}
                        </span>
                      )}
                      {selectedSolution.source && (
                        <span className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-200/50 bg-indigo-50/80 px-2.5 py-1.5 text-[11px] font-medium text-indigo-950 ring-1 ring-indigo-900/[0.06]">
                          {selectedSolution.source}
                        </span>
                      )}
                      {!selectedSolution.type && !selectedSolution.source && (
                        <span className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200/70 bg-white/90 px-2.5 py-1.5 text-[11px] font-medium text-slate-600">
                          <Sparkles className="h-3.5 w-3.5 text-indigo-500" aria-hidden />
                          AI / agentic
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                <div className="relative space-y-4 p-4 sm:space-y-5 sm:p-5">
                  <div className="relative overflow-hidden rounded-xl border border-slate-200/50 bg-slate-50/40 p-4 shadow-sm ring-1 ring-slate-900/[0.02] sm:p-5">
                    <div className="absolute left-0 top-0 h-full w-[3px] bg-gradient-to-b from-indigo-500 to-violet-500" aria-hidden />
                    <div className="flex items-start gap-3 pl-0.5">
                      <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-indigo-100/90 text-indigo-700">
                        <Target className="h-4 w-4" aria-hidden />
                      </span>
                      <div className="min-w-0">
                        <h5 className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Relevance</h5>
                        <p className="mt-2 text-[13px] leading-relaxed text-slate-700">
                          {selectedSolution.why || 'Not provided'}
                        </p>
                      </div>
                    </div>
                  </div>

                  <div className="grid gap-4 lg:grid-cols-2">
                    <div className="flex flex-col rounded-xl border border-slate-200/50 bg-white p-4 shadow-sm ring-1 ring-slate-900/[0.02] sm:p-5">
                      <div className="mb-3 flex items-center gap-2">
                        <ListTree className="h-4 w-4 text-slate-400" aria-hidden />
                        <h5 className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Implementation plan</h5>
                      </div>
                      <p className="flex-1 text-[13px] leading-relaxed text-slate-700">{selectedSolution.plan || 'Not provided'}</p>
                    </div>
                    <div className="flex flex-col rounded-xl border border-slate-200/50 bg-gradient-to-b from-slate-50/80 to-white p-4 shadow-sm ring-1 ring-slate-900/[0.02] sm:p-5">
                      <div className="mb-3 flex items-center gap-2">
                        <Link2 className="h-4 w-4 text-slate-400" aria-hidden />
                        <h5 className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Dependencies</h5>
                      </div>
                      <p className="text-[13px] leading-relaxed text-slate-700">{selectedSolution.dependencies || 'Not provided'}</p>
                    </div>
                  </div>

                  <div className="grid gap-4 sm:grid-cols-[1fr,auto] sm:items-stretch sm:gap-4">
                    <div className="overflow-hidden rounded-xl border border-emerald-200/50 bg-gradient-to-br from-emerald-50/90 via-white to-emerald-50/30 p-4 shadow-sm ring-1 ring-emerald-900/[0.04] sm:p-5">
                      <div className="mb-2 flex items-center gap-2">
                        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-100/90 text-emerald-800">
                          <TrendingUp className="h-4 w-4" aria-hidden />
                        </span>
                        <h5 className="text-[10px] font-semibold uppercase tracking-[0.16em] text-emerald-900/80">Expected business impact</h5>
                      </div>
                      <p className="text-[13px] leading-relaxed text-emerald-950/90">{selectedSolution.impact || 'Not provided'}</p>
                    </div>
                    <div className="flex min-h-[4.5rem] flex-col justify-center rounded-xl border border-indigo-200/60 bg-gradient-to-br from-indigo-50 via-violet-50/50 to-indigo-50/80 p-4 shadow-sm ring-1 ring-indigo-900/[0.05] sm:min-w-[10.5rem] sm:p-5">
                      <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-indigo-600/80">Delivery horizon</p>
                      <p className="mt-2 inline-flex items-center gap-2 text-sm font-semibold text-indigo-950">
                        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/80 shadow-sm ring-1 ring-indigo-200/60">
                          <Clock3 className="h-4 w-4 text-indigo-600" aria-hidden />
                        </span>
                        {selectedSolution.horizon || 'Not provided'}
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </section>

      <section
        className="relative overflow-hidden border-b border-slate-200/60 bg-gradient-to-b from-slate-50/95 via-white to-indigo-50/20 px-5 py-8 sm:px-8 sm:py-9"
        aria-labelledby="company-ai-roadmap-heading"
      >
        <div
          className="pointer-events-none absolute -right-20 top-24 h-72 w-72 rounded-full bg-gradient-to-bl from-indigo-400/[0.12] via-violet-400/[0.06] to-transparent blur-3xl"
          aria-hidden
        />
        <div
          className="pointer-events-none absolute -left-16 bottom-12 h-56 w-56 rounded-full bg-gradient-to-tr from-teal-400/[0.07] to-transparent blur-2xl"
          aria-hidden
        />

        <div className="relative mb-8 flex flex-col gap-5 sm:mb-9 sm:flex-row sm:items-end sm:justify-between">
          <div className="flex min-w-0 items-start gap-4">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-600 to-violet-600 text-gray-900 dark:text-white shadow-lg shadow-indigo-500/25 ring-1 ring-white/25">
              <Milestone className="h-5 w-5" aria-hidden />
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex items-center rounded-full bg-indigo-50 px-2.5 py-0.5 font-mono text-[10px] font-semibold tabular-nums text-indigo-700 ring-1 ring-indigo-200/70">
                  {sectionIndex.roadmap}
                </span>
                <span className="text-[10px] font-semibold uppercase tracking-[0.22em] text-indigo-600/85">Delivery</span>
              </div>
              <h3
                id="company-ai-roadmap-heading"
                className="mt-2 text-balance text-xl font-semibold tracking-tight text-slate-900 sm:text-2xl"
              >
                Implementation roadmap
              </h3>
              <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-slate-600">
                Phased milestones from kickoff through scale—use as a sequencing guide with your steering group.
              </p>
            </div>
          </div>
          {parsed.roadmap.length > 0 && (
            <div className="flex shrink-0 items-center gap-2 rounded-xl border border-slate-200/80 bg-white/90 px-3 py-2 shadow-sm ring-1 ring-slate-900/[0.03]">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-50 text-slate-600 ring-1 ring-slate-200/80">
                <Clock3 className="h-4 w-4" aria-hidden />
              </span>
              <div className="text-left">
                <p className="text-[9px] font-semibold uppercase tracking-wider text-slate-500">Horizon</p>
                <p className="text-xs font-semibold tabular-nums text-slate-800">
                  {parsed.roadmap.length} phase{parsed.roadmap.length === 1 ? '' : 's'}
                </p>
              </div>
            </div>
          )}
        </div>

        {parsed.roadmap.length === 0 ? (
          <p className="text-sm text-slate-500">No roadmap phases extracted from the response.</p>
        ) : (
          <div className="relative">
            <div
              className="absolute left-[1.3125rem] top-10 bottom-10 hidden w-px bg-gradient-to-b from-indigo-400/90 via-violet-400/70 to-teal-400/80 sm:block"
              aria-hidden
            />
            <ol className="relative m-0 list-none space-y-0 p-0">
              {parsed.roadmap.map((phase, idx) => {
                const windowLabel = phaseTimeWindow(phase.title);
                const heading = phaseHeading(phase.title);
                const accent =
                  idx % 3 === 0
                    ? 'from-indigo-600 to-violet-600 shadow-indigo-500/30 ring-indigo-200/50'
                    : idx % 3 === 1
                      ? 'from-violet-600 to-fuchsia-600 shadow-violet-500/30 ring-violet-200/50'
                      : 'from-teal-600 to-cyan-600 shadow-teal-500/25 ring-teal-200/50';

                return (
                  <li key={`${phase.title}-${idx}`} className="relative flex gap-4 pb-10 last:pb-0 sm:gap-6">
                    <div className="relative z-10 flex shrink-0 flex-col items-center sm:w-11">
                      <div
                        className={`flex h-11 w-11 items-center justify-center rounded-2xl border-2 border-white bg-gradient-to-br text-sm font-bold text-gray-900 dark:text-white shadow-lg ring-2 ${accent}`}
                        aria-hidden
                      >
                        {idx + 1}
                      </div>
                      {idx < parsed.roadmap.length - 1 && (
                        <div
                          className="mt-2 h-12 w-px shrink-0 bg-gradient-to-b from-indigo-300/90 to-violet-300/50 sm:hidden"
                          aria-hidden
                        />
                      )}
                    </div>

                    <div className="min-w-0 flex-1 pt-0.5">
                      <div className="group relative overflow-hidden rounded-2xl border border-slate-200/70 bg-white/90 p-4 shadow-[0_2px_16px_-4px_rgba(15,23,42,0.08)] ring-1 ring-slate-900/[0.03] backdrop-blur-[2px] transition duration-200 hover:border-indigo-200/80 hover:shadow-[0_12px_40px_-16px_rgba(99,102,241,0.2)] sm:p-5">
                        <div
                          className="pointer-events-none absolute -right-12 -top-12 h-32 w-32 rounded-full bg-gradient-to-br from-indigo-500/[0.06] to-transparent opacity-0 blur-2xl transition duration-300 group-hover:opacity-100"
                          aria-hidden
                        />
                        <div className="relative flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-indigo-700/85">
                                Phase {idx + 1}
                              </span>
                              {windowLabel && (
                                <span className="inline-flex items-center gap-1 rounded-full border border-slate-200/90 bg-slate-50/90 px-2 py-0.5 text-[10px] font-semibold tabular-nums text-slate-700 ring-1 ring-slate-900/[0.04]">
                                  <Clock3 className="h-3 w-3 text-slate-500" aria-hidden />
                                  {windowLabel}
                                </span>
                              )}
                            </div>
                            <h4 className="mt-2 text-balance text-base font-semibold leading-snug tracking-tight text-slate-900 sm:text-lg">
                              {heading}
                            </h4>
                          </div>
                          {idx < parsed.roadmap.length - 1 && (
                            <ArrowRight
                              className="hidden h-4 w-4 shrink-0 text-slate-300 transition group-hover:text-indigo-400 lg:block"
                              aria-hidden
                            />
                          )}
                        </div>

                        <ul className="relative mt-4 space-y-2.5 border-t border-slate-100/90 pt-4">
                          {phase.items.length > 0 ? (
                            phase.items.map((it, i) => (
                              <li
                                key={i}
                                className="flex gap-3 text-[13px] leading-relaxed text-slate-700"
                              >
                                <span className="mt-1.5 flex h-1.5 w-1.5 shrink-0 rounded-full bg-gradient-to-br from-indigo-500 to-violet-500 ring-2 ring-indigo-500/15" aria-hidden />
                                <span>{it}</span>
                              </li>
                            ))
                          ) : (
                            <li className="text-xs text-slate-500">No details provided.</li>
                          )}
                        </ul>
                      </div>
                    </div>
                  </li>
                );
              })}
            </ol>
          </div>
        )}
      </section>

      <section className="bg-white px-5 py-7 sm:px-8">
        <div className="mb-4 flex items-baseline gap-3 border-b border-slate-200/80 pb-3">
          <span className="font-mono text-xs font-medium text-indigo-500/80 tabular-nums">{sectionIndex.risks}</span>
          <h3 className="text-sm font-semibold uppercase tracking-[0.1em] text-slate-800">Risks &amp; mitigations</h3>
        </div>
        {parsed.risks.length > 0 ? (
          <div className="overflow-x-auto rounded-xl border border-slate-200/70 shadow-sm">
            <table className="w-full min-w-[520px] border-collapse text-left text-[13px]">
              <thead>
                <tr className="border-b border-slate-200/80 bg-gradient-to-r from-slate-100/95 to-slate-50/90 text-[10px] font-semibold uppercase tracking-wider text-slate-600">
                  <th className="w-[40%] px-3 py-2.5">Risk</th>
                  <th className="px-3 py-2.5">Mitigation</th>
                </tr>
              </thead>
              <tbody>
                {parsed.risks.map((r, idx) => (
                  <tr
                    key={idx}
                    className="border-b border-slate-100/90 last:border-0 odd:bg-white even:bg-slate-50/40"
                  >
                    <td className="align-top px-3 py-3 font-medium text-slate-900">{r.risk}</td>
                    <td className="align-top px-3 py-3 text-slate-700">{r.mitigation}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-slate-500">No risks extracted from the response.</p>
        )}
      </section>

      <footer className="border-t border-slate-200/60 bg-slate-50/90 px-5 py-3.5 sm:px-8">
        <p className="text-[10px] leading-relaxed text-slate-500">
          Generated for planning and discussion. Validate assumptions with business and technical owners before commitment.
        </p>
      </footer>
    </article>
  );
}
