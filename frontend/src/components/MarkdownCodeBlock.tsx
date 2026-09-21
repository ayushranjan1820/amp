import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import { Check, Copy, Play, Loader2 } from 'lucide-react';
import { format } from 'sql-formatter';
import { getMarkdownHighlighter, mapFenceToShikiLang, markdownShikiTheme } from './markdownShiki';

type MarkdownCodeBlockProps = {
  language: string;
  code: string;
  /** Browser Automation Agent: show “Run script” next to Copy */
  showRunScriptButton?: boolean;
  runScriptLabel?: string;
  onRunScript?: () => void;
  runScriptDisabled?: boolean;
  runScriptPending?: boolean;
};

function formatLanguageLabel(lang: string): string {
  if (!lang) return 'Code';
  const map: Record<string, string> = {
    sql: 'SQL',
    ts: 'TypeScript',
    tsx: 'TSX',
    js: 'JavaScript',
    jsx: 'JSX',
    py: 'Python',
    json: 'JSON',
    yaml: 'YAML',
    yml: 'YAML',
    bash: 'Shell',
    sh: 'Shell',
    xml: 'XML',
    html: 'HTML',
    css: 'CSS',
    md: 'Markdown',
  };
  const key = lang.toLowerCase();
  if (map[key]) return map[key];
  return key.charAt(0).toUpperCase() + key.slice(1);
}

const SQL_LANG_TAGS = new Set([
  'sql',
  'postgresql',
  'postgres',
  'mysql',
  'mariadb',
  'sqlite',
  'tsql',
  'mssql',
  'sqlserver',
  'transactsql',
  'plsql',
  'bigquery',
  'snowflake',
]);

function sqlFormatterLanguage(tag: string): 'postgresql' | 'mysql' | 'sqlite' | 'transactsql' | 'plsql' | 'sql' {
  const t = tag.toLowerCase();
  if (t === 'mysql' || t === 'mariadb') return 'mysql';
  if (t === 'sqlite') return 'sqlite';
  if (t === 'tsql' || t === 'mssql' || t === 'sqlserver' || t === 'transactsql') return 'transactsql';
  if (t === 'plsql') return 'plsql';
  if (t === 'postgres' || t === 'postgresql') return 'postgresql';
  if (t === 'sql') return 'sql';
  return 'sql';
}

function formatSqlForDisplay(raw: string, dialectTag: string): string {
  const trimmed = raw.replace(/\n$/, '').trim();
  if (!trimmed) return '';

  const dialect = sqlFormatterLanguage(dialectTag);
  const stepChunks = trimmed.split(/(?=^\s*--\s*Step\s+\d+)/m).map((c) => c.trim()).filter(Boolean);

  const formatOne = (chunk: string) => {
    try {
      return format(chunk, {
        language: dialect,
        tabWidth: 2,
        keywordCase: 'upper',
        indentStyle: 'standard',
        expressionWidth: 44,
        linesBetweenQueries: 2,
      });
    } catch {
      return chunk;
    }
  };

  if (stepChunks.length > 1) {
    return stepChunks.map(formatOne).join('\n\n');
  }

  return formatOne(trimmed);
}

function subscribeHtmlDark(onStoreChange: () => void) {
  const el = document.documentElement;
  const mo = new MutationObserver(onStoreChange);
  mo.observe(el, { attributes: true, attributeFilter: ['class'] });
  const mq = window.matchMedia('(prefers-color-scheme: dark)');
  mq.addEventListener('change', onStoreChange);
  return () => {
    mo.disconnect();
    mq.removeEventListener('change', onStoreChange);
  };
}

function getHtmlDarkSnapshot() {
  return document.documentElement.classList.contains('dark');
}

function getServerHtmlDarkSnapshot() {
  return false;
}

function useChatDarkMode() {
  return useSyncExternalStore(subscribeHtmlDark, getHtmlDarkSnapshot, getServerHtmlDarkSnapshot);
}

type HighlightState = { mode: 'html'; html: string } | { mode: 'plain' } | null;

/**
 * Fenced code block for chat markdown — Shiki highlighting, line gutter, copy.
 */
export default function MarkdownCodeBlock({
  language,
  code,
  showRunScriptButton = false,
  runScriptLabel = 'Run script',
  onRunScript,
  runScriptDisabled = false,
  runScriptPending = false,
}: MarkdownCodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const langLower = language.toLowerCase();
  const isSql = SQL_LANG_TAGS.has(langLower);

  const displayText = useMemo(() => {
    const raw = code.replace(/\n$/, '');
    if (isSql) {
      return formatSqlForDisplay(raw, langLower);
    }
    return raw;
  }, [code, isSql, langLower]);

  const copy = useCallback(() => {
    void navigator.clipboard?.writeText(displayText).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    });
  }, [displayText]);

  const label = formatLanguageLabel(language);
  const isDark = useChatDarkMode();
  const shikiLang = useMemo(() => mapFenceToShikiLang(langLower), [langLower]);
  const [highlight, setHighlight] = useState<HighlightState>(null);

  useEffect(() => {
    let cancelled = false;
    setHighlight(null);

    if (!displayText) {
      setHighlight({ mode: 'plain' });
      return;
    }

    void (async () => {
      try {
        const highlighter = await getMarkdownHighlighter();
        const html = highlighter.codeToHtml(displayText, {
          lang: shikiLang,
          theme: markdownShikiTheme(isDark),
          tabindex: false,
        });
        if (!cancelled) setHighlight({ mode: 'html', html });
      } catch {
        if (!cancelled) setHighlight({ mode: 'plain' });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [displayText, shikiLang, isDark]);

  const scrollSurface =
    highlight?.mode === 'html'
      ? 'bg-transparent [scrollbar-color:rgba(100,116,139,0.35)_transparent]'
      : 'bg-[#f4f5f7] [scrollbar-color:rgba(100,116,139,0.45)_transparent] dark:bg-[#0c0c0f]';

  return (
    <div className="my-2 overflow-hidden not-prose font-body rounded-xl border border-gray-200/80 bg-white/95 shadow-[0_1px_2px_rgba(0,0,0,0.04),0_8px_24px_-6px_rgba(0,0,0,0.1)] ring-1 ring-black/[0.03] backdrop-blur-[2px] dark:border-gray-800 dark:bg-gray-950/95 dark:shadow-[0_1px_0_rgba(255,255,255,0.04)_inset,0_12px_40px_-10px_rgba(0,0,0,0.5)] dark:ring-white/[0.06]">
      <div className="flex items-center justify-between gap-2 border-b border-gray-200/70 bg-gradient-to-b from-gray-50 to-gray-100/90 px-2.5 py-1.5 dark:border-gray-800/90 dark:from-gray-900 dark:to-gray-950/80">
        <div className="flex min-w-0 items-center gap-2">
          <span
            className="h-1.5 w-1.5 shrink-0 rounded-full bg-gradient-to-br from-primary-400 to-primary-600 shadow-[0_0_0_1px_rgba(0,0,0,0.06)] dark:from-primary-500 dark:to-primary-700 dark:shadow-[0_0_0_1px_rgba(255,255,255,0.08)]"
            aria-hidden
          />
          <span className="truncate text-[11px] font-semibold tracking-tight text-gray-800 dark:text-gray-100">
            {label}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {showRunScriptButton && onRunScript ? (
            <button
              type="button"
              onClick={onRunScript}
              disabled={runScriptDisabled || runScriptPending}
              title="Run this script on the server (same Python environment as the agent)"
              className="inline-flex shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-[10px] font-medium text-primary-700 transition-[color,background-color,transform,box-shadow] hover:bg-primary-500/10 hover:text-primary-800 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-45 dark:text-primary-300 dark:hover:bg-primary-500/15 dark:hover:text-primary-200"
            >
              {runScriptPending ? (
                <>
                  <Loader2 className="h-3 w-3 animate-spin opacity-90" strokeWidth={2} />
                  Running…
                </>
              ) : (
                <>
                  <Play className="h-3 w-3 opacity-90" strokeWidth={2} />
                  {runScriptLabel}
                </>
              )}
            </button>
          ) : null}
          <button
            type="button"
            onClick={copy}
            className="inline-flex shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-[10px] font-medium text-gray-600 transition-[color,background-color,transform,box-shadow] hover:bg-gray-900/[0.06] hover:text-gray-900 active:scale-[0.98] dark:text-gray-400 dark:hover:bg-white/[0.08] dark:hover:text-gray-100"
          >
            {copied ? (
              <>
                <Check className="h-3 w-3 text-green-600 dark:text-green-400" strokeWidth={2.25} />
                Copied
              </>
            ) : (
              <>
                <Copy className="h-3 w-3 opacity-70" strokeWidth={2} />
                Copy
              </>
            )}
          </button>
        </div>
      </div>
      <div
        className={`max-h-[min(360px,48vh)] overflow-x-auto overflow-y-auto [scrollbar-width:thin] [&::-webkit-scrollbar]:h-1.5 [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-gray-400/45 dark:[&::-webkit-scrollbar-thumb]:bg-gray-600/55 ${scrollSurface}`}
        style={{ scrollbarGutter: 'stable' }}
      >
        {highlight?.mode === 'html' ? (
          <div className="markdown-code-shiki selection:bg-primary-500/20 dark:selection:bg-primary-500/25" dangerouslySetInnerHTML={{ __html: highlight.html }} />
        ) : (
          <pre className="m-0 px-2 py-1.5 font-mono text-[12px] leading-[1.05] tracking-[-0.01em] text-gray-800 tabular-nums antialiased selection:bg-primary-500/20 dark:text-gray-200 dark:selection:bg-primary-500/25 sm:px-2.5 sm:py-1.5">
            <code className="block whitespace-pre text-left break-normal [overflow-wrap:normal]">{displayText}</code>
          </pre>
        )}
      </div>
    </div>
  );
}
