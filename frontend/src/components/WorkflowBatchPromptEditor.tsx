import {
  useCallback,
  useMemo,
  useState,
  type ChangeEvent,
  type KeyboardEvent,
} from 'react';
import { Check, Copy } from 'lucide-react';

const TAB_SPACES = '  ';

function lineColAt(text: string, caret: number): { line: number; col: number } {
  const head = text.slice(0, Math.min(caret, text.length));
  const lines = head.split('\n');
  const line = lines.length;
  const last = lines[lines.length - 1] ?? '';
  return { line, col: last.length + 1 };
}

export interface WorkflowBatchPromptEditorProps {
  id: string;
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
}

export default function WorkflowBatchPromptEditor({
  id,
  value,
  onChange,
  placeholder = 'Edit the prompt that will be sent…',
}: WorkflowBatchPromptEditorProps) {
  const [scrollTop, setScrollTop] = useState(0);
  const [copied, setCopied] = useState(false);
  const [caretPos, setCaretPos] = useState(() => value.length);

  const lineCount = useMemo(() => {
    if (!value) return 1;
    return value.split('\n').length;
  }, [value]);

  const gutterText = useMemo(() => {
    const n = Math.max(1, lineCount);
    return Array.from({ length: n }, (_, i) => String(i + 1)).join('\n');
  }, [lineCount]);

  const handleChange = useCallback(
    (e: ChangeEvent<HTMLTextAreaElement>) => {
      onChange(e.target.value);
      setCaretPos(e.target.selectionStart ?? 0);
    },
    [onChange],
  );

  const syncCaret = useCallback((e: Pick<HTMLTextAreaElement, 'selectionStart'>) => {
    setCaretPos(Math.min(Math.max(0, e.selectionStart ?? 0), value.length));
  }, [value]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key !== 'Tab') return;
      e.preventDefault();
      const el = e.currentTarget;
      const start = el.selectionStart;
      const end = el.selectionEnd;
      const next = value.slice(0, start) + TAB_SPACES + value.slice(end);
      onChange(next);
      requestAnimationFrame(() => {
        const pos = start + TAB_SPACES.length;
        el.selectionStart = el.selectionEnd = pos;
        setCaretPos(pos);
      });
    },
    [value, onChange],
  );

  const handleCopy = useCallback(() => {
    void navigator.clipboard.writeText(value).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    });
  }, [value]);

  const lineColCaret = useMemo(() => {
    const c = Math.min(Math.max(0, caretPos), value.length);
    return lineColAt(value, c);
  }, [value, caretPos]);
  const chars = value.length;

  return (
    <div className="overflow-hidden rounded-xl border border-gray-200 dark:border-white/[0.1] bg-white dark:bg-black/25 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)] ring-1 ring-gray-200 dark:ring-white/[0.03]">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-zinc-900/50 px-2.5 py-1.5">
        <p className="font-body text-[10px] text-zinc-500">
          <span className="tabular-nums text-zinc-400">
            Ln {lineColCaret.line}, Col {lineColCaret.col}
          </span>
          <span className="mx-1.5 text-zinc-700">·</span>
          <span className="tabular-nums">{lineCount} lines</span>
          <span className="mx-1.5 text-zinc-700">·</span>
          <span className="tabular-nums">{chars} chars</span>
          <span className="mx-1.5 text-zinc-700">·</span>
          <span className="text-zinc-600">Tab inserts spaces</span>
        </p>
        <button
          type="button"
          onClick={handleCopy}
          className="inline-flex items-center gap-1 rounded-lg border border-gray-200 dark:border-white/[0.08] bg-gray-100 dark:bg-white/[0.04] px-2 py-1 font-body text-[10px] font-medium text-zinc-300 transition hover:border-teal-500/25 hover:bg-teal-500/10 hover:text-teal-200 focus:outline-none focus-visible:ring-1 focus-visible:ring-teal-500/35"
          aria-label="Copy to clipboard"
        >
          {copied ? (
            <>
              <Check className="h-3 w-3 text-teal-400" strokeWidth={2.5} />
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

      <div className="grid min-h-[10.5rem] max-h-[28rem] w-full grid-cols-[minmax(2rem,auto)_1fr]">
        <div
          className="relative min-h-[10.5rem] overflow-hidden border-r border-gray-200 dark:border-white/[0.06] bg-zinc-950/85"
          aria-hidden
        >
          <pre
            className="pointer-events-none m-0 select-none whitespace-pre px-2 py-2.5 pr-1 text-right font-mono text-[12px] leading-relaxed text-zinc-600"
            style={{ transform: `translateY(-${scrollTop}px)` }}
          >
            {gutterText}
          </pre>
        </div>
        <textarea
          id={id}
          value={value}
          spellCheck={false}
          placeholder={placeholder}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onKeyUp={(e) => syncCaret(e.currentTarget)}
          onMouseUp={(e) => syncCaret(e.currentTarget)}
          onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
          onSelect={(e) => syncCaret(e.currentTarget)}
          onBlur={(e) => syncCaret(e.currentTarget)}
          rows={8}
          className="min-h-[10.5rem] max-h-[28rem] w-full resize-y border-0 bg-transparent px-2.5 py-2.5 pl-2 font-mono text-[12px] leading-relaxed text-zinc-100 caret-teal-400 placeholder:text-zinc-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-teal-500/20 selection:bg-teal-500/25"
          style={{ tabSize: 2 }}
        />
      </div>
    </div>
  );
}
