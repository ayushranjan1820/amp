import { useCallback, useEffect, useLayoutEffect, useMemo, useRef } from 'react';
import createEngine, { DiagramModel } from '@projectstorm/react-diagrams';
import { CanvasWidget, AbstractReactFactory } from '@projectstorm/react-canvas-core';
import { DiagramEngine, PortWidget } from '@projectstorm/react-diagrams-core';
import { DefaultNodeModel as DiagramDefaultNodeModel } from '@projectstorm/react-diagrams-defaults';
import type { Agent } from '../services/api';
import {
  buildWorkflowFlowGraph,
  computeLayeredLayout,
  computeLayers,
  parseWorkflowDiagramStoredPositions,
  serializeWorkflowDiagramStoredPositions,
  WF_NODE_HEIGHT,
  WF_NODE_WIDTH,
  type FlowGraphStepInput,
} from '../utils/workflowFlowGraph';
import { HarnessLinkFactory, HarnessLinkModel } from './workflowHarnessLink';

interface AgentWorkflowFlowDiagramProps {
  workflowName: string;
  steps: FlowGraphStepInput[];
  agents?: Agent[] | null;
  isLive?: boolean;
  /** When set, node positions are loaded/saved under this localStorage key (survives refresh). */
  layoutStorageKey?: string | null;
  onStepClick?: (stepNumber: number) => void;
  onHarnessEdgeClick?: (fromStep: number, toStep: number) => void;
}

type StepStatus = NonNullable<FlowGraphStepInput['status']>;

interface AgentNodeExtras {
  stepNumber: number;
  title: string;
  agentName: string;
  agentId: string;
  logoUrl?: string;
  status: StepStatus;
  dependsOn: string;
  mappingSummary: string;
}

const STATUS_NODE_COLOR: Record<StepStatus, string> = {
  pending: 'rgb(24, 31, 46)',
  running: 'rgb(16, 39, 66)',
  completed: 'rgb(9, 66, 50)',
  failed: 'rgb(84, 27, 40)',
};

const STATUS_TEXT_CLASS: Record<StepStatus, string> = {
  pending: 'text-zinc-300',
  running: 'text-sky-300',
  completed: 'text-emerald-300',
  failed: 'text-rose-300',
};

function StepStatusBadge({ status }: { status: StepStatus }) {
  const textClass = STATUS_TEXT_CLASS[status];

  if (status === 'running') {
    return (
      <span
        className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-sky-400/40 bg-gradient-to-r from-sky-500/[0.18] via-cyan-500/[0.12] to-violet-500/[0.15] px-2.5 py-1 text-[10px] font-semibold leading-none text-sky-100 shadow-[0_0_20px_-8px_rgba(56,189,248,0.65)]"
        role="status"
        aria-live="polite"
        aria-label="Step is running"
      >
        <span className="relative flex h-3.5 w-3.5 shrink-0 items-center justify-center" aria-hidden>
          <svg
            className="absolute h-3.5 w-3.5 animate-spin text-sky-300"
            viewBox="0 0 24 24"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            <circle className="opacity-20" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
            <path
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
              className="opacity-90"
            />
          </svg>
        </span>
        <span className="tracking-wide">Running</span>
      </span>
    );
  }

  return (
    <span
      className={`shrink-0 rounded-md border border-gray-200 dark:border-white/15 bg-white/5 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide ${textClass}`}
    >
      {status.toUpperCase()}
    </span>
  );
}

class AgentNodeModel extends DiagramDefaultNodeModel {
  constructor(options: { name: string; color: string; extras: AgentNodeExtras }) {
    super({ name: options.name, color: options.color, type: 'agent-node' });
    this.getOptions().extras = options.extras;
  }

  get extras(): AgentNodeExtras {
    return this.getOptions().extras as AgentNodeExtras;
  }
}

function AgentNodeWidget({
  node,
  engine,
  onStepClick,
}: {
  node: AgentNodeModel;
  engine: DiagramEngine;
  onStepClick?: (stepNumber: number) => void;
}) {
  const inPort = node.getInPorts()[0];
  const outPort = node.getOutPorts()[0];
  const meta = node.extras;
  const avatarLabel = (meta.agentName || meta.agentId || 'A').slice(0, 1).toUpperCase();
  const isRunning = meta.status === 'running';

  const handleHeaderClick = () => {
    onStepClick?.(meta.stepNumber);
  };

  return (
    <div
      className={`wf-agent-node w-[340px] overflow-hidden rounded-2xl border bg-white dark:bg-zinc-950/90 shadow-[0_20px_55px_-28px_rgba(0,0,0,0.25)] dark:shadow-[0_20px_55px_-28px_rgba(0,0,0,0.9)] backdrop-blur-sm ${
        isRunning
          ? 'border-sky-500/45 shadow-[0_0_32px_-14px_rgba(56,189,248,0.45),0_20px_55px_-28px_rgba(0,0,0,0.9)] ring-1 ring-sky-400/25'
          : 'border-gray-200 dark:border-white/10'
      }`}
      aria-busy={isRunning}
    >
      <div
        className={`cursor-pointer border-b px-3 py-2.5 transition-colors ${
          isRunning
            ? 'border-sky-500/25 bg-gradient-to-r from-sky-500/[0.14] via-violet-500/[0.12] to-cyan-500/[0.14] hover:from-sky-500/20 hover:via-violet-500/16 hover:to-cyan-500/18'
            : 'border-gray-200 dark:border-white/10 bg-gradient-to-r from-violet-500/12 via-fuchsia-500/8 to-cyan-400/12 hover:from-violet-500/18 hover:via-fuchsia-500/12 hover:to-cyan-400/16'
        }`}
        role="button"
        tabIndex={0}
        aria-label={`Open details for step ${meta.stepNumber}`}
        onDoubleClick={handleHeaderClick}
        // onKeyDown={handleHeaderKeyDown}
      >
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="font-mono text-[10px] text-zinc-500">STEP {String(meta.stepNumber).padStart(2, '0')}</p>
            <p className="line-clamp-2 text-[13px] font-semibold leading-4 text-zinc-900 dark:text-zinc-100">{meta.title}</p>
          </div>
          <StepStatusBadge status={meta.status} />
        </div>
      </div>

      <div className="space-y-2 px-3 py-2.5">
        <div className="flex items-center gap-2.5">
          <div
            className={`h-8 w-8 shrink-0 overflow-hidden rounded-lg border bg-gray-100 dark:bg-zinc-900/80 ${
              isRunning ? 'border-sky-400/50 shadow-[0_0_12px_-4px_rgba(56,189,248,0.5)] ring-2 ring-sky-400/25 ring-offset-1 ring-offset-zinc-950' : 'border-gray-200 dark:border-white/10'
            }`}
          >
            {meta.logoUrl ? (
              <img src={meta.logoUrl} alt="" className="h-full w-full object-cover" loading="lazy" />
            ) : (
              <div className="flex h-full w-full items-center justify-center text-[11px] font-bold text-zinc-700 dark:text-zinc-300">
                {avatarLabel}
              </div>
            )}
          </div>
          <div className="min-w-0">
            <p className="truncate text-[11px] text-zinc-800 dark:text-zinc-200">{meta.agentName}</p>
            <p className="truncate font-mono text-[10px] text-zinc-500">{meta.agentId}</p>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div className="rounded-lg border border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-zinc-900/65 px-2 py-1.5">
            <p className="text-[9px] uppercase tracking-wide text-zinc-500">Depends on</p>
            <p className="truncate text-[10px] text-zinc-700 dark:text-zinc-300">{meta.dependsOn}</p>
          </div>
          <div className="rounded-lg border border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-zinc-900/65 px-2 py-1.5">
            <p className="text-[9px] uppercase tracking-wide text-zinc-500">Input mapping</p>
            <p className="truncate text-[10px] text-zinc-700 dark:text-zinc-300">{meta.mappingSummary}</p>
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between border-t border-gray-200 dark:border-white/10 px-3 py-2">
        <div className="flex items-center gap-2">
          {inPort ? (
            <PortWidget port={inPort} engine={engine}>
              <div className="wf-agent-port h-3 w-3 rounded-full border border-violet-300/60 bg-violet-500/90" />
            </PortWidget>
          ) : null}
          <span className="text-[10px] text-zinc-500">IN</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-zinc-500">OUT</span>
          {outPort ? (
            <PortWidget port={outPort} engine={engine}>
              <div className="wf-agent-port h-3 w-3 rounded-full border border-cyan-300/60 bg-cyan-500/90" />
            </PortWidget>
          ) : null}
        </div>
      </div>
    </div>
  );
}

class AgentNodeFactory extends AbstractReactFactory<AgentNodeModel, DiagramEngine> {
  private readonly getOnStepClick?: () => ((stepNumber: number) => void) | undefined;

  constructor(getOnStepClick?: () => ((stepNumber: number) => void) | undefined) {
    super('agent-node');
    this.getOnStepClick = getOnStepClick;
  }

  generateReactWidget(event: { model: AgentNodeModel }) {
    return <AgentNodeWidget node={event.model} engine={this.engine} onStepClick={this.getOnStepClick?.()} />;
  }

  generateModel() {
    return new AgentNodeModel({
      name: 'Step',
      color: STATUS_NODE_COLOR.pending,
      extras: {
        stepNumber: 0,
        title: 'Node',
        agentName: 'Agent',
        agentId: 'agent-id',
        status: 'pending',
        logoUrl: undefined,
        dependsOn: 'None',
        mappingSummary: 'No input mapping',
      },
    });
  }
}

export default function AgentWorkflowFlowDiagram({
  workflowName,
  steps,
  agents,
  isLive,
  layoutStorageKey,
  onStepClick,
  onHarnessEdgeClick,
}: AgentWorkflowFlowDiagramProps) {
  const onStepClickRef = useRef<typeof onStepClick>(onStepClick);
  const onHarnessEdgeClickRef = useRef<typeof onHarnessEdgeClick>(onHarnessEdgeClick);
  const stepsRef = useRef(steps);
  const agentsRef = useRef(agents);
  const positionsOverrideRef = useRef<Map<number, { x: number; y: number }>>(new Map());
  const persistTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastPersistedJsonRef = useRef<string>('');

  useEffect(() => {
    onStepClickRef.current = onStepClick;
  }, [onStepClick]);

  useEffect(() => {
    onHarnessEdgeClickRef.current = onHarnessEdgeClick;
  }, [onHarnessEdgeClick]);

  useEffect(() => {
    stepsRef.current = steps;
  }, [steps]);

  useEffect(() => {
    agentsRef.current = agents;
  }, [agents]);

  useEffect(() => {
    return () => {
      if (persistTimerRef.current) clearTimeout(persistTimerRef.current);
    };
  }, []);

  const diagramStructureKey = useMemo(
    () =>
      steps
        .map((s) =>
          [
            s.step_number,
            (s.depends_on ?? []).slice().sort((a, b) => a - b).join(','),
            s.agent_id,
            s.agent ?? '',
            s.agent_name ?? '',
            [...Object.keys(s.prompt_harness ?? {})].sort().join(','),
            s.input_mapping ? JSON.stringify(s.input_mapping) : '',
          ].join('::'),
        )
        .join('|'),
    [steps],
  );

  const catalogSig = useMemo(
    () => (agents ?? []).map((a) => `${a.id}:${a.logo ?? ''}`).sort().join('|'),
    [agents],
  );

  /** Dependency columns that only change when `diagramStructureKey` changes (not on step status ticks). */
  const structuralColumns = useMemo(() => {
    const layers = computeLayers(steps);
    const maxLayer = Math.max(0, ...layers.values());
    const out: number[][] = Array.from({ length: maxLayer + 1 }, () => []);
    for (const s of steps) {
      const layer = layers.get(s.step_number) ?? 0;
      out[layer]!.push(s.step_number);
    }
    out.forEach((column) => column.sort((a, b) => a - b));
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- key covers structural fields; status-only updates must not reset the canvas
  }, [diagramStructureKey]);

  const { canvasWidth, canvasHeight } = useMemo(
    () => computeLayeredLayout(structuralColumns),
    [structuralColumns],
  );

  useLayoutEffect(() => {
    if (typeof localStorage === 'undefined') return;
    if (!layoutStorageKey) {
      positionsOverrideRef.current = new Map();
      lastPersistedJsonRef.current = '';
      return;
    }
    positionsOverrideRef.current = parseWorkflowDiagramStoredPositions(localStorage.getItem(layoutStorageKey));
    lastPersistedJsonRef.current = '';
  }, [layoutStorageKey]);

  const engine = useMemo(() => {
    const nextEngine = createEngine({
      registerDefaultZoomCanvasAction: false,
      registerDefaultPanAndZoomCanvasAction: false,
      repaintDebounceMs: 4,
    });
    nextEngine.setModel(new DiagramModel());
    nextEngine.getNodeFactories().registerFactory(new AgentNodeFactory(() => onStepClickRef.current));
    nextEngine.getLinkFactories().registerFactory(
      new HarnessLinkFactory(() => ({
        steps: stepsRef.current,
        onHarnessClick: (from, to) => onHarnessEdgeClickRef.current?.(from, to),
      })),
    );
    return nextEngine;
  }, []);

  const schedulePersistPositions = useCallback(() => {
    const key = layoutStorageKey;
    if (!key || typeof localStorage === 'undefined') return;
    if (persistTimerRef.current) clearTimeout(persistTimerRef.current);
    persistTimerRef.current = setTimeout(() => {
      persistTimerRef.current = null;
      const model = engine.getModel();
      const map = new Map<number, { x: number; y: number }>();
      for (const node of model.getNodes()) {
        if (!(node instanceof AgentNodeModel)) continue;
        const pt = node.getPosition();
        map.set(node.extras.stepNumber, { x: pt.x, y: pt.y });
      }
      const json = serializeWorkflowDiagramStoredPositions(map);
      if (json === lastPersistedJsonRef.current) return;
      lastPersistedJsonRef.current = json;
      try {
        localStorage.setItem(key, json);
      } catch {
        /* quota / private mode */
      }
    }, 350);
  }, [layoutStorageKey, engine]);


  useEffect(() => {
    const stepsNow = stepsRef.current;
    const agentsNow = agentsRef.current;
    const graph = buildWorkflowFlowGraph(stepsNow, agentsNow);
    const { positions } = computeLayeredLayout(structuralColumns);
    const model = new DiagramModel();
    const nodeByStep = new Map<number, AgentNodeModel>();

    for (const n of graph.nodes) {
      const source = stepsNow.find((s) => s.step_number === n.step_number);
      const depText = source?.depends_on?.length ? source.depends_on.join(', ') : 'None';
      const mappings = source?.input_mapping ? Object.entries(source.input_mapping) : [];
      const mappingSummary = mappings.length
        ? mappings
            .slice(0, 2)
            .map(([k, v]) => `${k}: ${String(v).slice(0, 24)}`)
            .join(' | ')
        : 'No custom mapping';
      const status = (source?.status || 'pending') as StepStatus;

      const node = new AgentNodeModel({
        name: `Step ${n.step_number}`,
        color: STATUS_NODE_COLOR[status],
        extras: {
          stepNumber: n.step_number,
          title: n.title,
          agentName: n.agent_name,
          agentId: n.agent_id,
          logoUrl: n.logoUrl,
          status,
          dependsOn: depText,
          mappingSummary,
        },
      });

      node.setLocked(false);
      node.addInPort('in');
      node.addOutPort('out');

      const defaultPos = positions.get(n.step_number) ?? { x: 0, y: 0 };
      const saved = positionsOverrideRef.current.get(n.step_number);
      const pos = saved ?? defaultPos;
      node.setPosition(pos.x, pos.y);
      node.registerListener({
        positionChanged: () => {
          const pt = node.getPosition();
          positionsOverrideRef.current.set(node.extras.stepNumber, { x: pt.x, y: pt.y });
          schedulePersistPositions();
        },
      });
      nodeByStep.set(n.step_number, node);
      model.addNode(node);
    }

    for (const e of graph.edges) {
      const src = nodeByStep.get(e.from);
      const dst = nodeByStep.get(e.to);
      if (!src || !dst) continue;
      const outPort = src.getOutPorts()[0];
      const inPort = dst.getInPorts()[0];
      if (!outPort || !inPort) continue;

      const lf = engine.getLinkFactories().getFactory('harness-link');
      if (!lf) continue;
      const link = outPort.link(inPort, lf) as HarnessLinkModel;
      link.setEdge(e.from, e.to);
      link.setLocked(true);
      link.getOptions().color = 'rgba(139, 92, 246, 0.85)';
      link.getOptions().width = 2.2;
      model.addLink(link);
    }

    engine.setModel(model);
    engine.repaintCanvas();
    schedulePersistPositions();
  }, [engine, diagramStructureKey, catalogSig, structuralColumns, layoutStorageKey, schedulePersistPositions]);

  useEffect(() => {
    const graphNodes = buildWorkflowFlowGraph(steps, agents ?? null).nodes;
    const metaByStep = new Map(graphNodes.map((n) => [n.step_number, n]));
    const model = engine.getModel();
    let changed = false;
    for (const node of model.getNodes()) {
      if (!(node instanceof AgentNodeModel)) continue;
      const source = steps.find((s) => s.step_number === node.extras.stepNumber);
      const meta = metaByStep.get(node.extras.stepNumber);
      if (!source || !meta) continue;
      const status = (source.status || 'pending') as StepStatus;
      const depText = source.depends_on?.length ? source.depends_on.join(', ') : 'None';
      const mappings = source.input_mapping ? Object.entries(source.input_mapping) : [];
      const mappingSummary = mappings.length
        ? mappings
            .slice(0, 2)
            .map(([k, v]) => `${k}: ${String(v).slice(0, 24)}`)
            .join(' | ')
        : 'No custom mapping';
      const ex = node.extras;
      if (
        ex.status !== status ||
        ex.title !== meta.title ||
        ex.agentName !== meta.agent_name ||
        ex.agentId !== meta.agent_id ||
        ex.logoUrl !== meta.logoUrl ||
        ex.dependsOn !== depText ||
        ex.mappingSummary !== mappingSummary
      ) {
        node.getOptions().extras = {
          stepNumber: node.extras.stepNumber,
          title: meta.title,
          agentName: meta.agent_name,
          agentId: meta.agent_id,
          logoUrl: meta.logoUrl,
          status,
          dependsOn: depText,
          mappingSummary,
        };
        node.getOptions().color = STATUS_NODE_COLOR[status];
        changed = true;
      }
    }
    if (changed) engine.repaintCanvas();
  }, [engine, steps, agents]);


  const handleWheelZoom = useCallback(
    (e: React.WheelEvent<HTMLDivElement>) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();

      const model = engine.getModel();
      const zoom = model.getZoomLevel();
      const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect();
      const px = e.clientX - rect.left;
      const py = e.clientY - rect.top;
      const ox = model.getOffsetX();
      const oy = model.getOffsetY();

      const zoomMultiplier = Math.exp(-(e.deltaMode === 1 ? 0.08 : 0.0022) * e.deltaY);
      const nextZoom = Math.min(240, Math.max(35, zoom * zoomMultiplier));
      if (!Number.isFinite(nextZoom) || Math.abs(nextZoom - zoom) < 0.01) return;

      // Keep cursor-anchored zoom so wheel zoom feels stable and smooth.
      const worldX = (px - ox) / (zoom / 100);
      const worldY = (py - oy) / (zoom / 100);
      const nextOx = px - worldX * (nextZoom / 100);
      const nextOy = py - worldY * (nextZoom / 100);

      model.setZoomLevel(nextZoom);
      model.setOffset(nextOx, nextOy);
      engine.repaintCanvas();
    },
    [engine],
  );

  const diagramMinWidth = Math.max(canvasWidth + WF_NODE_WIDTH / 2 + 120, 980);
  const diagramHeight = Math.max(canvasHeight + WF_NODE_HEIGHT / 2 + 120, 520);

  return (
    <div className="my-4 w-full overflow-hidden rounded-2xl border border-violet-500/20 bg-[#07041a] shadow-[0_20px_60px_-35px_rgba(139,92,246,0.6)]">
      <div className="flex items-center justify-between border-b border-violet-500/20 bg-black/30 px-3 py-2">
        <div className="min-w-0">
          <p className="truncate font-body text-xs font-semibold text-violet-100">{workflowName || 'Workflow'}</p>
          <p className="font-body text-[10px] text-violet-300/70">
            {steps.length} step{steps.length === 1 ? '' : 's'} - informative flow canvas
          </p>
        </div>
        {isLive ? (
          <span className="inline-flex items-center rounded-full border border-emerald-400/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-300">
            Live
          </span>
        ) : null}
      </div>

      <div
        className="relative w-full overflow-x-auto bg-[radial-gradient(circle_at_10%_8%,rgba(59,130,246,0.2),transparent_45%),radial-gradient(circle_at_90%_15%,rgba(168,85,247,0.25),transparent_42%),linear-gradient(rgba(99,102,241,0.12)_1px,transparent_1px),linear-gradient(90deg,rgba(99,102,241,0.12)_1px,transparent_1px)] [background-size:100%_100%,100%_100%,36px_36px,36px_36px]"
        onWheel={handleWheelZoom}
      >
        <div className="box-border p-6">
          <div
            className="box-border rounded-xl border border-gray-200 dark:border-white/10 bg-[#08051f]/80"
            style={{
              width: `max(100%, ${diagramMinWidth}px)`,
              height: diagramHeight,
            }}
          >
            <CanvasWidget className="h-full w-full" engine={engine} />
          </div>
        </div>
      </div>

      <style>{`
        .srd-diagram-container {
          background: transparent !important;
        }
        .srd-link path {
          stroke: rgba(167, 139, 250, 0.92) !important;
        }
        .wf-agent-port {
          box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.35);
        }
      `}</style>
    </div>
  );
}
