import { useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Copy,
  Check,
  FileText,
  ChevronDown,
  ChevronRight,
  ClipboardList,
  FlaskConical,
  Code2,
  LayoutList,
  Globe,
  Download,
  Play,
  Loader2,
} from 'lucide-react';
import { runWebTestPlaywrightSpec, type WebTestPlaywrightRunResult } from '../services/api';

interface TestReportViewProps {
  content: string;
  /** When true, Playwright report sections show Run / Download for TypeScript specs (Web Test Agent chat). */
  enablePlaywrightRunner?: boolean;
}

/** Extract first fenced TypeScript/JavaScript block that looks like a Playwright test file. */
export function extractPlaywrightSpecFromMarkdown(md: string): string | null {
  const fence = /```(?:typescript|ts|tsx|javascript|js|jsx)\s*\r?\n([\s\S]*?)```/gi;
  let m: RegExpExecArray | null;
  while ((m = fence.exec(md)) !== null) {
    const body = m[1].trim();
    if (!body.includes('@playwright/test')) continue;
    if (!body.includes('test(') && !body.includes('test.describe')) continue;
    return body;
  }
  return null;
}

interface Section {
  id: string;
  title: string;
  icon: any;
  content: string;
  color: string;
}

function parseTestReport(content: string): { meta: Record<string, string>; sections: Section[] } {
  const meta: Record<string, string> = {};

  const urlMatch = content.match(/\*\*Application URL:\*\*\s*(\S+)/);
  if (urlMatch) meta.url = urlMatch[1];

  const titleMatch = content.match(/^#\s+Test Report:\s*(.+)$/m);
  if (titleMatch) meta.title = titleMatch[1].trim();

  const icons: Record<string, any> = {
    'executive summary': Globe,
    'feature inventory': LayoutList,
    'manual test cases': ClipboardList,
    'automated test cases': FlaskConical,
    'automated test matrix': FlaskConical,
    'selenium test script': Code2,
    'playwright test script': Code2,
  };

  const colors: Record<string, string> = {
    'executive summary': 'blue',
    'feature inventory': 'emerald',
    'manual test cases': 'orange',
    'automated test cases': 'purple',
    'automated test matrix': 'purple',
    'selenium test script': 'rose',
    'playwright test script': 'cyan',
  };

  const sectionRegex = /^##\s+\d+\.\s+(.+)$/gm;
  const matches: { title: string; index: number }[] = [];
  let match;

  while ((match = sectionRegex.exec(content)) !== null) {
    matches.push({ title: match[1].trim(), index: match.index });
  }

  const sections: Section[] = matches.map((m, i) => {
    const end = i < matches.length - 1 ? matches[i + 1].index : content.length;
    const sectionContent = content.slice(m.index, end).replace(/^##\s+\d+\.\s+.+$/m, '').trim();

    const key = m.title.toLowerCase();
    const iconKey = Object.keys(icons).find(k => key.includes(k)) || '';
    const colorKey = Object.keys(colors).find(k => key.includes(k)) || '';

    return {
      id: `section-${i}`,
      title: m.title,
      icon: icons[iconKey] || FileText,
      content: sectionContent,
      color: colors[colorKey] || 'gray',
    };
  });

  return { meta, sections };
}

function SectionCard({
  section,
  defaultOpen,
  enablePlaywrightRunner = false,
}: {
  section: Section;
  defaultOpen: boolean;
  enablePlaywrightRunner?: boolean;
}) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  const [copied, setCopied] = useState(false);
  const [runBusy, setRunBusy] = useState(false);
  const [runResult, setRunResult] = useState<WebTestPlaywrightRunResult | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const Icon = section.icon;

  const isPlaywrightSection = section.title.toLowerCase().includes('playwright');
  const extractedSpec = useMemo(() => {
    if (!enablePlaywrightRunner || !isPlaywrightSection) return null;
    return extractPlaywrightSpecFromMarkdown(section.content);
  }, [enablePlaywrightRunner, isPlaywrightSection, section.content]);

  const handleDownloadSpec = () => {
    if (!extractedSpec) return;
    const blob = new Blob([extractedSpec], { type: 'text/typescript;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'web-test-playwright.spec.ts';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleRunSpec = async () => {
    if (!extractedSpec || runBusy) return;
    setRunBusy(true);
    setRunError(null);
    setRunResult(null);
    try {
      const res = await runWebTestPlaywrightSpec(extractedSpec, { headed: true, timeoutSec: 600 });
      setRunResult(res);
    } catch (e: unknown) {
      setRunError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunBusy(false);
    }
  };

  const handleCopySection = async () => {
    try {
      await navigator.clipboard.writeText(section.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Copy failed:', err);
    }
  };

  const colorMap: Record<string, { bg: string; border: string; text: string; icon: string; badge: string }> = {
    blue: { bg: 'bg-blue-50 dark:bg-blue-950/30', border: 'border-blue-200 dark:border-blue-800', text: 'text-blue-700 dark:text-blue-300', icon: 'text-blue-500', badge: 'bg-blue-100 dark:bg-blue-900/50 text-blue-700 dark:text-blue-300' },
    emerald: { bg: 'bg-emerald-50 dark:bg-emerald-950/30', border: 'border-emerald-200 dark:border-emerald-800', text: 'text-emerald-700 dark:text-emerald-300', icon: 'text-emerald-500', badge: 'bg-emerald-100 dark:bg-emerald-900/50 text-emerald-700 dark:text-emerald-300' },
    orange: { bg: 'bg-orange-50 dark:bg-orange-950/30', border: 'border-orange-200 dark:border-orange-800', text: 'text-orange-700 dark:text-orange-300', icon: 'text-orange-500', badge: 'bg-orange-100 dark:bg-orange-900/50 text-orange-700 dark:text-orange-300' },
    purple: { bg: 'bg-purple-50 dark:bg-purple-950/30', border: 'border-purple-200 dark:border-purple-800', text: 'text-purple-700 dark:text-purple-300', icon: 'text-purple-500', badge: 'bg-purple-100 dark:bg-purple-900/50 text-purple-700 dark:text-purple-300' },
    rose: { bg: 'bg-rose-50 dark:bg-rose-950/30', border: 'border-rose-200 dark:border-rose-800', text: 'text-rose-700 dark:text-rose-300', icon: 'text-rose-500', badge: 'bg-rose-100 dark:bg-rose-900/50 text-rose-700 dark:text-rose-300' },
    cyan: { bg: 'bg-cyan-50 dark:bg-cyan-950/30', border: 'border-cyan-200 dark:border-cyan-800', text: 'text-cyan-700 dark:text-cyan-300', icon: 'text-cyan-500', badge: 'bg-cyan-100 dark:bg-cyan-900/50 text-cyan-700 dark:text-cyan-300' },
    gray: { bg: 'bg-gray-50 dark:bg-gray-950/30', border: 'border-gray-200 dark:border-gray-800', text: 'text-gray-700 dark:text-gray-300', icon: 'text-gray-500', badge: 'bg-gray-100 dark:bg-gray-900/50 text-gray-700 dark:text-gray-300' },
  };

  const c = colorMap[section.color] || colorMap.gray;

  return (
    <div className={`rounded-xl border ${c.border} overflow-hidden transition-all duration-200`}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={`w-full flex items-center gap-3 px-4 py-3 ${isOpen ? c.bg : 'bg-white dark:bg-gray-900'} hover:${c.bg} transition-colors`}
      >
        <div className={`flex items-center justify-center w-8 h-8 rounded-lg ${c.badge}`}>
          <Icon className={`w-4 h-4`} />
        </div>
        <span className={`flex-1 text-left text-sm font-semibold ${c.text}`}>
          {section.title}
        </span>
        {isOpen ? (
          <ChevronDown className="w-4 h-4 text-gray-400" />
        ) : (
          <ChevronRight className="w-4 h-4 text-gray-400" />
        )}
      </button>

      {isOpen && (
        <div className="border-t border-gray-100 dark:border-gray-800">
          <div className="flex flex-wrap justify-end gap-2 px-4 pt-2">
            {enablePlaywrightRunner && isPlaywrightSection && extractedSpec && (
              <>
                <button
                  type="button"
                  onClick={() => { void handleRunSpec(); }}
                  disabled={runBusy}
                  className="flex items-center gap-1 px-2 py-1 text-[10px] font-medium rounded-md bg-cyan-600 hover:bg-cyan-700 disabled:opacity-50 text-white transition-colors"
                >
                  {runBusy ? (
                    <><Loader2 className="w-3 h-3 animate-spin" /><span>Running…</span></>
                  ) : (
                    <><Play className="w-3 h-3" /><span>Run in browser</span></>
                  )}
                </button>
                <button
                  type="button"
                  onClick={handleDownloadSpec}
                  className="flex items-center gap-1 px-2 py-1 text-[10px] font-medium rounded-md bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-600 dark:text-gray-400 transition-colors"
                >
                  <Download className="w-3 h-3" />
                  <span>Download .spec.ts</span>
                </button>
              </>
            )}
            <button
              onClick={handleCopySection}
              className="flex items-center gap-1 px-2 py-1 text-[10px] font-medium rounded-md bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-600 dark:text-gray-400 transition-colors"
            >
              {copied ? (
                <><Check className="w-3 h-3 text-green-500" /><span>Copied</span></>
              ) : (
                <><Copy className="w-3 h-3" /><span>Copy</span></>
              )}
            </button>
          </div>
          <div className="px-5 pb-5 pt-1">
            <div className="prose prose-sm dark:prose-invert max-w-none test-report-content">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  a: ({ href, children }) => (
                    <a href={href} target="_blank" rel="noopener noreferrer" className="text-orange-600 dark:text-orange-400 underline">{children}</a>
                  ),
                  table: ({ children }) => (
                    <div className="overflow-x-auto my-3 rounded-lg border border-gray-200 dark:border-gray-700">
                      <table className="min-w-full text-xs">{children}</table>
                    </div>
                  ),
                  thead: ({ children }) => (
                    <thead className="bg-gray-100 dark:bg-gray-800">{children}</thead>
                  ),
                  th: ({ children }) => (
                    <th className="px-3 py-2 text-left text-[11px] font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider border-b border-gray-200 dark:border-gray-700">{children}</th>
                  ),
                  td: ({ children }) => (
                    <td className="px-3 py-2 text-xs text-gray-700 dark:text-gray-300 border-b border-gray-100 dark:border-gray-800">{children}</td>
                  ),
                  tr: ({ children }) => (
                    <tr className="hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">{children}</tr>
                  ),
                  code: ({ children, className }) => {
                    const isBlock = className?.includes('language-');
                    if (isBlock) {
                      const lang = className?.replace('language-', '') || '';
                      return (
                        <div className="relative group my-3">
                          <div className="flex items-center justify-between px-3 py-1.5 bg-gray-900 dark:bg-gray-950 rounded-t-lg border border-b-0 border-gray-700">
                            <span className="text-[10px] font-mono text-gray-400 uppercase">{lang}</span>
                          </div>
                          <div className="bg-gray-900 dark:bg-gray-950 rounded-b-lg border border-t-0 border-gray-700 overflow-x-auto">
                            <pre className="p-3 text-xs leading-relaxed"><code className="text-gray-200">{children}</code></pre>
                          </div>
                        </div>
                      );
                    }
                    return <code className="bg-gray-200 dark:bg-gray-800 px-1.5 py-0.5 rounded text-orange-600 dark:text-orange-400 text-[11px] font-mono">{children}</code>;
                  },
                  pre: ({ children }) => <>{children}</>,
                  h3: ({ children }) => (
                    <h3 className="text-sm font-bold text-gray-800 dark:text-gray-200 mt-5 mb-2 pb-1 border-b border-gray-200 dark:border-gray-700">{children}</h3>
                  ),
                  h4: ({ children }) => (
                    <h4 className="text-xs font-bold text-gray-700 dark:text-gray-300 mt-3 mb-1">{children}</h4>
                  ),
                  strong: ({ children }) => (
                    <strong className="font-semibold text-gray-900 dark:text-white">{children}</strong>
                  ),
                }}
              >{section.content}</ReactMarkdown>
            </div>
            {(runError || runResult) && (
              <div className="mt-4 mx-5 mb-4 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900/80 p-3 text-xs">
                <div className="font-semibold text-gray-800 dark:text-gray-200 mb-2">Playwright run</div>
                {runError && (
                  <pre className="text-rose-600 dark:text-rose-400 whitespace-pre-wrap font-mono text-[11px]">{runError}</pre>
                )}
                {runResult && !runError && (
                  <div className="space-y-2 text-gray-700 dark:text-gray-300">
                    <div className="flex flex-wrap gap-2 text-[11px]">
                      <span className={runResult.success ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'}>
                        {runResult.success ? 'Passed' : 'Failed'}
                      </span>
                      {runResult.exit_code !== null && runResult.exit_code !== undefined && (
                        <span className="text-gray-500">exit {runResult.exit_code}</span>
                      )}
                    </div>
                    {runResult.message && (
                      <p className="text-amber-700 dark:text-amber-300 text-[11px]">{runResult.message}</p>
                    )}
                    <details className="group">
                      <summary className="cursor-pointer text-cyan-600 dark:text-cyan-400 text-[11px]">stdout</summary>
                      <pre className="mt-1 max-h-48 overflow-auto p-2 rounded bg-gray-100 dark:bg-gray-950 text-[10px] font-mono">{runResult.stdout}</pre>
                    </details>
                    <details className="group">
                      <summary className="cursor-pointer text-cyan-600 dark:text-cyan-400 text-[11px]">stderr</summary>
                      <pre className="mt-1 max-h-48 overflow-auto p-2 rounded bg-gray-100 dark:bg-gray-950 text-[10px] font-mono">{runResult.stderr}</pre>
                    </details>
                    <p className="text-[10px] text-gray-500 dark:text-gray-400 pt-1">
                      The browser opens on the machine running the API (your dev PC if localhost). Node.js and a first-time Playwright browser download are required.
                    </p>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function TestReportView({ content, enablePlaywrightRunner = false }: TestReportViewProps) {
  const { meta, sections } = parseTestReport(content);
  const [copiedAll, setCopiedAll] = useState(false);

  const handleCopyAll = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopiedAll(true);
      setTimeout(() => setCopiedAll(false), 2000);
    } catch (err) {
      console.error('Copy failed:', err);
    }
  };

  const handleDownload = () => {
    const blob = new Blob([content], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `test-report-${Date.now()}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="w-full">
      <div className="rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden bg-white dark:bg-gray-900 shadow-sm">
        <div className="bg-gradient-to-r from-orange-600 to-orange-500 px-5 py-4">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-3">
              <div className="flex items-center justify-center w-10 h-10 bg-white/20 rounded-xl backdrop-blur-sm">
                <FlaskConical className="w-5 h-5 text-white" />
              </div>
              <div>
                <h2 className="text-white font-bold text-base leading-tight">
                  {meta.title || 'Test Report'}
                </h2>
                <p className="text-orange-100 text-xs mt-0.5">
                  QA Test Report — Web Test Agent
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={handleDownload}
                className="flex items-center gap-1.5 px-2.5 py-1.5 text-[11px] font-medium rounded-lg bg-white/15 hover:bg-white/25 text-white transition-colors backdrop-blur-sm"
              >
                <Download className="w-3 h-3" />
                <span>Download</span>
              </button>
              <button
                onClick={handleCopyAll}
                className="flex items-center gap-1.5 px-2.5 py-1.5 text-[11px] font-medium rounded-lg bg-white/15 hover:bg-white/25 text-white transition-colors backdrop-blur-sm"
              >
                {copiedAll ? (
                  <><Check className="w-3 h-3" /><span>Copied!</span></>
                ) : (
                  <><Copy className="w-3 h-3" /><span>Copy All</span></>
                )}
              </button>
            </div>
          </div>

          {meta.url && (
            <div className="mt-3 flex items-center gap-2 bg-white/10 rounded-lg px-3 py-2 backdrop-blur-sm">
              <Globe className="w-3.5 h-3.5 text-orange-200" />
              <a href={meta.url} target="_blank" rel="noopener noreferrer" className="text-xs text-orange-100 hover:text-white font-mono truncate">
                {meta.url}
              </a>
            </div>
          )}
        </div>

        <div className="flex items-center gap-4 px-5 py-3 bg-gray-50 dark:bg-gray-800/50 border-b border-gray-200 dark:border-gray-700">
          <div className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
            <ClipboardList className="w-3.5 h-3.5" />
            <span>{sections.length} sections</span>
          </div>
          <div className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
            <FileText className="w-3.5 h-3.5" />
            <span>Generated report</span>
          </div>
        </div>

        <div className="p-4 space-y-3 bg-gray-50/50 dark:bg-gray-950/50">
          {sections.map((section, i) => (
            <SectionCard
              key={section.id}
              section={section}
              defaultOpen={i < 2}
              enablePlaywrightRunner={enablePlaywrightRunner}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

export function isTestReport(content: string): boolean {
  const markers = [
    '# Test Report:',
    '## 2. Feature Inventory',
    '## 3. Manual Test Cases',
    'Selenium Test Script',
    'Playwright Test Script',
  ];
  let matchCount = 0;
  for (const marker of markers) {
    if (content.includes(marker)) matchCount++;
  }
  return matchCount >= 2;
}
