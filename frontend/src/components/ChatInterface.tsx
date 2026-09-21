import { useState, useRef, useEffect, useCallback, Children, isValidElement, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { Send, Loader2, Trash2, MessageSquare, Brain, Wrench, CheckCircle2, ChevronDown, FileText, Upload, Download, Settings, Monitor, ChevronLeft, ChevronRight, ExternalLink, Cpu, ScrollText, AlertTriangle, Plug, Eye, EyeOff, RotateCcw, X, LayoutGrid, Share2 } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Agent, ThinkingStep, TaskStatusResponse, BrowserScreenshotEvent, PptSlideSnapshotEvent } from '../services/api';
import { chatWithAgentStream, pollTaskStatus, pingWebmcpBridge } from '../services/api';
import BPMNViewer from './BPMNViewer';
import MermaidDiagram from './MermaidDiagram';
import SuggestionChips from './SuggestionChips';
import StackBlitzEmbed from './StackBlitzEmbed';
import TestReportView, { isTestReport } from './TestReportView';
import SonarQubeReportView, { isSonarQubeReport } from './SonarQubeReportView';
import CompanyReportView, { isCompanyResearchReport, LatestNewsCardsSection, type NewsCardData } from './CompanyReportView';
import CompanyAiSolutionsView, { isCompanyAiSolutionsReport } from './CompanyAiSolutionsView';
import DocumentView, { isDocumentResponse } from './DocumentView';
import WebSearchResultView from './WebSearchResultView';
import PaginatedMarkdownTable from './PaginatedMarkdownTable';
import MarkdownCodeBlock from './MarkdownCodeBlock';
import { FileAttachmentInput, FileAttachmentBubble } from './FileAttachmentCard';
import AssistantMessageExportBar from './AssistantMessageExportBar';
import JiraDashboard, { type JiraChartData } from './JiraDashboard';
import EmailPreviewCard, { type EmailPreviewData } from './EmailPreviewCard';
import {
  getConfigFields,
  hasRequiredConfig,
  hasRequiredConfigForEffective,
  getMissingRequiredFieldsForEffective,
  getEffectiveConfig,
  getUserConfigPayloadForRequest,
} from '../utils/agentConfigStorage';
import { getAgentsMarketplaceApiBase } from '../utils/agentsApiBase';

interface ExtendedChatMessage {
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  thinking_steps?: ThinkingStep[];
  bpmn_xml?: string;
  file_name?: string;
  requires_token?: boolean;
  stackblitz_repo?: string;
  latest_news_cards?: NewsCardData[];
  chart_data?: JiraChartData;
  email_preview?: EmailPreviewData;
  download_url?: string;
  download_file_name?: string;
  /** Browser agent: basename for GET /api/browser-agent/html-report?file= */
  browser_html_report_file?: string;
  /** Browser agent: live screenshots streamed per step */
  browser_screenshots?: BrowserScreenshotEvent[];
  /** PPT Generator Agent: streamed SVG previews while each slide is authored */
  ppt_slide_snapshots?: PptSlideSnapshotEvent[];
  /** PPT Generator Agent: source URLs from Perplexity slide research */
  ppt_research_sources?: Array<{ title: string; url: string; date?: string }>;
  /** Browser agent: steps_executed from last run — used to replay DSL with screenshots on “Run script” */
  browser_steps_executed?: Record<string, unknown>[];
  standalone_html?: string;
  is_web_search?: boolean;
  web_search_sources?: Array<{ title: string; url: string; snippet: string; domain: string; image_url?: string | null }>;
  web_search_images?: string[];
  web_search_follow_ups?: string[];
  web_search_focus?: string;
  /** Meeting Prep Agent: candidate image URLs from Sonar (subset may be embedded in markdown). */
  report_image_urls?: string[];
  /** MongoDB Atlas KB Agent: chunks used for the answer (from SSE `done.sources`). */
  mongodb_rag_sources?: Array<{
    file_name: string;
    section?: string;
    score: number;
    preview: string;
  }>;
}

interface ChatInterfaceProps {
  agent: Agent;
  /** When set, shows a control to jump to the agent page Config tab (sidebar). */
  onOpenConfigTab?: () => void;
  /** When true, message list and composer are non-interactive (e.g. unsaved agent config). */
  blockedByUnsavedConfig?: boolean;
}

const BROWSER_CDP_STORAGE_KEY = 'browser_agent_cdp_endpoint';
const BROWSER_REMEMBER_LOGINS_KEY = 'browser_agent_remember_logins';
const BROWSER_HEADLESS_KEY = 'browser_agent_headless';
const WEBMCP_BRIDGE_URL_KEY = 'webmcp_agent_bridge_url';
const WEBMCP_BRIDGE_TOKEN_SESSION_KEY = 'webmcp_agent_bridge_token';

function MongoRagRetrievedChunks({
  sources,
}: {
  sources: NonNullable<ExtendedChatMessage['mongodb_rag_sources']>;
}) {
  if (!sources.length) return null;
  return (
    <details
      open
      className="mt-3 rounded-xl border border-gray-200 bg-gray-50/90 dark:border-gray-700 dark:bg-gray-900/60"
    >
      <summary className="cursor-pointer select-none list-inside px-3 py-2.5 text-xs font-medium text-gray-700 dark:text-gray-200 marker:text-gray-400 hover:text-gray-900 dark:hover:text-white">
        Retrieved chunks used for this answer ({sources.length})
      </summary>
      <div className="border-t border-gray-200 px-3 py-3 dark:border-gray-700">
        <ul className="space-y-3">
          {sources.map((s, i) => (
            <li key={`${s.file_name}-${i}`} className="text-xs">
              <div className="mb-1.5 flex flex-wrap items-center gap-2 text-gray-800 dark:text-gray-100">
                <FileText className="h-3.5 w-3.5 shrink-0 text-gray-600 dark:text-gray-400" />
                <span className="font-medium">{s.file_name || 'Unknown source'}</span>
                {s.section ? (
                  <span className="text-gray-500 dark:text-gray-400">· {s.section}</span>
                ) : null}
                <span className="rounded-md bg-gray-200/90 px-1.5 py-0.5 font-mono text-[0.625rem] tabular-nums text-gray-700 dark:bg-gray-800 dark:text-gray-300">
                  score {Number.isFinite(s.score) ? s.score.toFixed(4) : s.score}
                </span>
              </div>
              <pre className="max-h-52 overflow-y-auto whitespace-pre-wrap break-words rounded-lg border border-gray-200/80 bg-white p-2.5 font-mono text-[0.6875rem] leading-relaxed text-gray-800 dark:border-gray-700 dark:bg-gray-950 dark:text-gray-200">
                {s.preview}
              </pre>
            </li>
          ))}
        </ul>
      </div>
    </details>
  );
}

/** Remote images in agent markdown (e.g. Meeting Prep briefs with Perplexity image URLs). */
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

function friendlyBridgeError(err: string): string {
  const lower = err.toLowerCase();
  if (
    lower.includes('connection refused') ||
    lower.includes('winerror 10061') ||
    lower.includes('bridge unreachable') ||
    lower.includes('connect call failed') ||
    lower.includes('econnrefused')
  ) {
    return 'Bridge server is not running. Double-click start_bridge.bat (in browser/webmcp_bridge/) to start it, then try again.';
  }
  if (
    lower.includes('extension is not connected') ||
    lower.includes('no websocket') ||
    lower.includes('(503)') ||
    lower.includes('status_code=503')
  ) {
    return 'Chrome extension is not connected. Open the extension Options, paste the token from the bridge terminal, click Save, then try again.';
  }
  if (
    lower.includes('invalid bridge token') ||
    lower.includes('(403)') ||
    lower.includes('(401)') ||
    lower.includes('status_code=403') ||
    lower.includes('status_code=401')
  ) {
    return 'Wrong token. Copy the exact token printed in the bridge terminal window and paste it in the Token field.';
  }
  if (
    lower.includes('no active tab') ||
    lower.includes('injectable tab') ||
    lower.includes('browser-internal') ||
    lower.includes('chrome://')
  ) {
    return 'Please click on a regular website tab (not chrome://extensions or other browser pages), then try again.';
  }
  if (lower.includes('no tools') || lower.includes('list_tools')) {
    return 'No tools found on the active tab. Make sure the demo page (http://127.0.0.1:8765/) is open and is your active tab.';
  }
  return err;
}

/** Appends a query param so the preview iframe refetches after demo HTML/CSS changes (avoids stale disk/HTTP cache). */
function webmcpPreviewIframeSrc(rawUrl: string, bustKey: number): string {
  const u = rawUrl.trim();
  if (!u || u === 'about:blank') return u;
  try {
    const parsed = new URL(u);
    parsed.searchParams.set('_webmcp_preview', String(bustKey));
    return parsed.toString();
  } catch {
    const sep = u.includes('?') ? '&' : '?';
    return `${u}${sep}_webmcp_preview=${bustKey}`;
  }
}

const OVERLAY_COLORS: Record<string, string> = {
  click: '#34d399',
  fill: '#fbbf24',
  select: '#a78bfa',
  hover: '#38bdf8',
};

function BrowserScreenshotFrame({ shot }: { shot: BrowserScreenshotEvent }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const [layout, setLayout] = useState<{
    ox: number;
    oy: number;
    dw: number;
    dh: number;
    nw: number;
    nh: number;
  } | null>(null);

  const recomputeLayout = useCallback(() => {
    const img = imgRef.current;
    if (!img?.naturalWidth) return;
    const nw = img.naturalWidth;
    const nh = img.naturalHeight;
    const cw = img.clientWidth;
    const ch = img.clientHeight;
    if (cw < 1 || ch < 1) return;
    const scale = Math.min(cw / nw, ch / nh);
    const dw = nw * scale;
    const dh = nh * scale;
    const ox = (cw - dw) / 2;
    const oy = (ch - dh) / 2;
    setLayout({ ox, oy, dw, dh, nw, nh });
  }, []);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => recomputeLayout());
    ro.observe(el);
    return () => ro.disconnect();
  }, [recomputeLayout]);

  const overlays = shot.overlays?.length ? shot.overlays : [];
  const showOverlays = overlays.length > 0 && layout;

  return (
    <div ref={wrapRef} className="relative w-full bg-black/30">
      <img
        ref={imgRef}
        src={`data:${shot.mime};base64,${shot.image}`}
        alt={`Step ${shot.step} screenshot`}
        className="block w-full object-contain max-h-[400px] mx-auto"
        onLoad={recomputeLayout}
      />
      {showOverlays && (
        <svg
          className="absolute left-0 top-0 pointer-events-none overflow-visible"
          style={{
            left: layout!.ox,
            top: layout!.oy,
            width: layout!.dw,
            height: layout!.dh,
          }}
          viewBox={`0 0 ${layout!.nw} ${layout!.nh}`}
          preserveAspectRatio="none"
          aria-hidden
        >
          {overlays.map((o, i) => {
            const stroke = OVERLAY_COLORS[o.kind] ?? '#a1a1aa';
            const cap = (o.label || o.kind || '').slice(0, 72);
            return (
              <g key={i}>
                <rect
                  x={o.x}
                  y={o.y}
                  width={Math.max(o.width, 2)}
                  height={Math.max(o.height, 2)}
                  fill="rgba(255,255,255,0.04)"
                  stroke={stroke}
                  strokeWidth={2.5}
                  vectorEffect="non-scaling-stroke"
                />
                {cap ? (
                  <text
                    x={o.x + 4}
                    y={o.y + 14}
                    fill="#fafafa"
                    stroke="#0a0a0a"
                    strokeWidth={3}
                    paintOrder="stroke fill"
                    style={{ fontSize: '11px', fontFamily: "'Inter', ui-sans-serif, system-ui, sans-serif" }}
                  >
                    {cap}
                  </text>
                ) : null}
              </g>
            );
          })}
        </svg>
      )}
      {overlays.length > 0 && (
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 px-2 py-1.5 text-[10px] text-gray-600 dark:text-gray-400 border-t border-gray-200 dark:border-gray-800/80 bg-gray-50 dark:bg-gray-950/90">
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm bg-emerald-400" />
            click / matched control
          </span>
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm bg-amber-400" />
            fill
          </span>
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm bg-violet-400" />
            select
          </span>
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm bg-sky-400" />
            hover
          </span>
        </div>
      )}
    </div>
  );
}

function BrowserViewport({ screenshots, htmlReportFile }: { screenshots: BrowserScreenshotEvent[]; htmlReportFile?: string }) {
  const [current, setCurrent] = useState(screenshots.length - 1);
  const [showReport, setShowReport] = useState(false);

  useEffect(() => {
    setCurrent(screenshots.length - 1);
  }, [screenshots.length]);

  if (screenshots.length === 0) return null;

  const shot = screenshots[current];
  const reportUrl = htmlReportFile
    ? `/api/browser-agent/html-report?file=${encodeURIComponent(htmlReportFile)}`
    : null;

  return (
    <div className="mt-3 rounded-xl overflow-hidden border border-gray-200 dark:border-white/10 bg-white dark:bg-gray-950 shadow-lg">
      <div className="flex items-center gap-2 px-3 py-2 bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-700">
        <Monitor className="w-4 h-4 text-emerald-400 shrink-0" />
        <span className="text-xs font-medium text-gray-700 dark:text-gray-300 flex-1">Browser Viewport</span>
        <span className={`text-xs px-1.5 py-0.5 rounded font-mono ${shot.status === 'success' ? 'bg-emerald-900 text-emerald-300' : 'bg-red-900 text-red-300'}`}>
          Step {shot.step} — {shot.status}
        </span>
        {reportUrl && (
          <button
            onClick={() => setShowReport(v => !v)}
            className="flex items-center gap-1 text-xs text-sky-400 hover:text-sky-300 transition-colors ml-1"
          >
            <ExternalLink className="w-3.5 h-3.5" />
            {showReport ? 'Hide' : 'Full Report'}
          </button>
        )}
      </div>

      {showReport && reportUrl ? (
        <iframe
          src={reportUrl}
          className="w-full h-[500px] bg-white"
          title="Browser Agent Report"
          sandbox="allow-scripts allow-same-origin"
        />
      ) : (
        <BrowserScreenshotFrame shot={shot} />
      )}

      {screenshots.length > 1 && !showReport && (
        <div className="flex items-center gap-2 px-3 py-2 bg-white dark:bg-gray-900 border-t border-gray-200 dark:border-gray-700">
          <button
            onClick={() => setCurrent(c => Math.max(0, c - 1))}
            disabled={current === 0}
            className="p-1 rounded text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white disabled:opacity-30 transition-colors"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <div className="flex gap-1 flex-1 justify-center overflow-x-auto">
            {screenshots.map((_s, i) => (
              <button
                key={i}
                onClick={() => setCurrent(i)}
                className={`w-2 h-2 rounded-full transition-colors shrink-0 ${i === current ? 'bg-emerald-400' : 'bg-gray-600 hover:bg-gray-400'}`}
              />
            ))}
          </div>
          <button
            onClick={() => setCurrent(c => Math.min(screenshots.length - 1, c + 1))}
            disabled={current === screenshots.length - 1}
            className="p-1 rounded text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white disabled:opacity-30 transition-colors"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
          <span className="text-xs text-gray-500">{current + 1}/{screenshots.length}</span>
        </div>
      )}
    </div>
  );
}

function StandaloneHtmlPreview({ html }: { html?: string }) {
  const [interactiveBlobUrl, setInteractiveBlobUrl] = useState('');
  const [shareHint, setShareHint] = useState<string | null>(null);
  const [shareBusy, setShareBusy] = useState(false);

  useEffect(() => {
    if (!html) {
      setInteractiveBlobUrl('');
      return;
    }

    const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    setInteractiveBlobUrl(url);

    return () => {
      URL.revokeObjectURL(url);
    };
  }, [html]);

  const openInteractivePreview = useCallback(() => {
    if (!interactiveBlobUrl) return;
    const a = document.createElement('a');
    a.href = interactiveBlobUrl;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }, [interactiveBlobUrl]);

  const copyShareLink = useCallback(async () => {
    if (!html) return;
    setShareBusy(true);
    setShareHint(null);
    try {
      const base = getAgentsMarketplaceApiBase();
      const res = await fetch(`${base}/api/preview/standalone-html`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ html }),
      });
      const payload = (await res.json().catch(() => ({}))) as { detail?: string; path?: string };
      if (!res.ok) {
        throw new Error(typeof payload.detail === 'string' ? payload.detail : res.statusText);
      }
      const path = payload.path;
      if (!path || typeof path !== 'string') {
        throw new Error('Invalid response from server');
      }
      const url = `${base}${path}`;
      try {
        await navigator.clipboard.writeText(url);
        setShareHint('Link copied — send it to anyone who can reach this API host.');
      } catch {
        const ta = document.createElement('textarea');
        ta.value = url;
        ta.setAttribute('readonly', '');
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        setShareHint('Link copied — send it to anyone who can reach this API host.');
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Could not create share link';
      setShareHint(msg);
    } finally {
      setShareBusy(false);
    }
  }, [html]);

  useEffect(() => {
    setShareHint(null);
  }, [html]);

  if (!html) return null;

  return (
    <div className="mt-3 rounded-xl overflow-hidden border border-gray-200 dark:border-white/10 bg-white dark:bg-gray-950 shadow-lg">
      <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-center gap-2 min-w-0">
        <LayoutGrid className="w-4 h-4 text-cyan-300 shrink-0" />
        <span className="text-xs font-medium text-gray-700 dark:text-gray-300">Standalone HTML Preview</span>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 shrink-0">
        <button
          type="button"
          onClick={openInteractivePreview}
          disabled={!interactiveBlobUrl}
          className="inline-flex items-center gap-1 rounded-md border border-cyan-400/40 bg-cyan-500/10 px-2 py-1 text-[11px] font-medium text-cyan-200 transition-colors hover:bg-cyan-500/20 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <ExternalLink className="h-3.5 w-3.5" />
          Open in new tab
        </button>
        <button
          type="button"
          onClick={() => void copyShareLink()}
          disabled={shareBusy}
          className="inline-flex items-center gap-1 rounded-md border border-violet-400/40 bg-violet-500/10 px-2 py-1 text-[11px] font-medium text-violet-200 transition-colors hover:bg-violet-500/20 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {shareBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Share2 className="h-3.5 w-3.5" />}
          Copy share link
        </button>
        </div>
      </div>
      {shareHint ? (
        <div
          className={`px-3 py-2 text-[11px] border-b border-gray-200 dark:border-gray-700 ${
            shareHint.startsWith('Link copied')
              ? 'bg-emerald-950/40 text-emerald-100'
              : 'bg-amber-950/40 text-amber-100'
          }`}
        >
          {shareHint}
        </div>
      ) : null}
      <iframe
        srcDoc={html}
        title="Standalone HTML Preview"
        className="w-full h-[420px] bg-white"
        sandbox="allow-scripts allow-forms allow-modals allow-popups allow-downloads"
        allow="clipboard-read; clipboard-write; file-system-access"
      />
      <div className="border-t border-gray-200 bg-gray-50 px-3 py-2 text-[11px] text-gray-600 dark:border-gray-700 dark:bg-gray-900/70 dark:text-gray-300">
        For uploads or stricter sandbox limits, use Open in new tab. To send this page to someone else, use Copy share link (they need access to the same API server).
      </div>
    </div>
  );
}

function ThinkingStepsDisplay({ steps, isStreaming }: { steps: ThinkingStep[]; isStreaming?: boolean }) {
  const [isExpanded, setIsExpanded] = useState(() => Boolean(isStreaming));
  const prevStreamingRef = useRef(isStreaming);

  useEffect(() => {
    const wasStreaming = prevStreamingRef.current;
    if (wasStreaming && !isStreaming) {
      setIsExpanded(false);
    }
    prevStreamingRef.current = isStreaming;
  }, [isStreaming]);

  if (!steps || steps.length === 0) return null;

  const getStepIcon = (type: string) => {
    switch (type) {
      case 'thinking':
        return <Brain className="w-3.5 h-3.5 text-violet-500 dark:text-violet-400" />;
      case 'tool':
        return <Wrench className="w-3.5 h-3.5 text-indigo-500 dark:text-indigo-400" />;
      case 'tool_call':
        return <Wrench className="w-3.5 h-3.5 text-sky-500 dark:text-sky-400" />;
      case 'tool_result':
        return <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 dark:text-emerald-400" />;
      case 'llm_call':
        return <Cpu className="w-3.5 h-3.5 text-amber-500 dark:text-amber-400" />;
      case 'llm_response':
        return <ScrollText className="w-3.5 h-3.5 text-teal-500 dark:text-teal-400" />;
      default:
        return <Brain className="w-3.5 h-3.5 text-gray-500" />;
    }
  };

  const getStepLabel = (step: ThinkingStep) => {
    switch (step.type) {
      case 'thinking':
        return 'Thinking';
      case 'tool':
        return step.tool_name ? `Step · ${step.tool_name}` : 'Step';
      case 'tool_call':
        return `Calling: ${step.tool_name}`;
      case 'tool_result':
        return `Result from ${step.tool_name}`;
      case 'llm_call':
        return 'LLM request';
      case 'llm_response':
        return 'LLM response';
      default:
        return 'Processing';
    }
  };

  return (
    <div className="mb-3 overflow-hidden rounded-xl border border-gray-200/90 bg-white/70 shadow-md shadow-gray-900/[0.04] ring-1 ring-black/[0.02] backdrop-blur-md transition-shadow duration-300 dark:border-white/[0.08] dark:bg-zinc-900/50 dark:shadow-black/25 dark:ring-white/[0.04]">
      <div
        className="pointer-events-none h-px bg-gradient-to-r from-transparent via-primary-500/50 to-transparent opacity-70"
        aria-hidden
      />
      <button
        type="button"
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left transition-colors hover:bg-gray-50/90 dark:hover:bg-white/[0.04]"
      >
        <span className="text-gray-600 transition-transform duration-200 dark:text-zinc-500" style={{ transform: isExpanded ? 'rotate(0deg)' : 'rotate(-90deg)' }}>
          <ChevronDown className="h-3.5 w-3.5" />
        </span>
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-violet-500/15 to-primary-500/10 ring-1 ring-violet-500/20 dark:from-violet-400/10 dark:to-primary-500/10">
          <Brain className="h-3.5 w-3.5 text-violet-600 dark:text-violet-300" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-body text-xs font-semibold text-gray-800 dark:text-zinc-200">
              Reasoning trace
            </span>
            <span className="rounded-md bg-gray-100/90 px-1.5 py-0.5 font-body text-[0.625rem] font-bold tabular-nums text-gray-500 dark:bg-zinc-800 dark:text-zinc-400">
              {steps.length}
            </span>
            {isStreaming && (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-primary-500/25 bg-primary-500/10 px-2 py-0.5 font-body text-[0.625rem] font-semibold uppercase tracking-wide text-primary-700 dark:text-primary-300">
                <span className="relative flex h-1.5 w-1.5">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary-400 opacity-60" />
                  <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-primary-500" />
                </span>
                Live
              </span>
            )}
          </div>
        </div>
      </button>

      <div
        className={`grid transition-[grid-template-rows] duration-300 ease-out ${isExpanded ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}
      >
        <div className="min-h-0 overflow-hidden">
          <div className="border-t border-gray-100/90 px-3 pb-3 pt-1 dark:border-white/[0.06]">
            <div className="relative ml-2 space-y-0 border-l-2 border-primary-500/15 pl-4 dark:border-primary-400/20">
              {steps.map((step, index) => {
                const isLast = index === steps.length - 1;
                const livePulse = isStreaming && isLast;
                return (
                  <div
                    key={index}
                    className="relative pb-4 last:pb-1 animate-fade-in"
                    style={{ animationDelay: `${Math.min(index * 45, 400)}ms` }}
                  >
                    <span
                      className={`absolute -left-[21px] top-1.5 flex h-2.5 w-2.5 rounded-full border-2 border-white shadow-sm dark:border-zinc-900 ${
                        livePulse
                          ? 'bg-primary-500 shadow-[0_0_12px_rgba(232,141,20,0.55)] animate-pulse'
                          : step.type === 'tool_result'
                            ? 'bg-emerald-500'
                            : step.type === 'tool_call' || step.type === 'tool'
                              ? 'bg-sky-500'
                              : step.type === 'llm_call'
                                ? 'bg-amber-500'
                                : step.type === 'llm_response'
                                  ? 'bg-teal-500'
                                  : 'bg-violet-500'
                      }`}
                      aria-hidden
                    />
                    <div className="flex items-start gap-2 text-xs">
                      <div className="mt-0.5 shrink-0 opacity-90">{getStepIcon(step.type)}</div>
                      <div className="min-w-0 flex-1">
                        <div className="mb-0.5 flex flex-wrap items-center gap-2 font-semibold text-gray-800 dark:text-zinc-200">
                          <span>{getStepLabel(step)}</span>
                          {(step.model || step.provider) && (
                            <span className="rounded-md bg-gray-100/90 px-1.5 py-0.5 font-mono text-[0.625rem] font-normal text-gray-600 dark:bg-zinc-800 dark:text-zinc-400">
                              {[step.provider, step.model].filter(Boolean).join(' · ')}
                              {step.prompt_length != null && step.type === 'llm_call'
                                ? ` · ${step.prompt_length} chars`
                                : ''}
                              {step.response_length != null && step.type === 'llm_response'
                                ? ` · ${step.response_length} chars`
                                : ''}
                            </span>
                          )}
                        </div>
                        {step.tool_input && (step.type === 'tool_call' || step.type === 'llm_call') && (
                          <div className="mb-1 max-h-48 overflow-y-auto break-all rounded-lg border border-gray-200/80 bg-gray-50/90 px-2 py-1.5 font-mono text-[0.6875rem] text-gray-600 dark:border-zinc-700 dark:bg-zinc-950/80 dark:text-zinc-400">
                            {step.tool_input}
                          </div>
                        )}
                        <div
                          className={`overflow-y-auto break-words font-body text-[0.8125rem] leading-relaxed text-gray-600 dark:text-zinc-400 ${
                            step.type === 'llm_response' ? 'max-h-96 min-h-0' : 'max-h-60'
                          }`}
                        >
                          {step.type === 'llm_response' && step.truncated && (
                            <p className="mb-1 text-[0.6875rem] font-medium text-amber-700 dark:text-amber-400">
                              Preview truncated for the trace panel; full text is still used for the reply.
                            </p>
                          )}
                          {step.content}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function StreamContentSkeleton() {
  return (
    <div className="space-y-2.5 py-0.5" aria-hidden>
      <div className="chat-stream-skeleton-track h-2.5 w-[92%]" />
      <div className="chat-stream-skeleton-track h-2.5 w-[78%]" />
      <div className="chat-stream-skeleton-track h-2.5 w-[64%]" />
    </div>
  );
}

export default function ChatInterface({ agent, onOpenConfigTab, blockedByUnsavedConfig = false }: ChatInterfaceProps) {
  const [messages, setMessages] = useState<ExtendedChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  /** Identifies which Playwright code block is currently re-running (length + prefix hash). */
  const [pendingRerunScriptKey, setPendingRerunScriptKey] = useState<string | null>(null);
  const [currentThinkingStep, setCurrentThinkingStep] = useState<string>('');
  const [sessionId] = useState(() => `session-${Date.now()}`);
  const [uploadedFile, setUploadedFile] = useState<{ name: string; content: string; type: string; size?: number } | null>(null);
  const [githubToken, setGithubToken] = useState('');
  const [showTokenInput, setShowTokenInput] = useState(false);
  const [pendingPushQuery, setPendingPushQuery] = useState('');
  const [regeneratingDiagram, setRegeneratingDiagram] = useState<string | null>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const messageTextareaRef = useRef<HTMLTextAreaElement>(null);

  const [pptSlideImageModal, setPptSlideImageModal] = useState<{
    src: string;
    alt: string;
    caption?: string;
  } | null>(null);

  const [mongoIngested, setMongoIngested] = useState(false);
  const [showTextInput, setShowTextInput] = useState(false);
  const [rawTextInput, setRawTextInput] = useState('');

  useEffect(() => {
    setMongoIngested(false);
    setShowTextInput(false);
    setRawTextInput('');
  }, [agent.id]);

  useEffect(() => {
    if (!pptSlideImageModal) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setPptSlideImageModal(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [pptSlideImageModal]);

  const isBPMNAgent = agent.id === 'bpmn_generator';
  const isGitHubAgent = agent.id === 'github_repo';
  const isMongoRAGAgent = agent.id === 'mongodb_rag';
  const isDocFormatterAgent = agent.id === 'document_formatter';
  const isPPTAgent = agent.id === 'ppt_generator';
  const isCoderAgent = agent.id === 'coder_agent';
  const isCompanySolutionAgent = agent.id === 'company_solution_advisor';
  const isBrowserAutomationAgent = agent.id === 'browser_agent';
  const isWebMcpAgent = agent.id === 'webmcp_agent';

  const [browserCdpEndpoint, setBrowserCdpEndpoint] = useState(() => {
    try {
      return localStorage.getItem(BROWSER_CDP_STORAGE_KEY) ?? '';
    } catch {
      return '';
    }
  });

  const [browserRememberLogins, setBrowserRememberLogins] = useState(() => {
    try {
      const v = localStorage.getItem(BROWSER_REMEMBER_LOGINS_KEY);
      if (v === '0' || v === 'false') return false;
      return true;
    } catch {
      return true;
    }
  });

  const [browserRunInBackground, setBrowserRunInBackground] = useState(() => {
    try {
      const v = localStorage.getItem(BROWSER_HEADLESS_KEY);
      return v === '1' || v === 'true' || v === 'yes';
    } catch {
      return false;
    }
  });

  useEffect(() => {
    if (!isBrowserAutomationAgent) return;
    try {
      localStorage.setItem(BROWSER_CDP_STORAGE_KEY, browserCdpEndpoint);
    } catch {
      /* ignore quota / private mode */
    }
  }, [browserCdpEndpoint, isBrowserAutomationAgent]);

  useEffect(() => {
    if (!isBrowserAutomationAgent) return;
    try {
      localStorage.setItem(BROWSER_REMEMBER_LOGINS_KEY, browserRememberLogins ? '1' : '0');
    } catch {
      /* ignore */
    }
  }, [browserRememberLogins, isBrowserAutomationAgent]);

  useEffect(() => {
    if (!isBrowserAutomationAgent) return;
    try {
      localStorage.setItem(BROWSER_HEADLESS_KEY, browserRunInBackground ? '1' : '0');
    } catch {
      /* ignore */
    }
  }, [browserRunInBackground, isBrowserAutomationAgent]);

  const [browserClosing, setBrowserClosing] = useState(false);
  const [browserCloseMsg, setBrowserCloseMsg] = useState<string | null>(null);
  const handleCloseBrowser = useCallback(async () => {
    setBrowserClosing(true);
    setBrowserCloseMsg(null);
    try {
      const base = (window as any).__API_BASE ?? '';
      const resp = await fetch(`${base}/api/browser-agent/close`, { method: 'POST' });
      const data = await resp.json();
      const msg = data?.message || 'Browser closed.';
      setBrowserCloseMsg(msg);
      console.info('[BrowserAgent] Close:', msg);
    } catch (err) {
      setBrowserCloseMsg('Failed to reach server.');
      console.error('[BrowserAgent] Close error:', err);
    } finally {
      setBrowserClosing(false);
      setTimeout(() => setBrowserCloseMsg(null), 4000);
    }
  }, []);

  const browserAgentStreamExtras = useMemo(() => {
    if (!isBrowserAutomationAgent) return {};
    const cdp = browserCdpEndpoint.trim();
    return {
      headless: browserRunInBackground,
      rememberLogins: !cdp && browserRememberLogins,
      keepBrowserSession: true,
      ...(cdp ? { cdpEndpoint: cdp } : {}),
    };
  }, [
    isBrowserAutomationAgent,
    browserCdpEndpoint,
    browserRememberLogins,
    browserRunInBackground,
  ]);

  const [webmcpBridgeUrl, setWebmcpBridgeUrl] = useState(() => {
    try {
      return localStorage.getItem(WEBMCP_BRIDGE_URL_KEY) ?? 'http://127.0.0.1:3847';
    } catch {
      return 'http://127.0.0.1:3847';
    }
  });
  const [webmcpBridgeToken, setWebmcpBridgeToken] = useState(() => {
    try {
      return localStorage.getItem(WEBMCP_BRIDGE_TOKEN_SESSION_KEY) ?? '';
    } catch {
      return '';
    }
  });
  const [webmcpBridgeStatus, setWebmcpBridgeStatus] = useState<string | null>(null);
  const [webmcpBridgeTesting, setWebmcpBridgeTesting] = useState(false);
  const [webmcpShowPreview, setWebmcpShowPreview] = useState(true);
  const [webmcpPreviewUrl, setWebmcpPreviewUrl] = useState('http://127.0.0.1:8765/');
  const [webmcpIframeKey, setWebmcpIframeKey] = useState(() => Date.now());
  const webmcpIframeBlocked = useMemo(
    () => isWebMcpAgent && /^file:/i.test(webmcpPreviewUrl.trim()),
    [isWebMcpAgent, webmcpPreviewUrl]
  );
  const webmcpIframeSrc = webmcpIframeBlocked ? 'about:blank' : webmcpPreviewUrl;
  const webmcpIframeEffectiveSrc = useMemo(
    () => webmcpPreviewIframeSrc(webmcpIframeSrc, webmcpIframeKey),
    [webmcpIframeSrc, webmcpIframeKey]
  );

  useEffect(() => {
    if (!isWebMcpAgent) return;
    try {
      localStorage.setItem(WEBMCP_BRIDGE_URL_KEY, webmcpBridgeUrl);
    } catch {
      /* ignore */
    }
  }, [webmcpBridgeUrl, isWebMcpAgent]);

  useEffect(() => {
    if (!isWebMcpAgent) return;
    try {
      if (webmcpBridgeToken.trim()) {
        localStorage.setItem(WEBMCP_BRIDGE_TOKEN_SESSION_KEY, webmcpBridgeToken);
      } else {
        localStorage.removeItem(WEBMCP_BRIDGE_TOKEN_SESSION_KEY);
      }
    } catch {
      /* ignore */
    }
  }, [webmcpBridgeToken, isWebMcpAgent]);

  const webmcpAgentStreamExtras = useMemo(() => {
    if (!isWebMcpAgent) return {};
    return {
      webmcpBridgeUrl: webmcpBridgeUrl.trim(),
      webmcpBridgeToken: webmcpBridgeToken.trim(),
    };
  }, [isWebMcpAgent, webmcpBridgeUrl, webmcpBridgeToken]);

  const streamTransportExtras = useMemo(
    () => ({ ...browserAgentStreamExtras, ...webmcpAgentStreamExtras }),
    [browserAgentStreamExtras, webmcpAgentStreamExtras],
  );

  const configFields = getConfigFields(agent);
  const needsConfig = configFields.length > 0;
  const [configMissing, setConfigMissing] = useState(false);

  useEffect(() => {
    if (needsConfig) {
      setConfigMissing(!hasRequiredConfig(agent, configFields));
    }
  }, [agent.id, needsConfig]);

  const getUserConfig = (): Record<string, string> | undefined =>
    needsConfig ? getUserConfigPayloadForRequest(agent) : undefined;

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    
    const allowedTypes = isMongoRAGAgent
      ? ['pdf', 'docx', 'doc', 'xlsx', 'xls', 'pptx', 'ppt', 'txt', 'csv', 'md', 'json', 'xml']
      : isDocFormatterAgent
        ? ['pdf', 'docx', 'doc', 'pptx', 'ppt', 'xlsx', 'xls', 'txt', 'md', 'html', 'htm', 'csv', 'json', 'xml', 'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp']
        : isPPTAgent
          ? ['csv', 'xlsx', 'xls', 'pdf', 'txt', 'docx', 'doc']
          : isCoderAgent
            ? ['pdf', 'docx', 'doc', 'xlsx', 'xls', 'csv', 'txt']
            : isCompanySolutionAgent
              ? ['pdf', 'docx', 'doc', 'txt', 'md', 'html', 'htm']
              : ['pdf', 'docx', 'doc', 'xlsx', 'xls', 'txt'];
    const fileExt = file.name.split('.').pop()?.toLowerCase() || '';

    if (!allowedTypes.includes(fileExt)) {
      alert(isMongoRAGAgent
        ? 'Unsupported file type. Please upload PDF, Word, Excel, PowerPoint, or text files.'
        : isDocFormatterAgent
          ? 'Unsupported file type. Please upload PDF, Word, PowerPoint, Excel, HTML, text, or image files.'
          : isPPTAgent
            ? 'Unsupported file type. Please upload CSV, Excel, PDF, text, or Word files.'
            : isCoderAgent
              ? 'Unsupported file type. Please upload PDF, CSV, Excel, DOCX, or text files.'
              : isCompanySolutionAgent
                ? 'Unsupported file type. Please upload PDF, Word, text, Markdown, or HTML files.'
                : 'Unsupported file type. Please upload PDF, Word, Excel, or text files.');
      return;
    }
    
    const reader = new FileReader();
    reader.onload = () => {
      const base64 = (reader.result as string).split(',')[1];
      setUploadedFile({
        name: file.name,
        content: base64,
        type: fileExt,
        size: file.size
      });
    };
    reader.readAsDataURL(file);
  };
  
  const clearUploadedFile = () => {
    setUploadedFile(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const scrollToBottom = useCallback(() => {
    const root = scrollContainerRef.current;
    if (!root) return;
    const behavior: ScrollBehavior = isLoading ? 'auto' : 'smooth';
    const scrollsInternally = root.scrollHeight > root.clientHeight + 1;
    if (scrollsInternally) {
      root.scrollTo({ top: root.scrollHeight, behavior });
      return;
    }
    window.scrollTo({ top: document.documentElement.scrollHeight, behavior });
  }, [isLoading]);

  const MESSAGE_TEXTAREA_MAX_PX = 200;

  const adjustMessageTextareaHeight = useCallback(() => {
    const el = messageTextareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, MESSAGE_TEXTAREA_MAX_PX)}px`;
  }, []);

  useEffect(() => {
    adjustMessageTextareaHeight();
  }, [input, adjustMessageTextareaHeight]);

  useEffect(() => {
    scrollToBottom();
  }, [messages, currentThinkingStep, isLoading, scrollToBottom]);

  useEffect(() => {
    if (isMongoRAGAgent && messages.length === 0) {
      const welcomeMessage: ExtendedChatMessage = {
        role: 'assistant',
        content:
          "Welcome to the **MongoDB Atlas KB Agent**! \uD83C\uDF3F\n\n" +
          "I can help you build a knowledge base from your documents and answer questions using semantic search.\n\n" +
          "**How it works:**\n" +
          "1. Set **MONGODB_URI** on the **Config** tab (required) and save\n" +
          "2. Upload documents (PDF, Word, Excel, PowerPoint, TXT) or paste text\n" +
          "3. I'll chunk, embed, and store them in your Atlas cluster\n" +
          "4. Ask any question and I'll retrieve relevant context to answer!",
        timestamp: new Date().toISOString(),
      };
      setMessages([welcomeMessage]);
    }
  }, [isMongoRAGAgent]);

  const handleRegenerateDiagram = async (diagramType: 'architecture' | 'dataflow') => {
    if (isLoading || regeneratingDiagram) return;
    setRegeneratingDiagram(diagramType);
    const prompt = diagramType === 'architecture'
      ? 'Regenerate the architecture diagram'
      : 'Regenerate the data flow diagram';
    try {
      let fullResponse = '';
      await chatWithAgentStream(agent, prompt, { sessionId, githubToken: githubToken?.trim() || undefined, userConfig: getUserConfig() }, {
        onResponseChunk: (chunk, meta) => {
          if (meta?.reset) fullResponse = '';
          fullResponse += chunk;
        },
        onDone: (data) => { fullResponse = data.response || fullResponse; },
      });
      if (fullResponse) {
        setMessages((prev) => {
          const updated = [...prev];
          const lastAssistantIdx = updated.map((m, i) => m.role === 'assistant' ? i : -1).filter(i => i >= 0).pop();
          if (lastAssistantIdx !== undefined && lastAssistantIdx >= 0) {
            const oldContent = updated[lastAssistantIdx].content;
            const archHeading = '### Architecture Diagram';
            const dataFlowHeading = '### Data Flow Architecture Diagram';
            if (diagramType === 'architecture') {
              const archStart = oldContent.indexOf(archHeading);
              const dataFlowStart = oldContent.indexOf(dataFlowHeading);
              if (archStart >= 0) {
                const endPos = dataFlowStart >= 0 ? dataFlowStart : oldContent.length;
                const newArchSection = fullResponse.includes(archHeading) ? fullResponse.substring(fullResponse.indexOf(archHeading)) : fullResponse;
                const archOnly = newArchSection.includes(dataFlowHeading) ? newArchSection.substring(0, newArchSection.indexOf(dataFlowHeading)) : newArchSection;
                updated[lastAssistantIdx] = { ...updated[lastAssistantIdx], content: oldContent.substring(0, archStart) + archOnly.trim() + '\n\n' + oldContent.substring(endPos) };
              }
            } else {
              const dataFlowStart = oldContent.indexOf(dataFlowHeading);
              if (dataFlowStart >= 0) {
                const newFlowSection = fullResponse.includes(dataFlowHeading) ? fullResponse.substring(fullResponse.indexOf(dataFlowHeading)) : fullResponse;
                updated[lastAssistantIdx] = { ...updated[lastAssistantIdx], content: oldContent.substring(0, dataFlowStart) + newFlowSection.trim() };
              }
            }
          }
          return updated;
        });
      }
    } catch (e) {
      console.error('Failed to regenerate diagram:', e);
    } finally {
      setRegeneratingDiagram(null);
    }
  };

  const handleSuggestionClick = (text: string) => {
    if (isLoading) return;
    handleSend(text);
  };

  const handleTextIngest = async () => {
    if (!rawTextInput.trim() || isLoading) return;
    const text = rawTextInput.trim();
    setRawTextInput('');
    setShowTextInput(false);

    setMessages((prev) => [...prev, { role: 'user', content: `Ingest text (${text.length} characters)`, timestamp: new Date().toISOString() }]);
    setIsLoading(true);
    setCurrentThinkingStep('Processing and embedding text...');

    const assistantMsg: ExtendedChatMessage = { role: 'assistant', content: '', timestamp: new Date().toISOString() };
    setMessages((prev) => [...prev, assistantMsg]);

    try {
      await chatWithAgentStream(agent, 'ingest text', { sessionId, rawText: text, userConfig: getUserConfig() }, {
        onThinking: (step) => {
          setCurrentThinkingStep(step.content || 'Processing...');
          setMessages((prev) => { const u = [...prev]; const l = u.length - 1; if (u[l]?.role === 'assistant') u[l] = { ...u[l], thinking_steps: [...(u[l].thinking_steps || []), step] }; return u; });
        },
        onResponseChunk: (chunk, meta) => {
          setMessages((prev) => {
            const u = [...prev]; const l = u.length - 1;
            if (u[l]?.role === 'assistant') {
              const base = meta?.reset ? '' : (u[l].content || '');
              u[l] = { ...u[l], content: base + chunk };
            }
            return u;
          });
        },
        onDone: (data) => {
          if (data.ingested) {
            if (isMongoRAGAgent) setMongoIngested(true);
          }
          setMessages((prev) => { const u = [...prev]; const l = u.length - 1; if (u[l]?.role === 'assistant' && !u[l].content) u[l] = { ...u[l], content: data.response || 'Text ingestion completed.' }; return u; });
        },
        onError: (err) => {
          setMessages((prev) => { const u = [...prev]; const l = u.length - 1; if (u[l]?.role === 'assistant') u[l] = { ...u[l], content: `Ingestion failed: ${err.message}` }; return u; });
        },
      });
    } catch (error: any) {
      setMessages((prev) => { const u = [...prev]; const l = u.length - 1; if (u[l]?.role === 'assistant') u[l] = { ...u[l], content: `Ingestion failed: ${error.message}` }; return u; });
    } finally {
      setIsLoading(false);
      setCurrentThinkingStep('');
    }
  };

  const handleRunBrowserScript = async (
    scriptSource: string,
    replaySteps?: Record<string, unknown>[] | null,
  ) => {
    if (!isBrowserAutomationAgent || isLoading) return;

    if (needsConfig) {
      const effective = getEffectiveConfig(agent);
      if (!hasRequiredConfigForEffective(agent, configFields, effective)) {
        const stillMissing = getMissingRequiredFieldsForEffective(agent, configFields, effective);
        setConfigMissing(true);
        if (stillMissing.length > 0) {
          setMessages((prev) => [...prev, {
            role: 'assistant',
            content: `**Configuration Required**\n\nThis agent needs the following settings before it can process your request:\n\n${stillMissing.map(f => `- **\`${f.key}\`** — ${f.description}`).join('\n')}\n\nPlease go to the **Config** tab in the sidebar to enter your settings, then try again.`,
            timestamp: new Date().toISOString(),
          }]);
        }
        return;
      }
      setConfigMissing(false);
    }

    const blockKey = `${scriptSource.length}:${scriptSource.slice(0, 64)}`;
    const userMessage: ExtendedChatMessage = {
      role: 'user',
      content: 'Re-run generated Playwright script',
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMessage]);
    setIsLoading(true);
    setPendingRerunScriptKey(blockKey);
    setCurrentThinkingStep('Running exported Playwright script…');

    const assistantMsg: ExtendedChatMessage = {
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString(),
      browser_screenshots: [],
    };
    setMessages((prev) => [...prev, assistantMsg]);

    try {
      await chatWithAgentStream(
        agent,
        'Re-run generated Playwright script',
        {
          sessionId,
          userConfig: getUserConfig(),
          rerunStandaloneScript: scriptSource,
          replayStepsExecuted:
            replaySteps && replaySteps.length > 0 ? replaySteps : undefined,
          ...streamTransportExtras,
        },
        {
          onStart: () => setCurrentThinkingStep('Running exported Playwright script…'),
          onThinking: (step) => {
            setCurrentThinkingStep(step.content || 'Thinking...');
            setMessages((prev) => {
              const u = [...prev]; const l = u.length - 1;
              if (u[l]?.role === 'assistant') u[l] = { ...u[l], thinking_steps: [...(u[l].thinking_steps || []), step] };
              return u;
            });
          },
          onProgress: (data) => {
            setCurrentThinkingStep(data.message || data.stage || 'Processing...');
            setMessages((prev) => {
              const u = [...prev]; const l = u.length - 1;
              if (u[l]?.role === 'assistant') u[l] = { ...u[l], thinking_steps: [...(u[l].thinking_steps || []), { type: 'thinking', content: data.message || data.stage }] };
              return u;
            });
          },
          onBrowserScreenshot: (data) => {
            setMessages((prev) => {
              const u = [...prev]; const l = u.length - 1;
              if (u[l]?.role === 'assistant') {
                u[l] = {
                  ...u[l],
                  browser_screenshots: [...(u[l].browser_screenshots || []), data],
                };
              }
              return u;
            });
          },
          onResponseChunk: (chunk, meta) => {
            setMessages((prev) => {
              const u = [...prev]; const l = u.length - 1;
              if (u[l]?.role === 'assistant') {
                const base = meta?.reset ? '' : (u[l].content || '');
                u[l] = { ...u[l], content: base + chunk };
              }
              return u;
            });
          },
          onDone: (data) => {
            setMessages((prev) => {
              const u = [...prev]; const l = u.length - 1;
              if (u[l]?.role === 'assistant') {
                const steps = data.steps_executed;
                u[l] = {
                  ...u[l],
                  browser_html_report_file: data.html_report_file,
                  browser_steps_executed: Array.isArray(steps) ? steps as Record<string, unknown>[] : u[l].browser_steps_executed,
                };
                if (!u[l].content && data.response) u[l] = { ...u[l], content: data.response };
              }
              return u;
            });
          },
          onError: (err) => {
            setMessages((prev) => {
              const u = [...prev]; const l = u.length - 1;
              if (u[l]?.role === 'assistant') u[l] = { ...u[l], content: `Error: ${err.message}` };
              return u;
            });
          },
        },
      );
    } catch (error: unknown) {
      const msg = error instanceof Error ? error.message : 'Something went wrong.';
      setMessages((prev) => {
        const u = [...prev]; const l = u.length - 1;
        if (u[l]?.role === 'assistant' && !u[l].content) {
          u[l] = { ...u[l], content: `Error: ${msg}` };
          return u;
        }
        return [...prev, { role: 'assistant', content: `Error: ${msg}`, timestamp: new Date().toISOString() }];
      });
    } finally {
      setIsLoading(false);
      setPendingRerunScriptKey(null);
      setCurrentThinkingStep('');
    }
  };

  const handleSend = async (directMessage?: string) => {
    const msgText = directMessage || input.trim();
    if ((!msgText && !uploadedFile) || isLoading) return;

    if (isWebMcpAgent && !webmcpBridgeToken.trim()) {
      setMessages((prev) => [...prev, {
        role: 'assistant',
        content: '**Token required.** Paste the token printed by `start_bridge.bat` into the **Token** field above, then send your message.',
        timestamp: new Date().toISOString(),
      }]);
      return;
    }

    if (needsConfig) {
      const effective = getEffectiveConfig(agent);
      if (!hasRequiredConfigForEffective(agent, configFields, effective)) {
        const stillMissing = getMissingRequiredFieldsForEffective(agent, configFields, effective);
        setConfigMissing(true);
        if (stillMissing.length > 0) {
          setMessages((prev) => [...prev, {
            role: 'assistant',
            content: `**Configuration Required**\n\nThis agent needs the following settings before it can process your request:\n\n${stillMissing.map(f => `- **\`${f.key}\`** — ${f.description}`).join('\n')}\n\nPlease go to the **Config** tab in the sidebar to enter your settings, then try again.`,
            timestamp: new Date().toISOString(),
          }]);
        }
        return;
      }
      setConfigMissing(false);
    }

    const messageContent = msgText || (uploadedFile ? (isMongoRAGAgent ? `Ingest file: ${uploadedFile.name}` : isDocFormatterAgent ? `Format document: ${uploadedFile.name}` : isPPTAgent ? `Create presentation from uploaded file: ${uploadedFile.name}` : isCoderAgent ? `Build standalone HTML from uploaded file: ${uploadedFile.name}` : isCompanySolutionAgent ? `Analyze the attached document: ${uploadedFile.name}` : `Generate BPMN from uploaded file: ${uploadedFile.name}`) : '');
    const userMessage: ExtendedChatMessage = {
      role: 'user',
      content: uploadedFile ? `${messageContent} [File: ${uploadedFile.name}]` : messageContent,
      timestamp: new Date().toISOString(),
      file_name: uploadedFile?.name,
    };

    setMessages((prev) => [...prev, userMessage]);
    const currentInput = msgText || (uploadedFile ? (isMongoRAGAgent ? `Ingest file: ${uploadedFile.name}` : isDocFormatterAgent ? `Extract and format the content from this document` : isPPTAgent ? 'Create a professional presentation from the uploaded file. Highlight executive summary, key terms, and key business points.' : isCoderAgent ? 'Use this uploaded file as business context, expand the problem into outcomes, build section-wise code, review/test it, and return one standalone self-sufficient HTML page.' : isCompanySolutionAgent ? 'Analyze the attached document as the business problem description and recommend AI/agentic solutions.' : 'Generate BPMN from this document') : '');
    const currentFile = uploadedFile;
    if (!directMessage) setInput('');
    clearUploadedFile();
    setIsLoading(true);
    setCurrentThinkingStep('Analyzing your request...');

    const assistantMsg: ExtendedChatMessage = { role: 'assistant', content: '', timestamp: new Date().toISOString() };
    setMessages((prev) => [...prev, assistantMsg]);

    try {
      let doneData: any = null;

      await chatWithAgentStream(agent, currentInput, {
        sessionId,
        fileContent: currentFile?.content,
        fileType: currentFile?.type,
        fileName: currentFile?.name,
        userConfig: getUserConfig(),
        ...streamTransportExtras,
      }, {
        onStart: () => {
          setCurrentThinkingStep(`Processing with ${agent.name}...`);
        },
        onThinking: (step) => {
          setCurrentThinkingStep(step.content || 'Thinking...');
          setMessages((prev) => {
            const u = [...prev]; const l = u.length - 1;
            if (u[l]?.role === 'assistant') u[l] = { ...u[l], thinking_steps: [...(u[l].thinking_steps || []), step] };
            return u;
          });
        },
        onProgress: (data) => {
          setCurrentThinkingStep(data.message || data.stage || 'Processing...');
          setMessages((prev) => {
            const u = [...prev]; const l = u.length - 1;
            if (u[l]?.role === 'assistant') u[l] = { ...u[l], thinking_steps: [...(u[l].thinking_steps || []), { type: 'thinking', content: data.message || data.stage }] };
            return u;
          });
        },
        onBrowserScreenshot: (data) => {
          setMessages((prev) => {
            const u = [...prev]; const l = u.length - 1;
            if (u[l]?.role === 'assistant') {
              u[l] = {
                ...u[l],
                browser_screenshots: [...(u[l].browser_screenshots || []), data],
              };
            }
            return u;
          });
        },
        onPptSlideSnapshot: (data) => {
          setMessages((prev) => {
            const u = [...prev]; const l = u.length - 1;
            if (u[l]?.role === 'assistant') {
              u[l] = {
                ...u[l],
                ppt_slide_snapshots: [...(u[l].ppt_slide_snapshots || []), data],
              };
            }
            return u;
          });
        },
        onResponseChunk: (chunk, meta) => {
          setMessages((prev) => {
            const u = [...prev]; const l = u.length - 1;
            if (u[l]?.role === 'assistant') {
              const base = meta?.reset ? '' : (u[l].content || '');
              u[l] = { ...u[l], content: base + chunk };
            }
            return u;
          });
        },
        onDone: (data) => {
          doneData = data;
          setMessages((prev) => {
            const u = [...prev]; const l = u.length - 1;
            if (u[l]?.role === 'assistant') {
                const steps = data.steps_executed;
                const rs = data.research_sources;
                u[l] = {
                  ...u[l],
                  bpmn_xml: data.bpmn_xml,
                  requires_token: data.requires_token,
                  stackblitz_repo: data.stackblitz_repo,
                  latest_news_cards: data.latest_news_cards,
                  chart_data: data.chart_data,
                  email_preview: data.email_preview,
                  download_url: data.download_url,
                  download_file_name: data.file_name,
                  ppt_research_sources: Array.isArray(rs) ? rs : u[l].ppt_research_sources,
                  is_web_search: data.search_focus !== undefined && data.sources !== undefined,
                  web_search_sources: data.search_focus !== undefined ? data.sources : undefined,
                  mongodb_rag_sources:
                    isMongoRAGAgent &&
                    Array.isArray(data.sources) &&
                    data.sources.length > 0 &&
                    typeof (data.sources[0] as { file_name?: unknown })?.file_name === 'string'
                      ? (data.sources as ExtendedChatMessage['mongodb_rag_sources'])
                      : undefined,
                  web_search_images: data.search_focus !== undefined ? data.images : undefined,
                  web_search_follow_ups: data.search_focus !== undefined ? data.follow_up_questions : undefined,
                  web_search_focus: data.search_focus,
                  report_image_urls: Array.isArray(data.report_image_urls) ? data.report_image_urls : undefined,
                  browser_html_report_file: data.html_report_file,
                  browser_steps_executed: Array.isArray(steps) ? steps as Record<string, unknown>[] : u[l].browser_steps_executed,
                  standalone_html: typeof data.standalone_html === 'string' ? data.standalone_html : u[l].standalone_html,
                };
              {
                const serverRaw = data.response != null ? String(data.response) : '';
                const serverTrim = serverRaw.trim();
                const current = (u[l].content || '').trim();
                // Empty string is falsy in JS — still merge when server sent explicit '' and chunks are empty.
                if (serverTrim.length > 0 && (!current || serverTrim.length > current.length)) {
                  u[l].content = serverRaw;
                } else if (!serverTrim.length && !current) {
                  u[l].content = 'No response received.';
                }
              }
            }
            return u;
          });
        },
        onError: (err) => {
          setMessages((prev) => {
            const u = [...prev]; const l = u.length - 1;
            if (u[l]?.role === 'assistant') u[l] = { ...u[l], content: `Error: ${err.message}` };
            return u;
          });
        },
      });

      if (doneData) {
        if (isMongoRAGAgent && doneData.ingested !== undefined) {
          setMongoIngested(doneData.ingested);
        }
        if (doneData.requires_token) {
          setPendingPushQuery(currentInput);
          setShowTokenInput(true);
        }
        if (doneData.task_id) {
          const taskId = doneData.task_id;
          setCurrentThinkingStep('Generating unit tests... This may take a few minutes.');
          const pollResult = await new Promise<TaskStatusResponse>((resolve, reject) => {
            let lastStepCount = 0;
            const interval = setInterval(async () => {
              try {
                const status = await pollTaskStatus(taskId);
                if (status.thinking_steps && status.thinking_steps.length > lastStepCount) {
                  setCurrentThinkingStep(status.progress || 'Processing...');
                  lastStepCount = status.thinking_steps.length;
                  setMessages((prev) => { const u = [...prev]; const l = u.length - 1; if (u[l]?.role === 'assistant') u[l] = { ...u[l], thinking_steps: status.thinking_steps }; return u; });
                }
                if (status.status === 'completed') { clearInterval(interval); resolve(status); }
              } catch (err) { clearInterval(interval); reject(err); }
            }, 3000);
            setTimeout(() => { clearInterval(interval); reject(new Error('Test generation timed out.')); }, 1200000);
          });
          setMessages((prev) => { const u = [...prev]; const l = u.length - 1; if (u[l]?.role === 'assistant') u[l] = { ...u[l], content: pollResult.response || 'Test generation completed.', thinking_steps: pollResult.thinking_steps }; return u; });
        }
      }
    } catch (error: any) {
      setMessages((prev) => {
        const u = [...prev]; const l = u.length - 1;
        if (u[l]?.role === 'assistant' && !u[l].content) {
          u[l] = { ...u[l], content: `Error: ${error.message || 'Something went wrong.'}` };
          return u;
        }
        return [...prev, { role: 'assistant', content: `Error: ${error.message}`, timestamp: new Date().toISOString() }];
      });
    } finally {
      setIsLoading(false);
      setCurrentThinkingStep('');
    }
  };

  const handleClear = async () => {
    try {
      await chatWithAgentStream(agent, '', {
        clearHistory: true,
        sessionId,
        ...((isBrowserAutomationAgent || isWebMcpAgent) ? { ...streamTransportExtras } : {}),
      }, {});
    } catch (e) {
      // Silently ignore - some agents may not support clear_history
    }
    setMessages([]);
  };

  const handleTokenSubmit = async () => {
    if (!githubToken.trim() || isLoading) return;
    setShowTokenInput(false);
    setIsLoading(true);
    setCurrentThinkingStep('Pushing changes to GitHub...');

    const assistantMsg: ExtendedChatMessage = { role: 'assistant', content: '', timestamp: new Date().toISOString() };
    setMessages((prev) => [...prev, assistantMsg]);

    try {
      await chatWithAgentStream(agent, pendingPushQuery, { sessionId, githubToken: githubToken.trim(), userConfig: getUserConfig() }, {
        onThinking: (step) => {
          setCurrentThinkingStep(step.content || 'Pushing...');
          setMessages((prev) => { const u = [...prev]; const l = u.length - 1; if (u[l]?.role === 'assistant') u[l] = { ...u[l], thinking_steps: [...(u[l].thinking_steps || []), step] }; return u; });
        },
        onResponseChunk: (chunk, meta) => {
          setMessages((prev) => {
            const u = [...prev]; const l = u.length - 1;
            if (u[l]?.role === 'assistant') {
              const base = meta?.reset ? '' : (u[l].content || '');
              u[l] = { ...u[l], content: base + chunk };
            }
            return u;
          });
        },
        onDone: (data) => {
          setMessages((prev) => { const u = [...prev]; const l = u.length - 1; if (u[l]?.role === 'assistant' && !u[l].content) u[l] = { ...u[l], content: data.response || 'No response received.' }; return u; });
        },
        onError: (err) => {
          setMessages((prev) => { const u = [...prev]; const l = u.length - 1; if (u[l]?.role === 'assistant') u[l] = { ...u[l], content: `Error: ${err.message}` }; return u; });
        },
      });
    } catch (error: any) {
      setMessages((prev) => { const u = [...prev]; const l = u.length - 1; if (u[l]?.role === 'assistant') u[l] = { ...u[l], content: `Error: ${error.message || 'Failed to complete token-required action.'}` }; return u; });
    } finally {
      setIsLoading(false);
      setCurrentThinkingStep('');
      setGithubToken('');
      setPendingPushQuery('');
    }
  };

  const handleExamplePrompt = (prompt: string) => {
    setInput(prompt);
  };

  return (
    <div className="flex flex-col bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 overflow-hidden shadow-sm">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 dark:border-gray-800 bg-gradient-to-r from-gray-50 to-white dark:from-gray-900 dark:to-gray-900/80">
        <div className="flex items-center gap-3">
          <div className="relative">
            <div className="w-9 h-9 flex items-center justify-center bg-gradient-to-br from-primary-100 to-primary-50 dark:from-primary-900/30 dark:to-primary-800/20 rounded-xl overflow-hidden border border-primary-200/50 dark:border-primary-700/30">
              {agent.logo.startsWith('/') || agent.logo.startsWith('http') ? (
                <img src={agent.logo} alt={agent.name} className="w-6 h-6 object-contain" />
              ) : (
                <span className="text-xl">{agent.logo}</span>
              )}
            </div>
            <span className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 bg-green-500 rounded-full border-2 border-white dark:border-gray-900" />
          </div>
          <div>
            <h3 className="font-heading text-sm font-bold text-gray-900 dark:text-white">
              {agent.name}
            </h3>
            <p
              className={`font-body text-[10px] font-medium transition-colors duration-300 ${
                isLoading
                  ? 'text-primary-600 dark:text-primary-400'
                  : 'text-green-600 dark:text-green-400'
              }`}
            >
              {isLoading ? (
                <span className="inline-flex items-center gap-1.5">
                  <span className="relative flex h-1.5 w-1.5">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary-400/70 opacity-75" />
                    <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-primary-500" />
                  </span>
                  Responding…
                </span>
              ) : (
                'Online'
              )}
            </p>
          </div>
        </div>
        <button
          onClick={handleClear}
          className="p-1.5 text-gray-600 dark:text-gray-400 hover:text-red-500 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/10 rounded-lg transition-all"
          title="Clear chat"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>

      {blockedByUnsavedConfig && (
        <div
          className="shrink-0 px-3 py-2.5 border-b border-amber-200/90 dark:border-amber-800/40 bg-amber-50 dark:bg-amber-900/15"
          role="status"
          aria-live="polite"
        >
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:gap-3">
            <div className="flex items-start gap-2 min-w-0 flex-1">
              <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400 flex-shrink-0 mt-0.5" aria-hidden />
              <div className="space-y-1 min-w-0">
                <p className="font-body text-xs font-semibold text-amber-900 dark:text-amber-100">
                  Chat is disabled until configuration is saved
                </p>
                <p className="font-body text-[11px] text-amber-800 dark:text-amber-200/90 leading-relaxed">
                  You have unsaved changes in the <span className="font-semibold">Config</span> tab. Open it, then click{' '}
                  <span className="font-semibold">Save</span> to apply, <span className="font-semibold">Cancel</span> to discard those edits and reload what was last saved, or <span className="font-semibold">Clear</span> to remove all stored configuration on this device. Chat unlocks once there are no unsaved edits.
                </p>
              </div>
            </div>
            {onOpenConfigTab && (
              <button
                type="button"
                onClick={onOpenConfigTab}
                className="shrink-0 self-stretch sm:self-center px-3 py-1.5 text-[11px] font-semibold font-body rounded-lg bg-amber-600 hover:bg-amber-700 dark:bg-amber-700 dark:hover:bg-amber-600 text-gray-900 dark:text-white shadow-sm transition-colors"
              >
                Open Config
              </button>
            )}
          </div>
        </div>
      )}

      <div
        className={`flex flex-col ${
          isWebMcpAgent && webmcpShowPreview ? 'lg:flex-row lg:items-stretch' : ''
        }`}
      >
      <div
        ref={scrollContainerRef}
        className={`scroll-smooth p-5 space-y-4 bg-gradient-to-b from-gray-50/90 to-gray-50/50 dark:from-zinc-950 dark:to-gray-950 ${
          isWebMcpAgent && webmcpShowPreview ? 'min-w-0 flex-1' : ''
        } ${
          blockedByUnsavedConfig ? 'pointer-events-none select-none opacity-60' : ''
        }`}
        aria-disabled={blockedByUnsavedConfig || undefined}
      >
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center min-h-[min(50vh,420px)] text-center px-4 py-12">
            <div className="relative mb-5">
              <div className="w-16 h-16 gradient-primary rounded-2xl flex items-center justify-center shadow-lg shadow-primary-500/20">
                <MessageSquare className="w-8 h-8 text-gray-900 dark:text-white" />
              </div>
              <div className="absolute -inset-3 bg-primary-500/10 rounded-3xl blur-xl -z-10" />
            </div>
            <h4 className="font-heading text-lg font-bold text-gray-900 dark:text-white mb-1">
              Start a Conversation
            </h4>
            <p className="font-body text-xs text-gray-500 dark:text-gray-400 mb-5 max-w-xs">
              Ask anything or try one of these suggestions
            </p>
            <div className="grid grid-cols-1 gap-2 w-full max-w-md">
              {agent.usage.example_prompts.slice(0, 3).map((prompt, index) => (
                <button
                  key={index}
                  onClick={() => handleExamplePrompt(prompt)}
                  className="group font-body text-sm px-4 py-2.5 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 hover:border-primary-400 dark:hover:border-primary-600 text-gray-600 dark:text-gray-300 rounded-xl transition-all text-left hover:shadow-md hover:shadow-primary-500/5 hover:-translate-y-0.5"
                >
                  <span className="text-primary-500 mr-1.5 opacity-0 group-hover:opacity-100 transition-opacity">→</span>
                  <span className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{prompt}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((message, index) => {
          const isStreamingThis = Boolean(isLoading && index === messages.length - 1 && message.role === 'assistant');
          return (
            <div
              key={index}
              className={`chat-message flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
            <div
              className={
                message.role === 'user'
                  ? 'max-w-[85%]'
                  : 'w-full min-w-0 max-w-full'
              }
            >
              {message.role === 'assistant' && message.thinking_steps && message.thinking_steps.length > 0 && (
                <ThinkingStepsDisplay steps={message.thinking_steps} isStreaming={isStreamingThis} />
              )}
              {message.role === 'assistant' &&
                isStreamingThis &&
                currentThinkingStep &&
                (!message.thinking_steps || message.thinking_steps.length === 0) && (
                  <div className="mb-2 flex items-center gap-2 rounded-lg border border-primary-500/15 bg-primary-500/[0.06] px-3 py-2 font-body text-[0.6875rem] text-primary-800 dark:border-primary-500/20 dark:bg-primary-500/10 dark:text-primary-200/90">
                    <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-primary-600 dark:text-primary-400" />
                    <span className="min-w-0 leading-snug">{currentThinkingStep}</span>
                  </div>
                )}
              {message.role === 'assistant' && message.content.trim().length > 0 && (
                <AssistantMessageExportBar
                  content={message.content}
                  filenameBase={agent.name}
                  timestamp={message.timestamp}
                />
              )}
              {message.role === 'assistant' && message.bpmn_xml ? (
                <>
                  <div
                    className={`w-full min-w-0 rounded-2xl rounded-bl-md border border-gray-200 bg-gray-100 px-4 py-3 text-gray-900 transition-[box-shadow,border-color] duration-300 dark:border-gray-800 dark:bg-gray-900 dark:text-white ${
                      isStreamingThis ? 'shadow-md shadow-primary-500/[0.08] ring-1 ring-primary-500/20 dark:shadow-primary-500/10' : ''
                    }`}
                  >
                    <div className="prose prose-sm dark:prose-invert max-w-none w-full min-w-0 font-body">
                      {!message.content && isStreamingThis ? (
                        <StreamContentSkeleton />
                      ) : (
                        <>
                          <ReactMarkdown
                            remarkPlugins={[remarkGfm]}
                            components={{
                              a: ({ href, children }) => (
                                <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
                              ),
                              pre: ({ children }) => (
                                <details className="my-1">
                                  <summary className="cursor-pointer text-xs text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 select-none">View XML source</summary>
                                  <pre className="mt-1 max-h-48 overflow-auto text-xs">{children}</pre>
                                </details>
                              ),
                              code: ({ className, children, ...props }) => {
                                const isInline = !className;
                                if (isInline) return <code {...props}>{children}</code>;
                                return <code className={className} {...props}>{children}</code>;
                              },
                              table: ({ children }) => <PaginatedMarkdownTable>{children}</PaginatedMarkdownTable>,
                              img: ({ src, alt }) => <MarkdownRemoteImage src={src} alt={alt} />,
                            }}
                          >{message.content}</ReactMarkdown>
                          {isStreamingThis && !!message.content && <span className="stream-sse-cursor" aria-hidden />}
                        </>
                      )}
                      {!isLoading && index === messages.length - 1 && (
                        <SuggestionChips content={message.content} onSuggestionClick={handleSuggestionClick} disabled={isLoading} />
                      )}
                    </div>
                  </div>
                  <BPMNViewer xml={message.bpmn_xml} />
                </>
              ) : message.role === 'assistant' && isSonarQubeReport(message.content) ? (
                <SonarQubeReportView content={message.content} />
              ) : message.role === 'assistant' && isTestReport(message.content) ? (
                <TestReportView
                  content={message.content}
                  enablePlaywrightRunner={agent.id === 'web_test_agent'}
                />
              ) : message.role === 'assistant' && isCompanyAiSolutionsReport(message.content) ? (
                <CompanyAiSolutionsView content={message.content} />
              ) : message.role === 'assistant' && isCompanyResearchReport(message.content) ? (
                <CompanyReportView content={message.content} newsCards={message.latest_news_cards} />
              ) : message.role === 'assistant' && isDocumentResponse(message.content) ? (
                <DocumentView content={message.content} />
              ) : message.role === 'assistant' && message.is_web_search ? (
                <WebSearchResultView
                  content={message.content}
                  sources={message.web_search_sources}
                  images={message.web_search_images}
                  followUpQuestions={message.web_search_follow_ups}
                  searchFocus={message.web_search_focus}
                  onFollowUpClick={(q) => { setInput(q); }}
                />
              ) : (
                <div
                  className={`px-4 py-3 rounded-2xl ${
                    message.role === 'user'
                      ? 'gradient-primary text-gray-900 dark:text-white rounded-br-md'
                      : `w-full min-w-0 bg-gray-100 dark:bg-gray-900 text-gray-900 dark:text-white rounded-bl-md border border-gray-200 dark:border-gray-800 transition-[box-shadow,border-color] duration-300 ${
                          isStreamingThis ? 'shadow-md shadow-primary-500/[0.08] ring-1 ring-primary-500/20 dark:shadow-primary-500/10' : ''
                        }`
                  }`}
                >
                  {message.role === 'assistant' ? (
                    <div className="w-full min-w-0">
                      <div className="prose prose-sm dark:prose-invert max-w-none w-full min-w-0 font-body">
                        {!message.content && isStreamingThis ? (
                          <StreamContentSkeleton />
                        ) : (
                          <>
                            <ReactMarkdown
                              remarkPlugins={[remarkGfm]}
                              components={{
                                a: ({ href, children }) => (
                                  <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
                                ),
                                code: ({ children, className }) => {
                                  const isMermaid = className?.includes('language-mermaid');
                                  if (isMermaid) {
                                    const code = String(children).replace(/\n$/, '');
                                    const isArchDiagram = code.includes('graph ') || code.includes('flowchart ');
                                    const isDataFlow = code.includes('sequenceDiagram');
                                    const diagramType: 'architecture' | 'dataflow' | null = isGitHubAgent
                                      ? (isArchDiagram ? 'architecture' : isDataFlow ? 'dataflow' : null)
                                      : null;
                                    return (
                                      <MermaidDiagram
                                        chart={code}
                                        onRegenerate={diagramType ? () => handleRegenerateDiagram(diagramType) : undefined}
                                        isRegenerating={regeneratingDiagram === diagramType}
                                      />
                                    );
                                  }
                                  const langMatch = /language-([\w-+]+)/.exec(className || '');
                                  if (langMatch) {
                                    const codeStr = String(children).replace(/\n$/, '');
                                    const isExportedPlaywright =
                                      isBrowserAutomationAgent &&
                                      langMatch[1].toLowerCase() === 'python' &&
                                      codeStr.includes('Auto-generated Playwright script');
                                    const rerunKey = `${codeStr.length}:${codeStr.slice(0, 64)}`;
                                    return (
                                      <MarkdownCodeBlock
                                        language={langMatch[1]}
                                        code={codeStr}
                                        showRunScriptButton={isExportedPlaywright}
                                        onRunScript={
                                          isExportedPlaywright
                                            ? () => { void handleRunBrowserScript(codeStr, message.browser_steps_executed); }
                                            : undefined
                                        }
                                        runScriptDisabled={isLoading}
                                        runScriptPending={pendingRerunScriptKey === rerunKey}
                                      />
                                    );
                                  }
                                  return <code className="bg-gray-200 dark:bg-gray-800 px-1 py-0.5 rounded text-orange-600 dark:text-orange-300 text-xs">{children}</code>;
                                },
                                pre: ({ children }) => {
                                  const first = Children.toArray(children)[0];
                                  const cls =
                                    isValidElement(first) && first.props && typeof (first.props as { className?: string }).className === 'string'
                                      ? (first.props as { className: string }).className
                                      : '';
                                  if (cls.includes('language-')) {
                                    return <>{children}</>;
                                  }
                                  return (
                                    <pre className="my-2 p-3 rounded-xl bg-gray-100 dark:bg-gray-800/80 text-xs overflow-x-auto font-mono text-gray-800 dark:text-gray-200 border border-gray-200/90 dark:border-gray-700">
                                      {children}
                                    </pre>
                                  );
                                },
                                table: ({ children }) => <PaginatedMarkdownTable>{children}</PaginatedMarkdownTable>,
                                img: ({ src, alt }) => <MarkdownRemoteImage src={src} alt={alt} />,
                              }}
                            >{message.content}</ReactMarkdown>
                            {isStreamingThis && !!message.content && <span className="stream-sse-cursor" aria-hidden />}
                          </>
                        )}
                        {!isLoading && index === messages.length - 1 && (
                          <SuggestionChips content={message.content} onSuggestionClick={handleSuggestionClick} disabled={isLoading} />
                        )}
                      </div>
                      {message.mongodb_rag_sources && message.mongodb_rag_sources.length > 0 ? (
                        <MongoRagRetrievedChunks sources={message.mongodb_rag_sources} />
                      ) : null}
                    </div>
                  ) : (
                    (() => {
                      const fileMatch = message.content.match(/\[File:\s*(.+?)\]$/);
                      const textContent = fileMatch ? message.content.replace(/\s*\[File:\s*.+?\]$/, '') : message.content;
                      const fileName = fileMatch?.[1];
                      return (
                        <div>
                          {fileName && (
                            <div className="mb-2">
                              <FileAttachmentBubble fileName={fileName} variant={message.role === 'user' ? 'dark' : 'light'} />
                            </div>
                          )}
                          {textContent.trim() && (
                            <p className="font-body text-sm leading-relaxed">{textContent.trim()}</p>
                          )}
                        </div>
                      );
                    })()
                  )}
                </div>
              )}
              {message.role === 'assistant' && agent.id === 'meeting_prep' && message.latest_news_cards && message.latest_news_cards.length > 0 && (
                <div className="mt-3 w-full min-w-0">
                  <LatestNewsCardsSection newsCards={message.latest_news_cards} />
                </div>
              )}
              {message.role === 'assistant' && message.stackblitz_repo && (
                <StackBlitzEmbed repoSlug={message.stackblitz_repo} />
              )}
              {message.role === 'assistant' && message.chart_data && (
                <JiraDashboard data={message.chart_data} />
              )}
              {message.role === 'assistant' && message.email_preview && (
                <EmailPreviewCard data={message.email_preview} />
              )}
              {message.role === 'assistant' && (message.ppt_slide_snapshots?.length ?? 0) > 0 && (
                <div className="mt-3 w-full min-w-0 space-y-2">
                  <div className="flex items-center gap-2 text-xs font-medium text-slate-600 dark:text-slate-400">
                    <LayoutGrid className="h-3.5 w-3.5 shrink-0" aria-hidden />
                    Slide previews (live)
                  </div>
                  <div className="flex gap-2 overflow-x-auto pb-1">
                    {(message.ppt_slide_snapshots || []).map((snap, i) => {
                      const src = `data:${snap.mime || 'image/svg+xml'};base64,${snap.image}`;
                      const alt = snap.title || `Slide ${snap.slide_index}`;
                      const captionLine = `${snap.slide_index}. ${snap.slide_type || 'slide'}`;
                      return (
                        <div
                          key={`${snap.slide_index}-${i}`}
                          className="shrink-0 w-[168px] rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden bg-slate-50 dark:bg-slate-900/80"
                        >
                          <button
                            type="button"
                            onClick={() =>
                              setPptSlideImageModal({
                                src,
                                alt,
                                caption: [captionLine, snap.title].filter(Boolean).join(' · '),
                              })
                            }
                            className="block w-full border-0 bg-transparent p-0 cursor-zoom-in focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-500 focus-visible:ring-inset rounded-t-lg"
                            aria-label={`View full slide: ${alt}`}
                          >
                            <img
                              src={src}
                              alt={alt}
                              className="pointer-events-none w-full h-[95px] object-cover object-top bg-slate-900"
                            />
                          </button>
                          <div
                            className="px-1.5 py-1 text-[10px] leading-tight text-slate-600 dark:text-slate-400 truncate"
                            title={snap.title || ''}
                          >
                            {snap.slide_index}. {snap.slide_type || 'slide'}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
              {message.role === 'assistant' && message.ppt_research_sources && message.ppt_research_sources.length > 0 && (
                <div className="mt-2 w-full min-w-0 text-xs">
                  <p className="font-medium text-slate-600 dark:text-slate-400 mb-1">Research sources (sample)</p>
                  <ul className="list-disc pl-4 space-y-0.5 max-h-32 overflow-y-auto text-slate-600 dark:text-slate-400">
                    {message.ppt_research_sources.slice(0, 14).map((s, i) => (
                      <li key={`${s.url}-${i}`}>
                        <a
                          href={s.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-orange-600 dark:text-orange-400 hover:underline break-all"
                        >
                          {s.title || s.url}
                        </a>
                        {s.date ? <span className="text-slate-500"> ({s.date})</span> : null}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {message.role === 'assistant' && message.download_url && (
                <div className="mt-3">
                  <a
                    href={message.download_url}
                    download={message.download_file_name || 'presentation.pptx'}
                    className="inline-flex items-center gap-2 px-4 py-2.5 bg-gradient-to-r from-orange-500 to-orange-600 hover:from-orange-600 hover:to-orange-700 text-gray-900 dark:text-white rounded-lg text-sm font-medium transition-all shadow-md hover:shadow-lg"
                  >
                    <Download className="w-4 h-4" />
                    Download {message.download_file_name || 'Presentation.pptx'}
                  </a>
                </div>
              )}
              {message.role === 'assistant' && (message.browser_screenshots?.length || message.browser_html_report_file) && (
                <BrowserViewport
                  screenshots={message.browser_screenshots || []}
                  htmlReportFile={message.browser_html_report_file}
                />
              )}
              {message.role === 'assistant' && message.standalone_html && (
                <StandaloneHtmlPreview html={message.standalone_html} />
              )}
            </div>
          </div>
          );
        })}

        {showTokenInput && (
          <div className="flex justify-start">
            <div className="max-w-[85%] w-full">
              <div className="bg-orange-50 dark:bg-orange-900/20 border border-orange-200 dark:border-orange-800 rounded-2xl px-4 py-3">
                <p className="text-sm font-medium text-orange-800 dark:text-orange-300 mb-2">Enter your GitHub Personal Access Token</p>
                <p className="text-xs text-orange-600 dark:text-orange-400 mb-3">Your token is used only for this request and is not stored.</p>
                <div className="flex gap-2">
                  <input
                    type="password"
                    value={githubToken}
                    onChange={e => setGithubToken(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && handleTokenSubmit()}
                    placeholder="ghp_xxxxxxxxxxxx"
                    className="flex-1 px-3 py-2 text-sm bg-white dark:bg-gray-800 border border-orange-300 dark:border-orange-700 rounded-lg outline-none focus:ring-2 focus:ring-orange-500 text-gray-900 dark:text-white"
                  />
                  <button
                    onClick={handleTokenSubmit}
                    className="px-4 py-2 text-sm font-medium text-gray-900 dark:text-white bg-orange-600 hover:bg-orange-700 rounded-lg transition-colors"
                  >
                    Push
                  </button>
                  <button
                    onClick={() => { setShowTokenInput(false); setGithubToken(''); setPendingPushQuery(''); }}
                    className="px-3 py-2 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {isWebMcpAgent && webmcpShowPreview && (
        <div className="flex flex-col min-h-0 min-w-0 w-full lg:w-[min(440px,42%)] lg:min-w-[320px] lg:max-w-[520px] shrink-0 border-t lg:border-t-0 lg:border-l border-indigo-200/60 dark:border-indigo-900/50 bg-[#0f172a] max-h-[min(400px,44vh)] lg:max-h-none lg:self-stretch">
          <div className="flex items-center justify-between gap-2 px-3 py-2 bg-[#1e293b] border-b border-[#334155] flex-shrink-0">
            <div className="flex items-center gap-2 min-w-0">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse shrink-0" />
              <span className="text-[11px] font-semibold text-slate-200 shrink-0">Demo in chat</span>
            </div>
            <div className="flex items-center gap-0.5 shrink-0">
              <button
                type="button"
                onClick={() => setWebmcpIframeKey(Date.now())}
                title="Reload preview"
                className="p-1.5 rounded-md text-slate-400 hover:text-slate-200 hover:bg-white/5 transition-colors"
              >
                <RotateCcw className="w-3.5 h-3.5" />
              </button>
              <button
                type="button"
                onClick={() => setWebmcpShowPreview(false)}
                title="Close preview"
                className="p-1.5 rounded-md text-slate-400 hover:text-slate-200 hover:bg-white/5 transition-colors"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
          <div className="px-3 py-2 bg-[#0f172a] border-b border-[#334155] flex-shrink-0 space-y-2">
            <div className="flex items-center gap-2 min-w-0">
              <Monitor className="w-3.5 h-3.5 text-slate-500 shrink-0" aria-hidden />
              <input
                type="text"
                value={webmcpPreviewUrl}
                onChange={(e) => setWebmcpPreviewUrl(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && setWebmcpIframeKey(Date.now())}
                spellCheck={false}
                className="min-w-0 flex-1 text-[11px] leading-normal font-mono bg-[#1e293b] border border-[#334155] rounded-md px-2.5 py-1.5 text-slate-200 placeholder-slate-500 outline-none focus:border-indigo-500/60 focus:ring-1 focus:ring-indigo-500/25"
                placeholder="http://127.0.0.1:8765/"
              />
              <button
                type="button"
                onClick={() => setWebmcpIframeKey(Date.now())}
                className="shrink-0 rounded-md border border-[#334155] bg-[#1e293b] px-2.5 py-1.5 text-[11px] font-semibold text-indigo-300 hover:bg-[#263348] hover:text-indigo-200 transition-colors"
              >
                Go
              </button>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[10px] font-medium text-slate-500">Presets</span>
              <button
                type="button"
                title="Same page as file:///…/demo/index.html, served over HTTP (required in this iframe)"
                onClick={() => {
                  setWebmcpPreviewUrl('http://127.0.0.1:8765/');
                  setWebmcpIframeKey(Date.now());
                }}
                className="rounded-md border border-sky-500/30 bg-sky-500/10 px-2 py-1 text-[10px] font-semibold text-sky-300 hover:bg-sky-500/20 transition-colors"
              >
                index
              </button>
              <button
                type="button"
                title="Compact mirror UI"
                onClick={() => {
                  setWebmcpPreviewUrl('http://127.0.0.1:8765/mirror.html');
                  setWebmcpIframeKey(Date.now());
                }}
                className="rounded-md border border-violet-500/30 bg-violet-500/10 px-2 py-1 text-[10px] font-semibold text-violet-300 hover:bg-violet-500/20 transition-colors"
              >
                mirror
              </button>
            </div>
          </div>
          {webmcpIframeBlocked && (
            <div className="px-3 py-2 bg-amber-950/50 border-b border-amber-800/40 text-[10px] text-amber-100/95 leading-snug font-body">
              This app cannot embed <span className="font-mono">file://</span> in this iframe (browser security). Keep using{' '}
              <span className="font-mono">file://…/demo/index.html</span> in Chrome for the extension; here, from{' '}
              <span className="font-mono">browser/webmcp_bridge/demo</span> run{' '}
              <span className="font-mono text-amber-50/90">python -m http.server 8765</span> and use{' '}
              <span className="font-mono">http://127.0.0.1:8765/</span> (or tap <span className="font-semibold">index</span>).
            </div>
          )}
          <div className="flex min-h-0 flex-1 flex-col relative">
            <iframe
              key={webmcpIframeKey}
              src={webmcpIframeEffectiveSrc}
              title="WebMCP demo preview in chat"
              className="w-full min-h-[200px] flex-1 border-0 bg-[#0f172a]"
              sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
            />
          </div>
        </div>
      )}

      </div>

      {needsConfig && configMissing && (
        <div className="px-3 py-2 border-t border-amber-200 dark:border-amber-800/30 bg-amber-50 dark:bg-amber-900/10">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
            <div className="flex items-start gap-2 min-w-0 flex-1">
              <Settings className="w-3.5 h-3.5 text-amber-500 flex-shrink-0 mt-0.5" />
              <p className="font-body text-[11px] text-amber-800 dark:text-amber-300">
                <span className="font-semibold">Setup required.</span> Go to the <span className="font-semibold">Config</span> tab to enter your credentials before using this agent.
              </p>
            </div>
            {onOpenConfigTab && (
              <button
                type="button"
                onClick={onOpenConfigTab}
                className="shrink-0 self-stretch sm:self-center px-3 py-1.5 text-[11px] font-semibold font-body rounded-lg bg-amber-600 hover:bg-amber-700 dark:bg-amber-700 dark:hover:bg-amber-600 text-gray-900 dark:text-white shadow-sm transition-colors"
              >
                Open Config
              </button>
            )}
          </div>
        </div>
      )}

      <div
        className={`p-3 border-t border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-900 ${
          blockedByUnsavedConfig ? 'pointer-events-none select-none opacity-60' : ''
        }`}
        aria-disabled={blockedByUnsavedConfig || undefined}
      >
        {uploadedFile && (
          <div className="mb-2 max-w-xs">
            <FileAttachmentInput
              file={uploadedFile}
              onRemove={clearUploadedFile}
              variant="light"
            />
          </div>
        )}

        {isWebMcpAgent && (
          <details className="group mb-3 rounded-2xl border border-slate-200/90 dark:border-slate-700/70 bg-gradient-to-br from-white via-slate-50/80 to-sky-50/40 dark:from-zinc-900 dark:via-zinc-900/95 dark:to-sky-950/25 shadow-sm open:shadow-md open:shadow-sky-500/[0.06] dark:open:shadow-sky-900/20 open:ring-1 open:ring-sky-500/15 dark:open:ring-sky-400/10 transition-shadow">
            <summary className="cursor-pointer list-none [&::-webkit-details-marker]:hidden flex items-center gap-3 px-3.5 py-3 rounded-2xl hover:bg-slate-50/90 dark:hover:bg-zinc-800/40 transition-colors">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-sky-500 to-cyan-600 text-gray-900 dark:text-white shadow-sm shadow-sky-500/25">
                <Plug className="w-4 h-4" aria-hidden />
              </div>
              <div className="min-w-0 flex-1 text-left">
                <div className="text-sm font-semibold tracking-tight text-slate-800 dark:text-slate-100">
                  Chrome tab bridge
                </div>
                <div className="text-[11px] text-slate-500 dark:text-slate-400 leading-snug mt-0.5">
                  Expand to connect the local bridge, extension, and token — runs tools in your active Chrome tab.
                </div>
              </div>
              <ChevronDown
                className="w-4 h-4 shrink-0 text-slate-400 dark:text-slate-500 transition-transform duration-200 group-open:rotate-180"
                aria-hidden
              />
            </summary>

            <div className="px-3.5 pb-3.5 pt-0 space-y-3 border-t border-slate-200/70 dark:border-slate-700/60">
              <ol className="text-[11px] leading-relaxed text-slate-600 dark:text-slate-300 space-y-2.5">
                {[
                  <>
                    Run <code className="px-1.5 py-0.5 rounded-md bg-slate-100 dark:bg-zinc-800 font-mono text-[10px]">browser/webmcp_bridge/start_bridge.bat</code> — keep the window open and copy the <strong className="text-slate-800 dark:text-slate-200">Token</strong>.
                  </>,
                  <>
                    Chrome → <code className="px-1.5 py-0.5 rounded-md bg-slate-100 dark:bg-zinc-800 font-mono text-[10px]">chrome://extensions</code> → Developer mode → <strong className="text-slate-800 dark:text-slate-200">Load unpacked</strong> → <code className="px-1 font-mono text-[10px]">browser/webmcp_bridge/extension</code>
                  </>,
                  <>
                    Extension <strong className="text-slate-800 dark:text-slate-200">Options</strong> → same token &amp; port → <strong className="text-slate-800 dark:text-slate-200">Save</strong>.
                  </>,
                  <>
                    Open your target tab (e.g. demo via <code className="px-1 font-mono text-[10px]">http://127.0.0.1:8765/</code>), focus it, then <strong className="text-slate-800 dark:text-slate-200">Test connection</strong>.
                  </>,
                ].map((content, i) => (
                  <li key={i} className="flex gap-2.5">
                    <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-sky-500/15 text-[10px] font-bold text-sky-700 dark:text-sky-300">
                      {i + 1}
                    </span>
                    <span className="min-w-0 pt-0.5">{content}</span>
                  </li>
                ))}
              </ol>

              <div className="grid gap-2.5 sm:grid-cols-2">
                <div className="space-y-1 sm:col-span-1">
                  <label htmlFor="webmcp-bridge-url" className="block text-[10px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                    Bridge URL
                  </label>
                  <input
                    id="webmcp-bridge-url"
                    type="text"
                    value={webmcpBridgeUrl}
                    onChange={(e) => setWebmcpBridgeUrl(e.target.value)}
                    placeholder="http://127.0.0.1:3847"
                    disabled={isLoading}
                    spellCheck={false}
                    autoComplete="off"
                    className="w-full px-3 py-2 text-xs font-mono rounded-xl border border-slate-200 dark:border-slate-600 bg-white/90 dark:bg-zinc-950/80 text-slate-900 dark:text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-500/30 focus:border-sky-500/50"
                  />
                </div>
                <div className="space-y-1 sm:col-span-1">
                  <label htmlFor="webmcp-bridge-token" className="block text-[10px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                    Bearer token
                  </label>
                  <input
                    id="webmcp-bridge-token"
                    type="password"
                    value={webmcpBridgeToken}
                    onChange={(e) => setWebmcpBridgeToken(e.target.value)}
                    placeholder="From bridge terminal"
                    disabled={isLoading}
                    spellCheck={false}
                    autoComplete="off"
                    className="w-full px-3 py-2 text-xs font-mono rounded-xl border border-slate-200 dark:border-slate-600 bg-white/90 dark:bg-zinc-950/80 text-slate-900 dark:text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-500/30 focus:border-sky-500/50"
                  />
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => setWebmcpShowPreview(v => !v)}
                  className={`px-3 py-2 text-[11px] font-semibold rounded-xl flex items-center gap-1.5 transition-all ${
                    webmcpShowPreview
                      ? 'bg-indigo-100 dark:bg-indigo-950/50 text-indigo-800 dark:text-indigo-200 ring-1 ring-indigo-200/80 dark:ring-indigo-800/60'
                      : 'bg-slate-100/90 dark:bg-zinc-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200/80 dark:hover:bg-zinc-700'
                  }`}
                  title="Toggle live preview panel"
                >
                  {webmcpShowPreview ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                  {webmcpShowPreview ? 'Hide preview' : 'Live preview'}
                </button>
                <button
                  type="button"
                  disabled={isLoading || webmcpBridgeTesting || !webmcpBridgeToken.trim()}
                  onClick={async () => {
                    setWebmcpBridgeTesting(true);
                    setWebmcpBridgeStatus(null);
                    try {
                      const r = await pingWebmcpBridge({
                        bridge_base_url: webmcpBridgeUrl.trim(),
                        bridge_token: webmcpBridgeToken.trim(),
                      });
                      if (r.ok) {
                        setWebmcpBridgeStatus(
                          `ok:Connected — ${r.tool_count ?? 0} tool(s) found on tab: "${(r.session as { title?: string })?.title ?? 'unknown'}"`,
                        );
                      } else {
                        setWebmcpBridgeStatus(`err:${friendlyBridgeError(r.error || 'Connection failed')}`);
                      }
                    } catch (e) {
                      setWebmcpBridgeStatus(`err:${friendlyBridgeError(e instanceof Error ? e.message : 'Connection failed')}`);
                    } finally {
                      setWebmcpBridgeTesting(false);
                    }
                  }}
                  className="px-4 py-2 text-[11px] font-semibold rounded-xl bg-gradient-to-r from-sky-600 to-cyan-600 text-gray-900 dark:text-white shadow-sm shadow-sky-500/20 hover:from-sky-500 hover:to-cyan-500 disabled:opacity-45 disabled:shadow-none transition-all"
                >
                  {webmcpBridgeTesting ? 'Testing…' : 'Test connection'}
                </button>
              </div>

              {webmcpBridgeStatus ? (
                <div
                  className={`text-[11px] font-medium px-3 py-2.5 rounded-xl leading-snug ${
                    webmcpBridgeStatus.startsWith('ok:')
                      ? 'bg-emerald-50/90 dark:bg-emerald-950/35 text-emerald-900 dark:text-emerald-200 ring-1 ring-emerald-200/70 dark:ring-emerald-800/50'
                      : 'bg-rose-50/90 dark:bg-rose-950/35 text-rose-900 dark:text-rose-200 ring-1 ring-rose-200/70 dark:ring-rose-800/50'
                  }`}
                >
                  {webmcpBridgeStatus.startsWith('ok:') ? '✓ ' : '✗ '}
                  {webmcpBridgeStatus.replace(/^(ok:|err:)/, '')}
                </div>
              ) : null}
            </div>
          </details>
        )}

        {isBrowserAutomationAgent && (
          <div className="mb-3 space-y-3">
            <div className="flex flex-col gap-2.5 rounded-lg border border-gray-200 dark:border-gray-800 bg-gray-50/90 dark:bg-gray-950/50 px-3 py-2.5">
              <div className="flex items-center gap-2 text-xs font-medium text-gray-700 dark:text-gray-300">
                <Monitor className="w-3.5 h-3.5 shrink-0 opacity-80" aria-hidden />
                Browser for this chat
              </div>
              <label className="flex items-start gap-2.5 cursor-pointer text-xs text-gray-700 dark:text-gray-300">
                <input
                  type="checkbox"
                  className="mt-0.5 rounded border-gray-300 dark:border-gray-600 text-primary-600 focus:ring-primary-500/30"
                  checked={browserRememberLogins}
                  onChange={(e) => setBrowserRememberLogins(e.target.checked)}
                  disabled={isLoading || !!browserCdpEndpoint.trim()}
                />
                <span>
                  <span className="font-medium text-gray-900 dark:text-gray-100">Remember my logins on this computer</span>
                  <span className="block text-[11px] leading-snug text-gray-500 dark:text-gray-400 mt-0.5">
                    Sign in once when the browser opens. Your session is saved automatically in a normal app folder—no technical setup.
                  </span>
                </span>
              </label>
              <label className="flex items-start gap-2.5 cursor-pointer text-xs text-gray-700 dark:text-gray-300">
                <input
                  type="checkbox"
                  className="mt-0.5 rounded border-gray-300 dark:border-gray-600 text-primary-600 focus:ring-primary-500/30"
                  checked={browserRunInBackground}
                  onChange={(e) => setBrowserRunInBackground(e.target.checked)}
                  disabled={isLoading}
                />
                <span>
                  <span className="font-medium text-gray-900 dark:text-gray-100">Hide the browser window</span>
                  <span className="block text-[11px] leading-snug text-gray-500 dark:text-gray-400 mt-0.5">
                    Runs in the background. Uncheck this while logging in to a site for the first time.
                  </span>
                </span>
              </label>
              {browserCdpEndpoint.trim() ? (
                <p className="text-[11px] text-amber-700 dark:text-amber-300/90">
                  Desktop Chrome mode is on—the options above use your real Chrome profile instead of the saved folder.
                </p>
              ) : null}
            </div>

            <details className="group rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950/30 px-3 py-2">
              <summary className="cursor-pointer flex items-center gap-1.5 text-xs font-medium text-gray-600 dark:text-gray-400 list-none [&::-webkit-details-marker]:hidden">
                <ChevronDown className="w-3.5 h-3.5 shrink-0 transition-transform group-open:rotate-180 opacity-80" aria-hidden />
                Advanced: use my desktop Chrome (optional)
              </summary>
              <div className="mt-2 space-y-1 pt-1 border-t border-gray-100 dark:border-gray-800">
                <label htmlFor="browser-cdp-endpoint" className="sr-only">
                  Chrome debug URL
                </label>
                <input
                  id="browser-cdp-endpoint"
                  type="text"
                  value={browserCdpEndpoint}
                  onChange={(e) => setBrowserCdpEndpoint(e.target.value)}
                  placeholder="http://127.0.0.1:9222"
                  disabled={isLoading}
                  spellCheck={false}
                  autoComplete="off"
                  className="w-full px-3 py-2 text-xs font-mono bg-gray-50 dark:bg-gray-950 border border-gray-200 dark:border-gray-800 rounded-lg text-gray-900 dark:text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-primary-500/25 focus:border-primary-500/40"
                />
                <p className="text-[10px] leading-snug text-gray-500 dark:text-gray-500">
                  For experts: quit Chrome, restart with{' '}
                  <code className="px-1 py-0.5 rounded bg-gray-200/90 dark:bg-gray-800 text-gray-800 dark:text-gray-200">
                    --remote-debugging-port=9222
                  </code>
                  . Leave empty for the built-in browser (recommended).
                </p>
              </div>
            </details>

            <button
              type="button"
              onClick={handleCloseBrowser}
              disabled={browserClosing || isLoading}
              className="w-full flex items-center justify-center gap-1.5 px-3 py-1.5 text-xs font-medium text-red-700 dark:text-red-300 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800/60 rounded-lg hover:bg-red-100 dark:hover:bg-red-900/40 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {browserClosing ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden />
              ) : (
                <X className="w-3.5 h-3.5" aria-hidden />
              )}
              {browserClosing ? 'Closing browser…' : 'Close Browser'}
            </button>
            {browserCloseMsg && (
              <p className="text-[11px] text-center text-green-700 dark:text-green-300 mt-1 animate-pulse">
                {browserCloseMsg}
              </p>
            )}
          </div>
        )}

        {isMongoRAGAgent && showTextInput && (
          <div className="mb-3 space-y-2">
            <textarea
              value={rawTextInput}
              onChange={(e) => setRawTextInput(e.target.value)}
              placeholder="Paste your text content here for ingestion..."
              className="w-full px-3 py-2 bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg font-body text-sm text-gray-900 dark:text-white placeholder-gray-500 resize-y min-h-[80px] max-h-[200px]"
              rows={4}
              disabled={isLoading}
            />
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => { setShowTextInput(false); setRawTextInput(''); }}
                className="px-3 py-1.5 text-xs font-medium text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleTextIngest}
                disabled={!rawTextInput.trim() || isLoading}
                className="px-3 py-1.5 text-xs font-medium text-gray-900 dark:text-white bg-green-600 hover:bg-green-700 disabled:bg-gray-300 dark:disabled:bg-gray-700 rounded-lg transition-colors"
              >
                Ingest Text
              </button>
            </div>
          </div>
        )}

        <div className="flex items-end gap-3">
          {(isBPMNAgent || isDocFormatterAgent || isMongoRAGAgent || isPPTAgent || isCoderAgent || isCompanySolutionAgent) && (
            <>
              <input
                ref={fileInputRef}
                type="file"
                onChange={handleFileUpload}
                accept={isMongoRAGAgent
                  ? ".pdf,.docx,.doc,.xlsx,.xls,.pptx,.ppt,.txt,.csv,.md,.json,.xml"
                  : isDocFormatterAgent
                    ? ".pdf,.docx,.doc,.pptx,.ppt,.xlsx,.xls,.txt,.md,.html,.htm,.csv,.json,.xml,.png,.jpg,.jpeg,.gif,.bmp,.webp"
                    : isPPTAgent
                      ? ".csv,.xlsx,.xls,.pdf,.txt,.docx,.doc"
                      : isCoderAgent
                        ? ".pdf,.docx,.doc,.xlsx,.xls,.csv,.txt"
                        : isCompanySolutionAgent
                          ? ".pdf,.docx,.doc,.txt,.md,.html,.htm"
                          : ".pdf,.docx,.doc,.xlsx,.xls,.txt"}
                className="hidden"
                id="file-upload"
              />
              <label
                htmlFor="file-upload"
                className="flex shrink-0 items-center justify-center w-12 h-12 bg-gray-100 dark:bg-gray-800 border-2 border-gray-300 dark:border-gray-600 hover:border-orange-500 dark:hover:border-orange-500 hover:bg-gray-200 dark:hover:bg-gray-700 rounded-xl cursor-pointer transition-all"
                title={isMongoRAGAgent ? "Upload document for ingestion" : isDocFormatterAgent ? "Upload document to extract and format" : isPPTAgent ? "Upload CSV, Excel, PDF, text, or Word file for presentation generation" : isCoderAgent ? "Upload PDF, CSV, Excel, DOCX, or text file as coding context" : isCompanySolutionAgent ? "Optional: upload a PDF / Word / text file listing your existing AI solutions — the agent will prefer relevant ones from it." : "Upload PDF, Word, Excel, or text file"}
              >
                <Upload className="w-5 h-5 text-gray-600 dark:text-gray-300" />
              </label>
            </>
          )}
          {isMongoRAGAgent && (
            <button
              type="button"
              onClick={() => setShowTextInput(!showTextInput)}
              className="flex shrink-0 items-center justify-center px-3 py-3 h-12 bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-800 hover:border-primary-500 dark:hover:border-primary-600 rounded-xl cursor-pointer transition-all"
              title="Paste text for ingestion"
            >
              <FileText className="w-5 h-5 text-gray-500 dark:text-gray-400" />
            </button>
          )}
          <textarea
            ref={messageTextareaRef}
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              requestAnimationFrame(adjustMessageTextareaHeight);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            rows={1}
            placeholder={
              isMongoRAGAgent
                ? (mongoIngested ? 'Ask a question about your documents...' : 'Upload files or paste text to get started...')
                : isPPTAgent ? 'Describe your deck or upload CSV/Excel/PDF/TXT/DOCX...'
                : isDocFormatterAgent ? 'Upload a document or describe formatting...'
                : isBPMNAgent ? 'Describe process or upload a document...'
                : isCompanySolutionAgent ? 'Describe the business problem in detail. Optionally attach a PDF/Word/text of your existing AI solutions.'
                : `Message ${agent.name}...`
            }
            className="flex-1 min-h-[46px] max-h-[200px] px-4 py-3 bg-gray-50 dark:bg-gray-950 border border-gray-200 dark:border-gray-800 rounded-xl font-body text-sm text-gray-900 dark:text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-500/50 transition-all resize-none overflow-y-auto leading-relaxed"
            disabled={isLoading}
            aria-label={`Message ${agent.name}`}
          />
          <button
            type="button"
            onClick={() => handleSend()}
            disabled={(!input.trim() && !uploadedFile) || isLoading}
            className="flex shrink-0 min-h-[46px] min-w-[3rem] items-center justify-center px-4 py-3 gradient-primary hover:shadow-lg hover:shadow-primary-500/20 disabled:bg-gray-300 dark:disabled:bg-gray-700 disabled:shadow-none text-gray-900 dark:text-white rounded-xl transition-all disabled:cursor-not-allowed"
            aria-busy={isLoading}
          >
            {isLoading ? (
              <Loader2 className="h-5 w-5 animate-spin" aria-hidden />
            ) : (
              <Send className="h-5 w-5" aria-hidden />
            )}
          </button>
        </div>
      </div>

      {pptSlideImageModal &&
        createPortal(
          <div
            className="fixed inset-0 z-[100] flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm"
            role="dialog"
            aria-modal="true"
            aria-label={pptSlideImageModal.alt}
            onClick={() => setPptSlideImageModal(null)}
          >
            <div
              className="relative flex max-h-[min(92vh,1200px)] max-w-[min(96vw,1280px)] flex-col items-center gap-3"
              onClick={(e) => e.stopPropagation()}
            >
              <button
                type="button"
                onClick={() => setPptSlideImageModal(null)}
                className="absolute -right-1 -top-1 z-10 rounded-full border border-white/20 bg-white/95 p-2 text-gray-800 shadow-lg transition hover:bg-white dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:hover:bg-gray-700"
                aria-label="Close preview"
              >
                <X className="h-5 w-5" aria-hidden />
              </button>
              <img
                src={pptSlideImageModal.src}
                alt={pptSlideImageModal.alt}
                className="max-h-[min(88vh,1100px)] max-w-full rounded-lg object-contain bg-slate-950 shadow-2xl ring-1 ring-white/10"
              />
              {pptSlideImageModal.caption ? (
                <p className="max-w-full text-center text-sm text-gray-200">{pptSlideImageModal.caption}</p>
              ) : null}
            </div>
          </div>,
          document.body
        )}
    </div>
  );
}
