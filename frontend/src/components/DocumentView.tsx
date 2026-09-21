import { useState, Children, isValidElement } from 'react';
import { FileText, Check, Copy, Download } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import MermaidDiagram from './MermaidDiagram';
import MarkdownCodeBlock from './MarkdownCodeBlock';
import PaginatedMarkdownTable from './PaginatedMarkdownTable';

export function isDocumentResponse(content: string): boolean {
  const documentMarkers = [
    'Business Requirements Document',
    '## 📄 Complete BRD Document',
    '# Business Requirements Document',
    '## Executive Summary',
    '## 1. Executive Summary',
    '**BRD File Location:**',
    '--- Page ',
    '--- Slide ',
    '--- Sheet ',
    '[Slide 1]',
    '[Slide 2]',
    '[Page 1]',
    '[Page 2]',
  ];
  const markerCount = documentMarkers.filter(marker => content.includes(marker)).length;
  if (markerCount >= 2) return true;
  if (markerCount >= 1 && content.length > 500) {
    const headingCount = (content.match(/^#{1,3}\s+/gm) || []).length;
    return headingCount >= 3;
  }
  return false;
}

function MarkdownRemoteImage({ src, alt }: { src?: string; alt?: string }) {
  if (!src || !/^https?:\/\//i.test(src)) return null;
  return (
    <img
      src={src}
      alt={alt || ''}
      className="my-3 max-h-80 w-auto max-w-full rounded-lg border border-gray-200 object-contain dark:border-gray-700"
      loading="lazy"
      referrerPolicy="no-referrer"
    />
  );
}

interface DocumentViewProps {
  content: string;
  title?: string;
  subtitle?: string;
}

export default function DocumentView({ content, title, subtitle }: DocumentViewProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  const handleDownload = () => {
    const blob = new Blob([content], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${(title || 'document').replace(/\s+/g, '_').toLowerCase()}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const inferredTitle = title || inferTitle(content);
  const inferredSubtitle = subtitle || 'Formatted Document';

  return (
    <div className="w-full">
      <div className="document-header">
        <div className="document-header-icon">
          <FileText className="w-5 h-5" />
        </div>
        <div className="flex-1">
          <div className="document-header-title">{inferredTitle}</div>
          <div className="document-header-subtitle">{inferredSubtitle}</div>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={handleDownload}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg transition-all bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 border border-gray-200 dark:border-gray-600"
            title="Download as Markdown"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Download</span>
          </button>
          <button
            onClick={handleCopy}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg transition-all bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 border border-gray-200 dark:border-gray-600"
            title="Copy to clipboard"
          >
            {copied ? (
              <>
                <Check className="w-3.5 h-3.5 text-green-500" />
                <span className="text-green-600 dark:text-green-400">Copied!</span>
              </>
            ) : (
              <>
                <Copy className="w-3.5 h-3.5" />
                <span>Copy</span>
              </>
            )}
          </button>
        </div>
      </div>
      <div className="document-view">
        <div className="prose dark:prose-invert max-w-none">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              a: ({ href, children }) => (
                <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
              ),
              code: ({ children, className }) => {
                if (className?.includes('language-mermaid')) {
                  const code = String(children).replace(/\n$/, '');
                  return <MermaidDiagram chart={code} />;
                }
                const langMatch = /language-([\w-+]+)/.exec(className || '');
                if (langMatch) {
                  const codeStr = String(children).replace(/\n$/, '');
                  return <MarkdownCodeBlock language={langMatch[1]} code={codeStr} />;
                }
                return (
                  <code className="rounded bg-gray-200 px-1 py-0.5 font-mono text-sm text-orange-600 dark:bg-gray-800 dark:text-orange-300">
                    {children}
                  </code>
                );
              },
              pre: ({ children }) => {
                const first = Children.toArray(children)[0];
                const cls =
                  isValidElement(first) &&
                  first.props &&
                  typeof (first.props as { className?: string }).className === 'string'
                    ? (first.props as { className: string }).className
                    : '';
                if (cls.includes('language-')) {
                  return <>{children}</>;
                }
                return (
                  <pre className="my-2 overflow-x-auto rounded-xl border border-gray-200/90 bg-gray-100 p-3 font-mono text-xs text-gray-800 dark:border-gray-700 dark:bg-gray-800/80 dark:text-gray-200">
                    {children}
                  </pre>
                );
              },
              table: ({ children }) => <PaginatedMarkdownTable>{children}</PaginatedMarkdownTable>,
              img: ({ src, alt }) => <MarkdownRemoteImage src={src} alt={alt} />,
            }}
          >{content}</ReactMarkdown>
        </div>
      </div>
    </div>
  );
}

function inferTitle(content: string): string {
  const h1Match = content.match(/^#\s+(.+)$/m);
  if (h1Match) return h1Match[1].replace(/[#*_]/g, '').trim();
  const firstLine = content.split('\n').find(l => l.trim().length > 0);
  if (firstLine) {
    const clean = firstLine.replace(/[#*_\-]/g, '').trim();
    if (clean.length > 0 && clean.length < 80) return clean;
  }
  return 'Document';
}
