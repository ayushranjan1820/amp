import { Document, Packer, Paragraph } from 'docx';
import { toPng } from 'html-to-image';
import { jsPDF } from 'jspdf';

export function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** Readable plain text from markdown (headings, lists, links, emphasis). */
export function markdownToPlainText(md: string): string {
  let s = md.replace(/\r\n/g, '\n');
  s = s.replace(/```[\w-]*\n([\s\S]*?)```/g, (_, code: string) => `\n${String(code).trim()}\n`);
  s = s.replace(/`([^`]+)`/g, '$1');
  s = s.replace(/^#{1,6}\s+(.+)$/gm, '$1');
  s = s.replace(/\*\*\*(.+?)\*\*\*/g, '$1');
  s = s.replace(/\*\*(.+?)\*\*/g, '$1');
  s = s.replace(/__(.+?)__/g, '$1');
  s = s.replace(/\*(.+?)\*/g, '$1');
  s = s.replace(/_(.+?)_/g, '$1');
  s = s.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');
  s = s.replace(/!\[([^\]]*)\]\([^)]+\)/g, '$1');
  s = s.replace(/^---+$/gm, '');
  s = s.replace(/^\s*[-*+]\s+/gm, '');
  s = s.replace(/^\s*\d+\.\s+/gm, '');
  return s.replace(/\n{3,}/g, '\n\n').trim();
}

const FILENAME_FORBIDDEN = new Set('<>:"/\\|?*');

export function sanitizeExportBasename(raw: string): string {
  let cleaned = '';
  for (const ch of raw) {
    const cp = ch.codePointAt(0)!;
    if (cp < 32 || FILENAME_FORBIDDEN.has(ch)) continue;
    cleaned += ch;
  }
  const t = cleaned
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-+|-+$/g, '');
  return t.slice(0, 80) || 'export';
}

export function buildExportBasename(agentLabel: string, content: string, isoTs: string): string {
  const date = isoTs.slice(0, 10);
  const agentPart = sanitizeExportBasename(agentLabel.trim() || 'agent');
  const plain = markdownToPlainText(content);
  const firstLine = plain.split('\n')[0]?.trim() || 'message';
  const slug = sanitizeExportBasename(firstLine.slice(0, 48));
  return `${agentPart}-${date}-${slug}`.slice(0, 140);
}

export function exportChatMessageTxt(markdown: string, baseName: string): void {
  const body = `${markdownToPlainText(markdown)}\n`;
  const blob = new Blob([body], { type: 'text/plain;charset=utf-8' });
  triggerDownload(blob, `${baseName}.txt`);
}

/** Rasterize a DOM subtree into a multi-page A4 PDF (white background). */
export async function exportDomElementToPdf(targetElement: HTMLElement, baseName: string): Promise<boolean> {
  try {
    const rect = targetElement.getBoundingClientRect();
    if (rect.width < 4 || rect.height < 4) return false;

    const host = document.createElement('div');
    host.style.position = 'fixed';
    host.style.left = '-100000px';
    host.style.top = '0';
    host.style.width = `${Math.ceil(rect.width)}px`;
    host.style.maxWidth = `${Math.ceil(rect.width)}px`;
    host.style.background = '#ffffff';
    host.style.zIndex = '-1';

    const clone = targetElement.cloneNode(true) as HTMLElement;
    host.appendChild(clone);
    document.body.appendChild(host);

    try {
      const pngData = await toPng(clone, {
        cacheBust: true,
        pixelRatio: 2.5,
        backgroundColor: '#ffffff',
      });

      const probeImage = new Image();
      const imageLoaded = new Promise<void>((resolve, reject) => {
        probeImage.onload = () => resolve();
        probeImage.onerror = () => reject(new Error('Could not load generated image'));
      });
      probeImage.src = pngData;
      await imageLoaded;

      const doc = new jsPDF({ unit: 'mm', format: 'a4' });
      const margin = 8;
      const pageW = doc.internal.pageSize.getWidth();
      const pageH = doc.internal.pageSize.getHeight();
      const contentW = pageW - margin * 2;
      const contentH = pageH - margin * 2;

      const mmPerPx = contentW / probeImage.width;
      const pageSliceHeightPx = Math.max(1, Math.floor(contentH / mmPerPx));

      const pageCanvas = document.createElement('canvas');
      pageCanvas.width = probeImage.width;
      const pageCtx = pageCanvas.getContext('2d');
      if (!pageCtx) return false;

      let page = 0;
      for (let top = 0; top < probeImage.height; top += pageSliceHeightPx) {
        const sliceHeightPx = Math.min(pageSliceHeightPx, probeImage.height - top);
        pageCanvas.height = sliceHeightPx;
        pageCtx.clearRect(0, 0, pageCanvas.width, sliceHeightPx);
        pageCtx.drawImage(
          probeImage,
          0,
          top,
          probeImage.width,
          sliceHeightPx,
          0,
          0,
          probeImage.width,
          sliceHeightPx,
        );

        if (page > 0) doc.addPage();
        doc.addImage(
          pageCanvas.toDataURL('image/png'),
          'PNG',
          margin,
          margin,
          contentW,
          sliceHeightPx * mmPerPx,
          undefined,
          'FAST',
        );
        page += 1;
      }

      const pages = doc.getNumberOfPages();
      if (pages > 1) {
        for (let p = 1; p <= pages; p++) {
          doc.setPage(p);
          doc.setFontSize(9);
          doc.setTextColor(120);
          doc.text(`Page ${p} of ${pages}`, pageW - margin, pageH - 3.5, { align: 'right' });
        }
      }

      doc.save(`${baseName}.pdf`);
      return true;
    } finally {
      host.remove();
    }
  } catch {
    return false;
  }
}

export async function exportChatMessagePdf(
  markdown: string,
  baseName: string,
  targetElement?: HTMLElement | null,
): Promise<void> {
  if (targetElement) {
    try {
      const exported = await exportDomElementToPdf(targetElement, baseName);
      if (exported) return;
    } catch {
      // Fallback below keeps export working even if DOM capture fails.
    }
  }

  const plain = markdownToPlainText(markdown);
  const doc = new jsPDF({ unit: 'mm', format: 'a4' });
  const margin = 14;
  const pageW = doc.internal.pageSize.getWidth();
  const pageH = doc.internal.pageSize.getHeight();
  const maxW = pageW - margin * 2;
  const lines = doc.splitTextToSize(plain, maxW);
  let y = margin;
  const lineH = 6;
  const bottom = pageH - margin;
  for (let i = 0; i < lines.length; i++) {
    if (y + lineH > bottom) {
      doc.addPage();
      y = margin;
    }
    doc.text(lines[i] as string, margin, y);
    y += lineH;
  }
  doc.save(`${baseName}.pdf`);
}

export async function exportChatMessageDocx(markdown: string, baseName: string): Promise<void> {
  const plain = markdownToPlainText(markdown);
  const lines = plain.split(/\n/);
  const children =
    lines.length > 0
      ? lines.map((line) => new Paragraph(line.length ? line : '\u00a0'))
      : [new Paragraph('\u00a0')];

  const file = new Document({
    sections: [{ children }],
  });
  const blob = await Packer.toBlob(file);
  triggerDownload(blob, `${baseName}.docx`);
}
