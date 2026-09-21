import { useCallback, useMemo, useRef, useState } from 'react';
import { ChevronDown, Download, FileText, Loader2 } from 'lucide-react';
import {
  buildExportBasename,
  exportChatMessageDocx,
  exportChatMessagePdf,
  exportChatMessageTxt,
} from '../utils/chatMessageExport';

type ExportKind = 'txt' | 'pdf' | 'docx';

export default function AssistantMessageExportBar({
  content,
  filenameBase,
  timestamp,
}: {
  content: string;
  filenameBase: string;
  timestamp: string;
}) {
  const [busy, setBusy] = useState<ExportKind | null>(null);
  const busyLock = useRef(false);
  const detailsRef = useRef<HTMLDetailsElement>(null);

  const base = useMemo(
    () => buildExportBasename(filenameBase, content, timestamp),
    [filenameBase, content, timestamp],
  );

  const run = useCallback(
    async (kind: ExportKind) => {
      if (busyLock.current || !content.trim()) return;
      busyLock.current = true;
      setBusy(kind);
      try {
        if (kind === 'txt') exportChatMessageTxt(content, base);
        else if (kind === 'pdf') {
          if (detailsRef.current) detailsRef.current.open = false;
          const chatMessage = detailsRef.current?.closest('.chat-message') as HTMLElement | null;
          const captureRoot = (chatMessage?.firstElementChild as HTMLElement | null) ?? null;
          const bars = captureRoot
            ? Array.from(captureRoot.querySelectorAll<HTMLElement>('[data-assistant-export-bar="true"]'))
            : [];
          const previousDisplays = bars.map((bar) => bar.style.display);
          bars.forEach((bar) => {
            bar.style.display = 'none';
          });
          try {
            await exportChatMessagePdf(content, base, captureRoot);
          } finally {
            bars.forEach((bar, i) => {
              bar.style.display = previousDisplays[i] || '';
            });
          }
        }
        else await exportChatMessageDocx(content, base);
        if (detailsRef.current) detailsRef.current.open = false;
      } finally {
        busyLock.current = false;
        setBusy(null);
      }
    },
    [content, base],
  );

  if (!content.trim()) return null;

  return (
    <div className="mb-1.5 flex justify-end" data-assistant-export-bar="true">
      <details ref={detailsRef} className="group relative">
        <summary
          className="flex cursor-pointer list-none items-center gap-1 rounded-lg border border-gray-200 bg-white/90 px-2 py-1 text-[11px] font-semibold text-gray-600 shadow-sm transition-colors hover:bg-gray-50 hover:text-gray-900 dark:border-gray-700 dark:bg-gray-800/90 dark:text-gray-300 dark:hover:bg-gray-800 dark:hover:text-white [&::-webkit-details-marker]:hidden"
          title="Download this reply"
        >
          <Download className="h-3 w-3 shrink-0 opacity-80" aria-hidden />
          Export
          <ChevronDown className="h-3 w-3 shrink-0 opacity-70 transition-transform group-open:rotate-180" aria-hidden />
        </summary>
        <div
          className="absolute right-0 z-20 mt-1 min-w-[11rem] rounded-lg border border-gray-200 bg-white py-1 shadow-lg dark:border-gray-700 dark:bg-gray-900"
          role="menu"
        >
          <button
            type="button"
            role="menuitem"
            disabled={busy !== null}
            onClick={() => void run('txt')}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-gray-800 hover:bg-gray-50 disabled:opacity-50 dark:text-gray-100 dark:hover:bg-gray-800"
          >
            {busy === 'txt' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FileText className="h-3.5 w-3.5 opacity-70" />}
            Plain text (.txt)
          </button>
          <button
            type="button"
            role="menuitem"
            disabled={busy !== null}
            onClick={() => void run('docx')}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-gray-800 hover:bg-gray-50 disabled:opacity-50 dark:text-gray-100 dark:hover:bg-gray-800"
          >
            {busy === 'docx' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FileText className="h-3.5 w-3.5 opacity-70" />}
            Word (.docx)
          </button>
          <button
            type="button"
            role="menuitem"
            disabled={busy !== null}
            onClick={() => void run('pdf')}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-gray-800 hover:bg-gray-50 disabled:opacity-50 dark:text-gray-100 dark:hover:bg-gray-800"
          >
            {busy === 'pdf' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FileText className="h-3.5 w-3.5 opacity-70" />}
            PDF (.pdf)
          </button>
        </div>
      </details>
    </div>
  );
}
