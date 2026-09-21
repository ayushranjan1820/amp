import {
  Children,
  Fragment,
  isValidElement,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { ChevronLeft, ChevronRight, Download } from 'lucide-react';

const DEFAULT_PAGE_SIZE = 10;

function csvEscapeCell(value: string): string {
  if (/[",\r\n]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

function buildCsv(headers: string[], rows: string[][]): string {
  const lines: string[] = [];
  lines.push(headers.map((h) => csvEscapeCell(h ?? '')).join(','));
  const n = headers.length;
  for (const row of rows) {
    const padded = row.slice(0, n);
    while (padded.length < n) padded.push('');
    lines.push(padded.map((c) => csvEscapeCell(c ?? '')).join(','));
  }
  return `\uFEFF${lines.join('\r\n')}`;
}

function downloadCsvFile(filename: string, csv: string) {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function cellText(node: ReactNode): string {
  if (node == null || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(cellText).join('');
  if (isValidElement(node)) {
    return cellText((node.props as { children?: ReactNode }).children);
  }
  return '';
}

type ParseOk = { headers: string[]; rows: string[][]; rawFallback: false };
type ParseFallback = { rawFallback: true };

function parseTableChildren(children: ReactNode): ParseOk | ParseFallback {
  const headers: string[] = [];
  const bodyRows: string[][] = [];

  const consumeTr = (tr: ReactNode, asHeader: boolean) => {
    if (!isValidElement(tr) || tr.type !== 'tr') return;
    const cells: string[] = [];
    Children.forEach((tr.props as { children?: ReactNode }).children, (cell) => {
      if (!isValidElement(cell)) return;
      const t = cell.type;
      if (t === 'th' || t === 'td') {
        cells.push(cellText((cell.props as { children?: ReactNode }).children).trim());
      }
    });
    if (!cells.length) return;
    if (asHeader) {
      headers.push(...cells);
    } else {
      bodyRows.push(cells);
    }
  };

  const walkThead = (thead: ReactNode) => {
    if (!isValidElement(thead) || thead.type !== 'thead') return;
    Children.forEach((thead.props as { children?: ReactNode }).children, (tr) => {
      consumeTr(tr, true);
    });
  };

  const walkTbody = (tbody: ReactNode) => {
    if (!isValidElement(tbody) || tbody.type !== 'tbody') return;
    Children.forEach((tbody.props as { children?: ReactNode }).children, (tr) => {
      consumeTr(tr, false);
    });
  };

  const walkSections = (nodes: ReactNode) => {
    Children.forEach(nodes, (section) => {
      if (!isValidElement(section)) return;
      if (section.type === Fragment) {
        walkSections((section.props as { children?: ReactNode }).children);
        return;
      }
      if (section.type === 'thead') walkThead(section);
      else if (section.type === 'tbody') walkTbody(section);
    });
  };
  walkSections(children);

  let h = [...headers];
  let r = [...bodyRows];

  if (!h.length && r.length) {
    h = r[0];
    r = r.slice(1);
  }

  if (!h.length && !r.length) {
    return { rawFallback: true };
  }

  if (!h.length) {
    const maxCols = Math.max(0, ...r.map((row) => row.length));
    h = Array.from({ length: maxCols }, (_, i) => `Column ${i + 1}`);
  }

  return { headers: h, rows: r, rawFallback: false };
}

type PaginatedMarkdownTableProps = {
  children: ReactNode;
  pageSize?: number;
};

/**
 * Renders markdown tables with client-side pagination and updated styling.
 * Falls back to a styled native table if the structure cannot be parsed.
 */
export default function PaginatedMarkdownTable({
  children,
  pageSize = DEFAULT_PAGE_SIZE,
}: PaginatedMarkdownTableProps) {
  const parsed = useMemo(() => parseTableChildren(children), [children]);
  const [page, setPage] = useState(0);

  if (parsed.rawFallback) {
    return (
      <div className="my-3 rounded-xl border border-gray-200/90 dark:border-gray-700/90 bg-white/80 dark:bg-gray-900/60 shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full border-collapse text-sm font-body">
            {children}
          </table>
        </div>
      </div>
    );
  }

  const { headers, rows } = parsed;
  const total = rows.length;
  const totalPages = total === 0 ? 1 : Math.max(1, Math.ceil(total / pageSize));

  useEffect(() => {
    setPage(0);
  }, [headers.join('\u0001'), rows.length]);

  useEffect(() => {
    if (page > totalPages - 1) {
      setPage(Math.max(0, totalPages - 1));
    }
  }, [page, totalPages]);

  const currentPage = Math.min(Math.max(0, page), totalPages - 1);
  const start = currentPage * pageSize;
  const pageRows = rows.slice(start, start + pageSize);

  const handleExportCsv = () => {
    if (!total) return;
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:-]/g, '').replace('T', '-');
    const csv = buildCsv(headers, rows);
    downloadCsvFile(`table-export-${stamp}.csv`, csv);
  };

  return (
    <div className="my-3 rounded-xl border border-gray-200/90 dark:border-gray-700/90 bg-white dark:bg-gray-900/40 shadow-sm shadow-gray-900/5 dark:shadow-black/20 overflow-hidden not-prose">
      <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 border-b border-gray-200/90 dark:border-gray-700/80 bg-gray-50/90 dark:bg-gray-800/40">
        <span className="text-[11px] font-medium text-gray-500 dark:text-gray-400 tabular-nums">
          {total === 0 ? 'No rows' : `${total} row${total === 1 ? '' : 's'}`}
        </span>
        <button
          type="button"
          onClick={handleExportCsv}
          disabled={total === 0}
          className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-[11px] font-semibold text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-40 disabled:pointer-events-none transition-colors"
        >
          <Download className="w-3.5 h-3.5 opacity-80" strokeWidth={2.25} />
          Export CSV
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse text-sm font-body">
          <thead>
            <tr className="bg-gradient-to-b from-gray-50 to-gray-100/90 dark:from-gray-800 dark:to-gray-800/70 border-b border-gray-200 dark:border-gray-700">
              {headers.map((h, i) => (
                <th
                  key={i}
                  scope="col"
                  className="sticky top-0 z-[1] px-3.5 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-gray-600 dark:text-gray-300 align-top break-words whitespace-normal backdrop-blur-sm bg-gray-100/95 dark:bg-gray-800/95 border-b border-gray-200/80 dark:border-gray-700"
                >
                  {h || '—'}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
            {pageRows.length === 0 ? (
              <tr>
                <td
                  colSpan={Math.max(1, headers.length)}
                  className="px-3.5 py-8 text-center text-sm text-gray-500 dark:text-gray-400"
                >
                  No data rows
                </td>
              </tr>
            ) : (
              pageRows.map((row, ri) => (
                <tr
                  key={start + ri}
                  className="transition-colors hover:bg-primary-500/[0.04] dark:hover:bg-primary-400/[0.06] even:bg-gray-50/60 dark:even:bg-gray-800/25"
                >
                  {headers.map((_, ci) => (
                    <td
                      key={ci}
                      className="px-3.5 py-2 text-gray-800 dark:text-gray-200 align-top break-words whitespace-normal min-w-0"
                    >
                      {row[ci] ?? ''}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2.5 border-t border-gray-200/90 dark:border-gray-700/90 bg-gray-50/80 dark:bg-gray-800/50">
          <p className="text-xs text-gray-500 dark:text-gray-400 font-medium tabular-nums">
            {total === 0 ? (
              'No rows'
            ) : (
              <>
                <span className="text-gray-700 dark:text-gray-300">{start + 1}</span>
                {'–'}
                <span className="text-gray-700 dark:text-gray-300">
                  {Math.min(start + pageSize, total)}
                </span>
                <span className="text-gray-400 dark:text-gray-500 mx-1">of</span>
                <span className="text-gray-700 dark:text-gray-300">{total}</span>
              </>
            )}
          </p>
          <div className="flex items-center gap-1">
            <button
              type="button"
              aria-label="Previous page"
              disabled={currentPage <= 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              className="inline-flex items-center justify-center w-8 h-8 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-40 disabled:pointer-events-none transition-colors"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span className="text-xs text-gray-600 dark:text-gray-400 px-2 min-w-[4.5rem] text-center tabular-nums font-medium">
              {currentPage + 1} / {totalPages}
            </span>
            <button
              type="button"
              aria-label="Next page"
              disabled={currentPage >= totalPages - 1}
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              className="inline-flex items-center justify-center w-8 h-8 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-40 disabled:pointer-events-none transition-colors"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
