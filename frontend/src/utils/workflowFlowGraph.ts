import type { Agent } from '../services/api';

/** Output shape produced by an edge-level Prompt Harness (LLM refinement between steps). */
export type PromptHarnessOutputFormat = 'markdown' | 'json' | 'text';

/** Stored on the *target* step, keyed by upstream step number string (e.g. `"1"`). */
export interface PromptHarnessEdgeConfig {
  /** Env-style overrides merged over the downstream agent's workflow credentials (LLM_PROVIDER, models, keys, …). */
  default_config?: Record<string, string>;
  /** Instructions for how to reshape the upstream agent output. */
  expected_output_description?: string;
  /** Defaults to markdown when omitted. */
  output_format?: PromptHarnessOutputFormat;
  /** Hard cap on harness output length after the LLM (Unicode code points); enforced server-side. */
  max_output_chars?: number;
}

/** Minimal step shape for building the flow graph (matches Agent Studio `WorkflowStep`). */
export interface FlowGraphStepInput {
  step_number: number;
  agent_id: string;
  agent: string;
  agent_name?: string;
  depends_on?: number[];
  input_mapping?: Record<string, string>;
  prompt_harness?: Record<string, PromptHarnessEdgeConfig>;
  status?: 'pending' | 'running' | 'completed' | 'failed';
}

export interface WorkflowFlowNode {
  id: string;
  step_number: number;
  title: string;
  agent_id: string;
  agent_name: string;
  logoUrl?: string;
  status: NonNullable<FlowGraphStepInput['status']>;
}

export interface WorkflowFlowEdge {
  from: number;
  to: number;
  label?: string;
}

export interface WorkflowFlowGraph {
  nodes: WorkflowFlowNode[];
  edges: WorkflowFlowEdge[];
}

function normalizeLogoUrl(raw: string | undefined): string | undefined {
  let logoUrl = raw?.trim();
  if (
    !logoUrl ||
    logoUrl.startsWith('http://') ||
    logoUrl.startsWith('https://') ||
    logoUrl.startsWith('/') ||
    logoUrl.startsWith('data:')
  ) {
    return logoUrl || undefined;
  }
  return `/${logoUrl}`;
}

function edgeLabelForDep(step: FlowGraphStepInput, dep: number): string | undefined {
  const mapping = step.input_mapping || {};
  let desc = mapping[`description_${dep}`] || '';
  if (!desc && mapping.description && String(mapping.from_step) === String(dep)) {
    desc = mapping.description;
  }
  const trimmed = desc.replace(/\s+/g, ' ').trim();
  return trimmed ? trimmed.slice(0, 56) : undefined;
}

export function computeLayers(steps: FlowGraphStepInput[]): Map<number, number> {
  const byNum = new Map(steps.map((s) => [s.step_number, s]));
  const memo = new Map<number, number>();

  function layerOf(sn: number): number {
    if (memo.has(sn)) return memo.get(sn)!;
    const s = byNum.get(sn);
    if (!s) {
      memo.set(sn, 0);
      return 0;
    }
    const deps = s.depends_on?.length ? s.depends_on : [];
    if (deps.length === 0) {
      memo.set(sn, 0);
      return 0;
    }
    const L = Math.max(...deps.map((d) => layerOf(d))) + 1;
    memo.set(sn, L);
    return L;
  }

  steps.forEach((s) => layerOf(s.step_number));
  return memo;
}

/**
 * Canonical JSON flow for the Agent Studio diagram: nodes (titles, agents, logos) + DAG edges.
 * Always derived from the current step list so edits and live run status stay in sync.
 */
export function buildWorkflowFlowGraph(
  steps: FlowGraphStepInput[],
  agents: Agent[] | null | undefined,
): WorkflowFlowGraph {
  const agentById = new Map((agents ?? []).map((a) => [a.id, a]));

  const nodes: WorkflowFlowNode[] = steps.map((s) => {
    const catalog = agentById.get(s.agent_id);
    const agent_name = (s.agent_name || catalog?.name || s.agent_id || '').trim() || s.agent_id;
    const title = (s.agent || `Step ${s.step_number}`).trim() || `Step ${s.step_number}`;
    return {
      id: `S${s.step_number}`,
      step_number: s.step_number,
      title,
      agent_id: s.agent_id,
      agent_name,
      logoUrl: normalizeLogoUrl(catalog?.logo),
      status: s.status || 'pending',
    };
  });

  const edges: WorkflowFlowEdge[] = [];
  for (const s of steps) {
    const deps = s.depends_on || [];
    for (const dep of deps) {
      edges.push({
        from: dep,
        to: s.step_number,
        label: edgeLabelForDep(s, dep),
      });
    }
  }

  return { nodes, edges };
}

/** Fixed node box for grid layout (matches AgentWorkflowFlowDiagram cards). */
export const WF_NODE_WIDTH = 272;
export const WF_NODE_HEIGHT = 132;
export const WF_H_GAP = 72;
export const WF_V_GAP = 44;
export const WF_PAD = 56;

/**
 * Layered DAG layout: columns by dependency depth, vertical stack per column,
 * columns vertically centered to the tallest — no node overlap at default positions.
 */
export function computeLayeredLayout(columns: number[][]): {
  positions: Map<number, { x: number; y: number }>;
  canvasWidth: number;
  canvasHeight: number;
} {
  const n = columns.length;
  if (n === 0) {
    return { positions: new Map(), canvasWidth: WF_PAD * 2, canvasHeight: WF_PAD * 2 };
  }

  const colHeights = columns.map(
    (col) => col.length * WF_NODE_HEIGHT + Math.max(0, col.length - 1) * WF_V_GAP,
  );
  const maxH = Math.max(...colHeights);

  const positions = new Map<number, { x: number; y: number }>();
  for (let ci = 0; ci < n; ci++) {
    const col = columns[ci]!;
    const colH = colHeights[ci]!;
    const y0 = WF_PAD + (maxH - colH) / 2;
    const x = WF_PAD + ci * (WF_NODE_WIDTH + WF_H_GAP);
    let y = y0;
    for (const sn of col) {
      positions.set(sn, { x, y });
      y += WF_NODE_HEIGHT + WF_V_GAP;
    }
  }

  const canvasWidth = WF_PAD * 2 + n * WF_NODE_WIDTH + Math.max(0, n - 1) * WF_H_GAP;
  const canvasHeight = WF_PAD * 2 + maxH;
  return { positions, canvasWidth, canvasHeight };
}

/** localStorage payload: step number → canvas position */
export type WorkflowDiagramStoredPositions = Record<string, { x: number; y: number }>;

const WORKFLOW_DIAGRAM_POS_PREFIX = 'agents.workflowDiagram.positions.v1:' as const;

/** Key for persisted node positions when a workflow has a server id. */
export function workflowDiagramLayoutStorageKey(workflowId: string | undefined | null): string | null {
  const id = typeof workflowId === 'string' ? workflowId.trim() : '';
  return id ? `${WORKFLOW_DIAGRAM_POS_PREFIX}${id}` : null;
}

/** Key for workflows not saved yet — stable for current name + step set. */
export function workflowDiagramLayoutDraftKey(workflowName: string, stepNumbers: number[]): string {
  const sig = stepNumbers.slice().sort((a, b) => a - b).join('.');
  const name = encodeURIComponent(workflowName.trim().slice(0, 64) || 'untitled');
  return `${WORKFLOW_DIAGRAM_POS_PREFIX}draft:${name}:${sig}`;
}

export function parseWorkflowDiagramStoredPositions(raw: string | null): Map<number, { x: number; y: number }> {
  const out = new Map<number, { x: number; y: number }>();
  if (!raw) return out;
  try {
    const o = JSON.parse(raw) as unknown;
    if (!o || typeof o !== 'object') return out;
    for (const [k, v] of Object.entries(o as WorkflowDiagramStoredPositions)) {
      const sn = Number(k);
      if (!Number.isFinite(sn)) continue;
      if (
        v &&
        typeof v === 'object' &&
        typeof (v as { x: unknown }).x === 'number' &&
        typeof (v as { y: unknown }).y === 'number'
      ) {
        out.set(sn, { x: (v as { x: number }).x, y: (v as { y: number }).y });
      }
    }
  } catch {
    /* ignore malformed */
  }
  return out;
}

export function serializeWorkflowDiagramStoredPositions(
  positions: Map<number, { x: number; y: number }>,
): string {
  const o: WorkflowDiagramStoredPositions = {};
  for (const [sn, p] of positions) {
    o[String(sn)] = { x: p.x, y: p.y };
  }
  return JSON.stringify(o);
}
