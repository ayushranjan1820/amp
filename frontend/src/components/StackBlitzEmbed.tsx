import { useCallback, useEffect, useMemo, useState } from 'react';
import { Maximize2, Minimize2, ExternalLink, AlertTriangle, RefreshCw } from 'lucide-react';

interface StackBlitzEmbedProps {
  repoSlug: string;
  darkMode?: boolean;
}

function buildEmbedUrl(repoSlug: string, darkMode: boolean): string {
  const u = new URL(`https://stackblitz.com/github/${repoSlug}`);
  u.searchParams.set('embed', '1');
  u.searchParams.set('view', 'preview');
  u.searchParams.set('theme', darkMode ? 'dark' : 'light');
  u.searchParams.set('hideNavigation', '0');
  u.searchParams.set('hideExplorer', '0');
  return u.toString();
}

export default function StackBlitzEmbed({ repoSlug, darkMode = false }: StackBlitzEmbedProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [embedError, setEmbedError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);

  const iframeSrc = useMemo(() => buildEmbedUrl(repoSlug, darkMode), [repoSlug, darkMode]);

  const handleIframeLoad = useCallback(() => {
    setLoading(false);
    setEmbedError(false);
  }, []);

  useEffect(() => {
    setLoading(true);
    setEmbedError(false);
    const t = window.setTimeout(() => {
      setLoading((still) => {
        if (still) {
          setEmbedError(true);
          return false;
        }
        return still;
      });
    }, 90000);
    return () => window.clearTimeout(t);
  }, [iframeSrc, reloadKey]);

  const retry = useCallback(() => {
    setEmbedError(false);
    setLoading(true);
    setReloadKey((k) => k + 1);
  }, []);

  const borderColor = darkMode ? 'border-gray-200 dark:border-gray-700' : 'border-gray-200';
  const bgColor = darkMode ? 'bg-white dark:bg-gray-950' : 'bg-white';
  const headerBg = darkMode ? 'bg-white dark:bg-gray-900' : 'bg-gray-50';
  const textColor = darkMode ? 'text-gray-700 dark:text-gray-300' : 'text-gray-700';
  const mutedText = darkMode ? 'text-gray-400 dark:text-gray-400' : 'text-gray-500';
  const hoverBg = darkMode ? 'hover:bg-gray-800' : 'hover:bg-gray-200';
  const badgeBg = darkMode ? 'bg-blue-900/30 text-blue-400' : 'bg-blue-100 text-blue-700';

  return (
    <div className={`mt-3 rounded-xl border ${borderColor} overflow-hidden ${bgColor}`}>
      <div className={`flex items-center justify-between px-4 py-2.5 ${headerBg} border-b ${borderColor}`}>
        <div className="flex items-center gap-2">
          <svg className="w-4 h-4" viewBox="0 0 28 28" fill="none">
            <path d="M12.747 16.273h-7.46L18.925 1.5l-3.671 10.227h7.46L9.075 26.5l3.672-10.227z" fill="#1389FD"/>
          </svg>
          <span className={`text-xs font-medium ${textColor}`}>StackBlitz Sandbox</span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${badgeBg}`}>{repoSlug}</span>
        </div>
        <div className="flex items-center gap-1">
          <a
            href={`https://stackblitz.com/github/${repoSlug}`}
            target="_blank"
            rel="noopener noreferrer"
            className={`p-1.5 rounded-lg ${hoverBg} transition-colors`}
            title="Open in StackBlitz"
          >
            <ExternalLink className={`w-3.5 h-3.5 ${mutedText}`} />
          </a>
          <button
            type="button"
            onClick={() => setIsExpanded(!isExpanded)}
            className={`p-1.5 rounded-lg ${hoverBg} transition-colors`}
            title={isExpanded ? 'Collapse' : 'Expand'}
          >
            {isExpanded ? (
              <Minimize2 className={`w-3.5 h-3.5 ${mutedText}`} />
            ) : (
              <Maximize2 className={`w-3.5 h-3.5 ${mutedText}`} />
            )}
          </button>
        </div>
      </div>
      <div
        className={`relative transition-all duration-300 ${isExpanded ? 'h-[700px]' : 'h-[450px]'}`}
      >
        <iframe
          key={`${iframeSrc}-${reloadKey}`}
          title={`StackBlitz: ${repoSlug}`}
          src={iframeSrc}
          className="h-full w-full min-h-0 border-0"
          onLoad={handleIframeLoad}
          allow="accelerometer; camera; encrypted-media; geolocation; gyroscope; microphone; midi; clipboard-read; clipboard-write; payment; usb; xr-spatial-tracking; cross-origin-isolated"
          referrerPolicy="strict-origin-when-cross-origin"
        />
        {loading && !embedError && (
          <div
            className={`absolute inset-0 flex items-center justify-center ${bgColor} z-10`}
          >
            <div className="flex flex-col items-center gap-3">
              <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
              <p className={`text-xs ${mutedText}`}>Loading sandbox…</p>
            </div>
          </div>
        )}
        {embedError && (
          <div
            className={`absolute inset-0 flex flex-col items-center justify-center gap-4 px-4 ${bgColor} z-20`}
          >
            <AlertTriangle className={`w-10 h-10 shrink-0 ${darkMode ? 'text-amber-400' : 'text-amber-500'}`} />
            <div className="text-center">
              <p className={`text-sm font-medium ${textColor} mb-1`}>
                Embedded preview did not finish loading
              </p>
              <p className={`text-xs ${mutedText} max-w-md`}>
                StackBlitz WebContainers need a normal browser tab. Simple Browser, strict extensions,
                or network blocks often stop the VM. Open the repo on StackBlitz (or GitHub) instead.
              </p>
            </div>
            <div className="flex flex-wrap items-center justify-center gap-3">
              <button
                type="button"
                onClick={retry}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border ${borderColor} ${hoverBg} ${textColor} transition-colors`}
              >
                <RefreshCw className="w-3.5 h-3.5" />
                Reload embed
              </button>
              <a
                href={`https://stackblitz.com/github/${repoSlug}`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-blue-600 text-gray-900 dark:text-white hover:bg-blue-700 transition-colors"
              >
                <ExternalLink className="w-3.5 h-3.5" />
                Open in StackBlitz
              </a>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
