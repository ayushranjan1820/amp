import { useState, useEffect, useRef, useCallback, useMemo, Fragment } from 'react';
import { Children, isValidElement } from 'react';
import type { ReactNode, ChangeEvent } from 'react';
import {
  Bot,
  MessageSquare,
  User,
  Activity,
  Zap,
  Users,
  AlertCircle,
  CheckCircle,
  Check,
  Loader2,
  Key,
  Trash2,
  Edit2,
  Save,
  X,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  ArrowLeft,
  AlertTriangle,
  Send,
  Database,
  Download,
  FileText,
  Play,
  Calendar,
  Sparkles,
  SlidersHorizontal,
  LayoutGrid,
  ChevronRight,
  PenLine,
  Wand2,
  Brain,
  Paperclip,
} from 'lucide-react';
import {
  getAgents,
  generateWorkflow,
  executeWorkflowStream,
  executeWorkflowStepStream,
  submitWorkflowInput,
  saveWorkflow,
  listWorkflows,
  getWorkflow,
  deleteWorkflow,
  fetchAllVectorIndexes,
  listWorkflowExecutions,
  getWorkflowExecution,
  getWorkflowExecutionStep,
  deleteWorkflowExecution,
  type AgentsCatalog as CatalogData,
} from '../services/api';
import AgentWorkflowFlowDiagram from './AgentWorkflowFlowDiagram';
import WorkflowBatchPromptEditor from './WorkflowBatchPromptEditor';
import PromptHarnessModal from './PromptHarnessModal';
import BPMNViewer from './BPMNViewer';
import AgentConfigPanel from './AgentConfigPanel';
import WorkflowMemoryGraphModal from './WorkflowMemoryGraphModal';
import { useLoading } from '../context/LoadingContext';
import { useAuth } from '../context/AuthContext';
import { Link, useNavigate } from 'react-router-dom';
import {
  getConfigFields,
  buildAgentUserConfigsForWorkflowWithServerOverlay,
  buildAgentUserConfigsForWorkflowStorage,
  applyServerAgentConfigsToLocal,
  hasRequiredConfig,
} from '../utils/agentConfigStorage';
import { buildAgentExtraKwargsForAgents, fileToStored, type StoredAgentFile } from '../utils/agentConfigFiles';
import ReactMarkdown from 'react-markdown';
import type { Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import CompanyAiSolutionsView, { isCompanyAiSolutionsReport } from './CompanyAiSolutionsView';
import { linkifySourceCitations } from '../utils/linkifyMarkdownSources';
import MermaidDiagram from './MermaidDiagram';
import {
  workflowDiagramLayoutDraftKey,
  workflowDiagramLayoutStorageKey,
  type PromptHarnessEdgeConfig,
} from '../utils/workflowFlowGraph';

const WORKFLOWS_TAB_STEP_MODE_KEY = 'workflows-tab-step-mode';

function readStoredWorkflowStepMode(): 'auto' | 'step' {
  try {
    const v = localStorage.getItem(WORKFLOWS_TAB_STEP_MODE_KEY);
    if (v === 'step' || v === 'auto') return v;
  } catch {
    /* ignore */
  }
  return 'auto';
}

function hasRenderableListContent(children: ReactNode): boolean {
  return Children.toArray(children).some((child) => {
    if (child == null || typeof child === 'boolean') {
      return false;
    }
    if (typeof child === 'string' || typeof child === 'number') {
      return String(child).trim().length > 0;
    }
    if (Array.isArray(child)) {
      return hasRenderableListContent(child);
    }
    if (isValidElement<{ children?: ReactNode }>(child)) {
      return hasRenderableListContent(child.props?.children);
    }
    return false;
  });
}

const workflowAgentMarkdownComponents: Partial<Components> = {
  /** Avoid nested <pre>: react-markdown already wraps fenced blocks in <pre><code>. */
  pre: ({ children }) => <>{children}</>,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" className="font-medium text-inherit">
      {children}
    </a>
  ),
  code: ({ className, children, node, ...props }) => {
    if (className?.includes('language-mermaid')) {
      const chart = String(children).replace(/\n$/, '');
      return <MermaidDiagram chart={chart} />;
    }
    if (className?.includes('language-review-json')) {
      const raw = String(children).replace(/\n$/, '');
      let formatted = raw.trim();
      try {
        formatted = JSON.stringify(JSON.parse(formatted), null, 2);
      } catch {
        // keep as-is if not valid JSON
      }
      return (
        <pre className="my-3 overflow-x-auto rounded-xl border border-teal-200/80 bg-teal-50/95 p-3 font-mono text-[0.8125rem] leading-relaxed text-slate-800 shadow-[inset_0_1px_0_rgba(255,255,255,0.5)] [tab-size:2] ring-1 ring-teal-900/[0.06]">
          <code className="block whitespace-pre font-mono text-inherit" {...props}>
            {formatted}
          </code>
        </pre>
      );
    }
    const isBlock = node?.position && node.position.start.line !== node.position.end.line;
    if (!isBlock && !className) {
      return (
        <code
          className="rounded-lg bg-slate-100/90 px-1.5 py-0.5 font-mono text-[0.8125rem] text-black ring-1 ring-slate-200/60"
          {...props}
        >
          {children}
        </code>
      );
    }
    return (
      <pre className="my-3 overflow-x-auto rounded-xl border border-slate-200/70 bg-slate-50/95 p-3 font-mono text-[0.8125rem] leading-relaxed text-black shadow-[inset_0_1px_0_rgba(255,255,255,0.45)] [tab-size:2]">
        <code className={`block whitespace-pre font-mono text-inherit ${className ?? ''}`} {...props}>
          {children}
        </code>
      </pre>
    );
  },
  table: ({ children }) => (
    <div className="workflow-md-table-wrap my-4 w-full overflow-hidden rounded-xl border border-slate-200/70 bg-white/95 shadow-sm shadow-slate-900/5 ring-1 ring-slate-900/[0.03]">
      <div className="overflow-x-auto">
        <table className="workflow-md-table w-full min-w-[20rem] border-collapse text-[0.8125rem] leading-snug">
          {children}
        </table>
      </div>
    </div>
  ),
  tr: ({ children }) => <tr className="transition-colors even:bg-slate-50/70 hover:bg-slate-100/50">{children}</tr>,
  th: ({ children }) => (
    <th className="border-b border-slate-200/90 bg-slate-50 px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-600">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border-b border-slate-100/95 px-4 py-2.5 text-slate-700">{children}</td>
  ),
  h1: ({ children }) => (
    <h1 className="workflow-md-h1 font-heading text-balance text-slate-900">{children}</h1>
  ),
  h2: ({ children }) => (
    <h2 className="workflow-md-h2 font-heading text-slate-900">{children}</h2>
  ),
  h3: ({ children }) => (
    <h3 className="workflow-md-h3 font-heading text-slate-800">{children}</h3>
  ),
  h4: ({ children }) => (
    <h4 className="workflow-md-h4 font-heading text-slate-800">{children}</h4>
  ),
  h5: ({ children }) => (
    <h5 className="workflow-md-h5 font-heading text-slate-700">{children}</h5>
  ),
  h6: ({ children }) => (
    <h6 className="workflow-md-h6 font-heading text-slate-600">{children}</h6>
  ),
  ul: ({ children }) => (
    <ul className="workflow-md-ul not-prose my-0 list-none pl-0 text-slate-600 [content-visibility:auto]">
      {children}
    </ul>
  ),
  ol: ({ children }) => (
    <ol className="workflow-md-ol not-prose my-0 list-none pl-0 text-slate-600 [content-visibility:auto]">
      {children}
    </ol>
  ),
  li: ({ children }) => {
    if (!hasRenderableListContent(children)) {
      return null;
    }
    return <li className="workflow-md-li not-prose leading-[1.65]">{children}</li>;
  },
  p: ({ children }) => <p className="workflow-md-p mb-0 text-slate-600 last:mb-0">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold text-slate-900">{children}</strong>,
  blockquote: ({ children }) => (
    <blockquote className="workflow-md-blockquote my-4 rounded-xl border border-slate-200/65 border-l-[3px] border-l-[var(--color-pwc-orange)] bg-slate-50/70 py-3 pl-4 pr-4 text-slate-700 not-italic leading-relaxed shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="workflow-md-hr my-8 border-0" />,
};

function WorkflowAgentMarkdown({ content, isStreaming }: { content: string; isStreaming?: boolean }) {
  const normalizedContent = content?.trim() ?? '';
  if (!normalizedContent) {
    return null;
  }

  return (
    <article
      className="workflow-md-document workflow-agent-markdown [color-scheme:light] w-full max-w-none overflow-hidden rounded-xl border border-slate-200/80 bg-white text-slate-800 shadow-[0_1px_0_rgba(255,255,255,0.9)_inset,0_8px_20px_-16px_rgba(15,23,42,0.18)] ring-1 ring-slate-200/45"
      data-export-root="workflow-agent-markdown"
    >
      <div
        className="workflow-md-prose workflow-md-prose--business prose prose-sm max-w-none w-full overflow-x-hidden break-words px-4 py-4 text-left font-body antialiased selection:bg-orange-100/70 selection:text-slate-900 sm:px-5 sm:py-5 lg:px-6 lg:py-5 [&>*]:max-w-none"
        data-export-prose
      >
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={workflowAgentMarkdownComponents}>
          {linkifySourceCitations(normalizedContent)}
        </ReactMarkdown>
        {isStreaming && (
          <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse rounded-full bg-orange-500/70 align-text-bottom" />
        )}
      </div>
    </article>
  );
}

function formatDate(dateStr: string) {
  const d = new Date(dateStr);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}
function parseKbCompositeLabel(label: string): { db_name: string; collection: string; index_name: string; label: string } | null {
  const parts = label.split('.');
  if (parts.length < 3) return null;
  const db_name = parts[0];
  const index_name = parts[parts.length - 1]!;
  const collection = parts.slice(1, -1).join('.');
  return { db_name, collection, index_name, label };
}

/** Compact display for long KB index labels in the workflow step picker. */
/** One line for Run timeline from Claude Code / agent thinking payloads. */
function formatAgentThinkingLine(thinking: Record<string, unknown>): string {
  const typ = String(thinking.type ?? '');
  const content = String(thinking.content ?? '').trim();
  const tool = thinking.tool_name != null ? String(thinking.tool_name) : '';
  if (typ === 'tool_call') {
    return content || (tool ? `Tool: ${tool}` : 'Tool call');
  }
  if (typ === 'tool_result') {
    return content || (tool ? `Result (${tool})` : 'Tool result');
  }
  if (typ === 'thinking' || typ === 'text') {
    return content || '(thinking)';
  }
  return content || `[${typ || 'step'}]`;
}

function formatKbShortLabel(label: string, max = 44): string {
  if (!label) return '';
  if (label.length <= max) return label;
  const parts = label.split('.');
  if (parts.length >= 3) {
    const db = parts[0];
    const indexName = parts[parts.length - 1]!;
    const coll = parts.slice(1, -1).join('.');
    const candidate = `${db} › ${coll} › ${indexName}`;
    if (candidate.length <= max) return candidate;
  }
  return `${label.slice(0, Math.max(8, max - 1))}…`;
}

/** SVG ring spinner for workflow step “running” UI (step list + status chip). */
function StepRunningSpinner({ className }: { className?: string }) {
  return (
    <svg
      className={`shrink-0 animate-spin ${className ?? ''}`}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden
    >
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
      <path
        fill="currentColor"
        className="opacity-90"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
      />
    </svg>
  );
}

interface KBIndexConfig {
  db_name: string;
  collection: string;
  index_name: string;
  top_k: number;
  enabled: boolean;
}

interface WorkflowStep {
  step_number: number;
  agent_id: string;
  agent: string;
  agent_name?: string;
  query: string;
  depends_on: number[];
  input_mapping?: Record<string, string>;
  prompt_harness?: Record<string, PromptHarnessEdgeConfig>;
  status?: 'pending' | 'running' | 'completed' | 'failed';
  kb_index?: KBIndexConfig;
}

interface WorkflowDefinition {
  name: string;
  steps: WorkflowStep[];
  mermaid: string;
}

interface SavedWorkflow {
  id: string;
  name: string;
  instruction: string;
  definition: WorkflowDefinition;
  mermaid_code: string;
  created_at: string;
  memory_enabled?: boolean;
}

const WORKFLOW_STEP_MAX_ATTACHMENTS = 5;
const WORKFLOW_STEP_MAX_ATTACHMENT_BYTES = 12 * 1024 * 1024;

function storedFilesToUploadedFilesPayload(files: StoredAgentFile[] | undefined) {
  if (!files?.length) return undefined;
  return files.map((f) => ({
    file_name: f.file_name,
    file_type: f.file_type,
    file_content: f.file_content,
  }));
}

function remapStepPromptAttachments(
  map: Record<number, StoredAgentFile[]>,
  deletedStepNum: number,
): Record<number, StoredAgentFile[]> {
  const out: Record<number, StoredAgentFile[]> = {};
  for (const [k, v] of Object.entries(map)) {
    const n = Number(k);
    if (Number.isNaN(n) || n === deletedStepNum) continue;
    const nn = n > deletedStepNum ? n - 1 : n;
    out[nn] = v;
  }
  return out;
}

interface ChatMessage {
  id: string;
  type:
    | 'system'
    | 'agent_start'
    | 'agent_input'
    | 'agent_progress'
    | 'agent_thinking'
    | 'agent_complete'
    | 'agent_failed'
    | 'agent_streaming'
    | 'needs_input'
    | 'user_reply'
    | 'workflow_complete';
  stepNumber?: number;
  agentName?: string;
  content: string;
  fullQuery?: string;
  timestamp: Date;
  success?: boolean;
  fullResponse?: string;
  isStreaming?: boolean;
  bpmn_xml?: string;
  download_url?: string;
}

/** Use markdown rendering when the final/agent response is markdown, or when log lines contain fenced blocks (e.g. ```review-json). */
function messageUsesWorkflowAgentMarkdown(msg: Pick<ChatMessage, 'type' | 'content'>): boolean {
  if (msg.type === 'agent_streaming' || msg.type === 'agent_complete') {
    return true;
  }
  if (
    msg.type === 'agent_thinking' ||
    msg.type === 'agent_start' ||
    msg.type === 'agent_progress' ||
    msg.type === 'agent_failed'
  ) {
    return /(^|\n)```/.test(msg.content);
  }
  return false;
}

interface FollowUpPrompt {
  executionId: string;
  stepNumber: number;
  agentName: string;
  question: string;
}

interface ExecutionSummary {
  id: string;
  workflow_id: string;
  status: string;
  started_at: string;
  completed_at: string | null;
}

interface ExecutionStepDetail {
  step_number: number;
  agent_id: string;
  agent_name: string;
  status: string;
  /** Populated lazily on expand. */
  query?: string;
  /** Populated lazily on expand. */
  response?: string;
  /** Populated lazily on expand (only when has_bpmn). */
  bpmn_xml?: string;
  /** Cheap: not a body field, returned by the summary endpoint. */
  download_url?: string;
  created_at: string;
  /** Summary-only fields — present before the body is fetched. */
  query_length?: number;
  response_length?: number;
  has_bpmn?: boolean;
  /** Loading indicator while the body is being fetched on expand. */
  bodyLoading?: boolean;
  /** True once query/response have been fetched for this step. */
  bodyLoaded?: boolean;
}

interface WorkflowsTabProps {
  routeWorkflowId?: string;
}

type CatalogAgent = NonNullable<CatalogData['agents']>[number];

function WorkflowStepConfigureSection({
  agent,
  configOk,
  onSaved,
}: {
  agent: CatalogAgent;
  configOk: boolean;
  onSaved: () => void;
}) {
  return (
    <div
      className={`relative overflow-hidden rounded-2xl border p-3 sm:p-3.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)] ${
        configOk
          ? 'border-emerald-500/15 bg-gradient-to-br from-zinc-950/80 via-zinc-900/50 to-emerald-950/15'
          : 'border-amber-500/20 bg-gradient-to-br from-zinc-950/80 via-zinc-900/50 to-amber-950/20'
      }`}
    >
      <div
        className={`pointer-events-none absolute inset-0 ${
          configOk
            ? 'bg-[radial-gradient(120%_80%_at_100%_-20%,rgba(52,211,153,0.08),transparent_45%)]'
            : 'bg-[radial-gradient(120%_80%_at_100%_-20%,rgba(251,191,36,0.09),transparent_45%)]'
        }`}
        aria-hidden
      />
      <div className="relative">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2.5">
            <div
              className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-xl shadow-inner ${
                configOk
                  ? 'bg-emerald-500/10 text-emerald-400 ring-1 ring-emerald-500/25'
                  : 'bg-amber-500/10 text-amber-400 ring-1 ring-amber-500/30'
              }`}
            >
              <Key className="h-4 w-4" strokeWidth={1.75} />
            </div>
            <div className="min-w-0">
              <p className="font-body text-[11px] font-semibold tracking-tight text-gray-900 dark:text-white">Connection</p>
              <p className="font-body text-[9px] text-zinc-500">
                Browser + saved with workflow (for server-side runs)
              </p>
            </div>
          </div>
          {configOk ? (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/20 bg-emerald-500/[0.12] px-2.5 py-1 text-[10px] font-medium text-emerald-200">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.6)]" aria-hidden />
              Complete
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/25 bg-amber-500/[0.12] px-2.5 py-1 text-[10px] font-medium text-amber-100">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-400" aria-hidden />
              Incomplete
            </span>
          )}
        </div>
        <AgentConfigPanel agent={agent} compact workflowEmbed onSaved={onSaved} />
      </div>
    </div>
  );
}

export function WorkflowsTab({ routeWorkflowId }: WorkflowsTabProps = {}) {
  const { isAuthenticated, role } = useAuth();
  const isAdmin = role === 'admin' || role === 'super_admin';
  const navigate = useNavigate();
  const isSharedWorkflowRunMode = !isAuthenticated && !!routeWorkflowId;
  const lastLoadedRouteIdRef = useRef<string | undefined>(undefined);
  const [instruction, setInstruction] = useState('');
  const [workflow, setWorkflow] = useState<WorkflowDefinition | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isExecuting, setIsExecuting] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [savedWorkflows, setSavedWorkflows] = useState<SavedWorkflow[]>([]);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [editingStep, setEditingStep] = useState<number | null>(null);
  const [pipelineTab, setPipelineTab] = useState<'diagram' | 'steps'>('steps');
  const [expandedMsg, setExpandedMsg] = useState<string | null>(null);
  const [collapsedLogMsgIds, setCollapsedLogMsgIds] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [followUpQueue, setFollowUpQueue] = useState<FollowUpPrompt[]>([]);
  const [followUpInput, setFollowUpInput] = useState('');
  const [isSubmittingFollowUp, setIsSubmittingFollowUp] = useState(false);
  const [stepMode, setStepMode] = useState<'auto' | 'step'>(() => readStoredWorkflowStepMode());
  const [batchApproval, setBatchApproval] = useState<{
    executionId: string;
    batchNum: number;
    nextAgents: string[];
    nextStepNumbers: number[];
    nextStepInputs: Record<string, string>;
  } | null>(null);
  const [isSubmittingBatchApproval, setIsSubmittingBatchApproval] = useState(false);
  const [kbIndexes, setKbIndexes] = useState<Array<{ db_name: string; collection: string; index_name: string; label: string }>>([]);
  const [kbIndexesLoaded, setKbIndexesLoaded] = useState(false);
  const [kbIndexesLoading, setKbIndexesLoading] = useState(false);
  const [kbPickerOpenIdx, setKbPickerOpenIdx] = useState<number | null>(null);
  const kbPickerRef = useRef<HTMLDivElement>(null);
  const [activeView, setActiveView] = useState<'builder' | 'library'>('builder');
  const [currentWorkflowId, setCurrentWorkflowId] = useState<string | undefined>(undefined);
  const [memoryEnabled, setMemoryEnabled] = useState<boolean>(false);
  const [memoryGraphOpen, setMemoryGraphOpen] = useState<boolean>(false);
  const [executions, setExecutions] = useState<ExecutionSummary[]>([]);
  const [selectedExecution, setSelectedExecution] = useState<{ execution: ExecutionSummary; steps: ExecutionStepDetail[] } | null>(null);
  const [loadingExecution, setLoadingExecution] = useState(false);
  const [executionsRefreshing, setExecutionsRefreshing] = useState(false);
  /** Cache of already-fetched execution summaries, keyed by execution id. */
  const executionDetailCacheRef = useRef<Record<string, { execution: ExecutionSummary; steps: ExecutionStepDetail[] }>>({});
  const [expandedHistoryMsg, setExpandedHistoryMsg] = useState<string | null>(null);
  const [studioCatalog, setStudioCatalog] = useState<CatalogData | null>(null);
  const [stepModalStepNumber, setStepModalStepNumber] = useState<number | null>(null);
  const [promptHarnessEdge, setPromptHarnessEdge] = useState<{ fromStep: number; toStep: number } | null>(null);
  const [workflowTitleEditOpen, setWorkflowTitleEditOpen] = useState(false);
  const [workflowTitleDraft, setWorkflowTitleDraft] = useState('');
  /** Bumps after inline agent config save so step status badges re-read localStorage. */
  const [, setWorkflowAgentConfigTick] = useState(0);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const missionTextareaRef = useRef<HTMLTextAreaElement>(null);
  const workflowNameInputRef = useRef<HTMLInputElement>(null);
  const executionIdRef = useRef<string>('');
  const chunkBufferRef = useRef<Record<number, { chunks: string; agentName: string; timer: ReturnType<typeof setTimeout> | null }>>({});
  const autoSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const workflowVersionRef = useRef(0);
  const currentWorkflowIdRef = useRef<string | undefined>(undefined);
  const prevCurrentWorkflowIdForTitleEditRef = useRef<string | undefined>(undefined);
  /** Credentials last loaded from or saved to the server for this workflow (execute merge). */
  const workflowStoredConfigsRef = useRef<Record<string, Record<string, string>> | null>(null);
  /** Resolved input the agent received for each step (from SSE step_input). Used to re-run a step with the same input. */
  const lastStepInputsRef = useRef<Record<number, string>>({});
  const [stepPromptAttachments, setStepPromptAttachments] = useState<Record<number, StoredAgentFile[]>>({});
  const rerunFileInputRef = useRef<HTMLInputElement>(null);
  const [rerunningStep, setRerunningStep] = useState<number | null>(null);
  const [rerunModal, setRerunModal] = useState<{
    stepNumber: number;
    agentLabel: string;
    input: string;
    attachments: StoredAgentFile[];
  } | null>(null);
  const { withLoader } = useLoading();

  /** Non-empty agent credentials to persist on the workflow (localStorage + catalog defaults). */
  const getPersistedAgentConfigsForSave = useCallback((): Record<string, Record<string, string>> | undefined => {
    if (!workflow?.steps?.length || !studioCatalog?.agents?.length) return undefined;
    const cfg = buildAgentUserConfigsForWorkflowStorage(workflow.steps, studioCatalog.agents);
    return Object.keys(cfg).length ? cfg : undefined;
  }, [workflow?.steps, studioCatalog?.agents]);

  const stripStepProgressPlaceholders = useCallback((messages: ChatMessage[], stepNumber: number) =>
    messages.filter(
      m =>
        !(
          m.stepNumber === stepNumber &&
          (m.type === 'agent_start' || m.type === 'agent_progress')
        ),
    ), []);

  const flushChunkBuffer = useCallback((stepNumber: number) => {
    const buf = chunkBufferRef.current[stepNumber];
    if (!buf || !buf.chunks) return;
    const bufferedText = buf.chunks;
    const agentName = buf.agentName;
    buf.chunks = '';
    const streamId = `stream-${stepNumber}`;
    setChatMessages(prev => {
      const existingIdx = prev.findIndex(m => m.id === streamId);
      if (existingIdx !== -1) {
        const updated = [...prev];
        updated[existingIdx] = {
          ...updated[existingIdx],
          content: updated[existingIdx].content + bufferedText,
        };
        return updated;
      }
      const withoutStale = stripStepProgressPlaceholders(prev, stepNumber);
      return [
        ...withoutStale,
        {
          id: streamId,
          type: 'agent_streaming' as const,
          stepNumber,
          agentName,
          content: bufferedText,
          timestamp: new Date(),
          isStreaming: true,
        },
      ];
    });
  }, [stripStepProgressPlaceholders]);

  const scrollToBottom = useCallback(() => {
    setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);
  }, []);

  const focusMissionTextarea = useCallback(() => {
    const el = missionTextareaRef.current;
    if (!el) return;
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    window.setTimeout(() => {
      el.focus({ preventScroll: true });
      const len = el.value.length;
      el.setSelectionRange(len, len);
    }, 280);
  }, []);

  const beginWorkflowTitleEdit = useCallback(() => {
    if (!workflow || isSharedWorkflowRunMode) return;
    setWorkflowTitleDraft(workflow.name || '');
    setWorkflowTitleEditOpen(true);
  }, [workflow, isSharedWorkflowRunMode]);

  const commitWorkflowTitleEdit = useCallback(() => {
    const trimmed = workflowTitleDraft.trim();
    setWorkflowTitleEditOpen(false);
    setWorkflowTitleDraft('');
    if (!workflow || !trimmed) return;
    if (trimmed === workflow.name) return;
    setWorkflow({ ...workflow, name: trimmed });
  }, [workflowTitleDraft, workflow]);

  const cancelWorkflowTitleEdit = useCallback(() => {
    setWorkflowTitleEditOpen(false);
    setWorkflowTitleDraft('');
  }, []);

  const addMessage = useCallback((msg: Omit<ChatMessage, 'id' | 'timestamp'>) => {
    const newMsg = { ...msg, id: Math.random().toString(36).slice(2), timestamp: new Date() };
    console.log('[Workflow] Adding message:', msg.type, msg.content?.slice(0, 80));
    setChatMessages(prev => {
      const updated = [...prev, newMsg];
      console.log('[Workflow] Messages count:', updated.length);
      return updated;
    });
    scrollToBottom();
  }, [scrollToBottom]);

  const loadSavedWorkflows = async () => {
    if (!isAuthenticated) {
      setSavedWorkflows([]);
      return;
    }
    try {
      const data = await withLoader('Loading saved agents...', () => listWorkflows());
      setSavedWorkflows(Array.isArray(data) ? data : data.workflows || []);
    } catch {
      setSavedWorkflows([]);
    }
  };

  useEffect(() => {
    void loadSavedWorkflows();
  }, [isAuthenticated]);

  useEffect(() => {
    if (!isAuthenticated && activeView === 'library') {
      setActiveView('builder');
    }
  }, [isAuthenticated, activeView]);

  useEffect(() => {
    try {
      localStorage.setItem(WORKFLOWS_TAB_STEP_MODE_KEY, stepMode);
    } catch {
      /* ignore quota / private mode */
    }
  }, [stepMode]);

  useEffect(() => {
    if (!routeWorkflowId) {
      lastLoadedRouteIdRef.current = undefined;
      return;
    }
    if (lastLoadedRouteIdRef.current === routeWorkflowId) return;
    const target = savedWorkflows.find((w) => w.id === routeWorkflowId);
    const fallback: SavedWorkflow = {
      id: routeWorkflowId,
      name: '',
      instruction: '',
      definition: { name: '', steps: [], mermaid: '' },
      mermaid_code: '',
      created_at: '',
    };
    lastLoadedRouteIdRef.current = routeWorkflowId;
    setActiveView('builder');
    void handleLoadWorkflow(target || fallback);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeWorkflowId, savedWorkflows, isAuthenticated]);

  useEffect(() => {
    // Use /api/agents (not /api/catalog) so public studio can load agent metadata + config fields without admin "agents" permission.
    getAgents().then(setStudioCatalog).catch(() => {});
  }, []);

  useEffect(() => {
    currentWorkflowIdRef.current = currentWorkflowId;
  }, [currentWorkflowId]);

  /** Close rename UI when navigating between saved workflows, not when the id is first minted by auto-save (undefined → id). */
  useEffect(() => {
    const prevId = prevCurrentWorkflowIdForTitleEditRef.current;
    const curId = currentWorkflowId;
    const switchedDifferentSavedWorkflow =
      typeof prevId === 'string' && typeof curId === 'string' && prevId !== curId;
    const clearedSavedWorkflow = typeof prevId === 'string' && curId === undefined;
    if (switchedDifferentSavedWorkflow || clearedSavedWorkflow) {
      setWorkflowTitleEditOpen(false);
      setWorkflowTitleDraft('');
    }
    prevCurrentWorkflowIdForTitleEditRef.current = curId;
  }, [currentWorkflowId]);

  useEffect(() => {
    if (!workflowTitleEditOpen) return;
    const id = window.requestAnimationFrame(() => {
      workflowNameInputRef.current?.focus();
      workflowNameInputRef.current?.select();
    });
    return () => window.cancelAnimationFrame(id);
  }, [workflowTitleEditOpen]);

  useEffect(() => {
    if (!isAuthenticated || !workflow || !workflow.name) return;
    workflowVersionRef.current += 1;
    const currentVersion = workflowVersionRef.current;
    if (autoSaveTimerRef.current) clearTimeout(autoSaveTimerRef.current);
    autoSaveTimerRef.current = setTimeout(async () => {
      if (currentVersion !== workflowVersionRef.current) return;
      try {
        const agentConfigs = getPersistedAgentConfigsForSave();
        const result = await saveWorkflow({
          id: currentWorkflowIdRef.current,
          name: workflow.name,
          instruction,
          definition: { name: workflow.name, steps: workflow.steps },
          mermaid_code: workflow.mermaid,
          memory_enabled: memoryEnabled,
          ...(agentConfigs ? { agent_user_configs: agentConfigs } : {}),
        });
        const wid = result?.id as string | undefined;
        if (wid && !currentWorkflowIdRef.current) {
          currentWorkflowIdRef.current = wid;
          setCurrentWorkflowId(wid);
        }
        if (wid) {
          setSavedWorkflows((prev) => {
            const idx = prev.findIndex((w) => w.id === wid);
            const patch: SavedWorkflow = {
              id: wid,
              name: workflow.name,
              instruction,
              definition: {
                name: workflow.name,
                steps: workflow.steps,
                mermaid: workflow.mermaid,
              },
              mermaid_code: workflow.mermaid,
              created_at: idx === -1 ? new Date().toISOString() : prev[idx]!.created_at,
              memory_enabled: memoryEnabled,
            };
            if (idx === -1) return [patch, ...prev];
            const next = prev.filter((_, i) => i !== idx);
            return [patch, ...next];
          });
        }
        if (agentConfigs) {
          workflowStoredConfigsRef.current = agentConfigs;
        }
      } catch (e) {
        console.warn('Auto-save failed:', e);
      }
    }, 1000);
    return () => {
      if (autoSaveTimerRef.current) clearTimeout(autoSaveTimerRef.current);
    };
  }, [isAuthenticated, workflow?.steps, workflow?.mermaid, workflow?.name, instruction, memoryEnabled, getPersistedAgentConfigsForSave]);

  const loadKbIndexes = async () => {
    if (kbIndexesLoaded || kbIndexesLoading) return;
    setKbIndexesLoading(true);
    try {
      const data = await withLoader('Loading knowledge base indexes...', () => fetchAllVectorIndexes());
      setKbIndexes(data.indexes || []);
      setKbIndexesLoaded(true);
    } catch (err) {
      console.warn('Failed to load KB indexes:', err);
    } finally {
      setKbIndexesLoading(false);
    }
  };

  useEffect(() => {
    if (kbPickerOpenIdx === null) return;
    const onDoc = (e: MouseEvent) => {
      if (kbPickerRef.current && !kbPickerRef.current.contains(e.target as Node)) {
        setKbPickerOpenIdx(null);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setKbPickerOpenIdx(null);
    };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [kbPickerOpenIdx]);

  useEffect(() => {
    setKbPickerOpenIdx(null);
  }, [editingStep]);

  useEffect(() => {
    if (stepModalStepNumber === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setStepModalStepNumber(null);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [stepModalStepNumber]);

  useEffect(() => {
    if (rerunModal === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && rerunningStep === null) setRerunModal(null);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [rerunModal, rerunningStep]);

  useEffect(() => {
    if (!workflow || stepModalStepNumber === null) return;
    if (!workflow.steps.some((s) => s.step_number === stepModalStepNumber)) {
      setStepModalStepNumber(null);
    }
  }, [workflow, stepModalStepNumber]);

  const loadExecutions = async (wfId: string) => {
    try {
      const data = await withLoader('Loading execution history...', () => listWorkflowExecutions(wfId));
      setExecutions(data.executions || []);
    } catch (e) {
      console.warn('Failed to load executions:', e);
      setExecutions([]);
    }
  };

  const refreshExecutions = useCallback(async () => {
    const wfId = currentWorkflowId;
    if (!wfId) return;
    setExecutionsRefreshing(true);
    try {
      const data = await listWorkflowExecutions(wfId);
      setExecutions(data.executions || []);
    } catch (e) {
      console.warn('Failed to refresh executions:', e);
    } finally {
      setExecutionsRefreshing(false);
    }
  }, [currentWorkflowId]);

  const loadExecutionDetail = async (exec: ExecutionSummary) => {
    setExpandedHistoryMsg(null);
    const cached = executionDetailCacheRef.current[exec.id];
    if (cached) {
      setSelectedExecution(cached);
      return;
    }
    setLoadingExecution(true);
    try {
      const data = await getWorkflowExecution(exec.id);
      const steps: ExecutionStepDetail[] = (data.execution?.steps || []).map((s: any) => ({
        step_number: s.step_number,
        agent_id: s.agent_id,
        agent_name: s.agent_name,
        status: s.status,
        download_url: s.download_url || undefined,
        created_at: s.created_at,
        query_length: s.query_length ?? 0,
        response_length: s.response_length ?? 0,
        has_bpmn: !!s.has_bpmn,
        bodyLoaded: false,
      }));
      const entry = { execution: exec, steps };
      executionDetailCacheRef.current[exec.id] = entry;
      setSelectedExecution(entry);
    } catch (e) {
      console.warn('Failed to load execution detail:', e);
    } finally {
      setLoadingExecution(false);
    }
  };

  /** Fetch the full body for a single step on first expand; cached thereafter. */
  const ensureStepBody = useCallback(async (executionId: string, stepNumber: number) => {
    const applyPatch = (patch: Partial<ExecutionStepDetail>) => {
      const cached = executionDetailCacheRef.current[executionId];
      if (cached) {
        cached.steps = cached.steps.map((s) => (s.step_number === stepNumber ? { ...s, ...patch } : s));
      }
      setSelectedExecution((prev) =>
        prev && prev.execution.id === executionId
          ? { ...prev, steps: prev.steps.map((s) => (s.step_number === stepNumber ? { ...s, ...patch } : s)) }
          : prev,
      );
    };
    const cached = executionDetailCacheRef.current[executionId];
    const step = cached?.steps.find((s) => s.step_number === stepNumber);
    if (!step || step.bodyLoaded || step.bodyLoading) return;
    applyPatch({ bodyLoading: true });
    try {
      const data = await getWorkflowExecutionStep(executionId, stepNumber);
      const body = data.step || {};
      applyPatch({
        query: body.query || '',
        response: body.response || '',
        bpmn_xml: body.bpmn_xml || undefined,
        bodyLoaded: true,
        bodyLoading: false,
      });
    } catch (e) {
      console.warn('Failed to load step body:', e);
      applyPatch({ bodyLoading: false });
    }
  }, []);

  const handleStepKbIndexChange = (stepIndex: number, value: string) => {
    if (!workflow) return;
    const updated = [...workflow.steps];
    if (!value) {
      updated[stepIndex] = { ...updated[stepIndex], kb_index: undefined };
    } else {
      const idx =
        kbIndexes.find(i => i.label === value) ?? parseKbCompositeLabel(value);
      if (idx) {
        updated[stepIndex] = {
          ...updated[stepIndex],
          kb_index: {
            db_name: idx.db_name,
            collection: idx.collection,
            index_name: idx.index_name,
            top_k: updated[stepIndex].kb_index?.top_k || 5,
            enabled: true,
          },
        };
      }
    }
    setWorkflow({ ...workflow, steps: updated });
  };

  const handleStepKbTopKChange = (stepIndex: number, topK: number) => {
    if (!workflow) return;
    const updated = [...workflow.steps];
    if (updated[stepIndex].kb_index) {
      updated[stepIndex] = {
        ...updated[stepIndex],
        kb_index: { ...updated[stepIndex].kb_index!, top_k: topK },
      };
    }
    setWorkflow({ ...workflow, steps: updated });
  };

  const handleGenerate = async () => {
    if (isSharedWorkflowRunMode || !instruction.trim()) return;
    setIsGenerating(true);
    setError(null);
    setChatMessages([]);
    setPipelineTab('steps');
    if (!routeWorkflowId) {
      setCurrentWorkflowId(undefined);
      currentWorkflowIdRef.current = undefined;
    }
    setMemoryEnabled(false);
    setStepPromptAttachments({});
    workflowStoredConfigsRef.current = null;
    try {
      const raw = await withLoader('Generating workflow...', () => generateWorkflow(instruction));
      const data = raw.workflow || raw;
      const wf: WorkflowDefinition = {
        name: data.name || 'Generated Agent',
        steps: (data.steps || []).map((s: any) => ({
          ...s,
          agent: s.label || s.agent || s.agent_id || '',
          agent_id: s.agent_id || '',
          agent_name: s.agent_name || '',
          status: 'pending' as const,
        })),
        mermaid: data.mermaid || data.mermaid_code || '',
      };
      setWorkflow(wf);
    } catch (e: any) {
      setError(e.message || 'Failed to generate workflow');
    } finally {
      setIsGenerating(false);
    }
  };

  const processWorkflowStreamEvent = (event: { event: string; data: any }) => {
    const { event: eventType, data } = event;

    if (eventType === 'execution_started') {
      executionIdRef.current = data.execution_id;
    } else if (eventType === 'batch_start') {
      addMessage({
        type: 'system',
        content: data.message || `Starting batch of ${data.step_numbers?.length || 0} steps...`,
      });
    } else if (eventType === 'batch_complete') {
      addMessage({
        type: 'system',
        content: data.message || `Batch complete — ${data.completed_count}/${data.total_count} steps done`,
      });
    } else if (eventType === 'step_start') {
      addMessage({
        type: 'agent_start',
        stepNumber: data.step_number,
        agentName: data.agent_name,
        content: `Processing: "${data.query}"`,
      });
      setWorkflow(prev => {
        if (!prev) return null;
        const steps = prev.steps.map(s =>
          s.step_number === data.step_number ? { ...s, status: 'running' as const } : s
        );
        return { ...prev, steps, mermaid: regenerateMermaid(steps) };
      });
    } else if (eventType === 'step_input') {
      if (typeof data.full_query === 'string' && typeof data.step_number === 'number') {
        lastStepInputsRef.current[data.step_number] = data.full_query;
      }
      addMessage({
        type: 'agent_input',
        stepNumber: data.step_number,
        agentName: data.agent_name,
        content: `Agent Input`,
        fullQuery: data.full_query,
      });
    } else if (eventType === 'step_progress') {
      setChatMessages(prev => {
        const startIdx = [...prev].reverse().findIndex(
          m => m.type === 'agent_start' && m.stepNumber === data.step_number
        );
        if (startIdx !== -1) {
          const actualIdx = prev.length - 1 - startIdx;
          const updated = [...prev];
          updated[actualIdx] = { ...updated[actualIdx], content: data.message || 'Working...' };
          return updated;
        }
        return [...prev, {
          id: `progress-${data.step_number}-${Date.now()}`,
          type: 'agent_progress' as const,
          stepNumber: data.step_number,
          agentName: data.agent_name,
          content: data.message || 'Working...',
          timestamp: new Date(),
        }];
      });
    } else if (eventType === 'step_thinking') {
      const thinking = data.thinking && typeof data.thinking === 'object'
        ? (data.thinking as Record<string, unknown>)
        : {};
      const line = formatAgentThinkingLine(thinking);
      if (!line) return;
      setChatMessages(prev => [
        ...prev,
        {
          id: `think-${data.step_number}-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
          type: 'agent_thinking' as const,
          stepNumber: data.step_number,
          agentName: data.agent_name,
          content: line,
          timestamp: new Date(),
        },
      ]);
    } else if (eventType === 'step_output') {
      const sn = data.step_number;
      if (!chunkBufferRef.current[sn]) {
        chunkBufferRef.current[sn] = { chunks: '', agentName: data.agent_name || '', timer: null };
      }
      chunkBufferRef.current[sn].chunks += (data.chunk || '');
      if (chunkBufferRef.current[sn].timer) clearTimeout(chunkBufferRef.current[sn].timer);
      chunkBufferRef.current[sn].timer = setTimeout(() => flushChunkBuffer(sn), 80);
    } else if (eventType === 'step_complete') {
      const sn = data.step_number;
      if (chunkBufferRef.current[sn]?.timer) {
        clearTimeout(chunkBufferRef.current[sn].timer);
      }
      delete chunkBufferRef.current[sn];
      const streamId = `stream-${sn}`;
      setChatMessages(prev => {
        const streamIdx = prev.findIndex(m => m.id === streamId);
        const dropStale = (msgs: ChatMessage[]) => stripStepProgressPlaceholders(msgs, sn);
        if (streamIdx !== -1) {
          const updated = [...prev];
          updated[streamIdx] = {
            ...updated[streamIdx],
            type: 'agent_complete' as const,
            content: data.response || updated[streamIdx].content,
            fullResponse: data.response,
            isStreaming: false,
            success: true,
            bpmn_xml: data.bpmn_xml || undefined,
            download_url: data.download_url || undefined,
          };
          return dropStale(updated);
        }
        const startIdx = prev.findIndex(
          m => m.stepNumber === sn && (m.type === 'agent_start' || m.type === 'agent_progress'),
        );
        if (startIdx !== -1) {
          const updated = [...prev];
          updated[startIdx] = {
            ...updated[startIdx],
            id: `complete-${sn}-${Date.now()}`,
            type: 'agent_complete' as const,
            content: data.response || 'Completed successfully',
            fullResponse: data.response,
            success: true,
            isStreaming: false,
            bpmn_xml: data.bpmn_xml || undefined,
            download_url: data.download_url || undefined,
          };
          return dropStale(updated);
        }
        return dropStale([
          ...prev,
          {
            id: `complete-${data.step_number}-${Date.now()}`,
            type: 'agent_complete' as const,
            stepNumber: data.step_number,
            agentName: data.agent_name,
            content: data.response || 'Completed successfully',
            fullResponse: data.response,
            timestamp: new Date(),
            success: true,
            isStreaming: false,
            bpmn_xml: data.bpmn_xml || undefined,
            download_url: data.download_url || undefined,
          },
        ]);
      });
      setWorkflow(prev => {
        if (!prev) return null;
        const steps = prev.steps.map(s =>
          s.step_number === data.step_number ? { ...s, status: 'completed' as const } : s
        );
        return { ...prev, steps, mermaid: regenerateMermaid(steps) };
      });
    } else if (eventType === 'step_failed') {
      const snf = data.step_number;
      setChatMessages(prev => [
        ...stripStepProgressPlaceholders(prev, snf).filter(
          m => !(m.id === `stream-${snf}` && m.type === 'agent_streaming'),
        ),
        {
          id: `failed-${snf}-${Date.now()}`,
          type: 'agent_failed' as const,
          stepNumber: snf,
          agentName: data.agent_name,
          content: data.error || 'Step failed',
          timestamp: new Date(),
          success: false,
        },
      ]);
      setWorkflow(prev => {
        if (!prev) return null;
        const steps = prev.steps.map(s =>
          s.step_number === data.step_number ? { ...s, status: 'failed' as const } : s
        );
        return { ...prev, steps, mermaid: regenerateMermaid(steps) };
      });
    } else if (eventType === 'needs_input') {
      addMessage({
        type: 'needs_input',
        stepNumber: data.step_number,
        agentName: data.agent_name,
        content: data.question,
      });
      setFollowUpQueue(prev => [...prev, {
        executionId: executionIdRef.current,
        stepNumber: data.step_number,
        agentName: data.agent_name,
        question: data.question,
      }]);
    } else if (eventType === 'step_resumed') {
      addMessage({
        type: 'system',
        stepNumber: data.step_number,
        agentName: data.agent_name,
        content: `Resuming with your input...`,
      });
    } else if (eventType === 'batch_approval_required') {
      setBatchApproval({
        executionId: executionIdRef.current,
        batchNum: data.batch,
        nextAgents: data.next_agents || [],
        nextStepNumbers: data.next_step_numbers || [],
        nextStepInputs: data.next_step_inputs || {},
      });
      addMessage({
        type: 'system',
        content: data.message || `Batch ${data.batch} complete — waiting for your approval to continue.`,
      });
    } else if (eventType === 'workflow_stopped') {
      setBatchApproval(null);
      addMessage({
        type: 'workflow_complete',
        content: data.message || 'Workflow stopped by user.',
        success: false,
      });
    } else if (eventType === 'workflow_complete') {
      const allOk = data.success;
      addMessage({
        type: 'workflow_complete',
        content: allOk
          ? 'All steps completed successfully!'
          : 'Agent finished with some failures.',
        success: allOk,
      });
    }
  };

  const handleRerunStep = async (
    stepNumber: number,
    inputOverride?: string,
    attachmentsOverride?: StoredAgentFile[],
  ) => {
    if (!workflow || isExecuting || rerunningStep !== null) return;
    const step = workflow.steps.find(s => s.step_number === stepNumber);
    if (!step) return;

    const previousInput = inputOverride ?? lastStepInputsRef.current[stepNumber];
    if (previousInput == null || !previousInput.trim()) {
      setError('Agent input cannot be empty.');
      return;
    }

    let agents = studioCatalog?.agents;
    if (!agents?.length) {
      try {
        const data = await withLoader('Loading catalog…', () => getAgents());
        agents = data.agents;
        setStudioCatalog(data);
      } catch {
        setError('Could not load the agent catalog. Check your connection and try again.');
        return;
      }
    }

    const wfCfg = buildAgentUserConfigsForWorkflowWithServerOverlay(
      [step],
      agents!,
      workflowStoredConfigsRef.current,
    );
    if (!wfCfg.ok) {
      const detail = wfCfg.missing
        .map((m) => `${m.agentName} — missing: ${m.missingKeys.join(', ')}`)
        .join('\n');
      setError(`Configure this agent first:\n\n${detail}`);
      return;
    }

    setRerunningStep(stepNumber);
    setError(null);
    setFollowUpQueue([]);
    if (chunkBufferRef.current[stepNumber]?.timer) {
      clearTimeout(chunkBufferRef.current[stepNumber].timer!);
    }
    delete chunkBufferRef.current[stepNumber];

    // Drop prior messages for this step so the rerun timeline is clean.
    setChatMessages(prev => prev.filter(m => m.stepNumber !== stepNumber));
    setWorkflow(prev => {
      if (!prev) return null;
      const steps = prev.steps.map(s =>
        s.step_number === stepNumber ? { ...s, status: 'pending' as const } : s
      );
      return { ...prev, steps, mermaid: regenerateMermaid(steps) };
    });

    addMessage({
      type: 'system',
      content: `Re-running step ${stepNumber} (${step.agent || step.agent_id}) with the previous input...`,
    });

    const extraKwargs = step.agent_id
      ? buildAgentExtraKwargsForAgents([step.agent_id])
      : {};

    const uploadPayload = storedFilesToUploadedFilesPayload(
      attachmentsOverride ?? stepPromptAttachments[stepNumber],
    );

    try {
      await executeWorkflowStepStream(
        {
          step: {
            step_number: step.step_number,
            agent_id: step.agent_id,
            agent: step.agent,
            agent_name: step.agent_name,
            ...(uploadPayload ? { uploaded_files: uploadPayload } : {}),
          },
          query: previousInput,
          agent_user_configs: wfCfg.configs,
          ...(Object.keys(extraKwargs).length ? { agent_extra_kwargs: extraKwargs } : {}),
        },
        processWorkflowStreamEvent,
      );
    } catch (e: any) {
      setError(e.message || 'Failed to re-run step');
      addMessage({
        type: 'system',
        content: `Re-run error: ${e.message || 'Unknown error'}`,
      });
    } finally {
      setRerunningStep(null);
    }
  };

  const handleExecute = async () => {
    if (!workflow) return;
    console.log('[Workflow] Execute clicked, workflow:', workflow.name, 'steps:', workflow.steps.length);

    let agents = studioCatalog?.agents;
    if (!agents?.length) {
      try {
        const data = await withLoader('Loading catalog…', () => getAgents());
        agents = data.agents;
        setStudioCatalog(data);
      } catch {
        setError('Could not load the agent catalog. Check your connection and try again.');
        return;
      }
    }

    const wfCfg = buildAgentUserConfigsForWorkflowWithServerOverlay(
      workflow.steps,
      agents!,
      workflowStoredConfigsRef.current,
    );
    if (!wfCfg.ok) {
      const detail = wfCfg.missing
        .map((m) => `${m.agentName} — missing: ${m.missingKeys.join(', ')}`)
        .join('\n');
      setError(
        `Configure these agents in the marketplace first (open the agent → Config tab, save settings in this browser):\n\n${detail}`,
      );
      return;
    }

    setIsExecuting(true);
    setError(null);
    setChatMessages([]);
    setFollowUpQueue([]);
    setBatchApproval(null);
    Object.values(chunkBufferRef.current).forEach(b => b.timer && clearTimeout(b.timer));
    chunkBufferRef.current = {};
    lastStepInputsRef.current = {};
    const updatedSteps = workflow.steps.map(s => ({ ...s, status: 'pending' as const }));
    const liveMermaid = regenerateMermaid(updatedSteps);
    setWorkflow({ ...workflow, steps: updatedSteps, mermaid: liveMermaid });
    setPipelineTab('diagram');

    addMessage({
      type: 'system',
      content: `Starting workflow "${workflow.name}" with ${workflow.steps.length} step${workflow.steps.length > 1 ? 's' : ''}...`,
    });

    const stepAgentIds = Array.from(new Set(workflow.steps.map((s) => s.agent_id).filter(Boolean) as string[]));
    const extraKwargs = buildAgentExtraKwargsForAgents(stepAgentIds);

    const stepsPayload = workflow.steps.map((s) => {
      const uploads = storedFilesToUploadedFilesPayload(stepPromptAttachments[s.step_number]);
      return {
        ...s,
        ...(uploads ? { uploaded_files: uploads } : {}),
      };
    });

    try {
      await executeWorkflowStream(
        {
          definition: { name: workflow.name, steps: stepsPayload },
          workflow_id: currentWorkflowIdRef.current,
          agent_user_configs: wfCfg.configs,
          step_mode: stepMode,
          ...(Object.keys(extraKwargs).length ? { agent_extra_kwargs: extraKwargs } : {}),
        },
        processWorkflowStreamEvent,
      );
    } catch (e: any) {
      setError(e.message || 'Failed to execute workflow');
      addMessage({
        type: 'system',
        content: `Execution error: ${e.message || 'Unknown error'}`,
      });
    } finally {
      setIsExecuting(false);
      const wfId = currentWorkflowIdRef.current;
      if (wfId && localStorage.getItem('admin_token')) {
        loadExecutions(wfId);
      }
    }
  };

  const currentFollowUp = followUpQueue.length > 0 ? followUpQueue[0] : null;

  const handleBatchContinue = async () => {
    if (!batchApproval || isSubmittingBatchApproval) return;
    setIsSubmittingBatchApproval(true);
    try {
      const payload = JSON.stringify({
        cmd: 'continue',
        overrides: batchApproval.nextStepInputs,
      });
      await submitWorkflowInput(batchApproval.executionId, -batchApproval.batchNum, payload);
      setBatchApproval(null);
      addMessage({ type: 'system', content: 'Continuing to next batch...' });
    } catch (e: any) {
      setError(e.message || 'Failed to continue');
    } finally {
      setIsSubmittingBatchApproval(false);
    }
  };

  const handleBatchStop = async () => {
    if (!batchApproval || isSubmittingBatchApproval) return;
    setIsSubmittingBatchApproval(true);
    try {
      await submitWorkflowInput(batchApproval.executionId, -batchApproval.batchNum, 'stop');
      setBatchApproval(null);
    } catch (e: any) {
      setError(e.message || 'Failed to stop');
    } finally {
      setIsSubmittingBatchApproval(false);
    }
  };

  const handleFollowUpSubmit = async () => {
    if (!currentFollowUp || !followUpInput.trim()) return;
    setIsSubmittingFollowUp(true);
    addMessage({
      type: 'user_reply',
      stepNumber: currentFollowUp.stepNumber,
      agentName: currentFollowUp.agentName,
      content: followUpInput,
    });
    try {
      await submitWorkflowInput(currentFollowUp.executionId, currentFollowUp.stepNumber, followUpInput);
      setFollowUpQueue(prev => prev.slice(1));
      setFollowUpInput('');
    } catch (e: any) {
      setError(e.message || 'Failed to submit response');
    } finally {
      setIsSubmittingFollowUp(false);
    }
  };

  const handleSave = async () => {
    if (!workflow || !isAuthenticated) return;
    setIsSaving(true);
    setError(null);
    try {
      const agentConfigs = getPersistedAgentConfigsForSave();
      const result = await withLoader('Saving workflow...', () => saveWorkflow({
        id: currentWorkflowId,
        name: workflow.name,
        instruction,
        definition: { name: workflow.name, steps: workflow.steps },
        mermaid_code: workflow.mermaid,
        ...(agentConfigs ? { agent_user_configs: agentConfigs } : {}),
      }));
      if (result?.id) setCurrentWorkflowId(result.id);
      if (agentConfigs) workflowStoredConfigsRef.current = agentConfigs;
      await loadSavedWorkflows();
    } catch (e: any) {
      setError(e.message || 'Failed to save workflow');
    } finally {
      setIsSaving(false);
    }
  };

  const handleReset = () => {
    workflowStoredConfigsRef.current = null;
    lastStepInputsRef.current = {};
    setStepPromptAttachments({});
    setInstruction('');
    setWorkflow(null);
    setChatMessages([]);
    setEditingStep(null);
    setError(null);
    setFollowUpQueue([]);
    setBatchApproval(null);
    setCurrentWorkflowId(undefined);
    setMemoryEnabled(false);
    setPipelineTab('steps');
    setExecutions([]);
    setSelectedExecution(null);
    lastLoadedRouteIdRef.current = undefined;
    if (routeWorkflowId) navigate('/agent-studio');
  };

  const handleLoadWorkflow = async (saved: SavedWorkflow) => {
    try {
      const needsCatalog = !studioCatalog?.agents?.length;
      const [full, catalogResult, executionsResult] = await withLoader(
        'Loading workflow details...',
        () =>
          Promise.all([
            getWorkflow(saved.id),
            needsCatalog ? getAgents().catch(() => null) : Promise.resolve(null),
            listWorkflowExecutions(saved.id).catch(() => null),
          ]),
      );
      const data = full.workflow || full;
      setInstruction(data.instruction || saved.instruction);
      setPipelineTab('steps');
      const def = data.definition || {};
      const loadedSteps = (def.steps || []).map((s: any) => ({
        ...s,
        agent: s.label || s.agent || s.agent_id || '',
        agent_id: s.agent_id || '',
        agent_name: s.agent_name || '',
        status: 'pending' as const,
      }));
      setCurrentWorkflowId(data.id || saved.id);
      setMemoryEnabled(Boolean(data.memory_enabled));
      setStepPromptAttachments({});
      setWorkflow({
        name: def.name || data.name || saved.name,
        steps: loadedSteps,
        mermaid: data.mermaid_code || '',
      });
      let agents = studioCatalog?.agents;
      if (!agents?.length && catalogResult) {
        agents = catalogResult.agents;
        setStudioCatalog(catalogResult);
      }
      workflowStoredConfigsRef.current =
        isAuthenticated && data.agent_user_configs && typeof data.agent_user_configs === 'object'
          ? data.agent_user_configs
          : null;
      if (isAuthenticated && data.agent_user_configs && agents?.length) {
        applyServerAgentConfigsToLocal(data.agent_user_configs, loadedSteps, agents);
        setWorkflowAgentConfigTick((t) => t + 1);
      }
      setChatMessages([]);
      setEditingStep(null);
      setError(null);
      setSelectedExecution(null);
      executionDetailCacheRef.current = {};
      lastStepInputsRef.current = {};
      setExecutions(isAuthenticated ? executionsResult?.executions || [] : []);
    } catch (e: any) {
      setError(e.message || 'Failed to load workflow');
    }
  };

  const handleDeleteWorkflow = async (id: string) => {
    if (!isAuthenticated) return;
    try {
      await withLoader('Deleting workflow...', () => deleteWorkflow(id));
      await loadSavedWorkflows();
    } catch {}
  };

  const handleDeleteExecution = async (exec: ExecutionSummary) => {
    if (!isAuthenticated || !currentWorkflowId) return;
    if (!window.confirm('Delete this run from history? This cannot be undone.')) return;
    try {
      await withLoader('Deleting run...', () => deleteWorkflowExecution(exec.id));
      delete executionDetailCacheRef.current[exec.id];
      setExecutions((prev) => prev.filter((e) => e.id !== exec.id));
      setSelectedExecution((sel) => (sel?.execution.id === exec.id ? null : sel));
      setExpandedHistoryMsg(null);
    } catch (e: any) {
      setError(e.message || 'Failed to delete run');
    }
  };

  const handleStepQueryChange = (stepIndex: number, newQuery: string) => {
    if (!workflow) return;
    const updated = [...workflow.steps];
    updated[stepIndex] = { ...updated[stepIndex], query: newQuery };
    setWorkflow({ ...workflow, steps: updated });
  };

  const regenerateMermaid = (steps: WorkflowStep[]): string => {
    if (steps.length === 0) {
      return [
        'flowchart TB',
        '  EMPTY["No steps defined — add a step to build the DAG"]',
        '  style EMPTY fill:#0f172a,stroke:#475569,stroke-width:1.5px,color:#94a3b8',
      ].join('\n');
    }

    const lines: string[] = [
      'flowchart TB',
      '  WFIngress([Workflow ingress])',
      '  subgraph WG["Multi-agent DAG · shared runtime context"]',
      '    direction TB',
    ];

    steps.forEach((s) => {
      const label = (s.agent || s.agent_id).replace(/"/g, "'").replace(/\[/g, '(').replace(/\]/g, ')');
      const agentName = (s.agent_name || s.agent_id || '').replace(/"/g, "'").replace(/\[/g, '(').replace(/\]/g, ')');
      const aid = (s.agent_id || '—').replace(/"/g, "'");
      const sub =
        agentName && agentName !== label
          ? `<br/>agent · ${agentName}`
          : `<br/>id · ${aid}`;
      lines.push(`    S${s.step_number}[["Step ${s.step_number} · ${label}${sub}"]]`);
    });

    steps.forEach((s) => {
      const mapping = s.input_mapping || {};
      (s.depends_on || []).forEach((d) => {
        let desc = mapping[`description_${d}`] || '';
        if (!desc && mapping['description'] && String(mapping['from_step']) === String(d)) {
          desc = mapping['description'];
        }
        if (desc) {
          const safeDesc = desc.replace(/"/g, "'").substring(0, 48);
          lines.push(`    S${d} -->|"${safeDesc}"| S${s.step_number}`);
        } else {
          lines.push(`    S${d} -->|"ctx: S${d}→S${s.step_number}"| S${s.step_number}`);
        }
      });
    });

    lines.push('  end');
    lines.push('  WFEgress([Workflow egress])');

    const hasOutgoing = new Set<number>();
    steps.forEach((s) => {
      (s.depends_on || []).forEach((d) => hasOutgoing.add(d));
    });
    const roots = steps.filter((s) => !(s.depends_on && s.depends_on.length)).map((s) => s.step_number);
    const sinks = steps.filter((s) => !hasOutgoing.has(s.step_number)).map((s) => s.step_number);

    roots.forEach((r) => lines.push(`  WFIngress -->|"enqueue"| S${r}`));
    sinks.forEach((n) => lines.push(`  S${n} -->|"emit"| WFEgress`));

    lines.push('  style WFIngress fill:#082f49,stroke:#38bdf8,stroke-width:2px,color:#e0f2fe');
    lines.push('  style WFEgress fill:#082f49,stroke:#38bdf8,stroke-width:2px,color:#e0f2fe');

    /** Execution-aware node styles (updates as SSE advances step_start / complete / failed). */
    steps.forEach((s) => {
      const st = s.status || 'pending';
      if (st === 'running') {
        lines.push(
          `  style S${s.step_number} fill:#152642,stroke:#60a5fa,stroke-width:2.5px,color:#eff6ff`,
        );
      } else if (st === 'completed') {
        lines.push(
          `  style S${s.step_number} fill:#0c1f14,stroke:#4ade80,stroke-width:2px,color:#ecfccb`,
        );
      } else if (st === 'failed') {
        lines.push(
          `  style S${s.step_number} fill:#1a080a,stroke:#f87171,stroke-width:2px,color:#fecdd3`,
        );
      } else {
        lines.push(
          `  style S${s.step_number} fill:#111827,stroke:#64748b,stroke-width:1.5px,color:#e2e8f0`,
        );
      }
    });

    return lines.join('\n');
  };

  const handleStepDependencyToggle = (stepIndex: number, depStepNum: number) => {
    if (!workflow) return;
    const updated = [...workflow.steps];
    const step = { ...updated[stepIndex] };
    const currentDeps = [...(step.depends_on || [])];
    const depIdx = currentDeps.indexOf(depStepNum);
    if (depIdx >= 0) {
      currentDeps.splice(depIdx, 1);
      const mapping = { ...(step.input_mapping || {}) };
      delete mapping[`from_step_${depStepNum}`];
      delete mapping[`description_${depStepNum}`];
      if (mapping.from_step !== undefined && Number(mapping.from_step) === depStepNum) {
        delete mapping.from_step;
        delete mapping.description;
      }
      step.input_mapping = Object.keys(mapping).length > 0 ? mapping : undefined;
      step.query = step.query.replace(new RegExp(`\\n*Use the following information from previous steps:\\nOutput from step ${depStepNum}:\\n\\{\\{step_${depStepNum}_output\\}\\}`, 'g'), '');
      step.query = step.query.replace(new RegExp(`\\n*Output from step ${depStepNum}:\\n\\{\\{step_${depStepNum}_output\\}\\}`, 'g'), '');
      step.query = step.query.replaceAll(`{{step_${depStepNum}_output}}`, '');
    } else {
      currentDeps.push(depStepNum);
      currentDeps.sort((a, b) => a - b);
      if (!step.query.includes(`{{step_${depStepNum}_output}}`)) {
        step.query = `${step.query}\n\nOutput from step ${depStepNum}:\n{{step_${depStepNum}_output}}`;
      }
    }
    step.depends_on = currentDeps;
    updated[stepIndex] = step;
    setWorkflow({ ...workflow, steps: updated, mermaid: regenerateMermaid(updated) });
  };

  const handleDeleteStep = (stepIndex: number) => {
    if (!workflow) return;
    const deletedStep = workflow.steps[stepIndex];
    const deletedNum = deletedStep.step_number;
    const remaining = workflow.steps.filter((_, i) => i !== stepIndex);
    const renumbered = remaining.map((s, i) => {
      const newNum = i + 1;
      const newDeps = (s.depends_on || [])
        .filter(d => d !== deletedNum)
        .map(d => d > deletedNum ? d - 1 : d);
      let newQuery = s.query;
      newQuery = newQuery.replace(new RegExp(`\\n*Use the following information from previous steps:\\nOutput from step ${deletedNum}:\\n\\{\\{step_${deletedNum}_output\\}\\}`, 'g'), '');
      newQuery = newQuery.replace(new RegExp(`\\n*Output from step ${deletedNum}:\\n\\{\\{step_${deletedNum}_output\\}\\}`, 'g'), '');
      newQuery = newQuery.replaceAll(`{{step_${deletedNum}_output}}`, '');
      for (let oldN = deletedNum + 1; oldN <= workflow.steps.length; oldN++) {
        const newN = oldN - 1;
        newQuery = newQuery.replaceAll(`{{step_${oldN}_output}}`, `{{step_${newN}_output}}`);
      }
      const newMapping: Record<string, string> = {};
      if (s.input_mapping) {
        Object.entries(s.input_mapping).forEach(([key, val]) => {
          if (key.includes(`_${deletedNum}`)) return;
          let newKey = key;
          for (let oldN = deletedNum + 1; oldN <= workflow.steps.length; oldN++) {
            newKey = newKey.replace(`_${oldN}`, `_${oldN - 1}`);
          }
          newMapping[newKey] = val;
        });
      }
      return {
        ...s,
        step_number: newNum,
        depends_on: newDeps,
        query: newQuery.trim(),
        input_mapping: Object.keys(newMapping).length > 0 ? newMapping : undefined,
      };
    });
    setStepPromptAttachments((prev) => remapStepPromptAttachments(prev, deletedNum));
    setWorkflow({ ...workflow, steps: renumbered, mermaid: regenerateMermaid(renumbered) });
    setEditingStep(null);
  };

  const handleInputMappingDescChange = (stepIndex: number, depStepNum: number, description: string) => {
    if (!workflow) return;
    const updated = [...workflow.steps];
    const step = { ...updated[stepIndex] };
    const mapping: Record<string, string> = { ...(step.input_mapping || {}) };
    mapping[`from_step_${depStepNum}`] = String(depStepNum);
    mapping[`description_${depStepNum}`] = description;
    step.input_mapping = mapping;
    updated[stepIndex] = step;
    setWorkflow({ ...workflow, steps: updated });
  };

  const handleDiagramStepClick = useCallback((stepNumber: number) => {
    setPipelineTab('steps');
    setStepModalStepNumber(stepNumber);
  }, []);

  const handleHarnessEdgeClick = useCallback((fromStep: number, toStep: number) => {
    setPromptHarnessEdge({ fromStep, toStep });
  }, []);

  const handleSavePromptHarness = useCallback(
    (cfg: PromptHarnessEdgeConfig | null) => {
      if (!workflow || !promptHarnessEdge) return;
      const idx = workflow.steps.findIndex((s) => s.step_number === promptHarnessEdge.toStep);
      if (idx < 0) return;
      const prevStep = workflow.steps[idx];
      const step = { ...prevStep };
      const key = String(promptHarnessEdge.fromStep);
      const nextMap: Record<string, PromptHarnessEdgeConfig> = { ...(step.prompt_harness || {}) };
      if (!cfg) {
        delete nextMap[key];
      } else {
        nextMap[key] = cfg;
      }
      if (Object.keys(nextMap).length === 0) {
        delete step.prompt_harness;
      } else {
        step.prompt_harness = nextMap;
      }
      const updated = [...workflow.steps];
      updated[idx] = step;
      setWorkflow({ ...workflow, steps: updated });
    },
    [workflow, promptHarnessEdge],
  );

  const harnessMergedAgentEnv = useMemo(() => {
    if (!workflow?.steps?.length || !studioCatalog?.agents?.length || !promptHarnessEdge) return {};
    const cfgs = buildAgentUserConfigsForWorkflowStorage(workflow.steps, studioCatalog.agents);
    const step = workflow.steps.find((s) => s.step_number === promptHarnessEdge.toStep);
    if (!step?.agent_id) return {};
    const row = cfgs[step.agent_id];
    return row ? { ...row } : {};
  }, [workflow?.steps, studioCatalog?.agents, promptHarnessEdge]);

  const harnessInitialConfig =
    workflow && promptHarnessEdge
      ? workflow.steps.find((s) => s.step_number === promptHarnessEdge.toStep)?.prompt_harness?.[
          String(promptHarnessEdge.fromStep)
        ]
      : undefined;

  const handleStepAttachmentChange = useCallback(async (stepNum: number, e: ChangeEvent<HTMLInputElement>) => {
    // Snapshot before clearing — `files` can be cleared in place when we reset value (live reference).
    const incoming = Array.from(e.target.files ?? []);
    e.target.value = '';
    if (!incoming.length) return;

    const sn = stepNum;
    const nextItems: StoredAgentFile[] = [];
    let skippedOversized = false;
    for (const file of incoming) {
      if (file.size > WORKFLOW_STEP_MAX_ATTACHMENT_BYTES) {
        skippedOversized = true;
        continue;
      }
      try {
        nextItems.push(await fileToStored(file));
      } catch {
        setError(`Could not read file "${file.name}".`);
        return;
      }
    }
    if (skippedOversized) {
      setError(
        `Skipped one or more files over ${WORKFLOW_STEP_MAX_ATTACHMENT_BYTES / (1024 * 1024)}MB (per-file limit).`,
      );
    }

    let hitCap = false;
    setStepPromptAttachments((prev) => {
      const cur = [...(prev[sn] ?? [])];
      for (const it of nextItems) {
        if (cur.length >= WORKFLOW_STEP_MAX_ATTACHMENTS) {
          hitCap = true;
          break;
        }
        cur.push(it);
      }
      return { ...prev, [sn]: cur };
    });

    if (hitCap) {
      setError(`At most ${WORKFLOW_STEP_MAX_ATTACHMENTS} attachments per step.`);
    } else if (!skippedOversized && nextItems.length > 0) {
      setError(null);
    }
  }, []);

  const removeStepPromptAttachment = useCallback((stepNum: number, fileIndex: number) => {
    setStepPromptAttachments((prev) => {
      const list = [...(prev[stepNum] ?? [])];
      list.splice(fileIndex, 1);
      if (!list.length) {
        const { [stepNum]: _removed, ...rest } = prev;
        return rest;
      }
      return { ...prev, [stepNum]: list };
    });
  }, []);

  const onRerunModalFilesPicked = useCallback(async (e: ChangeEvent<HTMLInputElement>) => {
    const incoming = Array.from(e.target.files ?? []);
    e.target.value = '';
    if (!incoming.length) return;

    const nextItems: StoredAgentFile[] = [];
    let skippedOversized = false;
    for (const file of incoming) {
      if (file.size > WORKFLOW_STEP_MAX_ATTACHMENT_BYTES) {
        skippedOversized = true;
        continue;
      }
      try {
        nextItems.push(await fileToStored(file));
      } catch {
        setError(`Could not read file "${file.name}".`);
        return;
      }
    }
    if (skippedOversized) {
      setError(
        `Skipped one or more files over ${WORKFLOW_STEP_MAX_ATTACHMENT_BYTES / (1024 * 1024)}MB (per-file limit).`,
      );
    }

    let hitCap = false;
    setRerunModal((prev) => {
      if (!prev) return prev;
      const cur = [...prev.attachments];
      for (const it of nextItems) {
        if (cur.length >= WORKFLOW_STEP_MAX_ATTACHMENTS) {
          hitCap = true;
          break;
        }
        cur.push(it);
      }
      return { ...prev, attachments: cur };
    });

    if (hitCap) {
      setError(`At most ${WORKFLOW_STEP_MAX_ATTACHMENTS} attachments per step.`);
    } else if (!skippedOversized && nextItems.length > 0) {
      setError(null);
    }
  }, []);

  const stepModalIndex =
    stepModalStepNumber !== null && workflow
      ? workflow.steps.findIndex((s) => s.step_number === stepModalStepNumber)
      : -1;
  const stepModal = stepModalIndex >= 0 && workflow ? workflow.steps[stepModalIndex] : null;
  const stepModalCatalogAgent = stepModal
    ? studioCatalog?.agents?.find((a) => a.id === stepModal.agent_id) ?? null
    : null;
  const stepModalConfigFields = stepModalCatalogAgent ? getConfigFields(stepModalCatalogAgent) : [];
  const stepModalConfigOk =
    !stepModalCatalogAgent || stepModalConfigFields.length === 0
      ? true
      : hasRequiredConfig(stepModalCatalogAgent, stepModalConfigFields);

  const openInlineEditorFromModal = useCallback(() => {
    if (!workflow || !stepModal) return;
    const idx = workflow.steps.findIndex((s) => s.step_number === stepModal.step_number);
    if (idx < 0) return;
    setPipelineTab('steps');
    setEditingStep(idx);
    setStepModalStepNumber(null);
    window.setTimeout(() => {
      document.getElementById(`workflow-step-card-${stepModal.step_number}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 0);
  }, [workflow, stepModal]);

  const renderStepPromptEditor = (
    step: WorkflowStep,
    stepIndex: number,
    attachmentScope: 'step-card' | 'step-modal' = 'step-card',
  ) => {
    const attachInputId = `workflow-step-attach-${attachmentScope}-${step.step_number}-${stepIndex}`;
    return (
    <div>
      <div className="mb-1.5 flex items-center gap-1.5">
        <Edit2 className="h-3 w-3 shrink-0 text-primary-400" />
        <span className="font-body text-[10px] font-semibold uppercase tracking-wide text-gray-600 dark:text-gray-400">Step prompt</span>
        <span className="truncate font-body text-[9px] text-gray-400 dark:text-gray-600">Instructions for this agent</span>
      </div>
      <textarea
        value={step.query}
        onChange={(e) => handleStepQueryChange(stepIndex, e.target.value)}
        rows={2}
        className="min-h-[4rem] w-full resize-y rounded-lg border border-gray-200 dark:border-white/[0.06] bg-black/20 px-3 py-2 font-body text-xs text-gray-200 transition-all placeholder:text-gray-600 focus:border-primary-500/40 focus:outline-none focus:ring-1 focus:ring-primary-500/10 sm:text-sm"
        placeholder="e.g. 'Research the latest market trends for AI startups and summarize key findings'"
      />
      <div className="mt-2 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <input
            id={attachInputId}
            type="file"
            multiple
            accept=".pdf,.doc,.docx,.txt,.md,.csv,.xlsx,.xls,.xlsm,.xltx,.xltm,.xlsb,.ods,.pptx,.ppt,.html,.htm,.json,.xml,.png,.jpg,.jpeg,.webp,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
            className="sr-only"
            onChange={(e) => void handleStepAttachmentChange(step.step_number, e)}
          />
          <label
            htmlFor={attachInputId}
            className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-gray-200 dark:border-white/[0.08] bg-white/[0.03] px-2.5 py-1 font-body text-[10px] font-medium text-gray-700 dark:text-gray-300 transition-colors hover:bg-white/[0.07]"
          >
            <Paperclip className="h-3 w-3 text-primary-400" />
            Attach files
          </label>
          <span className="font-body text-[9px] text-gray-400 dark:text-gray-600">
            Up to {WORKFLOW_STEP_MAX_ATTACHMENTS} · {WORKFLOW_STEP_MAX_ATTACHMENT_BYTES / (1024 * 1024)}MB each · sent with Run
          </span>
        </div>
        {(stepPromptAttachments[step.step_number]?.length ?? 0) > 0 && (
          <ul className="flex flex-wrap gap-2">
            {stepPromptAttachments[step.step_number]!.map((f, i) => (
              <li
                key={`${f.file_name}-${i}-${f.uploaded_at ?? i}`}
                className="group flex max-w-full items-center gap-1 rounded-lg border border-gray-200 dark:border-white/[0.08] bg-black/25 py-1 pl-2 pr-1"
              >
                <FileText className="h-3 w-3 shrink-0 text-primary-400/80" aria-hidden />
                <span className="min-w-0 truncate font-mono text-[10px] text-gray-700 dark:text-gray-300" title={f.file_name}>
                  {f.file_name}
                </span>
                <button
                  type="button"
                  onClick={() => removeStepPromptAttachment(step.step_number, i)}
                  className="shrink-0 rounded p-0.5 text-gray-400 dark:text-gray-600 transition-colors hover:bg-white/[0.08] hover:text-red-300"
                  title="Remove"
                  aria-label={`Remove ${f.file_name}`}
                >
                  <X className="h-3 w-3" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
    );
  };

  const renderStepKnowledgeBaseEditor = (step: WorkflowStep, stepIndex: number) => (
    <div className="rounded-lg border border-gray-200 dark:border-white/[0.04] bg-gray-50 dark:bg-black/15 p-2.5 sm:p-3">
      <div className="mb-1 flex items-center gap-1.5">
        <div className="flex h-5 w-5 items-center justify-center rounded-md bg-gradient-to-br from-blue-500/15 to-cyan-500/10 ring-1 ring-blue-500/10">
          <Database className="h-2.5 w-2.5 text-blue-400" />
        </div>
        <span className="font-body text-[11px] font-semibold text-gray-700 dark:text-gray-300">Knowledge Base</span>
        <span className="rounded bg-blue-500/10 px-1 py-0.5 font-body text-[8px] font-bold uppercase text-blue-400 ring-1 ring-blue-500/15">RAG</span>
      </div>
      <p className="mb-2 ml-6 font-body text-[9px] leading-snug text-gray-400 dark:text-gray-600 sm:ml-7">Optional vector index for retrieval before run</p>
      {kbIndexesLoading && !kbIndexesLoaded ? (
        <div className="flex items-center justify-center gap-2 py-4">
          <Loader2 className="h-4 w-4 animate-spin text-blue-400" />
          <span className="font-body text-xs text-gray-500">Loading indexes...</span>
        </div>
      ) : (
        <>
          {(() => {
            const kbComposite =
              step.kb_index?.enabled && step.kb_index.db_name
                ? `${step.kb_index.db_name}.${step.kb_index.collection}.${step.kb_index.index_name}`
                : '';
            const kbOptions = [...kbIndexes];
            if (kbComposite && !kbOptions.some((k) => k.label === kbComposite)) {
              const parsed = parseKbCompositeLabel(kbComposite);
              if (parsed) kbOptions.unshift(parsed);
            }
            kbOptions.sort((a, b) => a.label.localeCompare(b.label));
            return (
              <div className="flex min-w-0 items-center gap-2.5">
                <div
                  className="relative min-w-0 flex-1"
                  ref={kbPickerOpenIdx === stepIndex ? kbPickerRef : undefined}
                >
                  <button
                    type="button"
                    onClick={() => {
                      void loadKbIndexes();
                      setKbPickerOpenIdx((open) => (open === stepIndex ? null : stepIndex));
                    }}
                    className="flex w-full min-w-0 items-center gap-2 rounded-lg border border-gray-200 dark:border-white/[0.06] bg-black/20 px-3 py-2 text-left font-body text-xs text-gray-700 dark:text-gray-300 transition-all hover:border-blue-500/30 focus:border-blue-500/40 focus:outline-none focus:ring-1 focus:ring-blue-500/15"
                    aria-expanded={kbPickerOpenIdx === stepIndex}
                    aria-haspopup="listbox"
                  >
                    <span
                      className="min-w-0 flex-1 truncate font-mono text-[11px] leading-snug text-gray-200"
                      title={kbComposite || 'No KB index'}
                    >
                      {kbComposite ? formatKbShortLabel(kbComposite) : 'No KB index'}
                    </span>
                    <ChevronDown
                      className={`h-4 w-4 shrink-0 text-gray-500 transition-transform ${kbPickerOpenIdx === stepIndex ? 'rotate-180' : ''}`}
                      aria-hidden
                    />
                  </button>
                  {kbPickerOpenIdx === stepIndex && (
                    <div
                      role="listbox"
                      className="absolute left-0 right-0 top-full z-[100] mt-1 max-h-52 overflow-x-hidden overflow-y-auto rounded-lg border border-gray-200 dark:border-white/[0.1] bg-white dark:bg-zinc-950 py-1 shadow-[0_16px_40px_-12px_rgba(0,0,0,0.85)] ring-1 ring-black/40"
                    >
                      <button
                        type="button"
                        role="option"
                        aria-selected={!kbComposite}
                        className={`flex w-full px-3 py-2.5 text-left text-[11px] transition-colors ${!kbComposite ? 'bg-blue-500/15 text-blue-200' : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-white/[0.06]'}`}
                        onClick={() => {
                          handleStepKbIndexChange(stepIndex, '');
                          setKbPickerOpenIdx(null);
                        }}
                      >
                        No KB index
                      </button>
                      {kbOptions.length === 0 && (
                        <p className="px-3 py-2 text-[10px] leading-relaxed text-gray-500">
                          No vector indexes found. Add collections and indexes under{' '}
                          <span className="text-gray-600 dark:text-gray-400">Knowledge Base</span>.
                        </p>
                      )}
                      {kbOptions.map((ki) => (
                        <button
                          key={ki.label}
                          type="button"
                          role="option"
                          aria-selected={kbComposite === ki.label}
                          title={ki.label}
                          className={`flex w-full px-3 py-2.5 text-left font-mono text-[10px] leading-snug transition-colors ${kbComposite === ki.label ? 'bg-blue-500/15 text-blue-100' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/[0.06]'}`}
                          onClick={() => {
                            handleStepKbIndexChange(stepIndex, ki.label);
                            setKbPickerOpenIdx(null);
                          }}
                        >
                          <span className="break-all">{ki.label}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                {step.kb_index && step.kb_index.enabled && step.kb_index.db_name && (
                  <div className="flex shrink-0 items-center gap-1.5">
                    <label className="font-body text-[11px] text-gray-400 dark:text-gray-600">Top K</label>
                    <input
                      type="number"
                      min={1}
                      max={20}
                      value={step.kb_index.top_k}
                      onChange={(e) => handleStepKbTopKChange(stepIndex, Math.max(1, Math.min(20, parseInt(e.target.value) || 5)))}
                      className="w-12 rounded-lg border border-gray-200 dark:border-white/[0.06] bg-black/20 px-2 py-2 text-center font-body text-xs text-gray-700 dark:text-gray-300 transition-all focus:border-blue-500/40 focus:outline-none"
                    />
                  </div>
                )}
              </div>
            );
          })()}
          {step.kb_index && step.kb_index.enabled && step.kb_index.db_name && (
            <p className="mt-2.5 font-body text-[10px] leading-relaxed text-blue-400/40">
              Retrieves top {step.kb_index.top_k} chunks from <span className="text-blue-400/60">{step.kb_index.collection}</span> before execution
            </p>
          )}
        </>
      )}
    </div>
  );

  const getMsgIcon = (msg: ChatMessage) => {
    const shell = 'flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ring-1 bg-gradient-to-br';
    switch (msg.type) {
      case 'system':
        return <div className={`${shell} from-gray-700/50 to-gray-800/30 ring-white/[0.08]`}><Zap className="h-4 w-4 text-gray-700 dark:text-gray-300" /></div>;
      case 'agent_start':
      case 'agent_progress':
      case 'agent_streaming':
        return <div className={`${shell} from-blue-500/25 to-blue-600/10 ring-blue-500/25`}><Loader2 className="h-4 w-4 animate-spin text-blue-400" /></div>;
      case 'agent_thinking':
        return <div className={`${shell} from-teal-500/20 to-cyan-600/10 ring-teal-500/25`}><Activity className="h-4 w-4 text-teal-300" /></div>;
      case 'agent_input':
        return <div className={`${shell} from-violet-500/25 to-purple-600/10 ring-violet-500/25`}><FileText className="h-4 w-4 text-violet-300" /></div>;
      case 'agent_complete':
        return <div className={`${shell} from-emerald-500/25 to-green-600/10 ring-emerald-500/25`}><CheckCircle className="h-4 w-4 text-emerald-400" /></div>;
      case 'agent_failed':
        return <div className={`${shell} from-red-500/25 to-red-900/20 ring-red-500/25`}><AlertCircle className="h-4 w-4 text-red-400" /></div>;
      case 'needs_input':
        return <div className={`${shell} from-amber-500/25 to-yellow-600/10 ring-amber-500/25`}><MessageSquare className="h-4 w-4 text-amber-300" /></div>;
      case 'user_reply':
        return <div className={`${shell} from-primary-500/30 to-primary-600/10 ring-primary-500/25`}><User className="h-4 w-4 text-primary-300" /></div>;
      case 'workflow_complete':
        return <div className={`${shell} from-emerald-500/25 to-green-600/10 ring-emerald-500/25`}><CheckCircle className="h-4 w-4 text-emerald-400" /></div>;
    }
  };

  const getExecutionLogTag = (msg: ChatMessage): { text: string; className: string } => {
    switch (msg.type) {
      case 'system':
        return { text: 'System', className: 'bg-slate-500/12 text-slate-400 ring-slate-500/20' };
      case 'agent_start':
      case 'agent_progress':
        return { text: 'Progress', className: 'bg-blue-500/12 text-blue-400 ring-blue-500/20' };
      case 'agent_thinking':
        return { text: 'Live step', className: 'bg-teal-500/12 text-teal-300 ring-teal-500/22' };
      case 'agent_streaming':
        return { text: 'Streaming', className: 'bg-sky-500/12 text-sky-400 ring-sky-500/20' };
      case 'agent_input':
        return { text: 'Input', className: 'bg-violet-500/12 text-violet-300 ring-violet-500/20' };
      case 'agent_complete':
        return { text: 'Output', className: 'bg-emerald-500/12 text-emerald-400 ring-emerald-500/20' };
      case 'agent_failed':
        return { text: 'Error', className: 'bg-red-500/12 text-red-400 ring-red-500/20' };
      case 'needs_input':
        return { text: 'Question', className: 'bg-amber-500/12 text-amber-400 ring-amber-500/20' };
      case 'user_reply':
        return { text: 'You', className: 'bg-primary-500/12 text-primary-400 ring-primary-500/20' };
      case 'workflow_complete':
        return { text: msg.success ? 'Complete' : 'Finished', className: msg.success ? 'bg-emerald-500/12 text-emerald-400 ring-emerald-500/20' : 'bg-red-500/12 text-red-400 ring-red-500/20' };
      default:
        return { text: 'Event', className: 'bg-gray-500/12 text-gray-600 dark:text-gray-400 ring-gray-500/20' };
    }
  };

  const studioExplainerSteps = [
    {
      step: 1,
      shortLabel: 'Describe',
      title: 'Say what you need—in your own words',
      body: 'Type a short description of the job (for example: “compare three vendors and email me a table”). No code, no special format.',
      icon: MessageSquare,
    },
    {
      step: 2,
      shortLabel: 'Draft',
      title: 'We sketch the agent for you',
      body: 'Agent Studio turns your description into a step-by-step plan, picks specialist agents from the catalog, and draws a flow you can read.',
      icon: Wand2,
    },
    {
      step: 3,
      shortLabel: 'Tune',
      title: 'Adjust only if you want to',
      body: 'Rename steps, attach documents or knowledge bases, or fix details—everything stays optional until you are happy.',
      icon: SlidersHorizontal,
    },
    {
      step: 4,
      shortLabel: 'Run',
      title: 'Run and watch it work',
      body: 'Press Run to execute. You will see live progress and can answer questions if an agent needs more input.',
      icon: Play,
    },
  ] as const;

  const studioHowPipelineAccent = [
    'from-violet-500/35 to-violet-800/20 ring-violet-400/45 text-violet-50',
    'from-primary-500/35 to-primary-800/18 ring-primary-400/40 text-primary-50',
    'from-fuchsia-500/30 to-fuchsia-900/18 ring-fuchsia-400/38 text-fuchsia-50',
    'from-emerald-500/32 to-emerald-900/18 ring-emerald-400/42 text-emerald-50',
  ] as const;

  const missionSuggestionExamples = [
    'Summarize savings vs money-market vs CD products for a one-page retail branch training sheet',
    'Draft board-ready talking points on commercial real estate concentration and mitigations',
    "Research peer banks' mobile deposit limits and fees; produce a competitive brief with three recommendations",
    'Build a middle-market loan covenant monitoring checklist and flag items that need legal or credit review',
    'Generate a BRD for retail KYC / identity refresh, then create JIRA tickets per requirement with compliance tags',
    'AML assessment for a new correspondent banking partner: red-flag scenarios, escalation playbook, and internal audit interview questions',
  ] as const;

  return (
    <div className="relative mx-auto max-w-[1600px] overflow-x-hidden px-4 py-8 sm:px-6 lg:px-10 lg:py-10">
      <input
        ref={rerunFileInputRef}
        type="file"
        className="sr-only"
        tabIndex={-1}
        multiple
        accept=".pdf,.doc,.docx,.txt,.md,.csv,.xlsx,.xls,.pptx,.ppt,.html,.htm,.json,.xml,.png,.jpg,.jpeg,.webp"
        onChange={onRerunModalFilesPicked}
        aria-hidden
      />
      <div className="pointer-events-none absolute inset-0 -z-10 opacity-[0.4]" aria-hidden>
        <div
          className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.028)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.028)_1px,transparent_1px)] bg-[length:56px_56px] [mask-image:linear-gradient(to_bottom,black_0%,black_35%,transparent_85%)]"
        />
        {/* Keep glow inside the scroll width: positive translate-x was pushing past the viewport */}
        <div className="absolute right-0 top-0 h-[min(50vh,420px)] w-[min(90vw,520px)] -translate-y-1/4 translate-x-0 rounded-full bg-primary-600/[0.07] blur-[100px]" />
      </div>

      <header className="mb-8 lg:mb-10" aria-labelledby="agent-studio-heading">
        <div className="relative overflow-hidden rounded-3xl border border-gray-200 dark:border-white/[0.08] bg-gradient-to-b from-zinc-900/95 via-zinc-950/98 to-zinc-950 shadow-[0_24px_80px_-32px_rgba(0,0,0,0.85)] ring-1 ring-white/[0.05]">
          <div className="pointer-events-none absolute -left-24 top-1/2 h-56 w-56 -translate-y-1/2 rounded-full bg-violet-600/[0.08] blur-[100px]" aria-hidden />
          <div className="pointer-events-none absolute -right-16 top-0 h-48 w-48 rounded-full bg-primary-500/[0.09] blur-[90px]" aria-hidden />
          <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/12 to-transparent" aria-hidden />

          <div className="relative p-6 sm:p-8 lg:p-10">
            <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between lg:gap-10">
              <div className="min-w-0 flex-1 space-y-5">
                <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:gap-6">
                  <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-amber-400/25 via-primary-500/30 to-violet-600/25 shadow-lg shadow-primary-950/40 ring-1 ring-white/10">
                    <Sparkles className="h-7 w-7 text-amber-100/90" strokeWidth={1.5} />
                  </div>
                  <div className="min-w-0 space-y-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-full border border-primary-500/25 bg-primary-500/[0.1] px-3 py-1 font-body text-[10px] font-bold uppercase tracking-[0.16em] text-primary-200/95">
                        Your words → your agent
                      </span>
                      {activeView === 'builder' && workflow && (
                        <span className="rounded-full bg-emerald-500/10 px-2.5 py-1 font-body text-[10px] font-semibold text-emerald-300/90 ring-1 ring-emerald-500/25">
                          Ready to run
                        </span>
                      )}
                    </div>
                    <div>
                      <h1
                        id="agent-studio-heading"
                        className="font-heading text-3xl font-bold tracking-[-0.02em] text-gray-900 dark:text-white sm:text-4xl lg:text-[2.25rem] lg:leading-tight"
                      >
                        <span className="bg-gradient-to-br from-white via-zinc-100 to-zinc-400 bg-clip-text text-transparent">
                          Agent Studio
                        </span>
                      </h1>
                      <p className="mt-3 max-w-2xl text-pretty font-body text-base leading-relaxed text-zinc-400 sm:text-[1.05rem]">
                        You do not need to code. Describe what you want done in everyday language—Agent Studio builds a multi-step agent
                        for you, using specialists from the catalog. Adjust details if you like, then run it and follow along live.
                      </p>
                    </div>
                    <ul className="grid gap-2.5 sm:max-w-2xl sm:grid-cols-1">
                      {[
                        'Write your goal in normal sentences; we turn it into steps and a flow diagram.',
                        'Specialist agents are chosen for you—you can rename or reorder later.',
                        'Add files or knowledge bases when you need the agent to use your data.',
                      ].map((line) => (
                        <li key={line} className="flex gap-3 font-body text-sm leading-relaxed text-zinc-300">
                          <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 ring-1 ring-emerald-500/25">
                            <CheckCircle className="h-3 w-3 text-emerald-400" strokeWidth={2.5} aria-hidden />
                          </span>
                          <span>{line}</span>
                        </li>
                      ))}
                    </ul>
                    {!isAuthenticated ? (
                      <div className="rounded-2xl border border-gray-200 dark:border-white/[0.08] bg-white/[0.03] p-4 ring-1 ring-white/[0.04] sm:p-5">
                        <p className="font-body text-sm leading-relaxed text-zinc-300">
                          <span className="font-semibold text-gray-900 dark:text-white">Try it without an account.</span>{' '}
                          You can generate and run agents in this browser session right away.
                        </p>
                        <p className="mt-2 font-body text-sm leading-relaxed text-zinc-500">
                          <Link to="/admin/login" className="font-semibold text-primary-400 underline-offset-2 hover:underline">
                            Sign in
                          </Link>{' '}
                          when you want to save agents under <span className="font-medium text-zinc-400">My agents</span> and open them again later.
                        </p>
                      </div>
                    ) : null}
                    {activeView === 'builder' ? (
                      <div className="mt-4">
                        <button
                          type="button"
                          disabled={isSharedWorkflowRunMode}
                          onClick={focusMissionTextarea}
                          className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-primary-500 to-violet-600 px-5 py-2.5 font-body text-sm font-semibold text-gray-900 dark:text-white shadow-lg shadow-primary-950/40 transition-all hover:from-primary-400 hover:to-violet-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400/50 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950 disabled:cursor-not-allowed disabled:from-zinc-800 disabled:to-zinc-800 disabled:text-zinc-500 disabled:shadow-none"
                          title={isSharedWorkflowRunMode ? 'Generation is disabled for shared links' : 'Start writing your mission'}
                          aria-controls="workflows-mission-input"
                        >
                          <PenLine className="h-4 w-4" strokeWidth={2} />
                          Get started
                        </button>
                      </div>
                    ) : null}
                  </div>
                </div>
              </div>

              <div className="flex w-full min-w-0 shrink-0 flex-col gap-4 lg:max-w-[min(34rem,100%)] xl:max-w-[min(42rem,100%)]">
                <div className="flex items-start gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-500/25 to-primary-500/15 ring-1 ring-white/10">
                    <LayoutGrid className="h-[18px] w-[18px] text-violet-200/95" strokeWidth={2} aria-hidden />
                  </div>
                  <div className="min-w-0 pt-0.5">
                    <p className="font-body text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-500">How it works</p>
                    <p className="mt-1 font-body text-xs leading-snug text-zinc-400">
                      Plain language in, a live multi-step agent out—sketched for you, editable anytime.
                    </p>
                  </div>
                </div>

                <div className="relative overflow-hidden rounded-2xl border border-gray-200 dark:border-white/[0.08] bg-gradient-to-br from-violet-500/[0.14] via-zinc-950/80 to-primary-500/[0.1] p-3.5 ring-1 ring-white/[0.06] shadow-[inset_0_1px_0_0_rgba(255,255,255,0.06)] sm:p-4">
                  <div
                    className="studio-how-deco-orbit pointer-events-none absolute -right-8 -top-8 h-[8.5rem] w-[8.5rem] rounded-full border border-dashed border-gray-200 dark:border-white/[0.08]"
                    aria-hidden
                  />
                  <div
                    className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_75%_55%_at_50%_-10%,rgba(139,92,246,0.14),transparent_60%)]"
                    aria-hidden
                  />
                  <p className="relative mb-3 text-center font-body text-[9px] font-semibold uppercase tracking-[0.22em] text-zinc-500">
                    Flow at a glance
                  </p>
                  <div className="relative flex items-end justify-between gap-0.5 sm:gap-1">
                    {studioExplainerSteps.map(({ step, icon: Icon, shortLabel }, i) => {
                      const accent = studioHowPipelineAccent[i]!;
                      return (
                        <Fragment key={step}>
                          <div
                            className="studio-how-pipeline-node flex min-w-0 flex-1 flex-col items-center gap-1.5"
                            style={{ animationDelay: `${(step - 1) * 0.42}s` }}
                          >
                            <div
                              className={`relative flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br shadow-md ring-2 ring-offset-[3px] ring-offset-zinc-950/95 sm:h-10 sm:w-10 ${accent}`}
                            >
                              <Icon className="h-[15px] w-[15px] drop-shadow sm:h-[17px] sm:w-[17px]" strokeWidth={2} aria-hidden />
                            </div>
                            <span className="text-center font-body text-[8px] font-semibold uppercase leading-tight tracking-wide text-zinc-300 sm:text-[9px]">
                              {shortLabel}
                            </span>
                          </div>
                          {i < studioExplainerSteps.length - 1 ? (
                            <div
                              className="studio-how-link mb-6 h-[3px] min-w-[2px] flex-[0.4] rounded-full bg-gradient-to-r from-violet-400/70 via-primary-400/55 to-fuchsia-400/65 sm:mb-7"
                              style={{ animationDelay: `${(step - 1) * 0.42 + 0.2}s` }}
                              aria-hidden
                            />
                          ) : null}
                        </Fragment>
                      );
                    })}
                  </div>
                </div>

                <div className="relative">
                  <div
                    className="pointer-events-none absolute left-5 top-9 bottom-9 w-px bg-gradient-to-b from-violet-500/60 via-primary-500/35 to-emerald-500/55"
                    aria-hidden
                  />
                  <ol className="relative space-y-0" aria-label="Steps to build an agent">
                    {studioExplainerSteps.map(({ step, title, body, icon: Icon }) => (
                      <li
                        key={step}
                        className="studio-how-step-card group relative flex gap-3.5 pb-5 last:pb-0"
                      >
                        <div className="relative z-10 shrink-0">
                          <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-gray-200 dark:border-white/[0.1] bg-white dark:bg-zinc-950/85 shadow-inner ring-2 ring-violet-500/25 transition-all duration-300 group-hover:border-white/[0.14] group-hover:ring-primary-400/40 group-hover:shadow-[0_0_22px_-8px_rgba(139,92,246,0.5)]">
                            <Icon className="h-4 w-4 text-zinc-100" strokeWidth={1.85} aria-hidden />
                          </div>
                        </div>
                        <div className="min-w-0 flex-1 rounded-2xl border border-gray-200 dark:border-white/[0.07] bg-gray-50 dark:bg-white/[0.025] p-3.5 ring-1 ring-white/[0.04] transition-all duration-300 group-hover:border-white/[0.11] group-hover:bg-white/[0.045] sm:p-4">
                          <div className="flex flex-wrap items-baseline gap-2">
                            <span className="font-mono text-[10px] font-bold tabular-nums text-zinc-500">0{step}</span>
                            <span className="font-heading text-sm font-semibold text-gray-900 dark:text-white">{title}</span>
                          </div>
                          <p className="mt-1.5 font-body text-xs leading-relaxed text-zinc-500 sm:text-[0.8125rem]">{body}</p>
                        </div>
                      </li>
                    ))}
                  </ol>
                </div>
              </div>
            </div>
          </div>
        </div>
      </header>

      <nav
        className="mb-8 inline-flex rounded-2xl border border-gray-200 dark:border-white/[0.06] bg-zinc-950/70 p-1 shadow-[0_16px_48px_-24px_rgba(0,0,0,0.85)] ring-1 ring-white/[0.04] backdrop-blur-xl"
        aria-label="Studio views"
      >
        <button
          type="button"
          onClick={() => setActiveView('builder')}
          className={`relative flex items-center gap-2 rounded-xl px-5 py-2.5 font-body text-sm font-semibold transition-all duration-200 ${
            activeView === 'builder'
              ? 'bg-white/[0.1] text-gray-900 dark:text-white shadow-inner ring-1 ring-white/10'
              : 'text-zinc-500 hover:text-zinc-200'
          }`}
        >
          <Zap className="h-4 w-4 shrink-0 text-amber-400/90" />
          Builder
          <span
            className={`hidden text-[10px] font-semibold uppercase tracking-wider sm:inline ${
              activeView === 'builder' ? 'text-primary-300/70' : 'text-zinc-600'
            }`}
          >
            Design
          </span>
        </button>
        <button
          type="button"
          disabled={!isAuthenticated}
          onClick={() => {
            if (!isAuthenticated) return;
            setActiveView('library');
            void loadSavedWorkflows();
          }}
          className={`relative flex items-center gap-2 rounded-xl px-5 py-2.5 font-body text-sm font-semibold transition-all duration-200 ${
            activeView === 'library'
              ? 'bg-white/[0.1] text-gray-900 dark:text-white shadow-inner ring-1 ring-white/10'
              : 'text-zinc-500 hover:text-zinc-200'
          } ${!isAuthenticated ? 'cursor-not-allowed opacity-45 hover:text-zinc-500' : ''}`}
          title={isAuthenticated ? 'Saved workflows' : 'Sign in to open My agents'}
        >
          <LayoutGrid className="h-4 w-4 shrink-0 text-violet-400/80" />
          My agents
          {isAuthenticated && savedWorkflows.length > 0 && (
            <span className="rounded-md bg-white/[0.08] px-1.5 py-0.5 font-mono text-[11px] font-bold text-zinc-300 ring-1 ring-white/[0.08]">
              {savedWorkflows.length}
            </span>
          )}
        </button>
      </nav>

      {error && (
        <div
          role="alert"
          className="mb-6 flex items-start gap-4 rounded-2xl border border-red-500/20 bg-red-500/[0.05] p-4 ring-1 ring-red-500/10 backdrop-blur-sm"
        >
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-red-500/15 ring-1 ring-red-500/25">
            <AlertCircle className="h-5 w-5 text-red-400" />
          </div>
          <p className="min-w-0 flex-1 whitespace-pre-wrap font-body text-sm leading-relaxed text-red-200/90">{error}</p>
          <button
            type="button"
            onClick={() => setError(null)}
            className="shrink-0 rounded-lg p-1.5 text-red-400/70 transition-colors hover:bg-red-500/15 hover:text-red-300"
            aria-label="Dismiss error"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* ===== LIBRARY VIEW ===== */}
      {activeView === 'library' && (
        <div>
          {savedWorkflows.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-3xl border border-dashed border-gray-200 dark:border-white/[0.08] bg-zinc-950/40 py-20 text-center ring-1 ring-white/[0.04]">
              <div className="mb-6 flex h-20 w-20 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-500/15 to-primary-600/10 ring-1 ring-white/10">
                <LayoutGrid className="h-9 w-9 text-zinc-500" strokeWidth={1.25} />
              </div>
              <p className="mb-2 font-heading text-lg font-semibold text-zinc-200">No saved agents yet</p>
              <p className="max-w-md px-4 font-body text-sm leading-relaxed text-zinc-500">
                Your agents will appear here. Build one in <span className="font-medium text-zinc-400">Builder</span>, then use{' '}
                <span className="font-medium text-zinc-400">Save</span> to add it to My agents.
              </p>
              <button
                type="button"
                onClick={() => setActiveView('builder')}
                className="mt-8 inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-primary-500 to-violet-600 px-6 py-3 font-body text-sm font-semibold text-gray-900 dark:text-white shadow-lg shadow-primary-950/35 transition-all hover:from-primary-400 hover:to-violet-500"
              >
                <Zap className="h-4 w-4" />
                Open builder
              </button>
            </div>
          ) : (
            <>
              <p className="mb-6 max-w-2xl font-body text-sm leading-relaxed text-zinc-500">
                Open any card to load it in the builder. From there you can edit steps, run again, or remove the saved agent.
              </p>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                {savedWorkflows.map((saved) => {
                  const steps = saved.definition?.steps ?? [];
                  const n = steps.length;
                  return (
                    <div
                      key={saved.id}
                      className="group relative"
                    >
                      {/* Glow effect layer */}
                      <div className="pointer-events-none absolute -inset-px rounded-2xl opacity-0 transition-opacity duration-500 group-hover:opacity-100 bg-gradient-to-br from-primary-500/20 via-violet-500/10 to-transparent blur-sm" />

                      <div className="relative overflow-hidden rounded-2xl border border-gray-200 dark:border-white/[0.08] bg-[#0d0d12] shadow-[0_1px_0_0_rgba(255,255,255,0.04)_inset,0_4px_32px_-4px_rgba(0,0,0,0.6)] transition-all duration-300 group-hover:border-white/[0.13] group-hover:shadow-[0_8px_40px_-8px_rgba(99,102,241,0.2)] group-hover:-translate-y-0.5">

                        {/* Top shimmer line */}
                        <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/[0.10] to-transparent" />
                        {/* Hover top accent */}
                        <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-primary-400/70 to-transparent opacity-0 transition-opacity duration-500 group-hover:opacity-100" />
                        {/* Ambient orb top-right */}
                        <div className="pointer-events-none absolute -right-8 -top-16 h-40 w-40 rounded-full bg-primary-500/[0.08] blur-3xl transition-opacity duration-500 opacity-60 group-hover:opacity-100" />

                        <button
                          type="button"
                          onClick={() => { navigate(`/agent-studio/${saved.id}`); setActiveView('builder'); }}
                          className="relative flex w-full flex-col text-left px-5 pt-5 pb-5 sm:px-6 sm:pt-5"
                        >
                          {/* Header row */}
                          <div className="flex items-start gap-3.5">
                            {/* Icon */}
                            <div className="relative shrink-0 mt-0.5">
                              <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-primary-500/20 via-violet-600/10 to-transparent ring-1 ring-white/[0.10] transition-all duration-300 group-hover:ring-primary-400/30 group-hover:from-primary-500/28">
                                <Bot className="h-5 w-5 text-primary-300" strokeWidth={1.75} />
                              </div>
                              <span className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full bg-emerald-400 ring-2 ring-[#0d0d12]" title="Saved" />
                            </div>

                            {/* Meta + title */}
                            <div className="min-w-0 flex-1">
                              <div className="mb-2 flex flex-wrap items-center gap-1.5">
                                <span className="inline-flex items-center gap-1 rounded-md bg-primary-500/[0.12] px-2 py-0.5 font-body text-[10px] font-semibold uppercase tracking-widest text-primary-300/90 ring-1 ring-primary-500/20">
                                  <Zap className="h-2.5 w-2.5" strokeWidth={2.5} />
                                  Agent
                                </span>
                                {n > 0 && (
                                  <span className="inline-flex items-center gap-1 rounded-md bg-white/[0.05] px-2 py-0.5 font-body text-[10px] font-medium text-zinc-400 ring-1 ring-white/[0.07]">
                                    <Users className="h-2.5 w-2.5 text-zinc-500" strokeWidth={2} />
                                    {n} step{n !== 1 ? 's' : ''}
                                  </span>
                                )}
                                {saved.created_at && (
                                  <span className="ml-auto inline-flex items-center gap-1 font-body text-[10px] tabular-nums text-zinc-600">
                                    <Calendar className="h-2.5 w-2.5" strokeWidth={2} />
                                    {formatDate(saved.created_at)}
                                  </span>
                                )}
                              </div>
                              <h4 className="font-heading text-[15px] font-semibold leading-snug tracking-tight text-gray-900 dark:text-white/95 line-clamp-2">
                                {saved.name}
                              </h4>
                            </div>
                          </div>

                          {/* Description */}
                          <p className="mt-3 flex items-start gap-2 font-body text-[11.5px] leading-relaxed text-zinc-500 line-clamp-2 pl-[3.25rem]">
                            <span>
                              {saved.instruction || (
                                <span className="italic text-zinc-600">No mission description yet.</span>
                              )}
                            </span>
                          </p>

                          {/* Pipeline */}
                          {n > 0 && (
                            <div className="mt-4 border-t border-gray-200 dark:border-white/[0.05] pt-3.5">
                              <p className="mb-2 font-body text-[9.5px] font-bold uppercase tracking-[0.18em] text-zinc-600">
                                Pipeline
                              </p>
                              <div className="flex flex-wrap items-center gap-1.5">
                                {steps.slice(0, 4).map((s, i) => (
                                  <Fragment key={i}>
                                    {i > 0 && (
                                      <ChevronRight className="h-2.5 w-2.5 shrink-0 text-zinc-700" aria-hidden strokeWidth={2.5} />
                                    )}
                                    <span
                                      className="max-w-[130px] truncate rounded-md bg-gray-100 dark:bg-white/[0.04] px-2.5 py-1 font-body text-[10px] font-medium text-zinc-400 ring-1 ring-white/[0.06] transition-colors duration-200 group-hover:text-zinc-300 group-hover:ring-primary-500/20 group-hover:bg-primary-500/[0.06]"
                                      title={s.agent}
                                    >
                                      {s.agent}
                                    </span>
                                  </Fragment>
                                ))}
                                {n > 4 && (
                                  <span className="rounded-md bg-white/[0.03] px-2 py-1 font-body text-[10px] font-medium text-zinc-600 ring-1 ring-white/[0.05]">
                                    +{n - 4}
                                  </span>
                                )}
                              </div>
                            </div>
                          )}
                        </button>

                        {/* Delete button */}
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); handleDeleteWorkflow(saved.id); }}
                          className="absolute right-3 top-3 z-10 rounded-lg p-1.5 text-zinc-600 opacity-0 transition-all duration-200 hover:bg-red-500/12 hover:text-red-400 group-hover:opacity-100"
                          title="Delete agent"
                        >
                          <Trash2 className="h-3.5 w-3.5" strokeWidth={2} />
                        </button>

                        {/* Arrow indicator */}
                        <div
                          className="pointer-events-none absolute bottom-4 right-4 flex h-7 w-7 items-center justify-center rounded-lg bg-white/[0.05] text-zinc-500 opacity-0 ring-1 ring-white/[0.07] transition-all duration-300 group-hover:opacity-100 group-hover:text-primary-300 group-hover:bg-primary-500/[0.08] group-hover:ring-primary-500/20"
                          aria-hidden
                        >
                          <ChevronRight className="h-4 w-4" strokeWidth={2.5} />
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>
      )}

      {/* ===== BUILDER VIEW ===== */}
      {activeView === 'builder' && (
        <>

      {/* Mission composer */}
      <div className="relative mb-8">
        <div className="relative overflow-hidden rounded-3xl border border-gray-200 dark:border-white/[0.08] bg-zinc-900/40 shadow-[0_20px_60px_-28px_rgba(0,0,0,0.65)] ring-1 ring-white/[0.04] backdrop-blur-xl">
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-primary-500/[0.06] via-transparent to-violet-600/[0.04]" />
          <div className="relative p-5 sm:p-6">
            <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="flex items-start gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary-500/25 to-violet-600/20 ring-1 ring-primary-500/25">
                  <SlidersHorizontal className="h-5 w-5 text-primary-300" />
                </div>
                <div>
                  <span className="font-body text-sm font-semibold text-zinc-200">Mission</span>
                  <p className="mt-0.5 max-w-xl font-body text-xs leading-relaxed text-zinc-500">
                    Describe the outcome. The model proposes sub-agents, ordering, and data handoffs—you stay in control before you run.
                  </p>
                </div>
              </div>
              {workflow && (
                <button
                  type="button"
                  onClick={handleReset}
                  className="inline-flex shrink-0 items-center gap-1.5 rounded-xl border border-gray-200 dark:border-white/[0.06] bg-white/[0.03] px-3 py-2 font-body text-xs font-medium text-zinc-400 transition-all hover:border-white/[0.1] hover:bg-gray-100 dark:hover:bg-white/[0.06] hover:text-zinc-200"
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                  New agent
                </button>
              )}
            </div>

            {!workflow && !isGenerating && (
              <div
                className="relative mb-4 overflow-hidden rounded-2xl border border-gray-200 dark:border-white/[0.07] bg-gray-50 dark:bg-zinc-950/35 shadow-[inset_0_1px_0_0_rgba(255,255,255,0.05),0_1px_0_0_rgba(255,255,255,0.02)] backdrop-blur-md"
                role="region"
                aria-labelledby="mission-suggestions-heading"
              >
                <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-violet-500/[0.07] via-transparent to-fuchsia-600/[0.04]" aria-hidden />
                <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/15 to-transparent" aria-hidden />
                <div className="relative px-4 py-4 sm:px-5 sm:py-5">
                  <div className="mb-4 flex flex-col gap-3 sm:mb-5 sm:flex-row sm:items-center sm:justify-between">
                    <div className="flex items-start gap-3.5">
                      <div className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-500/30 via-violet-600/15 to-fuchsia-600/20 shadow-[0_12px_40px_-16px_rgba(139,92,246,0.55)] ring-1 ring-white/10">
                        <Sparkles className="h-[18px] w-[18px] text-violet-100" strokeWidth={2} />
                      </div>
                      <div className="min-w-0 space-y-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3
                            id="mission-suggestions-heading"
                            className="font-body text-sm font-semibold tracking-tight text-zinc-100"
                          >
                            Suggestions
                          </h3>
                          <span className="rounded-full border border-gray-200 dark:border-white/[0.08] bg-gray-100 dark:bg-white/[0.04] px-2 py-0.5 font-body text-[10px] font-medium uppercase tracking-widest text-zinc-500">
                            Quick fill
                          </span>
                        </div>
                        <p className="max-w-2xl font-body text-xs leading-relaxed text-zinc-500">
                          Choose a starter mission to load below—tweak the wording, then hit Generate when you are ready.
                        </p>
                      </div>
                    </div>
                  </div>
                  <ul className="grid list-none gap-3 sm:grid-cols-3 sm:gap-3.5" role="list">
                    {missionSuggestionExamples.map((example, i) => (
                      <li key={i} className="min-h-0">
                        <button
                          type="button"
                          disabled={isSharedWorkflowRunMode}
                          onClick={() => setInstruction(example)}
                          aria-label={`Apply suggestion: ${example}`}
                          className={`group relative flex h-full min-h-[5.25rem] w-full flex-col justify-between overflow-hidden rounded-xl border border-gray-200 dark:border-white/[0.06] bg-gradient-to-b from-white/[0.05] to-white/[0.015] px-3.5 py-3 text-left shadow-[0_8px_32px_-24px_rgba(0,0,0,0.85)] transition-all duration-300 ${
                            isSharedWorkflowRunMode
                              ? 'cursor-not-allowed opacity-55'
                              : 'hover:border-violet-400/35 hover:from-violet-500/[0.12] hover:to-zinc-950/70 hover:shadow-[0_24px_48px_-28px_rgba(139,92,246,0.22)] focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/45 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950'
                          }`}
                        >
                          <span
                            className="pointer-events-none absolute -right-8 -top-10 h-28 w-28 rounded-full bg-violet-500/15 opacity-0 blur-3xl transition-opacity duration-500 group-hover:opacity-100"
                            aria-hidden
                          />
                          <div className="relative flex gap-2.5">
                            <span className="mt-0.5 shrink-0 font-mono text-[10px] font-semibold tabular-nums leading-none text-zinc-600 transition-colors group-hover:text-violet-400/90">
                              {String(i + 1).padStart(2, '0')}
                            </span>
                            <span className="line-clamp-3 font-body text-[12.5px] leading-snug text-zinc-300 transition-colors group-hover:text-zinc-50 sm:text-[13px]">
                              {example}
                            </span>
                          </div>
                          <span className="relative mt-3 inline-flex items-center gap-1 font-body text-[11px] font-medium text-zinc-500 transition-colors group-hover:text-violet-200">
                            Apply to mission
                            <ChevronRight
                              className="h-3.5 w-3.5 transition-transform duration-300 group-hover:translate-x-0.5"
                              strokeWidth={2}
                            />
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            )}

            <div className="flex flex-col gap-3">
              <div
                className="group relative overflow-hidden rounded-[1.35rem] border border-gray-200 dark:border-white/[0.09] bg-white dark:bg-zinc-950/45 shadow-[inset_0_1px_0_0_rgba(255,255,255,0.06),0_12px_40px_-28px_rgba(0,0,0,0.55)] ring-1 ring-white/[0.04] backdrop-blur-md transition-[border-color,box-shadow,ring-color] duration-300 focus-within:border-primary-500/20 focus-within:shadow-[inset_0_1px_0_0_rgba(255,255,255,0.08),0_0_0_1px_rgba(99,102,241,0.12),0_20px_48px_-24px_rgba(99,102,241,0.18)] focus-within:ring-primary-500/15"
              >
                <div
                  className="pointer-events-none absolute inset-0 bg-gradient-to-br from-primary-500/[0.05] via-transparent to-violet-600/[0.06] opacity-70 transition-opacity duration-300 group-focus-within:opacity-100"
                  aria-hidden
                />
                <div
                  className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/25 to-transparent"
                  aria-hidden
                />
                <textarea
                  id="workflows-mission-input"
                  disabled={isSharedWorkflowRunMode}
                  ref={(el) => {
                    missionTextareaRef.current = el;
                    if (el) {
                      el.style.height = 'auto';
                      el.style.height = `${Math.max(el.scrollHeight, 72)}px`;
                    }
                  }}
                  value={instruction}
                  onChange={(e) => {
                    if (isSharedWorkflowRunMode) return;
                    setInstruction(e.target.value);
                    const t = e.target;
                    t.style.height = 'auto';
                    t.style.height = `${Math.max(t.scrollHeight, 72)}px`;
                  }}
                  placeholder={
                    isSharedWorkflowRunMode
                      ? 'Mission generation is disabled for shared links. Configure credentials below and run this agent.'
                      : 'e.g. Research competitors, draft a one-pager, open JIRA stories for gaps, and email the summary to the team.'
                  }
                  rows={2}
                  className="relative z-[1] min-h-[72px] w-full max-h-[300px] resize-y rounded-[1.35rem] border-0 bg-transparent px-4 py-3.5 font-body text-[15px] leading-[1.55] tracking-[-0.01em] text-gray-900 dark:text-zinc-100 shadow-none placeholder:text-gray-400 dark:placeholder:text-zinc-500 placeholder:transition-colors focus:outline-none focus:placeholder:text-gray-500 dark:focus:placeholder:text-zinc-400 sm:text-sm sm:leading-relaxed sm:tracking-normal caret-violet-300 selection:bg-violet-500/25 selection:text-white disabled:cursor-not-allowed disabled:text-gray-400 dark:disabled:text-zinc-500 disabled:placeholder:text-gray-300 dark:disabled:placeholder:text-zinc-600"
                />
              </div>
              {isSharedWorkflowRunMode ? (
                <p className="px-1 font-body text-xs text-zinc-500">
                  Workflow generation is locked for shared links. You can still configure required agent credentials and run this agent.
                </p>
              ) : null}
              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={handleGenerate}
                  disabled={isSharedWorkflowRunMode || isGenerating || !instruction.trim()}
                  title={isSharedWorkflowRunMode ? 'Generation is disabled for shared links' : 'Generate a workflow'}
                  className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-primary-500 to-violet-600 px-5 py-2.5 font-body text-xs font-semibold text-gray-900 dark:text-white shadow-lg shadow-primary-950/45 ring-1 ring-white/15 transition-all hover:from-primary-400 hover:to-violet-500 hover:shadow-primary-500/20 hover:ring-white/25 disabled:cursor-not-allowed disabled:from-zinc-800 disabled:to-zinc-800 disabled:text-zinc-600 disabled:shadow-none disabled:ring-white/[0.06]"
                >
                  {isGenerating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                  {isGenerating ? 'Generating…' : 'Generate'}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {workflow && (
        <>
          <div
            className={`mb-8 overflow-hidden rounded-3xl border border-gray-200 dark:border-white/[0.07] bg-white dark:bg-zinc-900/35 shadow-[0_20px_50px_-28px_rgba(0,0,0,0.6)] ring-1 ring-white/[0.04] backdrop-blur-md ${
              editingStep !== null || kbPickerOpenIdx !== null ? '!overflow-visible' : ''
            }`}
          >
            <div className="border-b border-gray-200 dark:border-white/[0.06] bg-black/15 px-4 py-4 sm:px-5">
              <div className="mb-0 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-amber-500/20 to-orange-600/15 ring-1 ring-amber-500/25">
                    <Activity className="h-5 w-5 text-amber-300" />
                  </div>
                  <div className="min-w-0 flex-1">
                    {workflowTitleEditOpen ? (
                      <div className="flex flex-wrap items-center gap-2">
                        <input
                          ref={workflowNameInputRef}
                          type="text"
                          value={workflowTitleDraft}
                          onChange={(e) => setWorkflowTitleDraft(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                              e.preventDefault();
                              commitWorkflowTitleEdit();
                            } else if (e.key === 'Escape') {
                              e.preventDefault();
                              cancelWorkflowTitleEdit();
                            }
                          }}
                          placeholder="Workflow name"
                          aria-label="Workflow name"
                          className="min-w-[12rem] max-w-full flex-1 rounded-lg border border-white/[0.12] bg-zinc-950/80 px-3 py-1.5 font-heading text-base font-semibold tracking-tight text-gray-900 dark:text-white shadow-inner shadow-black/20 placeholder:text-zinc-600 focus:border-violet-500/45 focus:outline-none focus:ring-1 focus:ring-violet-500/30"
                        />
                        <button
                          type="button"
                          onClick={commitWorkflowTitleEdit}
                          title="Save name"
                          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-emerald-500/30 bg-emerald-500/[0.12] text-emerald-200 transition-colors hover:bg-emerald-500/[0.2]"
                          aria-label="Save workflow name"
                        >
                          <Check className="h-4 w-4" strokeWidth={2} />
                        </button>
                        <button
                          type="button"
                          onClick={cancelWorkflowTitleEdit}
                          title="Cancel"
                          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-gray-200 dark:border-white/[0.1] bg-white dark:bg-zinc-950/60 text-zinc-400 transition-colors hover:border-white/[0.16] hover:text-zinc-200"
                          aria-label="Cancel renaming workflow"
                        >
                          <X className="h-4 w-4" strokeWidth={2} />
                        </button>
                      </div>
                    ) : (
                      <div className="flex min-w-0 items-center gap-2">
                        <h3 className="min-w-0 truncate font-heading text-base font-semibold tracking-tight text-gray-900 dark:text-white">
                          {workflow.name || 'Generated agent'}
                        </h3>
                        {!isSharedWorkflowRunMode ? (
                          <button
                            type="button"
                            onClick={beginWorkflowTitleEdit}
                            title="Edit workflow name"
                            className="shrink-0 rounded-lg border border-transparent p-1 text-zinc-500 transition-colors hover:border-gray-300 dark:hover:border-white/[0.08] hover:bg-gray-100 dark:hover:bg-white/[0.05] hover:text-gray-800 dark:hover:text-zinc-200"
                            aria-label="Edit workflow name"
                          >
                            <PenLine className="h-4 w-4" strokeWidth={2} />
                          </button>
                        ) : null}
                      </div>
                    )}
                    <p className="mt-0.5 font-body text-xs text-zinc-500">
                      <span className="lg:hidden">
                        {workflow.steps.length} step{workflow.steps.length !== 1 ? 's' : ''} · select a step to edit prompts, RAG, and dependencies
                      </span>
                      <span className="hidden lg:inline">
                        {workflow.steps.length} step{workflow.steps.length !== 1 ? 's' : ''} · flow diagram and step editor side by side
                      </span>
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  {isAuthenticated && (
                    <button
                      type="button"
                      onClick={() => setMemoryEnabled((v) => !v)}
                      title={
                        memoryEnabled
                          ? 'Memory ON — agents recall prior runs and store new ones (mem0)'
                          : 'Memory OFF — turn on to let agents learn across runs (mem0)'
                      }
                      className={`group inline-flex items-center gap-2 rounded-xl border px-3 py-2 font-body text-xs font-semibold transition-all ${
                        memoryEnabled
                          ? 'border-emerald-500/30 bg-emerald-500/[0.12] text-emerald-100 hover:bg-emerald-500/[0.18]'
                          : 'border-gray-200 dark:border-white/[0.08] bg-zinc-950/50 text-zinc-400 hover:text-zinc-200 hover:border-white/[0.14]'
                      }`}
                    >
                      <Brain
                        className={`h-3.5 w-3.5 ${memoryEnabled ? 'text-emerald-300' : 'text-zinc-500'}`}
                      />
                      <span>Memory</span>
                      <span
                        className={`relative inline-flex h-4 w-7 items-center rounded-full transition-colors ${
                          memoryEnabled ? 'bg-emerald-500/70' : 'bg-zinc-700'
                        }`}
                        aria-hidden
                      >
                        <span
                          className={`inline-block h-3 w-3 transform rounded-full bg-white shadow transition-transform ${
                            memoryEnabled ? 'translate-x-3.5' : 'translate-x-0.5'
                          }`}
                        />
                      </span>
                    </button>
                  )}
                  {isAuthenticated && isAdmin && currentWorkflowId && (
                    <button
                      type="button"
                      onClick={() => setMemoryGraphOpen(true)}
                      title="View memory graph (admin only)"
                      className="inline-flex items-center gap-2 rounded-xl border border-emerald-500/25 bg-emerald-500/[0.08] px-3 py-2 font-body text-xs font-semibold text-emerald-100 transition-all hover:bg-emerald-500/[0.16] hover:border-emerald-500/40"
                    >
                      <Brain className="h-3.5 w-3.5 text-emerald-300" />
                      View Memory
                    </button>
                  )}
                  <div className="inline-flex items-center rounded-xl border border-gray-200 dark:border-white/[0.06] bg-zinc-950/50 p-0.5 lg:hidden">
                  <button
                    type="button"
                    onClick={() => setPipelineTab('steps')}
                    className={`flex items-center gap-1.5 rounded-lg px-3 py-2 font-body text-xs font-semibold transition-all ${
                      pipelineTab === 'steps'
                        ? 'bg-white/[0.1] text-gray-900 dark:text-white ring-1 ring-white/10'
                        : 'text-zinc-500 hover:text-zinc-300'
                    }`}
                  >
                    Steps
                    <span className="rounded-md bg-gray-100 dark:bg-white/[0.06] px-1.5 py-0.5 font-mono text-[10px] font-bold text-zinc-400">
                      {workflow.steps.length}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setPipelineTab('diagram')}
                    className={`flex items-center gap-1.5 rounded-lg px-3 py-2 font-body text-xs font-semibold transition-all ${
                      pipelineTab === 'diagram'
                        ? 'bg-white/[0.1] text-gray-900 dark:text-white ring-1 ring-white/10'
                        : 'text-zinc-500 hover:text-zinc-300'
                    }`}
                  >
                    <Activity className="h-3.5 w-3.5" />
                    Diagram
                  </button>
                  </div>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 divide-y divide-gray-200 dark:divide-white/[0.06]">
              <div
                className={`p-4 lg:min-h-[min(200px,28vh)] ${pipelineTab === 'diagram' ? 'block' : 'hidden'} lg:block`}
              >
                {workflow.steps.length > 0 ? (
                  <div className="w-full min-w-0 overflow-x-auto">
                    <AgentWorkflowFlowDiagram
                      workflowName={workflow.name || 'Workflow'}
                      steps={workflow.steps}
                      agents={studioCatalog?.agents}
                      isLive={isExecuting}
                      layoutStorageKey={
                        workflowDiagramLayoutStorageKey(currentWorkflowId) ??
                        workflowDiagramLayoutDraftKey(
                          workflow.name ?? '',
                          workflow.steps.map((s) => s.step_number),
                        )
                      }
                      onStepClick={handleDiagramStepClick}
                      onHarnessEdgeClick={handleHarnessEdgeClick}
                    />
                  </div>
                ) : (
                  <div className="flex min-h-[200px] flex-col items-center justify-center py-10 text-center lg:min-h-[min(280px,38vh)]">
                    <Activity className="mb-3 h-8 w-8 text-gray-700" />
                    <p className="mb-1 font-body text-sm font-medium text-gray-500">No flow diagram yet</p>
                    <p className="font-body text-xs text-gray-400 dark:text-gray-600">
                      Add steps to see the live flow map with agents and dependencies.
                    </p>
                  </div>
                )}
              </div>

              <div
                className={`min-h-0 min-w-0 p-4 ${pipelineTab === 'steps' ? 'block' : 'hidden'} lg:block`}
              >
            <div className="relative">
              <div className="space-y-2 sm:space-y-2.5 relative">
                {workflow.steps.map((step, idx) => {
                  const isActive = editingStep === idx;
                  const isCompleted = step.status === 'completed';
                  const isFailed = step.status === 'failed';
                  const isRunning = step.status === 'running';
                  const accentColor = isCompleted ? 'rgb(34 197 94)' : isFailed ? 'rgb(239 68 68)' : isRunning ? 'rgb(59 130 246)' : 'rgb(249 115 22)';
                  const catalogAgentForStep =
                    studioCatalog?.agents?.find((a) => a.id === step.agent_id) ?? null;
                  const stepConfigFields = catalogAgentForStep ? getConfigFields(catalogAgentForStep) : [];
                  const stepConfigOk =
                    !catalogAgentForStep || stepConfigFields.length === 0
                      ? true
                      : hasRequiredConfig(catalogAgentForStep, stepConfigFields);
                  return (
                    <div
                      key={idx}
                      id={`workflow-step-card-${step.step_number}`}
                      className={`relative ${kbPickerOpenIdx === idx ? 'z-40' : 'z-0'}`}
                    >
                      {idx < workflow.steps.length - 1 && (
                        <div className="absolute left-[18px] sm:left-5 top-full w-px h-2.5 z-10" style={{ background: `linear-gradient(to bottom, ${accentColor}40, transparent)` }} />
                      )}
                      <div
                        className={`group relative ${isActive ? 'overflow-visible' : 'overflow-hidden'} rounded-2xl transition-all duration-300 backdrop-blur-md ${
                          isActive
                            ? 'border border-white/[0.07] bg-gradient-to-br from-zinc-900/95 via-zinc-900/80 to-zinc-950/95 shadow-[0_12px_48px_-16px_rgba(0,0,0,0.65)] ring-1 ring-white/[0.06]'
                            : isRunning
                              ? 'border border-sky-500/45 bg-gradient-to-br from-sky-950/[0.22] via-zinc-900/45 to-zinc-950/65 shadow-[0_0_52px_-14px_rgba(56,189,248,0.42),0_12px_40px_-22px_rgba(0,0,0,0.55)] ring-1 ring-sky-400/35 hover:border-sky-400/55 hover:from-sky-950/30 hover:via-zinc-900/52 hover:to-zinc-950/75'
                              : 'border border-white/[0.04] bg-gradient-to-br from-zinc-900/40 to-zinc-950/60 hover:border-white/[0.07] hover:from-zinc-900/55 hover:to-zinc-950/75'
                        }`}
                        aria-busy={isRunning}
                      >
                        <div className="absolute left-0 top-0 bottom-0 w-[3px] rounded-l-2xl transition-all duration-300" style={{
                          background: isActive
                            ? `linear-gradient(to bottom, ${accentColor}, ${accentColor}60)`
                            : isRunning
                              ? `linear-gradient(to bottom, ${accentColor}, ${accentColor}50)`
                              : `linear-gradient(to bottom, ${accentColor}50, ${accentColor}15)`
                        }} />

                        <div className={`${isActive ? 'p-3 pl-3.5 sm:p-3.5 sm:pl-4' : 'p-4 pl-5'}`}>
                          <div className="flex items-start gap-3">
                            <div className="relative shrink-0 transition-all duration-300">
                              <div
                                className={`flex h-9 w-9 items-center justify-center rounded-xl font-body text-xs font-bold sm:h-10 sm:text-sm ${
                                  isRunning
                                    ? 'text-sky-200 ring-2 ring-sky-400/50 ring-offset-2 ring-offset-zinc-950 shadow-[0_0_22px_-6px_rgba(56,189,248,0.65)]'
                                    : ''
                                }`}
                                style={{
                                  background: `linear-gradient(135deg, ${accentColor}18, ${accentColor}08)`,
                                  color: accentColor,
                                  boxShadow: isRunning
                                    ? `0 0 0 1px rgba(56,189,248,0.35), 0 2px 12px rgba(56,189,248,0.15)`
                                    : `0 0 0 1px ${accentColor}20, 0 2px 8px ${accentColor}08`,
                                }}
                              >
                                {isCompleted ? (
                                  <CheckCircle className="h-4 w-4 sm:h-[18px] sm:w-[18px]" />
                                ) : isRunning ? (
                                  <StepRunningSpinner className="h-[17px] w-[17px] text-sky-200 sm:h-[19px] sm:w-[19px]" />
                                ) : isFailed ? (
                                  <AlertCircle className="h-4 w-4 sm:h-[18px] sm:w-[18px]" />
                                ) : (
                                  step.step_number
                                )}
                              </div>
                            </div>

                            <div className="flex-1 min-w-0">
                              <div className={`flex items-start justify-between gap-2 sm:gap-3 ${isActive ? 'pb-2.5 border-b border-white/[0.05]' : ''}`}>
                                <div className="min-w-0">
                                  <div className="flex items-center gap-2 flex-wrap">
                                    <h4 className="font-body text-sm sm:text-[15px] font-semibold text-gray-900 dark:text-white tracking-tight leading-snug [text-shadow:0_1px_12px_rgba(0,0,0,0.35)]">{step.agent}</h4>
                                    {step.agent_name && step.agent_name !== step.agent && (
                                      <span className="px-1.5 py-0.5 text-[9px] sm:text-[10px] text-gray-500 font-body bg-white/[0.03] rounded-md ring-1 ring-white/[0.04]">{step.agent_name}</span>
                                    )}
                                  </div>
                                  {step.depends_on && step.depends_on.length > 0 && (
                                    <div className="flex items-center gap-1.5 mt-0.5">
                                      <ArrowLeft className="w-3 h-3 text-gray-400 dark:text-gray-600 rotate-180" />
                                      <span className="text-[10px] text-gray-400 dark:text-gray-600 font-body">Receives input from step{step.depends_on.length > 1 ? 's' : ''}</span>
                                      {step.depends_on.map(d => (
                                        <span key={d} className="w-5 h-5 text-[10px] font-body font-bold bg-orange-500/10 text-orange-400/80 rounded-md flex items-center justify-center ring-1 ring-orange-500/15">
                                          {d}
                                        </span>
                                      ))}
                                    </div>
                                  )}
                                </div>

                                <div className="flex items-center gap-1.5 shrink-0">
                                  <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 text-[10px] sm:text-[11px] font-body font-medium rounded-full transition-all ${
                                    isCompleted ? 'text-emerald-300 bg-emerald-500/[0.12] ring-1 ring-emerald-500/25' :
                                    isFailed ? 'text-red-300 bg-red-500/[0.12] ring-1 ring-red-500/25' :
                                    isRunning ? 'text-sky-200 bg-gradient-to-r from-sky-500/[0.14] to-cyan-500/[0.1] ring-1 ring-sky-400/35 shadow-[0_0_18px_-8px_rgba(56,189,248,0.55)]' :
                                    'text-zinc-400 bg-gray-100 dark:bg-white/[0.04] ring-1 ring-white/[0.06]'
                                  }`}>
                                    {isRunning ? (
                                      <StepRunningSpinner className="h-3 w-3 text-sky-300 sm:h-3.5 sm:w-3.5" />
                                    ) : (
                                      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                                        isCompleted ? 'bg-emerald-400' : isFailed ? 'bg-red-400' : 'bg-zinc-500'
                                      }`} aria-hidden />
                                    )}
                                    {isCompleted ? 'Done' : isFailed ? 'Failed' : isRunning ? 'Running' : 'Pending'}
                                  </span>
                                  <button
                                    onClick={() => setEditingStep(isActive ? null : idx)}
                                    className={`flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] sm:text-xs font-body font-medium transition-all ${isActive ? 'text-primary-300 bg-primary-500/[0.15] ring-1 ring-primary-400/25 shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]' : 'text-zinc-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-white/[0.06] ring-1 ring-transparent hover:ring-white/10'}`}
                                    title="Edit step"
                                  >
                                    <Edit2 className="w-3 h-3 shrink-0" />
                                    <span>{isActive ? 'Editing' : 'Configure'}</span>
                                  </button>
                                  {!isExecuting && workflow && workflow.steps.length > 1 && (
                                    <button
                                      onClick={() => handleDeleteStep(idx)}
                                      className="w-6 h-6 sm:w-7 sm:h-7 rounded-md flex items-center justify-center transition-all text-gray-700 hover:text-red-400 hover:bg-red-500/10"
                                      title="Remove this step"
                                    >
                                      <Trash2 className="w-3 h-3" />
                                    </button>
                                  )}
                                </div>
                              </div>

                              {!isActive && catalogAgentForStep && stepConfigFields.length > 0 && (
                                <div className="mt-2 flex flex-wrap items-center gap-2">
                                  <span
                                    className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-lg text-[10px] font-body font-medium ring-1 ${
                                      stepConfigOk
                                        ? 'text-emerald-400/90 bg-emerald-500/[0.07] ring-emerald-500/15'
                                        : 'text-amber-400/90 bg-amber-500/[0.08] ring-amber-500/20'
                                    }`}
                                  >
                                    <Key className="w-3 h-3 shrink-0 opacity-80" />
                                    {stepConfigOk ? 'Agent config ready' : 'Agent config required — open Configure'}
                                  </span>
                                </div>
                              )}
                              {!catalogAgentForStep && step.agent_id && studioCatalog && (
                                <p className="mt-2 text-[10px] text-gray-400 dark:text-gray-600 font-body">
                                  Unknown agent id <code className="text-gray-600 dark:text-gray-400">{step.agent_id}</code> — config not shown.
                                </p>
                              )}
                              {!studioCatalog && step.agent_id && (
                                <p className="mt-2 text-[10px] text-gray-400 dark:text-gray-600 font-body italic">Loading agent catalog…</p>
                              )}

                              {isActive ? (
                                <div className="mt-2.5 sm:mt-3 space-y-2.5 sm:space-y-3">
                                  {catalogAgentForStep && stepConfigFields.length > 0 && (
                                    <WorkflowStepConfigureSection
                                      agent={catalogAgentForStep}
                                      configOk={stepConfigOk}
                                      onSaved={() => setWorkflowAgentConfigTick((t) => t + 1)}
                                    />
                                  )}
                                  {renderStepPromptEditor(step, idx, 'step-card')}
                                  {workflow && workflow.steps.length > 1 && step.step_number > 1 && (
                                    <div className="p-2.5 sm:p-3 bg-gray-50 dark:bg-black/15 border border-gray-200 dark:border-white/[0.04] rounded-lg">
                                      <div className="flex items-center gap-1.5 mb-1">
                                        <div className="w-5 h-5 rounded-md bg-gradient-to-br from-orange-500/15 to-amber-500/10 flex items-center justify-center ring-1 ring-orange-500/10">
                                          <ArrowLeft className="w-2.5 h-2.5 text-orange-400 rotate-180" />
                                        </div>
                                        <span className="text-[11px] font-body font-semibold text-gray-700 dark:text-gray-300">Dependencies</span>
                                      </div>
                                      <p className="text-[9px] text-gray-400 dark:text-gray-600 font-body mb-2 ml-6 sm:ml-7 leading-snug">Earlier steps feed into this step</p>
                                      <div className="space-y-2">
                                        {workflow.steps
                                          .filter(s => s.step_number < step.step_number)
                                          .map(prevStep => {
                                            const isLinked = (step.depends_on || []).includes(prevStep.step_number);
                                            return (
                                              <div key={prevStep.step_number} className={`rounded-lg border transition-all ${isLinked ? 'border-orange-500/20 bg-orange-500/[0.04]' : 'border-white/[0.04] bg-black/10'}`}>
                                                <div className="flex items-center gap-2.5 px-3 py-2">
                                                  <button
                                                    onClick={() => handleStepDependencyToggle(idx, prevStep.step_number)}
                                                    className={`w-5 h-5 rounded flex items-center justify-center shrink-0 transition-all ${isLinked ? 'bg-orange-500 text-gray-900 dark:text-white' : 'bg-gray-100 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-transparent hover:border-orange-500/30'}`}
                                                  >
                                                    {isLinked && <CheckCircle className="w-3 h-3" />}
                                                  </button>
                                                  <div className="flex items-center gap-2 flex-1 min-w-0">
                                                    <span className="w-5 h-5 text-[10px] font-body font-bold bg-gray-100 dark:bg-white/[0.06] text-gray-600 dark:text-gray-400 rounded-full flex items-center justify-center shrink-0">
                                                      {prevStep.step_number}
                                                    </span>
                                                    <span className="text-xs font-body text-gray-700 dark:text-gray-300 truncate">{prevStep.agent}</span>
                                                  </div>
                                                </div>
                                                {isLinked && (
                                                  <div className="px-3 pb-2.5">
                                                    <input
                                                      type="text"
                                                      value={step.input_mapping?.[`description_${prevStep.step_number}`] || (String(step.input_mapping?.from_step) === String(prevStep.step_number) ? step.input_mapping?.description || '' : '')}
                                                      onChange={(e) => handleInputMappingDescChange(idx, prevStep.step_number, e.target.value)}
                                                      placeholder="How to use this output (e.g., Use research data to generate diagram)"
                                                      className="w-full bg-black/20 border border-gray-200 dark:border-white/[0.06] rounded-lg px-3 py-1.5 text-[11px] text-gray-600 dark:text-gray-400 font-body focus:border-orange-500/30 focus:outline-none transition-all placeholder:text-gray-600"
                                                    />
                                                  </div>
                                                )}
                                              </div>
                                            );
                                          })}
                                      </div>
                                      {(step.depends_on || []).length > 0 && (
                                        <p className="mt-2.5 text-[10px] text-orange-400/40 font-body leading-relaxed">
                                          This step will receive output from step{(step.depends_on || []).length > 1 ? 's' : ''} {(step.depends_on || []).join(', ')} via {'{{step_N_output}}'} placeholders in the query
                                        </p>
                                      )}
                                    </div>
                                  )}
                                  {renderStepKnowledgeBaseEditor(step, idx)}
                                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between pt-2 border-t border-gray-200 dark:border-white/[0.03]">
                                    <p className="text-[9px] text-gray-400 dark:text-gray-600 font-body leading-snug">Auto-saved. Close when done.</p>
                                    <button
                                      onClick={() => {
                                        if (workflow) {
                                          setWorkflow({ ...workflow, mermaid: regenerateMermaid(workflow.steps) });
                                        }
                                        setEditingStep(null);
                                      }}
                                      className="shrink-0 px-3 py-1.5 text-[11px] font-body font-semibold text-gray-900 dark:text-white bg-gradient-to-r from-primary-500/25 to-primary-600/20 hover:from-primary-500/35 hover:to-primary-600/30 rounded-lg transition-all ring-1 ring-primary-500/20 flex items-center justify-center gap-1.5 w-full sm:w-auto"
                                    >
                                      <CheckCircle className="w-3 h-3" />
                                      Done
                                    </button>
                                  </div>
                                </div>
                              ) : (
                                <div className="mt-2">
                                  <p className="font-body text-[13px] text-gray-400/90 leading-relaxed line-clamp-2">{step.query}</p>
                                  <div className="mt-3 flex items-center gap-2 flex-wrap">
                                    {step.kb_index && step.kb_index.enabled && step.kb_index.db_name && (
                                      <div className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-blue-500/[0.06] rounded-lg ring-1 ring-blue-500/10">
                                        <Database className="w-2.5 h-2.5 text-blue-400/50" />
                                        <span className="text-[10px] text-blue-400/60 font-body font-medium">
                                          KB: {step.kb_index.collection} &middot; top {step.kb_index.top_k}
                                        </span>
                                      </div>
                                    )}
                                    {step.depends_on && step.depends_on.length > 0 && step.depends_on.map(d => {
                                      const desc = step.input_mapping?.[`description_${d}`] || step.input_mapping?.description || '';
                                      return (
                                        <span key={`dep-${d}`} className="inline-flex items-center gap-1.5 px-2.5 py-1 text-[10px] font-body font-medium text-orange-400/60 bg-orange-500/[0.04] rounded-lg ring-1 ring-orange-500/10">
                                          <span className="w-4 h-4 text-[9px] font-bold bg-orange-500/15 text-orange-400/80 rounded-md flex items-center justify-center">
                                            {d}
                                          </span>
                                          {desc ? desc : `Uses step ${d} output`}
                                        </span>
                                      );
                                    })}
                                    {!step.kb_index?.enabled && (!step.depends_on || step.depends_on.length === 0) && step.step_number === 1 && (
                                      <span className="text-[10px] text-gray-400 dark:text-gray-600 font-body italic">Standalone step &mdash; no dependencies</span>
                                    )}
                                  </div>
                                </div>
                              )}
                            </div>
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

        </>
      )}

          <PromptHarnessModal
            open={promptHarnessEdge !== null}
            edge={promptHarnessEdge}
            initialConfig={harnessInitialConfig}
            mergedAgentEnv={harnessMergedAgentEnv}
            onClose={() => setPromptHarnessEdge(null)}
            onSave={handleSavePromptHarness}
          />

          <WorkflowMemoryGraphModal
            open={memoryGraphOpen}
            workflowId={currentWorkflowId}
            workflowName={workflow?.name ?? ''}
            onClose={() => setMemoryGraphOpen(false)}
          />

          {stepModal && (
            <div
              className="fixed inset-0 z-[120] flex items-center justify-center overflow-y-auto bg-black/75 p-4 backdrop-blur-sm"
              role="dialog"
              aria-modal="true"
              aria-label={`Step ${stepModal.step_number} details`}
              onClick={() => setStepModalStepNumber(null)}
            >
              <div
                className="relative my-auto flex max-h-[calc(100vh-2rem)] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-gray-200 dark:border-white/[0.1] bg-white dark:bg-zinc-900/95 shadow-2xl shadow-black/60 ring-1 ring-white/[0.08]"
                onClick={(e) => e.stopPropagation()}
              >
                <div className="pointer-events-none absolute -right-20 -top-20 h-52 w-52 rounded-full bg-violet-500/12 blur-3xl" />
                <div className="pointer-events-none absolute -bottom-16 -left-16 h-48 w-48 rounded-full bg-primary-500/10 blur-3xl" />

                <div className="relative border-b border-gray-200 dark:border-white/[0.08] bg-black/30 px-5 py-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-mono text-[11px] uppercase tracking-wide text-zinc-500">Step {String(stepModal.step_number).padStart(2, '0')}</p>
                      <h4 className="mt-1 text-base font-semibold text-gray-900 dark:text-white">{stepModal.agent}</h4>
                      {stepModal.agent_name && stepModal.agent_name !== stepModal.agent ? (
                        <p className="mt-0.5 text-xs text-zinc-400">{stepModal.agent_name}</p>
                      ) : null}
                    </div>
                    <button
                      type="button"
                      onClick={() => setStepModalStepNumber(null)}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-gray-200 dark:border-white/[0.08] bg-white/[0.03] text-zinc-400 transition-colors hover:bg-white/[0.08] hover:text-zinc-200"
                      aria-label="Close step modal"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                </div>

                <div className="relative min-h-0 space-y-4 overflow-y-auto px-5 py-4">
                  {stepModalCatalogAgent && stepModalConfigFields.length > 0 ? (
                    <WorkflowStepConfigureSection
                      agent={stepModalCatalogAgent}
                      configOk={stepModalConfigOk}
                      onSaved={() => setWorkflowAgentConfigTick((t) => t + 1)}
                    />
                  ) : stepModalCatalogAgent && stepModalConfigFields.length === 0 ? (
                    <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/[0.08] px-3.5 py-3 text-xs text-emerald-200">
                      This agent has no configurable connection fields.
                    </div>
                  ) : stepModal.agent_id && studioCatalog ? (
                    <p className="rounded-xl border border-gray-200 dark:border-white/[0.08] bg-black/20 px-3.5 py-3 text-xs text-zinc-400">
                      Unknown agent id <code className="text-zinc-300">{stepModal.agent_id}</code> - config is not available.
                    </p>
                  ) : (
                    <p className="rounded-xl border border-gray-200 dark:border-white/[0.08] bg-black/20 px-3.5 py-3 text-xs text-zinc-500 italic">
                      Loading agent catalog...
                    </p>
                  )}

                  {stepModalIndex >= 0 ? (
                    <>
                      {renderStepPromptEditor(stepModal, stepModalIndex, 'step-modal')}
                      {renderStepKnowledgeBaseEditor(stepModal, stepModalIndex)}
                    </>
                  ) : null}

                  <div className="flex flex-col gap-2 border-t border-gray-200 dark:border-white/[0.08] pt-4 sm:flex-row sm:items-center sm:justify-end">
                    <button
                      type="button"
                      onClick={() => setStepModalStepNumber(null)}
                      className="inline-flex items-center justify-center rounded-lg border border-gray-200 dark:border-white/[0.08] bg-white/[0.03] px-3.5 py-2 text-xs font-medium text-zinc-300 transition-all hover:bg-white/[0.08]"
                    >
                      Close
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleSave()}
                      disabled={!workflow || !isAuthenticated || isSaving}
                      title={isAuthenticated ? 'Save workflow changes' : 'Sign in to save'}
                      className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-gradient-to-r from-emerald-500 to-teal-600 px-3.5 py-2 text-xs font-semibold text-gray-900 dark:text-white shadow-lg shadow-emerald-950/35 transition-all hover:from-emerald-400 hover:to-teal-500 disabled:cursor-not-allowed disabled:from-zinc-700 disabled:to-zinc-700 disabled:text-zinc-500 disabled:shadow-none"
                    >
                      {isSaving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                      Save
                    </button>
                    <button
                      type="button"
                      onClick={openInlineEditorFromModal}
                      className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-gradient-to-r from-primary-500 to-violet-600 px-4 py-2 text-xs font-semibold text-gray-900 dark:text-white shadow-lg shadow-primary-950/40 transition-all hover:from-primary-400 hover:to-violet-500"
                    >
                      <Edit2 className="h-3.5 w-3.5" />
                      Open Configure Panel
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {rerunModal && (
            <div
              className="fixed inset-0 z-[130] flex items-center justify-center overflow-y-auto bg-black/75 p-4 backdrop-blur-sm"
              role="dialog"
              aria-modal="true"
              aria-label={`Re-run step ${rerunModal.stepNumber}`}
              onClick={() => {
                if (rerunningStep === null) setRerunModal(null);
              }}
            >
              <div
                className="relative my-auto flex max-h-[calc(100vh-2rem)] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-gray-200 dark:border-white/[0.1] bg-white dark:bg-zinc-900/95 shadow-2xl shadow-black/60 ring-1 ring-white/[0.08]"
                onClick={(e) => e.stopPropagation()}
              >
                <div className="pointer-events-none absolute -right-20 -top-20 h-52 w-52 rounded-full bg-primary-500/12 blur-3xl" />
                <div className="pointer-events-none absolute -bottom-16 -left-16 h-48 w-48 rounded-full bg-emerald-500/10 blur-3xl" />

                <div className="relative border-b border-gray-200 dark:border-white/[0.08] bg-black/30 px-5 py-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-mono text-[11px] uppercase tracking-wide text-zinc-500">Re-run step {String(rerunModal.stepNumber).padStart(2, '0')}</p>
                      <h4 className="mt-1 text-base font-semibold text-gray-900 dark:text-white">{rerunModal.agentLabel}</h4>
                      <p className="mt-0.5 text-xs text-zinc-400">
                        Edit the agent input below if needed, then re-run only this step.
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => setRerunModal(null)}
                      disabled={rerunningStep !== null}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-gray-200 dark:border-white/[0.08] bg-white/[0.03] text-zinc-400 transition-colors hover:bg-white/[0.08] hover:text-zinc-200 disabled:cursor-not-allowed disabled:opacity-50"
                      aria-label="Close re-run modal"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                </div>

                <div className="relative min-h-0 space-y-3 overflow-y-auto px-5 py-4">
                  <div>
                    <div className="mb-1.5 flex items-center gap-1.5">
                      <FileText className="h-3 w-3 shrink-0 text-primary-400" />
                      <span className="font-body text-[10px] font-semibold uppercase tracking-wide text-gray-600 dark:text-gray-400">Agent input</span>
                      <span className="truncate font-body text-[9px] text-gray-400 dark:text-gray-600">
                        {rerunModal.input.length} chars
                      </span>
                    </div>
                    <textarea
                      value={rerunModal.input}
                      onChange={(e) =>
                        setRerunModal((prev) => (prev ? { ...prev, input: e.target.value } : prev))
                      }
                      rows={14}
                      disabled={rerunningStep !== null}
                      className="min-h-[16rem] w-full resize-y rounded-lg border border-gray-200 dark:border-white/[0.08] bg-black/30 px-3 py-2 font-mono text-xs leading-relaxed text-gray-200 transition-all placeholder:text-gray-600 focus:border-primary-500/40 focus:outline-none focus:ring-1 focus:ring-primary-500/15 disabled:cursor-not-allowed disabled:opacity-60"
                      placeholder="Enter the input to send to this agent…"
                      autoFocus
                    />
                  </div>

                  <div className="space-y-2">
                    <div className="mb-1 flex items-center gap-1.5">
                      <Paperclip className="h-3 w-3 shrink-0 text-primary-400" />
                      <span className="font-body text-[10px] font-semibold uppercase tracking-wide text-gray-600 dark:text-gray-400">
                        Attachments for this run
                      </span>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        disabled={rerunningStep !== null}
                        onClick={() => rerunFileInputRef.current?.click()}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 dark:border-white/[0.08] bg-white/[0.03] px-2.5 py-1 font-body text-[10px] font-medium text-gray-700 dark:text-gray-300 transition-colors hover:bg-white/[0.07] disabled:opacity-50"
                      >
                        <Paperclip className="h-3 w-3 text-primary-400" />
                        Add files
                      </button>
                      <span className="font-body text-[9px] text-gray-400 dark:text-gray-600">
                        Up to {WORKFLOW_STEP_MAX_ATTACHMENTS} · {WORKFLOW_STEP_MAX_ATTACHMENT_BYTES / (1024 * 1024)}MB each
                      </span>
                    </div>
                    {rerunModal.attachments.length > 0 && (
                      <ul className="flex flex-wrap gap-2">
                        {rerunModal.attachments.map((f, i) => (
                          <li
                            key={`rerun-${f.file_name}-${i}`}
                            className="group flex max-w-full items-center gap-1 rounded-lg border border-gray-200 dark:border-white/[0.08] bg-black/25 py-1 pl-2 pr-1"
                          >
                            <FileText className="h-3 w-3 shrink-0 text-primary-400/80" aria-hidden />
                            <span className="min-w-0 truncate font-mono text-[10px] text-gray-700 dark:text-gray-300" title={f.file_name}>
                              {f.file_name}
                            </span>
                            <button
                              type="button"
                              disabled={rerunningStep !== null}
                              onClick={() =>
                                setRerunModal((prev) =>
                                  prev
                                    ? {
                                        ...prev,
                                        attachments: prev.attachments.filter((_, j) => j !== i),
                                      }
                                    : prev,
                                )
                              }
                              className="shrink-0 rounded p-0.5 text-gray-400 dark:text-gray-600 transition-colors hover:bg-white/[0.08] hover:text-red-300 disabled:opacity-40"
                              aria-label={`Remove ${f.file_name}`}
                            >
                              <X className="h-3 w-3" />
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>

                  <div className="flex flex-col gap-2 border-t border-gray-200 dark:border-white/[0.08] pt-4 sm:flex-row sm:items-center sm:justify-end">
                    <button
                      type="button"
                      onClick={() => setRerunModal(null)}
                      disabled={rerunningStep !== null}
                      className="inline-flex items-center justify-center rounded-lg border border-gray-200 dark:border-white/[0.08] bg-white/[0.03] px-3.5 py-2 text-xs font-medium text-zinc-300 transition-all hover:bg-white/[0.08] disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      onClick={async () => {
                        if (!rerunModal) return;
                        const sn = rerunModal.stepNumber;
                        const input = rerunModal.input;
                        const attachments = rerunModal.attachments;
                        if (!input.trim()) {
                          setError('Agent input cannot be empty.');
                          return;
                        }
                        lastStepInputsRef.current[sn] = input;
                        setStepPromptAttachments((prev) => ({ ...prev, [sn]: attachments }));
                        setRerunModal(null);
                        await handleRerunStep(sn, input, attachments);
                      }}
                      disabled={rerunningStep !== null || !rerunModal.input.trim()}
                      className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-gradient-to-r from-primary-500 to-violet-600 px-4 py-2 text-xs font-semibold text-gray-900 dark:text-white shadow-lg shadow-primary-950/40 transition-all hover:from-primary-400 hover:to-violet-500 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {rerunningStep !== null ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <RefreshCw className="h-3.5 w-3.5" />
                      )}
                      {rerunningStep !== null ? 'Re-running…' : 'Re-run with this input'}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {(chatMessages.length > 0 || isExecuting) && (
            <div className="mb-8 flex flex-col overflow-hidden rounded-3xl border border-gray-200 dark:border-white/[0.07] bg-white dark:bg-zinc-950/80 shadow-[0_24px_60px_-28px_rgba(0,0,0,0.65)] ring-1 ring-white/[0.04] backdrop-blur-md">
              <div className="relative border-b border-gray-200 dark:border-white/[0.06] bg-black/25 px-4 py-4 sm:px-5">
                <div className="pointer-events-none absolute inset-0 bg-gradient-to-r from-emerald-500/[0.05] via-transparent to-primary-500/[0.04]" />
                <div className="relative flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex items-center gap-3">
                    <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500/25 to-teal-600/15 ring-1 ring-emerald-500/30">
                      <Activity className="h-5 w-5 text-emerald-300" />
                    </div>
                    <div>
                      <h3 className="font-heading text-base font-semibold tracking-tight text-gray-900 dark:text-white">Run timeline</h3>
                      <p className="mt-0.5 max-w-md font-body text-xs leading-relaxed text-zinc-500">
                        Live execution log: system events, agent I/O, streaming output, and completion state.
                      </p>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-lg border border-gray-200 dark:border-white/[0.06] bg-gray-100 dark:bg-white/[0.04] px-2.5 py-1 font-mono text-[10px] text-zinc-400">
                      {chatMessages.length} event{chatMessages.length !== 1 ? 's' : ''}
                    </span>
                    {(isExecuting || rerunningStep !== null) && (
                      <div className="flex items-center gap-2 rounded-lg border border-emerald-500/25 bg-emerald-500/10 px-3 py-1.5">
                        <span className="relative flex h-2 w-2">
                          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                          <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
                        </span>
                        <span className="font-body text-xs font-medium text-emerald-300">
                          {rerunningStep !== null ? `Re-running step ${rerunningStep}` : 'Running'}
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              <div
                className="flex-1 px-3 py-4 sm:px-5"
              >
                <div className="relative space-y-1">
                  <div className="pointer-events-none absolute left-[17px] top-6 bottom-6 w-px bg-gradient-to-b from-emerald-500/20 via-white/[0.06] to-transparent sm:left-[18px]" aria-hidden />
                  {chatMessages.map((msg) => {
                    const isMsgExpanded = expandedMsg === msg.id;
                    const isAccordionLogMessage =
                      msg.type === 'agent_thinking' ||
                      msg.type === 'agent_start' ||
                      msg.type === 'agent_progress';
                    const isLogMsgCollapsed = !!collapsedLogMsgIds[msg.id];
                    const usesWorkflowMd = messageUsesWorkflowAgentMarkdown(msg);
                    const isLongMarkdownResponse =
                      usesWorkflowMd && !msg.isStreaming && msg.content.length > 500;
                    const isLongPlainResponse =
                      !msg.isStreaming &&
                      !usesWorkflowMd &&
                      msg.type !== 'agent_input' &&
                      msg.content.length > 900;
                    const tag = getExecutionLogTag(msg);
                    const title =
                      msg.type === 'user_reply'
                        ? 'Your reply'
                        : msg.type === 'system' || msg.type === 'workflow_complete'
                          ? msg.type === 'workflow_complete'
                            ? 'Agent run'
                            : 'System'
                          : msg.agentName
                            ? `Step ${msg.stepNumber ?? '—'} · ${msg.agentName}`
                            : `Step ${msg.stepNumber ?? '—'}`;
                    return (
                  <div key={msg.id} className={`relative flex gap-3 pl-0 sm:gap-4 ${msg.type === 'user_reply' ? 'flex-row-reverse' : ''}`}>
                    <div className="relative z-[1] mt-1 shrink-0">{getMsgIcon(msg)}</div>
                    <div className={`min-w-0 flex-1 pb-5 ${msg.type === 'user_reply' ? 'flex flex-col items-end text-right' : ''}`}>
                      <div className={`mb-2 flex w-full flex-wrap items-center gap-2 ${msg.type === 'user_reply' ? 'justify-end' : ''}`}>
                        <span className={`rounded-md px-2 py-0.5 font-body text-[9px] font-bold uppercase tracking-wider ring-1 ${tag.className}`}>
                          {tag.text}
                        </span>
                        <span className="font-body text-[11px] font-medium text-gray-600 dark:text-gray-400">{title}</span>
                        <span className="font-mono text-[10px] tabular-nums text-gray-400 dark:text-gray-600">
                          {msg.timestamp.toLocaleTimeString()}
                        </span>
                        {isAccordionLogMessage && (
                          <button
                            type="button"
                            onClick={() =>
                              setCollapsedLogMsgIds((prev) => ({
                                ...prev,
                                [msg.id]: !prev[msg.id],
                              }))
                            }
                            className="ml-auto inline-flex items-center gap-1 rounded-md border border-white/[0.12] bg-white/[0.03] px-2 py-1 font-body text-[10px] text-gray-700 dark:text-gray-300 transition-colors hover:bg-white/[0.07] hover:text-gray-900 dark:hover:text-white"
                            aria-expanded={!isLogMsgCollapsed}
                            aria-label={isLogMsgCollapsed ? 'Expand message' : 'Collapse message'}
                          >
                            {isLogMsgCollapsed ? <ChevronDown className="h-3 w-3" /> : <ChevronUp className="h-3 w-3" />}
                            {isLogMsgCollapsed ? 'Expand' : 'Collapse'}
                          </button>
                        )}
                      </div>
                      <div
                        className={`overflow-hidden rounded-xl px-4 shadow-lg ring-1 backdrop-blur-sm transition-[padding,colors] ${
                        msg.type === 'user_reply'
                          ? 'max-w-xl text-left text-gray-200 ring-primary-500/20 self-end bg-primary-500/10'
                          : msg.type === 'agent_input'
                          ? 'bg-violet-500/[0.07] text-left ring-violet-500/15'
                          : msg.type === 'agent_start' || msg.type === 'agent_progress'
                          ? 'bg-blue-500/[0.07] text-left ring-blue-500/15'
                          : msg.type === 'agent_thinking'
                          ? 'bg-teal-500/[0.07] text-left ring-teal-500/15'
                          : msg.type === 'agent_streaming'
                          ? 'bg-sky-500/[0.07] text-left ring-sky-500/15'
                          : msg.type === 'agent_complete'
                          ? 'rounded-2xl bg-gradient-to-br from-zinc-900/85 via-zinc-950/92 to-zinc-950 text-left ring-1 ring-white/[0.1] shadow-[0_12px_40px_-20px_rgba(0,0,0,0.55)]'
                          : msg.type === 'agent_failed'
                          ? 'bg-red-500/[0.08] text-left ring-red-500/20'
                          : msg.type === 'needs_input'
                          ? 'bg-amber-500/[0.07] text-left ring-amber-500/15'
                          : msg.type === 'workflow_complete'
                          ? msg.success
                            ? 'bg-emerald-500/[0.08] ring-emerald-500/25 text-left'
                            : 'bg-red-500/[0.08] ring-red-500/20 text-left'
                          : 'bg-gray-900/60 text-left ring-white/[0.06]'
                      } ${isAccordionLogMessage && isLogMsgCollapsed ? 'py-2' : 'py-3'}`}>
                        {isAccordionLogMessage && isLogMsgCollapsed ? (
                          <p className="font-body text-xs text-gray-600 dark:text-gray-400">Message collapsed</p>
                        ) : (
                        msg.type === 'agent_input' && msg.fullQuery ? (
                          <div>
                            <button
                              onClick={() => setExpandedMsg(expandedMsg === msg.id ? null : msg.id)}
                              className="flex items-center gap-2 w-full text-left"
                            >
                              <FileText className="w-3.5 h-3.5 text-purple-400 shrink-0" />
                              <span className="font-body text-xs font-semibold text-purple-300">Actual Agent Input</span>
                              <span className="text-[10px] text-purple-400/50 font-body ml-1">({msg.fullQuery.length} chars)</span>
                              <ChevronDown className={`w-3.5 h-3.5 text-purple-400/50 ml-auto transition-transform ${expandedMsg === msg.id ? 'rotate-180' : ''}`} />
                            </button>
                            {expandedMsg === msg.id && (
                              <div className="mt-2 pt-2 border-t border-purple-500/15">
                                <pre className="whitespace-pre-wrap text-xs text-gray-700 dark:text-gray-300 font-body leading-relaxed max-h-[60vh] overflow-y-auto break-words">{msg.fullQuery}</pre>
                              </div>
                            )}
                          </div>
                        ) : usesWorkflowMd ? (
                          <div className="overflow-hidden">
                            {msg.isStreaming && (
                              <div className="flex items-center gap-2 mb-2 pb-2 border-b border-blue-500/20">
                                <Loader2 className="w-3 h-3 text-blue-400 animate-spin" />
                                <span className="font-body text-xs text-blue-400">Streaming response...</span>
                              </div>
                            )}
                            {msg.type === 'agent_complete' && !msg.isStreaming && (
                              <div className="flex items-center gap-2 mb-2 pb-2 border-b border-green-500/20">
                                <CheckCircle className="w-3 h-3 text-green-400" />
                                <span className="font-body text-xs text-green-400">Agent completed</span>
                              </div>
                            )}
                            <div className={`${isLongMarkdownResponse && !isMsgExpanded ? 'max-h-[60vh] overflow-hidden' : ''}`}>
                              {isCompanyAiSolutionsReport(msg.content) ? (
                                <CompanyAiSolutionsView content={msg.content} />
                              ) : (
                                <WorkflowAgentMarkdown content={msg.content} isStreaming={msg.isStreaming} />
                              )}
                            </div>
                            {msg.bpmn_xml && (
                              <div className="mt-3 border border-gray-700/50 rounded-lg overflow-hidden">
                                <BPMNViewer xml={msg.bpmn_xml} />
                              </div>
                            )}
                            {msg.download_url && (
                              <div className="mt-3">
                                <a
                                  href={msg.download_url}
                                  download
                                  className="inline-flex items-center gap-2 px-4 py-2.5 bg-gradient-to-r from-emerald-600 to-emerald-500 hover:from-emerald-500 hover:to-emerald-400 text-gray-900 dark:text-white text-sm font-semibold rounded-lg shadow-lg shadow-emerald-900/30 transition-all duration-200 hover:shadow-emerald-900/50 hover:scale-[1.02]"
                                >
                                  <Download className="w-4 h-4" />
                                  Download Presentation (.pptx)
                                </a>
                              </div>
                            )}
                            {isLongMarkdownResponse && (
                              <button
                                onClick={() => setExpandedMsg(isMsgExpanded ? null : msg.id)}
                                className="mt-2 flex items-center gap-1 text-xs text-primary-400 hover:text-primary-300 font-body transition-colors"
                              >
                                {isMsgExpanded ? <><ChevronUp className="w-3 h-3" /> Show less</> : <><ChevronDown className="w-3 h-3" /> Show full response</>}
                              </button>
                            )}
                          </div>
                        ) : (
                          <div>
                            <div className={`relative ${isLongPlainResponse && !isMsgExpanded ? 'max-h-[60vh] overflow-hidden' : ''}`}>
                              <p className="font-body text-sm text-gray-200 whitespace-pre-wrap break-words">{msg.content}</p>
                            </div>
                            {isLongPlainResponse && (
                              <button
                                onClick={() => setExpandedMsg(isMsgExpanded ? null : msg.id)}
                                className="mt-2 flex items-center gap-1 text-xs text-primary-400 hover:text-primary-300 font-body transition-colors"
                              >
                                {isMsgExpanded ? <><ChevronUp className="w-3 h-3" /> Show less</> : <><ChevronDown className="w-3 h-3" /> Show full response</>}
                              </button>
                            )}
                          </div>
                        )
                        )}
                      </div>
                      {(msg.type === 'agent_complete' || msg.type === 'agent_failed') &&
                        !msg.isStreaming &&
                        msg.stepNumber != null &&
                        lastStepInputsRef.current[msg.stepNumber] != null && (
                          <div className="mt-2 flex items-center gap-2">
                            <button
                              type="button"
                              onClick={() => {
                                const sn = msg.stepNumber!;
                                setRerunModal({
                                  stepNumber: sn,
                                  agentLabel: msg.agentName || `Step ${sn}`,
                                  input: lastStepInputsRef.current[sn] || '',
                                  attachments: [...(stepPromptAttachments[sn] ?? [])],
                                });
                              }}
                              disabled={isExecuting || rerunningStep !== null}
                              className="inline-flex items-center gap-1.5 rounded-lg border border-primary-500/25 bg-primary-500/10 px-2.5 py-1.5 font-body text-[11px] font-medium text-primary-200 transition-colors hover:border-primary-500/40 hover:bg-primary-500/15 hover:text-primary-100 disabled:cursor-not-allowed disabled:opacity-50"
                              title="Edit the input and re-run this agent"
                            >
                              {rerunningStep === msg.stepNumber ? (
                                <Loader2 className="h-3 w-3 animate-spin" />
                              ) : (
                                <RefreshCw className="h-3 w-3" />
                              )}
                              {rerunningStep === msg.stepNumber ? 'Re-running…' : 'Re-run this step'}
                            </button>
                          </div>
                        )}
                    </div>
                  </div>
                    );
                  })}
                  <div ref={chatEndRef} className="h-px shrink-0" aria-hidden />
                </div>
              </div>

              {currentFollowUp && (
                <div className="p-4 border-t border-yellow-500/10 bg-gradient-to-r from-yellow-500/[0.04] to-transparent">
                  <div className="flex items-start gap-3 mb-3">
                    <div className="w-8 h-8 rounded-xl bg-yellow-500/10 ring-1 ring-yellow-500/15 flex items-center justify-center shrink-0">
                      <MessageSquare className="w-4 h-4 text-yellow-400" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <p className="font-body text-xs font-semibold text-yellow-400">
                          Agent needs your input
                        </p>
                        <span className="px-2 py-0.5 text-[10px] font-body font-medium text-yellow-500/60 bg-yellow-500/[0.06] rounded-md ring-1 ring-yellow-500/10">
                          {currentFollowUp.agentName} &middot; Step {currentFollowUp.stepNumber}
                        </span>
                        {followUpQueue.length > 1 && <span className="text-[10px] text-yellow-600 font-body">+{followUpQueue.length - 1} more questions queued</span>}
                      </div>
                      <p className="font-body text-sm text-gray-200 whitespace-pre-wrap leading-relaxed">
                        {currentFollowUp.question}
                      </p>
                    </div>
                  </div>
                  <div className="flex gap-2 ml-11">
                    <input
                      type="text"
                      value={followUpInput}
                      onChange={(e) => setFollowUpInput(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleFollowUpSubmit()}
                      placeholder="Type your answer and press Enter..."
                      className="flex-1 bg-black/20 border border-yellow-500/15 rounded-xl px-4 py-2.5 text-sm text-gray-200 font-body placeholder-gray-400 dark:placeholder-gray-600 focus:border-yellow-500/30 focus:ring-1 focus:ring-yellow-500/10 focus:outline-none transition-all"
                      autoFocus
                    />
                    <button
                      onClick={handleFollowUpSubmit}
                      disabled={isSubmittingFollowUp || !followUpInput.trim()}
                      className="px-4 py-2.5 bg-gradient-to-r from-yellow-500 to-amber-600 hover:from-yellow-400 hover:to-amber-500 disabled:from-gray-700 disabled:to-gray-700 disabled:text-gray-500 text-gray-900 dark:text-white text-sm font-body font-semibold rounded-xl transition-all shadow-lg shadow-yellow-900/20 flex items-center gap-2"
                    >
                      {isSubmittingFollowUp ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                      Reply
                    </button>
                  </div>
                </div>
              )}

              {batchApproval &&
                !currentFollowUp &&
                batchApproval.nextStepNumbers.length > 0 && (
                  <div className="p-4 border-t border-gray-200 dark:border-white/[0.06] bg-zinc-950/60">
                    <p className="font-body text-xs font-semibold text-zinc-200 mb-0.5">
                      Next agent input (raw)
                    </p>
                    <p className="font-body text-[11px] text-zinc-500 mb-3">
                      Resolved prompt that will be sent next — edit before Continue, or leave as-is.
                    </p>
                    <div className="space-y-3">
                      {batchApproval.nextStepNumbers.map((sn, idx) => {
                        const key = String(sn);
                        const label =
                          batchApproval.nextAgents[idx] ?? `Step ${sn}`;
                        return (
                          <div key={sn}>
                            <label
                              htmlFor={`wf-batch-input-${key}`}
                              className="mb-1 block font-body text-[10px] font-medium uppercase tracking-wide text-zinc-500"
                            >
                              {label}
                              <span className="font-mono normal-case tracking-normal text-zinc-600">
                                {' '}
                                · #{sn}
                              </span>
                            </label>
                            <WorkflowBatchPromptEditor
                              id={`wf-batch-input-${key}`}
                              value={batchApproval.nextStepInputs[key] ?? ''}
                              onChange={(v) => {
                                setBatchApproval((prev) =>
                                  prev
                                    ? {
                                        ...prev,
                                        nextStepInputs: {
                                          ...prev.nextStepInputs,
                                          [key]: v,
                                        },
                                      }
                                    : null,
                                );
                              }}
                              placeholder="Edit the resolved prompt before continuing…"
                            />
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

              {batchApproval && !currentFollowUp && (
                <div className="p-4 border-t border-teal-500/10 bg-gradient-to-r from-teal-500/[0.04] to-transparent">
                  <div className="flex items-start gap-3 mb-3">
                    <div className="w-8 h-8 rounded-xl bg-teal-500/10 ring-1 ring-teal-500/15 flex items-center justify-center shrink-0">
                      <ChevronRight className="w-4 h-4 text-teal-400" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-body text-xs font-semibold text-teal-400 mb-1">
                        Ready for next batch
                      </p>
                      <p className="font-body text-sm text-gray-200 leading-relaxed">
                        Next up:{' '}
                        <span className="font-semibold text-gray-900 dark:text-white">
                          {batchApproval.nextAgents.join(', ')}
                        </span>
                      </p>
                      <p className="font-body text-xs text-zinc-500 mt-1">
                        Continue to run the next batch, or stop the workflow here.
                      </p>
                    </div>
                  </div>
                  <div className="flex gap-2 ml-11">
                    <button
                      onClick={handleBatchContinue}
                      disabled={isSubmittingBatchApproval}
                      className="inline-flex items-center gap-2 px-4 py-2.5 bg-gradient-to-r from-teal-500 to-emerald-600 hover:from-teal-400 hover:to-emerald-500 disabled:from-gray-700 disabled:to-gray-700 disabled:text-gray-500 text-gray-900 dark:text-white text-sm font-body font-semibold rounded-xl transition-all shadow-lg shadow-teal-900/20"
                    >
                      {isSubmittingBatchApproval ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4 fill-current" />}
                      Continue
                    </button>
                    <button
                      onClick={handleBatchStop}
                      disabled={isSubmittingBatchApproval}
                      className="inline-flex items-center gap-2 px-4 py-2.5 border border-red-500/20 bg-red-500/[0.06] hover:bg-red-500/[0.12] disabled:opacity-40 text-red-400 text-sm font-body font-medium rounded-xl transition-all"
                    >
                      <X className="w-4 h-4" />
                      Stop here
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {currentWorkflowId && (
            <div className="mb-8 overflow-hidden rounded-3xl border border-gray-200 dark:border-white/[0.07] bg-white dark:bg-zinc-900/35 shadow-[0_20px_50px_-28px_rgba(0,0,0,0.55)] ring-1 ring-white/[0.04] backdrop-blur-md">
              <div className="border-b border-gray-200 dark:border-white/[0.06] bg-black/15 px-4 py-4 sm:px-5">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500/25 to-purple-600/15 ring-1 ring-violet-500/25">
                      <Database className="h-5 w-5 text-violet-300" />
                    </div>
                    <div>
                      <h3 className="flex items-center gap-2 font-heading text-base font-semibold tracking-tight text-gray-900 dark:text-white">
                        Past runs
                        {executions.length > 0 && (
                          <span className="rounded-md bg-gray-100 dark:bg-white/[0.06] px-1.5 py-0.5 font-mono text-[10px] font-bold text-zinc-400">
                            {executions.length}
                          </span>
                        )}
                      </h3>
                      <p className="mt-0.5 font-body text-xs text-zinc-500">History for this saved agent, with per-step inputs and outputs</p>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 self-start sm:self-auto">
                    <button
                      type="button"
                      onClick={() => void refreshExecutions()}
                      disabled={executionsRefreshing}
                      aria-label="Refresh past runs"
                      title="Fetch latest runs from the server"
                      className="inline-flex items-center gap-1.5 rounded-xl border border-gray-200 dark:border-white/[0.06] bg-white/[0.03] px-3 py-2 font-body text-xs font-medium text-zinc-400 transition-all hover:border-white/[0.1] hover:bg-gray-100 dark:hover:bg-white/[0.06] hover:text-zinc-200 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <RefreshCw className={`h-3.5 w-3.5 ${executionsRefreshing ? 'animate-spin' : ''}`} />
                      Refresh
                    </button>
                    {selectedExecution && (
                      <>
                        <button
                          type="button"
                          onClick={() => {
                            setSelectedExecution(null);
                            setExpandedHistoryMsg(null);
                          }}
                          className="inline-flex items-center gap-1.5 rounded-xl border border-gray-200 dark:border-white/[0.06] bg-white/[0.03] px-3 py-2 font-body text-xs font-medium text-zinc-400 transition-all hover:border-white/[0.1] hover:bg-gray-100 dark:hover:bg-white/[0.06] hover:text-zinc-200"
                        >
                          <ArrowLeft className="h-3.5 w-3.5" /> Back to list
                        </button>
                        <button
                          type="button"
                          onClick={() => void handleDeleteExecution(selectedExecution.execution)}
                          aria-label="Delete this run"
                          title="Delete this run"
                          className="inline-flex items-center gap-1.5 rounded-xl border border-red-500/20 bg-red-500/[0.08] px-3 py-2 font-body text-xs font-medium text-red-300/90 transition-all hover:border-red-500/35 hover:bg-red-500/15 hover:text-red-200"
                        >
                          <Trash2 className="h-3.5 w-3.5" /> Delete run
                        </button>
                      </>
                    )}
                  </div>
                </div>
              </div>

              {executions.length === 0 ? (
                <div className="p-8 text-center">
                  <Play className="w-6 h-6 text-gray-700 mx-auto mb-2" />
                  <p className="text-sm text-gray-500 font-body font-medium mb-1">No runs yet</p>
                  <p className="text-xs text-gray-400 dark:text-gray-600 font-body">Run this agent to see a timestamped log of every execution here</p>
                </div>
              ) : !selectedExecution ? (
                <div className="p-3 space-y-1.5 max-h-[300px] overflow-y-auto">
                  {executions.map((exec) => (
                    <div
                      key={exec.id}
                      className="flex gap-2 rounded-xl ring-1 ring-gray-200 dark:ring-white/[0.03] bg-gray-100 dark:bg-gray-800/30 transition-all hover:ring-gray-300 dark:hover:ring-white/[0.06] hover:bg-gray-200 dark:hover:bg-gray-700/40 group"
                    >
                      <button
                        type="button"
                        onClick={() => loadExecutionDetail(exec)}
                        className="min-w-0 flex-1 text-left p-3 rounded-xl transition-all"
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className={`w-2 h-2 shrink-0 rounded-full ${exec.status === 'completed' ? 'bg-green-500' : exec.status === 'failed' ? 'bg-red-500' : 'bg-yellow-500 animate-pulse'}`} />
                            <span className="font-body text-xs font-medium text-gray-700 dark:text-gray-300">
                              {new Date(exec.started_at).toLocaleDateString()} {new Date(exec.started_at).toLocaleTimeString()}
                            </span>
                          </div>
                          <div className="flex shrink-0 items-center gap-2">
                            <span className={`px-2 py-0.5 text-[10px] font-body font-bold rounded-full ${
                              exec.status === 'completed' ? 'bg-green-500/10 text-green-400' :
                              exec.status === 'failed' ? 'bg-red-500/10 text-red-400' :
                              'bg-yellow-500/10 text-yellow-400'
                            }`}>
                              {exec.status}
                            </span>
                            <ChevronDown className="w-3 h-3 text-gray-400 dark:text-gray-600 group-hover:text-gray-400 -rotate-90" />
                          </div>
                        </div>
                        {exec.completed_at && (
                          <div className="mt-1 text-[10px] text-gray-400 dark:text-gray-600 font-body">
                            Duration: {Math.round((new Date(exec.completed_at).getTime() - new Date(exec.started_at).getTime()) / 1000)}s
                          </div>
                        )}
                      </button>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          void handleDeleteExecution(exec);
                        }}
                        aria-label="Delete this run"
                        title="Delete this run"
                        className="shrink-0 self-stretch px-3 rounded-r-xl border-l border-gray-200 dark:border-white/[0.06] text-zinc-500 transition-colors hover:bg-red-500/15 hover:text-red-300"
                      >
                        <Trash2 className="mx-auto h-4 w-4" />
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="flex-1 p-4 space-y-3">
                  {loadingExecution ? (
                    <div className="flex items-center justify-center py-8">
                      <Loader2 className="w-5 h-5 text-primary-400 animate-spin" />
                      <span className="ml-2 text-xs text-gray-500 font-body">Loading execution...</span>
                    </div>
                  ) : (
                    selectedExecution.steps.map((step, idx) => (
                      <div key={`hist-${step.step_number}-${idx}`} className="w-full">
                        <div className="flex items-center gap-2 mb-1.5">
                          {step.status === 'completed' ? (
                            <CheckCircle className="w-4 h-4 text-green-400" />
                          ) : (
                            <AlertTriangle className="w-4 h-4 text-red-400" />
                          )}
                        </div>
                        <div className="flex items-center gap-2 mb-1">
                          <span className="font-body text-xs font-semibold text-gray-700 dark:text-gray-300">
                            Step {step.step_number} — {step.agent_name || step.agent_id}
                          </span>
                          <span className="text-xs text-gray-400 dark:text-gray-600">
                            {new Date(step.created_at).toLocaleTimeString()}
                          </span>
                        </div>

                        {(step.query_length ?? (step.query?.length || 0)) > 0 && (
                          <div className="rounded-xl px-4 py-3 mb-2 bg-purple-500/10 border border-purple-500/20">
                            <button
                              onClick={() => {
                                const key = `q-${step.step_number}`;
                                const opening = expandedHistoryMsg !== key;
                                setExpandedHistoryMsg(opening ? key : null);
                                if (opening && selectedExecution) {
                                  void ensureStepBody(selectedExecution.execution.id, step.step_number);
                                }
                              }}
                              className="flex items-center gap-2 w-full text-left"
                            >
                              <FileText className="w-3.5 h-3.5 text-purple-400 shrink-0" />
                              <span className="font-body text-xs font-semibold text-purple-300">Agent Input</span>
                              <span className="text-[10px] text-purple-400/50 font-body ml-1">({step.query_length ?? step.query?.length ?? 0} chars)</span>
                              <ChevronDown className={`w-3.5 h-3.5 text-purple-400/50 ml-auto transition-transform ${expandedHistoryMsg === `q-${step.step_number}` ? 'rotate-180' : ''}`} />
                            </button>
                            {expandedHistoryMsg === `q-${step.step_number}` && (
                              <div className="mt-2 pt-2 border-t border-purple-500/15">
                                {step.bodyLoading && !step.bodyLoaded ? (
                                  <div className="flex items-center gap-2 py-2">
                                    <Loader2 className="w-3.5 h-3.5 text-purple-400 animate-spin" />
                                    <span className="text-[11px] text-purple-300/70 font-body">Loading input…</span>
                                  </div>
                                ) : (
                                  <pre className="whitespace-pre-wrap text-xs text-gray-700 dark:text-gray-300 font-body leading-relaxed max-h-[40vh] overflow-y-auto break-words">{step.query || ''}</pre>
                                )}
                              </div>
                            )}
                          </div>
                        )}

                        <div className={`rounded-xl px-4 py-3 overflow-hidden ${
                          step.status === 'completed' ? 'bg-[#0d1117] border border-gray-700/50' : 'bg-red-500/10 border border-red-500/20'
                        }`}>
                          <div className="flex items-center gap-2 mb-2 pb-2 border-b border-gray-700/30">
                            {step.status === 'completed' ? (
                              <CheckCircle className="w-3 h-3 text-green-400" />
                            ) : (
                              <AlertTriangle className="w-3 h-3 text-red-400" />
                            )}
                            <span className={`font-body text-xs ${step.status === 'completed' ? 'text-green-400' : 'text-red-400'}`}>
                              {step.status === 'completed' ? 'Completed' : 'Failed'}
                            </span>
                            {(step.response_length ?? step.response?.length ?? 0) > 0 && (
                              <span className="ml-auto text-[10px] text-gray-500 font-body">
                                {step.response_length ?? step.response?.length ?? 0} chars
                              </span>
                            )}
                          </div>
                          {step.bodyLoaded ? (
                            <>
                              {isCompanyAiSolutionsReport(step.response || '') ? (
                                <CompanyAiSolutionsView content={step.response || ''} />
                              ) : (
                                <WorkflowAgentMarkdown content={step.response || ''} />
                              )}
                              {(step.response?.length || 0) > 500 && (
                                <button
                                  onClick={() => setExpandedHistoryMsg(expandedHistoryMsg === `r-${step.step_number}` ? null : `r-${step.step_number}`)}
                                  className="mt-2 text-[10px] text-primary-400/60 hover:text-primary-400 font-body"
                                >
                                  {expandedHistoryMsg === `r-${step.step_number}` ? 'Show less' : 'Show full response'}
                                </button>
                              )}
                            </>
                          ) : step.bodyLoading ? (
                            <div className="flex items-center gap-2 py-3">
                              <Loader2 className="w-4 h-4 text-primary-400 animate-spin" />
                              <span className="text-xs text-gray-500 font-body">Loading response…</span>
                            </div>
                          ) : (
                            <button
                              type="button"
                              onClick={() => {
                                if (selectedExecution) void ensureStepBody(selectedExecution.execution.id, step.step_number);
                              }}
                              className="text-[11px] text-primary-400/70 hover:text-primary-400 font-body underline underline-offset-2"
                            >
                              Show response
                            </button>
                          )}
                          {step.bodyLoaded && step.bpmn_xml && (
                            <div className="mt-3 border border-gray-700/50 rounded-lg overflow-hidden">
                              <BPMNViewer xml={step.bpmn_xml} />
                            </div>
                          )}
                          {step.download_url && (
                            <a
                              href={step.download_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="mt-2 inline-flex items-center gap-1.5 px-3 py-1.5 bg-primary-500/15 hover:bg-primary-500/25 text-primary-400 rounded-lg text-xs font-body font-medium transition-colors"
                            >
                              <Download className="w-3 h-3" /> Download
                            </a>
                          )}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>
          )}

          {activeView === 'builder' && workflow ? (
            <div className="mt-8 flex flex-col gap-2 rounded-2xl border border-gray-200 dark:border-white/[0.08] bg-zinc-900/50 px-4 py-4 shadow-[0_12px_40px_-24px_rgba(0,0,0,0.55)] ring-1 ring-white/[0.04] backdrop-blur-sm sm:flex-row sm:flex-wrap sm:items-center sm:justify-end sm:gap-3 sm:px-5 sm:py-4">
              {/* Execution mode toggle */}
              <div className="flex items-center gap-1.5 rounded-xl border border-gray-200 dark:border-white/[0.08] bg-black/20 p-1">
                <button
                  onClick={() => setStepMode('auto')}
                  disabled={isExecuting}
                  className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 font-body text-xs font-medium transition-all ${stepMode === 'auto' ? 'bg-zinc-700 text-gray-900 dark:text-white shadow-sm' : 'text-zinc-400 hover:text-zinc-200'} disabled:cursor-not-allowed disabled:opacity-50`}
                  title="Run all agents automatically without pausing"
                >
                  <Zap className="h-3.5 w-3.5" />
                  Auto
                </button>
                <button
                  onClick={() => setStepMode('step')}
                  disabled={isExecuting}
                  className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 font-body text-xs font-medium transition-all ${stepMode === 'step' ? 'bg-zinc-700 text-gray-900 dark:text-white shadow-sm' : 'text-zinc-400 hover:text-zinc-200'} disabled:cursor-not-allowed disabled:opacity-50`}
                  title="Pause after each batch and ask for confirmation before continuing"
                >
                  <ChevronRight className="h-3.5 w-3.5" />
                  Step-by-step
                </button>
              </div>
              <button
                onClick={handleSave}
                disabled={!isAuthenticated || isSaving}
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-gray-200 dark:border-white/[0.1] bg-gray-100 dark:bg-white/[0.05] px-4 py-2.5 font-body text-sm font-medium text-zinc-100 shadow-sm transition-all hover:border-white/[0.14] hover:bg-white/[0.09] disabled:cursor-not-allowed disabled:opacity-40 sm:w-auto"
                title={isAuthenticated ? 'Save this agent to My agents' : 'Sign in to save'}
              >
                {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4 text-zinc-400" />}
                Save to My agents
              </button>
              <button
                onClick={handleExecute}
                disabled={isExecuting}
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-600 px-5 py-2.5 font-body text-sm font-semibold text-gray-900 dark:text-white shadow-lg shadow-emerald-950/35 transition-all hover:from-emerald-400 hover:to-teal-500 disabled:cursor-not-allowed disabled:from-zinc-700 disabled:to-zinc-700 disabled:text-zinc-500 disabled:shadow-none sm:w-auto"
                title="Run this agent"
              >
                {isExecuting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4 fill-current" />}
                {isExecuting ? 'Running…' : 'Run agent'}
              </button>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
