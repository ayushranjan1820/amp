import { useState } from 'react';
import { Globe, ExternalLink, Image, ChevronDown, ChevronRight, Search, Sparkles, BookOpen, Newspaper, Calculator, Microscope } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface SearchSource {
  title: string;
  url: string;
  snippet: string;
  domain: string;
  image_url?: string | null;
}

interface WebSearchResultViewProps {
  content: string;
  sources?: SearchSource[];
  images?: string[];
  followUpQuestions?: string[];
  searchFocus?: string;
  onFollowUpClick?: (question: string) => void;
}

const FOCUS_ICONS: Record<string, { icon: any; label: string; color: string }> = {
  general: { icon: Globe, label: 'General Search', color: 'text-blue-500' },
  news: { icon: Newspaper, label: 'News Search', color: 'text-red-500' },
  academic: { icon: BookOpen, label: 'Academic Research', color: 'text-purple-500' },
  writing: { icon: Sparkles, label: 'Writing Assistant', color: 'text-amber-500' },
  math: { icon: Calculator, label: 'Math & Science', color: 'text-green-500' },
  deep_research: { icon: Microscope, label: 'Deep Research', color: 'text-indigo-500' },
};

export function isWebSearchResponse(data: any): boolean {
  return data && typeof data === 'object' && data.search_focus !== undefined && data.sources !== undefined;
}

export default function WebSearchResultView({
  content,
  sources = [],
  images = [],
  followUpQuestions = [],
  searchFocus = 'general',
  onFollowUpClick,
}: WebSearchResultViewProps) {
  const [showAllSources, setShowAllSources] = useState(false);
  const [showImages, setShowImages] = useState(true);
  const [failedImageUrls, setFailedImageUrls] = useState<Set<string>>(new Set());

  const focusInfo = FOCUS_ICONS[searchFocus] || FOCUS_ICONS.general;
  const FocusIcon = focusInfo.icon;
  const displayedSources = showAllSources ? sources : sources.slice(0, 4);
  const validImages = images.filter((img) => !failedImageUrls.has(img));

  const handleImageError = (url: string) => {
    setFailedImageUrls(prev => new Set(prev).add(url));
  };

  return (
    <div className="w-full space-y-4">
      <div className="flex items-center gap-2 px-1">
        <FocusIcon className={`w-4 h-4 ${focusInfo.color}`} />
        <span className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
          {focusInfo.label}
        </span>
      </div>

      {validImages.length > 0 && (
        <div className="rounded-xl overflow-hidden border border-gray-200 dark:border-gray-700">
          <button
            onClick={() => setShowImages(!showImages)}
            className="w-full px-3 py-2 flex items-center gap-2 text-xs font-medium text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors bg-gray-50/50 dark:bg-gray-800/30"
          >
            {showImages ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
            <Image className="w-3.5 h-3.5 text-blue-500" />
            <span>{validImages.length} Images Found</span>
          </button>
          {showImages && (
            <div className="p-3 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
              {validImages.slice(0, 8).map((img, i) => (
                <a
                  key={i}
                  href={img}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block aspect-video rounded-lg overflow-hidden bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 hover:border-blue-400 dark:hover:border-blue-500 transition-colors group"
                >
                  <img
                    src={img}
                    alt={`Search result ${i + 1}`}
                    className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-200"
                    onError={() => handleImageError(img)}
                    loading="lazy"
                  />
                </a>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="px-4 py-3 rounded-2xl bg-gray-100 dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-bl-md">
        <div className="prose prose-sm dark:prose-invert max-w-none font-body">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              a: ({ href, children }) => (
                <a
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-600 dark:text-blue-400 hover:underline inline-flex items-center gap-0.5"
                >
                  {children}
                  <ExternalLink className="w-3 h-3 inline-block ml-0.5 flex-shrink-0" />
                </a>
              ),
              table: ({ children }) => (
                <div className="overflow-x-auto my-3">
                  <table className="min-w-full border-collapse border border-gray-300 dark:border-gray-700 text-sm">{children}</table>
                </div>
              ),
              thead: ({ children }) => <thead className="bg-gray-100 dark:bg-gray-800">{children}</thead>,
              th: ({ children }) => (
                <th className="border border-gray-300 dark:border-gray-700 px-3 py-1.5 text-left font-semibold text-gray-700 dark:text-gray-200 align-top break-words whitespace-normal">{children}</th>
              ),
              td: ({ children }) => (
                <td className="border border-gray-300 dark:border-gray-700 px-3 py-1.5 text-gray-600 dark:text-gray-300 align-top break-words whitespace-normal min-w-0">{children}</td>
              ),
              code: ({ children, className }) => {
                const isBlock = className?.includes('language-');
                if (isBlock) {
                  return (
                    <div className="bg-gray-100 dark:bg-gray-800 rounded-lg overflow-x-auto my-2">
                      <pre className="p-3 text-xs"><code>{children}</code></pre>
                    </div>
                  );
                }
                return (
                  <code className="bg-gray-200 dark:bg-gray-800 px-1 py-0.5 rounded text-orange-600 dark:text-orange-300 text-xs">
                    {children}
                  </code>
                );
              },
              pre: ({ children }) => <pre>{children}</pre>,
            }}
          >
            {content}
          </ReactMarkdown>
        </div>
      </div>

      {sources.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider px-1 flex items-center gap-1.5">
            <Globe className="w-3.5 h-3.5" />
            Sources ({sources.length})
          </h4>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {displayedSources.map((source, i) => (
              <a
                key={i}
                href={source.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-start gap-3 p-3 rounded-xl bg-white dark:bg-gray-800/50 border border-gray-200 dark:border-gray-700 hover:border-blue-300 dark:hover:border-blue-600 hover:shadow-sm transition-all group"
              >
                {source.image_url ? (
                  <img
                    src={source.image_url}
                    alt={source.title}
                    className="w-16 h-12 rounded-lg object-cover flex-shrink-0 bg-gray-100 dark:bg-gray-700"
                    onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                  />
                ) : (
                  <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-blue-100 to-blue-50 dark:from-blue-900/30 dark:to-blue-800/20 flex items-center justify-center flex-shrink-0">
                    <Globe className="w-5 h-5 text-blue-500" />
                  </div>
                )}
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-semibold text-gray-900 dark:text-white truncate group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">
                    {source.title || source.domain}
                  </p>
                  <p className="text-[10px] text-blue-600 dark:text-blue-400 truncate mt-0.5">
                    {source.domain}
                  </p>
                  {source.snippet && (
                    <p className="text-[11px] text-gray-500 dark:text-gray-400 line-clamp-2 mt-1">
                      {source.snippet}
                    </p>
                  )}
                </div>
                <ExternalLink className="w-3.5 h-3.5 text-gray-400 group-hover:text-blue-500 flex-shrink-0 mt-1 transition-colors" />
              </a>
            ))}
          </div>
          {sources.length > 4 && (
            <button
              onClick={() => setShowAllSources(!showAllSources)}
              className="text-xs text-blue-600 dark:text-blue-400 hover:underline font-medium px-1"
            >
              {showAllSources ? 'Show less' : `Show all ${sources.length} sources`}
            </button>
          )}
        </div>
      )}

      {followUpQuestions.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider px-1 flex items-center gap-1.5">
            <Search className="w-3.5 h-3.5" />
            Related Questions
          </h4>
          <div className="flex flex-wrap gap-2">
            {followUpQuestions.map((q, i) => (
              <button
                key={i}
                onClick={() => onFollowUpClick?.(q)}
                className="text-xs px-3 py-2 rounded-xl bg-white dark:bg-gray-800/50 border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300 hover:border-blue-300 dark:hover:border-blue-600 hover:text-blue-600 dark:hover:text-blue-400 hover:shadow-sm transition-all text-left"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
