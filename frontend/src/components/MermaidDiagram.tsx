import { useEffect, useRef, useState, useCallback } from 'react';
import {
  Maximize2,
  Minimize2,
  Download,
  Copy,
  Check,
  RefreshCw,
  ZoomIn,
  ZoomOut,
  Move,
  RotateCcw,
  Layers,
  Bot,
} from 'lucide-react';

/** Per-step metadata to paint agent logos and execution loaders on top of rendered Mermaid nodes. */
export interface WorkflowDiagramNodeOverlay {
  stepNumber: number;
  agentId: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  /** Resolved URL (absolute or root-relative), from agent catalog */
  logoUrl?: string;
  /** Display name to highlight inside the node label (HTML foreignObject or SVG text). */
  agentLabel?: string;
}

type DiagramPresentation = 'orchestration' | 'architecture';

interface MermaidDiagramProps {
  chart: string;
  onRegenerate?: () => void;
  isRegenerating?: boolean;
  /** True while the parent agent run is in progress — diagram updates from SSE-driven chart prop. */
  isLive?: boolean;
  /** When set, injects logos + optional running spinner onto matching flowchart nodes (`flowchart-S{n}-*`). */
  nodeOverlays?: WorkflowDiagramNodeOverlay[];
  /** `architecture` uses catalog-style chrome; default is live workflow styling. */
  presentation?: DiagramPresentation;
  className?: string;
}

function sanitizeMermaid(code: string): string {
  const lines = code.split('\n');
  const sanitized: string[] = [];
  const isSequence = code.includes('sequenceDiagram');

  for (const line of lines) {
    let s = line;
    const trimmed = s.trim();

    if (trimmed === '' || trimmed === 'end' || trimmed.startsWith('%%') ||
        trimmed.startsWith('graph ') || trimmed.startsWith('flowchart ') ||
        trimmed.startsWith('sequenceDiagram')) {
      sanitized.push(s);
      continue;
    }

    if (isSequence) {
      const participantMatch = trimmed.match(/^(participant\s+)(\S+.*\S)\s*$/);
      if (participantMatch && participantMatch[2].includes('(') && !participantMatch[2].includes(' as ')) {
        const name = participantMatch[2];
        const alias = name.replace(/[^a-zA-Z0-9]/g, '').slice(0, 12);
        s = `    participant ${alias} as ${name}`;
      }
      const msgMatch = s.match(/^(\s*\S+\s*->>?\s*\S+\s*:\s*)(.+)$/);
      if (msgMatch) {
        s = msgMatch[1] + msgMatch[2].replace(/[<>{}[\]]/g, '');
      }
      sanitized.push(s);
      continue;
    }

    if (trimmed.startsWith('subgraph ')) {
      const subMatch = trimmed.match(/^subgraph\s+(\w+)\s+(.+)$/);
      if (subMatch && /[(){}|<>&]/.test(subMatch[2]) && !subMatch[2].includes('"')) {
        s = `    subgraph ${subMatch[1]}["${subMatch[2]}"]`;
      } else if (!subMatch) {
        const rawMatch = trimmed.match(/^subgraph\s+(.+)$/);
        if (rawMatch && /[(){}|<>&]/.test(rawMatch[1]) && !rawMatch[1].includes('"')) {
          const safeId = rawMatch[1].replace(/[^a-zA-Z0-9]/g, '').slice(0, 12);
          s = `    subgraph ${safeId}["${rawMatch[1]}"]`;
        }
      }
      sanitized.push(s);
      continue;
    }

    s = s.replace(/(\w+)\[([^\]"]+)\]/g, (_m, id, label) => {
      if (/[(){}|<>&]/.test(label)) {
        return `${id}["${label.replace(/"/g, "'")}"]`;
      }
      return _m;
    });

    s = s.replace(/(\w+)\(([^)]*\([^)]*\)[^)]*)\)/g, (_m, id, label) => {
      return `${id}["${label.replace(/"/g, "'")}"]`;
    });

    sanitized.push(s);
  }

  return sanitized.join('\n');
}

const SVG_NS = 'http://www.w3.org/2000/svg';

/** Per-step nodes: cyan / violet / teal stack (agent-runtime look, not rainbow). */
const ORCHESTRATION_STEP_PALETTE: ReadonlyArray<{ fill: string; stroke: string; text: string }> = [
  { fill: '#0c4a6e', stroke: '#22d3ee', text: '#ecfeff' },
  { fill: '#4c1d95', stroke: '#c4b5fd', text: '#f5f3ff' },
  { fill: '#134e4a', stroke: '#2dd4bf', text: '#ccfbf1' },
  { fill: '#581c87', stroke: '#e879f9', text: '#fdf4ff' },
  { fill: '#164e63', stroke: '#67e8f9', text: '#ecfeff' },
  { fill: '#312e81', stroke: '#a5b4fc', text: '#eef2ff' },
  { fill: '#065f46', stroke: '#34d399', text: '#d1fae5' },
  { fill: '#6b21a8', stroke: '#d8b4fe', text: '#faf5ff' },
];

function buildOrchestrationStepNodeCSS(): string {
  const lines: string[] = [];
  for (let n = 1; n <= 16; n++) {
    const { fill, stroke, text } = ORCHESTRATION_STEP_PALETTE[(n - 1) % ORCHESTRATION_STEP_PALETTE.length]!;
    lines.push(
      `[id^="flowchart-S${n}-"] rect, [id^="flowchart-S${n}-"] rect.basic, [id^="flowchart-S${n}-"] rect.label-container, ` +
        `[id^="flowchart-S${n}-"] polygon, [id^="flowchart-S${n}-"] path { fill: ${fill} !important; stroke: ${stroke} !important; stroke-width: 2px !important; }`,
    );
    lines.push(
      `[id^="flowchart-S${n}-"] .label text, [id^="flowchart-S${n}-"] .label span, [id^="flowchart-S${n}-"] .label tspan { fill: ${text} !important; }`,
    );
  }
  return lines.join('\n');
}

/** Architecture fallback nodes: same agentic cool palette when ids are not flowchart-S{n}-. */
const VIVID_ARCH_NODE_PALETTE: ReadonlyArray<{ fill: string; stroke: string; text: string }> = [
  { fill: '#164e63', stroke: '#22d3ee', text: '#ecfeff' },
  { fill: '#3730a3', stroke: '#a5b4fc', text: '#eef2ff' },
  { fill: '#134e4a', stroke: '#5eead4', text: '#ccfbf1' },
  { fill: '#5b21b6', stroke: '#c4b5fd', text: '#f5f3ff' },
  { fill: '#0f766e', stroke: '#2dd4bf', text: '#ccfbf1' },
  { fill: '#4c1d95', stroke: '#d8b4fe', text: '#faf5ff' },
  { fill: '#155e75', stroke: '#67e8f9', text: '#ecfeff' },
  { fill: '#065f46', stroke: '#6ee7b7', text: '#d1fae5' },
];

const ARCH_NODE_SEMANTIC_CLASSES = new Set(['decision', 'terminal', 'datastore', 'ioshape']);

const FLOWCHART_RECT_RX = '18';

/** Mermaid sets inline fill/stroke with !important; only JS on the same element can replace it. */
function paintFlowchartNodeShapes(
  node: SVGGElement,
  c: { fill: string; stroke: string; text: string },
  strokePx: string,
) {
  const rect =
    (node.querySelector('rect.label-container') as SVGRectElement | null) ||
    (node.querySelector('rect.basic') as SVGRectElement | null) ||
    (node.querySelector('rect') as SVGRectElement | null);
  const polygon = node.querySelector('polygon') as SVGPolygonElement | null;
  const path = node.querySelector('path') as SVGPathElement | null;
  const circle = node.querySelector('circle') as SVGCircleElement | null;

  const paintEl = (el: SVGGraphicsElement) => {
    el.style.setProperty('fill', c.fill, 'important');
    el.style.setProperty('stroke', c.stroke, 'important');
    el.style.setProperty('stroke-width', strokePx, 'important');
  };

  if (rect) {
    paintEl(rect);
    rect.setAttribute('rx', FLOWCHART_RECT_RX);
    rect.setAttribute('ry', FLOWCHART_RECT_RX);
  }
  if (polygon) {
    paintEl(polygon);
  }
  if (path && !rect && !polygon) {
    paintEl(path);
  }
  if (circle && !rect && !polygon && !path) {
    paintEl(circle);
  }

  node.querySelectorAll('g.label text, g.label tspan').forEach((t) => {
    if (t instanceof SVGElement) {
      t.style.setProperty('fill', c.text, 'important');
    }
  });
}

/**
 * Apply vivid per-node colors and rounded rects after Mermaid render.
 * Theme CSS alone cannot override Mermaid's inline !important styles.
 */
function applyVividFlowchartNodeStyles(svgEl: SVGSVGElement, presentation: DiagramPresentation) {
  if (!svgEl.querySelector('.flowchart')) return;

  const isArch = presentation === 'architecture';
  const strokePx = isArch ? '2px' : '2.25px';

  const semanticVivid: Record<string, { fill: string; stroke: string; text: string }> = {
    decision: { fill: '#c2410c', stroke: '#fdba74', text: '#fff7ed' },
    terminal: { fill: '#0369a1', stroke: '#7dd3fc', text: '#e0f2fe' },
    datastore: { fill: '#15803d', stroke: '#86efac', text: '#dcfce7' },
    ioshape: { fill: '#1d4ed8', stroke: '#93c5fd', text: '#dbeafe' },
  };

  let fallbackIdx = 0;

  svgEl.querySelectorAll<SVGGElement>('g.node').forEach((node) => {
    const cls = node.getAttribute('class') || '';
    const parts = new Set(cls.split(/\s+/).filter(Boolean));

    if (isArch) {
      for (const sem of ARCH_NODE_SEMANTIC_CLASSES) {
        const vivid = semanticVivid[sem];
        if (parts.has(sem) && vivid) {
          paintFlowchartNodeShapes(node, vivid, strokePx);
          return;
        }
      }
    }

    const id = node.getAttribute('id') || '';
    if (/^flowchart-WFIngress-|^flowchart-WFEgress-/.test(id)) {
      paintFlowchartNodeShapes(
        node,
        { fill: '#042f2e', stroke: '#2dd4bf', text: '#ccfbf1' },
        strokePx,
      );
      return;
    }
    const stepMatch = /^flowchart-S(\d+)-/.exec(id);
    let colors: { fill: string; stroke: string; text: string };
    if (stepMatch) {
      const n = parseInt(stepMatch[1], 10);
      colors = ORCHESTRATION_STEP_PALETTE[(n - 1) % ORCHESTRATION_STEP_PALETTE.length]!;
    } else if (isArch) {
      colors = VIVID_ARCH_NODE_PALETTE[fallbackIdx % VIVID_ARCH_NODE_PALETTE.length]!;
      fallbackIdx += 1;
    } else {
      colors = ORCHESTRATION_STEP_PALETTE[fallbackIdx % ORCHESTRATION_STEP_PALETTE.length]!;
      fallbackIdx += 1;
    }
    paintFlowchartNodeShapes(node, colors, strokePx);
  });

  // Final pass: keep all node labels pure white on dark backgrounds.
  svgEl.querySelectorAll('g.node .label text, g.node .label tspan').forEach((el) => {
    if (el instanceof SVGElement) {
      el.style.setProperty('fill', '#ffffff', 'important');
      el.style.setProperty('stroke', 'none', 'important');
    }
  });
}

/** Step nodes in architecture mode: same saturated palette as orchestration (themeCSS pre-paint). */
/** Per execution status: highlight the catalog line (`agent · …` / `id · …`) in the node label. */
const STATUS_AGENT_LINE_FILL: Record<WorkflowDiagramNodeOverlay['status'], string> = {
  pending: '#fbbf24',
  running: '#38bdf8',
  completed: '#4ade80',
  failed: '#fb7185',
};

/** Matches the subtitle line we emit in `regenerateMermaid` (`agent · Name` / `id · aid`). */
const AGENT_OR_ID_LINE_RE = /^\s*(agent|id)\s*[·•]\s*\S/i;

/** Trailing role-style name when Mermaid merges label into one line (e.g. "… Web Search Agent"). */
const TRAILING_AGENT_ROLE_RE = /\s+([\w][\w\s&./-]{1,}\sAgent)\s*$/i;

function findLastInsensitiveIndex(haystack: string, needle: string): number {
  if (!needle) return -1;
  const h = haystack.toLowerCase();
  const n = needle.toLowerCase();
  return h.lastIndexOf(n);
}

/**
 * Mermaid often renders node labels as XHTML inside `foreignObject`; style the agent phrase with DOM (not SVG tspans).
 */
function injectAgentHighlightInHtmlLabel(el: HTMLElement, phrases: string[], fill: string): boolean {
  const full = (el.textContent ?? '').trim();
  if (!full) return false;

  const ordered = [...phrases]
    .map((p) => p.trim())
    .filter(Boolean)
    .sort((a, b) => b.length - a.length);

  let idx = -1;
  let len = 0;
  let bestEnd = -1;
  for (const phrase of ordered) {
    const i = findLastInsensitiveIndex(full, phrase);
    if (i < 0) continue;
    const end = i + phrase.length;
    if (end > bestEnd || (end === bestEnd && phrase.length > len)) {
      bestEnd = end;
      idx = i;
      len = phrase.length;
    }
  }

  if (idx < 0) {
    const m = full.match(TRAILING_AGENT_ROLE_RE);
    if (m && m[1]) {
      idx = full.length - m[1].length;
      len = m[1].length;
    }
  }

  if (idx < 0 || len <= 0) return false;

  const before = full.slice(0, idx);
  const matched = full.slice(idx, idx + len);
  const after = full.slice(idx + len);

  el.replaceChildren();
  el.style.setProperty('white-space', 'normal', 'important');
  el.style.setProperty('text-align', 'center', 'important');
  if (before) el.appendChild(document.createTextNode(before));
  const span = document.createElement('span');
  span.style.setProperty('color', fill, 'important');
  span.style.setProperty('font-weight', '650', 'important');
  span.textContent = matched;
  el.appendChild(span);
  if (after) el.appendChild(document.createTextNode(after));
  return true;
}

/**
 * After palette paint, recolor the agent line (SVG) or agent phrase (HTML foreignObject) per step status.
 */
function applyWorkflowAgentLineStatusColors(svgEl: SVGSVGElement, overlays: WorkflowDiagramNodeOverlay[]) {
  for (const node of overlays) {
    const host = svgEl.querySelector(`[id^="flowchart-S${node.stepNumber}-"]`) as SVGGElement | null;
    if (!host) continue;
    const fill = STATUS_AGENT_LINE_FILL[node.status];
    const phrases = [node.agentLabel, node.agentId].filter((p): p is string => Boolean(p?.trim()));

    const foreignObject = host.querySelector('foreignObject');
    if (foreignObject) {
      const htmlRoot = foreignObject.querySelector('div');
      if (htmlRoot instanceof HTMLElement) {
        if (injectAgentHighlightInHtmlLabel(htmlRoot, phrases, fill)) continue;
      }
    }

    const svgLabelRoot = host.querySelector('g.label');
    if (!svgLabelRoot) continue;

    const paintLeaf = (el: SVGElement, chunk: string) => {
      const trimmed = chunk.trim();
      if (!trimmed || !AGENT_OR_ID_LINE_RE.test(trimmed)) return;
      el.style.setProperty('fill', fill, 'important');
      el.style.setProperty('font-weight', '650', 'important');
    };

    const tspans = svgLabelRoot.querySelectorAll('tspan');
    if (tspans.length) {
      tspans.forEach((el) => {
        if (el instanceof SVGElement) paintLeaf(el, el.textContent ?? '');
      });
    } else {
      svgLabelRoot.querySelectorAll('text').forEach((el) => {
        if (el instanceof SVGTextElement && !el.querySelector('tspan')) {
          paintLeaf(el, el.textContent ?? '');
        }
      });
    }
  }
}

function buildEnterpriseWorkflowStepCSS(): string {
  const lines: string[] = [];
  for (let n = 1; n <= 16; n++) {
    const { fill, stroke, text } = ORCHESTRATION_STEP_PALETTE[(n - 1) % ORCHESTRATION_STEP_PALETTE.length]!;
    lines.push(
      `[id^="flowchart-S${n}-"] rect, [id^="flowchart-S${n}-"] rect.basic, [id^="flowchart-S${n}-"] rect.label-container, ` +
        `[id^="flowchart-S${n}-"] polygon, [id^="flowchart-S${n}-"] path { fill: ${fill} !important; stroke: ${stroke} !important; stroke-width: 2px !important; }`,
    );
    lines.push(
      `[id^="flowchart-S${n}-"] .label text, [id^="flowchart-S${n}-"] .label tspan { fill: ${text} !important; }`,
    );
  }
  return lines.join('\n');
}

type FlowchartChromeMode = 'orchestration' | 'architecture';

function buildFlowchartThemeCSS(
  edgeGlow: string,
  nodeShadow: string,
  edgeLabelStroke: string,
  mode: FlowchartChromeMode,
): string {
  const enterprise = mode === 'architecture';
  const edgeStrokeW = enterprise ? '1.35px' : '2.75px';
  const nodeStrokeW = enterprise ? '1px' : '2.25px';
  const edgeFilter = enterprise
    ? 'filter: drop-shadow(0 1px 1px rgba(0,0,0,0.45));'
    : `filter: drop-shadow(0 0 4px ${edgeGlow});`;
  const arrowFilter = enterprise
    ? 'filter: drop-shadow(0 1px 1px rgba(0,0,0,0.35));'
    : `filter: drop-shadow(0 0 2px ${edgeGlow});`;
  const nodeFilter = enterprise
    ? 'filter: drop-shadow(0 2px 6px rgba(0,0,0,0.4));'
    : `filter: drop-shadow(0 3px 8px ${nodeShadow});`;
  const stepTheme = enterprise ? buildEnterpriseWorkflowStepCSS() : buildOrchestrationStepNodeCSS();
  const labelWeight = enterprise ? '500' : '600';
  const clusterRx = enterprise ? '8px' : '16px';
  const labelColor = 'white';

  const semanticArch =
    mode === 'architecture'
      ? `
  .flowchart g.node.decision polygon {
    fill: #c2410c !important;
    stroke: #fdba74 !important;
    stroke-width: 2px !important;
  }
  .flowchart g.node.decision .label text,
  .flowchart g.node.decision .label tspan { fill: #fff7ed !important; }
  .flowchart g.node.terminal rect,
  .flowchart g.node.terminal path,
  .flowchart g.node.terminal polygon {
    fill: #0369a1 !important;
    stroke: #7dd3fc !important;
    stroke-width: 2px !important;
  }
  .flowchart g.node.terminal .label text,
  .flowchart g.node.terminal .label tspan { fill: #e0f2fe !important; }
  .flowchart g.node.datastore rect,
  .flowchart g.node.datastore path,
  .flowchart g.node.datastore polygon {
    fill: #15803d !important;
    stroke: #86efac !important;
    stroke-width: 2px !important;
  }
  .flowchart g.node.datastore .label text,
  .flowchart g.node.datastore .label tspan { fill: #dcfce7 !important; }
  .flowchart g.node.ioshape rect,
  .flowchart g.node.ioshape path {
    fill: #1d4ed8 !important;
    stroke: #93c5fd !important;
    stroke-width: 2px !important;
  }
  .flowchart g.node.ioshape .label text,
  .flowchart g.node.ioshape .label tspan { fill: #dbeafe !important; }
`.trim()
      : '';

  return `
  .flowchart .edgePath .path,
  .flowchart .flowchart-link {
    stroke-width: ${edgeStrokeW} !important;
    stroke-linecap: round !important;
    stroke-linejoin: round !important;
    ${edgeFilter}
  }
  .flowchart .arrowheadPath {
    ${arrowFilter}
  }
  .flowchart .edgeLabel rect {
    opacity: 1 !important;
    stroke: ${edgeLabelStroke} !important;
    stroke-width: ${enterprise ? '1px' : '1.75px'} !important;
    rx: ${enterprise ? '8px' : '10px'};
    ry: ${enterprise ? '8px' : '10px'};
    ${enterprise ? '' : 'fill: rgba(6, 32, 48, 0.94) !important;'}
  }
  .flowchart .edgeLabel .edgeLabel,
  .flowchart .edgeLabel text {
    font-weight: ${labelWeight} !important;
    letter-spacing: ${enterprise ? '0.01em' : '0.03em'};
    fill: ${labelColor} !important;
    color: ${labelColor} !important;
  }
  .flowchart .node rect,
  .flowchart .node circle,
  .flowchart .node polygon,
  .flowchart .node path {
    stroke-width: ${nodeStrokeW} !important;
    ${nodeFilter}
  }
  .flowchart .node .label,
  .flowchart .node .label text {
    font-weight: ${labelWeight} !important;
    fill: ${labelColor} !important;
    color: ${labelColor} !important;
  }
  .flowchart .nodeLabel,
  .flowchart .node .label foreignObject,
  .flowchart .node .label foreignObject *,
  .flowchart .edgeLabel foreignObject,
  .flowchart .edgeLabel foreignObject * {
    color: ${labelColor} !important;
    fill: ${labelColor} !important;
  }
  .flowchart,
  .flowchart .root,
  .flowchart .nodes,
  .flowchart .node,
  .flowchart .node .label {
    overflow: visible;
  }
  .flowchart .cluster rect {
    stroke-width: ${enterprise ? '1.25px' : '2px'} !important;
    rx: ${clusterRx};
    ry: ${clusterRx};
  }
  .flowchart g.node rect,
  .flowchart g.node rect.basic,
  .flowchart g.node rect.label-container {
    rx: ${enterprise ? '12px' : `${FLOWCHART_RECT_RX}px`};
    ry: ${enterprise ? '12px' : `${FLOWCHART_RECT_RX}px`};
  }
  ${stepTheme}
  ${semanticArch}
`.trim();
}

function injectWorkflowNodeOverlays(
  svgEl: SVGSVGElement,
  overlays: WorkflowDiagramNodeOverlay[],
  isLive: boolean | undefined,
  clipIdPrefix: string,
) {
  svgEl.querySelectorAll('g.workflow-node-overlay').forEach((g) => g.remove());

  if (!overlays.length) return;

  let defs = svgEl.querySelector('defs');
  if (!defs) {
    defs = document.createElementNS(SVG_NS, 'defs');
    svgEl.insertBefore(defs, svgEl.firstChild);
  }
  defs.querySelectorAll(`clipPath[id^="${clipIdPrefix}-"]`).forEach((c) => c.remove());

  for (const node of overlays) {
    const host = svgEl.querySelector(`[id^="flowchart-S${node.stepNumber}-"]`) as SVGGElement | null;
    if (!host) continue;

    const rect =
      (host.querySelector('rect.label-container') as SVGRectElement | null) ||
      (host.querySelector('rect.basic') as SVGRectElement | null) ||
      (host.querySelector('rect') as SVGRectElement | null);
    if (!rect) continue;

    const pad = 7;
    const logoSize = 24;
    /** Room for the badge so centered labels are not drawn under the logo. */
    const reserve = logoSize + pad * 2;
    const wAttr = rect.getAttribute('width');
    const xAttr = rect.getAttribute('x');
    if (wAttr != null && xAttr != null && !Number.isNaN(parseFloat(wAttr)) && !Number.isNaN(parseFloat(xAttr))) {
      const w = parseFloat(wAttr);
      const x = parseFloat(xAttr);
      rect.setAttribute('width', String(w + reserve));
      rect.setAttribute('x', String(x - reserve / 2));
    }
    const labelG = host.querySelector('g.label') as SVGGElement | null;
    if (labelG) {
      const prev = labelG.getAttribute('transform')?.trim() || '';
      labelG.setAttribute('transform', `translate(${reserve / 2}, 0) ${prev}`.trim());
    }

    let bbox: DOMRect;
    try {
      bbox = rect.getBBox();
    } catch {
      continue;
    }

    const g = document.createElementNS(SVG_NS, 'g');
    g.setAttribute('class', 'workflow-node-overlay');
    g.setAttribute('pointer-events', 'none');

    const lx = bbox.x + pad;
    const ly = bbox.y + pad;
    const clipId = `${clipIdPrefix}-s${node.stepNumber}`;

    const clip = document.createElementNS(SVG_NS, 'clipPath');
    clip.setAttribute('id', clipId);
    const clipCircle = document.createElementNS(SVG_NS, 'circle');
    clipCircle.setAttribute('cx', String(lx + logoSize / 2));
    clipCircle.setAttribute('cy', String(ly + logoSize / 2));
    clipCircle.setAttribute('r', String(logoSize / 2 - 0.5));
    clip.appendChild(clipCircle);
    defs.appendChild(clip);

    if (node.logoUrl) {
      const img = document.createElementNS(SVG_NS, 'image');
      img.setAttribute('href', node.logoUrl);
      img.setAttribute('x', String(lx));
      img.setAttribute('y', String(ly));
      img.setAttribute('width', String(logoSize));
      img.setAttribute('height', String(logoSize));
      img.setAttribute('clip-path', `url(#${clipId})`);
      img.setAttribute('preserveAspectRatio', 'xMidYMid slice');
      g.appendChild(img);
    } else {
      const fc = document.createElementNS(SVG_NS, 'circle');
      fc.setAttribute('cx', String(lx + logoSize / 2));
      fc.setAttribute('cy', String(ly + logoSize / 2));
      fc.setAttribute('r', String(logoSize / 2));
      fc.setAttribute('fill', '#334155');
      fc.setAttribute('stroke', 'rgba(255,255,255,0.14)');
      fc.setAttribute('stroke-width', '1');
      g.appendChild(fc);
      const t = document.createElementNS(SVG_NS, 'text');
      t.setAttribute('x', String(lx + logoSize / 2));
      t.setAttribute('y', String(ly + logoSize / 2 + 4));
      t.setAttribute('text-anchor', 'middle');
      t.setAttribute('fill', '#f1f5f9');
      t.setAttribute('font-size', '11');
      t.setAttribute('font-family', "'Inter', ui-sans-serif, system-ui, sans-serif");
      t.setAttribute('font-weight', '700');
      t.textContent = (node.agentId || '?').replace(/_/g, '').slice(0, 1).toUpperCase() || '?';
      g.appendChild(t);
    }

    if (node.status === 'running' && isLive) {
      const cx = bbox.x + bbox.width - 12;
      const cy = bbox.y + 12;
      const outer = document.createElementNS(SVG_NS, 'circle');
      outer.setAttribute('cx', String(cx));
      outer.setAttribute('cy', String(cy));
      outer.setAttribute('r', '11');
      outer.setAttribute('fill', 'rgba(15,23,42,0.92)');
      outer.setAttribute('stroke', 'rgba(96,165,250,0.5)');
      outer.setAttribute('stroke-width', '1');
      g.appendChild(outer);

      const spinWrap = document.createElementNS(SVG_NS, 'g');
      spinWrap.setAttribute('transform', `translate(${cx},${cy})`);
      const spinInner = document.createElementNS(SVG_NS, 'g');
      const anim = document.createElementNS(SVG_NS, 'animateTransform');
      anim.setAttribute('attributeName', 'transform');
      anim.setAttribute('attributeType', 'XML');
      anim.setAttribute('type', 'rotate');
      anim.setAttribute('from', '0 0 0');
      anim.setAttribute('to', '360 0 0');
      anim.setAttribute('dur', '0.7s');
      anim.setAttribute('repeatCount', 'indefinite');
      spinInner.appendChild(anim);
      const arc = document.createElementNS(SVG_NS, 'circle');
      arc.setAttribute('cx', '0');
      arc.setAttribute('cy', '0');
      arc.setAttribute('r', '6');
      arc.setAttribute('fill', 'none');
      arc.setAttribute('stroke', '#93c5fd');
      arc.setAttribute('stroke-width', '2.2');
      arc.setAttribute('stroke-linecap', 'round');
      arc.setAttribute('stroke-dasharray', '10 22');
      spinInner.appendChild(arc);
      spinWrap.appendChild(spinInner);
      g.appendChild(spinWrap);
    }

    host.appendChild(g);
  }
}

export default function MermaidDiagram({
  chart,
  onRegenerate,
  isRegenerating,
  isLive,
  nodeOverlays,
  presentation = 'orchestration',
  className = '',
}: MermaidDiagramProps) {
  const isArch = presentation === 'architecture';
  const headerTitle = isArch ? 'Agent topology' : 'Agent workflow';
  const headerSubtitle = isArch
    ? 'Catalog graph · pan, scroll, and zoom the stack'
    : 'Multi-agent steps · live wiring while a run streams (pan / zoom)';
  const containerRef = useRef<HTMLDivElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const svgContainerRef = useRef<HTMLDivElement>(null);
  const [svg, setSvg] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [copied, setCopied] = useState(false);
  const idRef = useRef(`mermaid-${Math.random().toString(36).slice(2, 11)}`);
  const renderSeqRef = useRef(0);

  const [scale, setScale] = useState(1);
  const [translate, setTranslate] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const dragStart = useRef({ x: 0, y: 0 });
  const translateStart = useRef({ x: 0, y: 0 });

  const renderDiagram = useCallback(async () => {
    if (!chart.trim()) return;
    setIsLoading(true);
    setError(null);

    try {
      const mermaid = (await import('mermaid')).default;

      const archVars = {
        background: 'transparent',
        primaryColor: '#0f172a',
        primaryTextColor: '#f8fafc',
        primaryBorderColor: '#22d3ee',
        secondaryColor: '#0c1222',
        secondaryBorderColor: '#64748b',
        tertiaryColor: '#020617',
        tertiaryBorderColor: '#334155',
        lineColor: '#5eead4',
        arrowheadColor: '#a5b4fc',
        defaultLinkColor: '#2dd4bf',
        textColor: '#e2e8f0',
        titleColor: '#94a3b8',
        mainBkg: '#080c14',
        secondBkg: '#0f172a',
        nodeBorder: '#334155',
        nodeTextColor: '#f1f5f9',
        edgeLabelBackground: 'rgba(8, 47, 73, 0.95)',
        clusterBkg: 'rgba(15, 23, 42, 0.78)',
        clusterBorder: 'rgba(34, 211, 238, 0.35)',
        fontFamily: "'Inter', ui-sans-serif, system-ui, sans-serif",
        fontSize: '10px',
        cScale0: '#164e63',
        cScale1: '#3730a3',
        cScale2: '#134e4a',
        cScale3: '#4c1d95',
        cScale4: '#155e75',
        cScale5: '#312e81',
        cScale6: '#065f46',
        cScale7: '#5b21b6',
        cScale8: '#0e7490',
        cScale9: '#1e3a8a',
        cScale10: '#164e63',
        cScale11: '#3730a3',
      };

      const orchVars = {
        background: 'transparent',
        primaryColor: '#155e75',
        primaryTextColor: '#ecfeff',
        primaryBorderColor: '#22d3ee',
        secondaryColor: '#4c1d95',
        secondaryBorderColor: '#c4b5fd',
        tertiaryColor: '#030712',
        tertiaryBorderColor: '#818cf8',
        lineColor: '#5eead4',
        arrowheadColor: '#a78bfa',
        defaultLinkColor: '#2dd4bf',
        textColor: '#ecfeff',
        titleColor: '#a5f4fc',
        mainBkg: '#050a12',
        secondBkg: '#0c1220',
        nodeBorder: '#22d3ee',
        nodeTextColor: '#f0fdfa',
        edgeLabelBackground: 'rgba(6, 32, 48, 0.94)',
        clusterBkg: 'rgba(15, 23, 42, 0.55)',
        clusterBorder: 'rgba(139, 92, 246, 0.45)',
        fontFamily: "'Inter', ui-sans-serif, system-ui, sans-serif",
        fontSize: '12px',
        cScale0: '#155e75',
        cScale1: '#5b21b6',
        cScale2: '#134e4a',
        cScale3: '#4c1d95',
        cScale4: '#164e63',
        cScale5: '#312e81',
        cScale6: '#065f46',
        cScale7: '#581c87',
        cScale8: '#0e7490',
        cScale9: '#6d28d9',
        cScale10: '#155e75',
        cScale11: '#5b21b6',
      };

      mermaid.initialize({
        startOnLoad: false,
        theme: 'dark',
        themeVariables: isArch ? archVars : orchVars,
        themeCSS: isArch
          ? buildFlowchartThemeCSS(
              'rgba(34, 211, 238, 0.22)',
              'rgba(0, 0, 0, 0.5)',
              'rgba(34, 211, 238, 0.45)',
              'architecture',
            )
          : buildFlowchartThemeCSS(
              'rgba(34, 211, 238, 0.55)',
              'rgba(34, 211, 238, 0.2)',
              'rgba(165, 243, 252, 0.65)',
              'orchestration',
            ),
        flowchart: {
          /** Straight edges read cleaner and use less canvas than splines in dense arch maps. */
          curve: isArch ? 'linear' : 'basis',
          /** Tight layout for sidebar architecture tab (reduces vertical scroll). */
          wrappingWidth: isArch ? 340 : 420,
          /** Extra padding keeps nodes, labels, and edge glow inside the viewBox (avoids SVG edge clip). */
          padding: isArch ? 12 : 28,
          diagramPadding: isArch ? 4 : 24,
          htmlLabels: false,
          nodeSpacing: isArch ? 28 : 52,
          rankSpacing: isArch ? 32 : 56,
          useMaxWidth: true,
        },
        sequence: { actorMargin: 50, messageMargin: 40 },
        securityLevel: 'strict',
      });

      const sanitizedChart = sanitizeMermaid(chart.trim());
      renderSeqRef.current += 1;
      const uniqueId = `${idRef.current}-r${renderSeqRef.current}`;
      const { svg: renderedSvg } = await mermaid.render(uniqueId, sanitizedChart);
      setSvg(renderedSvg);
      setScale(1);
      setTranslate({ x: 0, y: 0 });
    } catch (e: unknown) {
      const err = e as Error;
      console.error('Mermaid render error:', err);
      setError(err.message || 'Failed to render diagram');
    } finally {
      setIsLoading(false);
    }
  }, [chart, isArch]);

  useEffect(() => {
    renderDiagram();
  }, [renderDiagram]);

  /** After SVG paints: architecture default-node colors; workflow overlays (Mermaid replaces innerHTML each render). */
  useEffect(() => {
    if (!svg) return;
    const root = svgContainerRef.current;
    if (!root) return;

    const run = () => {
      const svgEl = root.querySelector('svg') as SVGSVGElement | null;
      if (!svgEl) return;
      /** Default SVG viewport clips filters/strokes; allow bleed so nodes are not visually cut off. */
      svgEl.setAttribute('overflow', 'visible');
      svgEl.style.overflow = 'visible';
      applyVividFlowchartNodeStyles(svgEl, presentation);
      if (nodeOverlays?.length) {
        injectWorkflowNodeOverlays(svgEl, nodeOverlays, isLive, `wf-clip-${idRef.current}`);
        applyWorkflowAgentLineStatusColors(svgEl, nodeOverlays);
      }
    };

    let innerRaf = 0;
    const outerRaf = requestAnimationFrame(() => {
      innerRaf = requestAnimationFrame(run);
    });
    return () => {
      cancelAnimationFrame(outerRaf);
      cancelAnimationFrame(innerRaf);
    };
  }, [svg, nodeOverlays, isLive, presentation]);

  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    if (e.button !== 0) return;
    e.preventDefault();
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    setIsDragging(true);
    dragStart.current = { x: e.clientX, y: e.clientY };
    translateStart.current = { ...translate };
  }, [translate]);

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (!isDragging) return;
    const dx = e.clientX - dragStart.current.x;
    const dy = e.clientY - dragStart.current.y;
    setTranslate({
      x: translateStart.current.x + dx,
      y: translateStart.current.y + dy,
    });
  }, [isDragging]);

  const handlePointerUp = useCallback((e: React.PointerEvent) => {
    (e.target as HTMLElement).releasePointerCapture(e.pointerId);
    setIsDragging(false);
  }, []);

  const handleWheel = useCallback((e: React.WheelEvent) => {
    const el = containerRef.current;
    if (!el) return;
    const zoomModifier = e.ctrlKey || e.metaKey;
    /** When the diagram is taller/wider than the viewport, allow normal scrolling instead of hijacking the wheel. */
    if (!zoomModifier) {
      const canScrollY = el.scrollHeight > el.clientHeight + 2;
      const canScrollX = el.scrollWidth > el.clientWidth + 2;
      if (canScrollY || canScrollX) return;
    }
    e.preventDefault();
    const rect = el.getBoundingClientRect();
    const mouseX = e.clientX - rect.left - rect.width / 2;
    const mouseY = e.clientY - rect.top - rect.height / 2;
    const delta = e.deltaY > 0 ? -0.1 : 0.1;
    setScale(prev => {
      const next = Math.min(Math.max(0.2, prev + delta), 3);
      const ratio = 1 - next / prev;
      setTranslate(t => ({
        x: t.x + (mouseX - t.x) * ratio,
        y: t.y + (mouseY - t.y) * ratio,
      }));
      return next;
    });
  }, []);

  const zoomIn = useCallback(() => setScale(prev => Math.min(prev + 0.2, 3)), []);
  const zoomOut = useCallback(() => setScale(prev => Math.max(prev - 0.2, 0.2)), []);
  const resetView = useCallback(() => {
    setScale(1);
    setTranslate({ x: 0, y: 0 });
  }, []);

  const handleDownload = () => {
    const live = svgContainerRef.current?.querySelector('svg');
    const payload = live ? new XMLSerializer().serializeToString(live) : svg;
    if (!payload) return;
    const blob = new Blob([payload], { type: 'image/svg+xml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'agent-flow-diagram.svg';
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleCopyCode = () => {
    navigator.clipboard.writeText(chart);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const toggleFullscreen = useCallback(() => {
    if (!wrapperRef.current) return;
    if (!document.fullscreenElement) {
      wrapperRef.current.requestFullscreen().catch(() => {});
    } else {
      document.exitFullscreen().catch(() => {});
    }
  }, []);

  useEffect(() => {
    const handler = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };
    document.addEventListener('fullscreenchange', handler);
    return () => document.removeEventListener('fullscreenchange', handler);
  }, []);

  if (isLoading) {
    if (isArch) {
      return (
        <div
          className={`overflow-hidden rounded-xl border border-slate-200/90 bg-white shadow-sm ring-1 ring-slate-900/[0.04] dark:border-slate-700/80 dark:bg-[#0b0f14] dark:shadow-xl dark:shadow-black/50 dark:ring-white/[0.06] ${className}`.trim()}
        >
          <div className="h-px w-full bg-gradient-to-r from-transparent via-slate-400/40 to-transparent dark:via-slate-500/35" />
          <div className="flex items-center justify-between gap-3 border-b border-slate-200/80 px-3 py-2.5 dark:border-white/[0.06] dark:bg-black/25">
            <div className="flex min-w-0 items-center gap-2.5">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100 dark:bg-slate-800/80 dark:ring-1 dark:ring-white/[0.06]">
                <Layers className="h-4 w-4 text-slate-600 dark:text-slate-300" />
              </div>
              <div className="min-w-0">
                <p className="font-body text-xs font-semibold tracking-tight text-slate-800 dark:text-slate-100">
                  {headerTitle}
                </p>
                <p className="font-body text-[10px] leading-snug text-slate-500 dark:text-slate-500">{headerSubtitle}</p>
              </div>
            </div>
          </div>
          <div className="flex min-h-[180px] items-center justify-center bg-slate-50/80 px-4 py-10 dark:bg-[#080c10]">
            <div className="flex flex-col items-center gap-3">
              <div
                className="h-6 w-6 animate-spin rounded-full border-2 border-slate-300 border-t-slate-600 dark:border-slate-600 dark:border-t-slate-300"
                aria-label="Rendering diagram"
              />
              <span className="font-body text-xs text-slate-500 dark:text-slate-400">Rendering diagram…</span>
            </div>
          </div>
        </div>
      );
    }
    return (
      <div
        className={`my-4 overflow-hidden rounded-2xl border border-cyan-500/20 bg-gradient-to-br from-[#030712] via-[#060a18] to-[#050818] shadow-[0_24px_64px_-28px_rgba(34,211,238,0.18),0_20px_50px_-30px_rgba(88,28,135,0.25)] ring-1 ring-cyan-400/10 ${className}`.trim()}
      >
        <div className="flex items-center justify-between border-b border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-black/30 px-4 py-2.5">
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-cyan-500/10 ring-1 ring-cyan-400/20">
              <Bot className="h-4 w-4 text-cyan-300" />
            </div>
            <div className="min-w-0">
              <span className="font-body text-xs font-semibold tracking-tight text-gray-200">{headerTitle}</span>
              <p className="font-body text-[10px] leading-snug text-gray-500">{headerSubtitle}</p>
            </div>
          </div>
          {isLive && (
            <span className="flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2 py-0.5 font-body text-[10px] font-medium text-emerald-400 ring-1 ring-emerald-500/20">
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400" />
              </span>
              Live
            </span>
          )}
        </div>
        <div className="flex min-h-[200px] items-center justify-center px-6 py-10">
          <div className="flex items-center gap-3 text-gray-400">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary-500 border-t-transparent" />
            <span className="font-body text-sm text-gray-500">Rendering diagram…</span>
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="my-4">
        <div className="overflow-hidden rounded-xl border border-red-500/20 bg-red-950/20 ring-1 ring-red-500/10 backdrop-blur-sm">
          <div className="flex items-center justify-between border-b border-red-500/10 px-4 py-3">
            <p className="font-body text-sm text-red-300">{`Couldn't render this diagram`}</p>
            {onRegenerate && (
              <button
                type="button"
                onClick={onRegenerate}
                disabled={isRegenerating}
                className="flex items-center gap-2 rounded-lg bg-primary-600 px-3 py-1.5 font-body text-xs font-semibold text-white transition-colors hover:bg-primary-500 disabled:cursor-not-allowed disabled:bg-gray-700"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${isRegenerating ? 'animate-spin' : ''}`} />
                {isRegenerating ? 'Working…' : 'Regenerate'}
              </button>
            )}
          </div>
        </div>
        <details className="mt-2 overflow-hidden rounded-lg border border-gray-200 dark:border-white/[0.06] bg-white dark:bg-gray-900/40">
          <summary className="cursor-pointer select-none px-3 py-2 font-body text-xs text-gray-500 hover:text-gray-300">
            Mermaid source
          </summary>
          <pre className="max-h-48 overflow-auto border-t border-gray-200 dark:border-white/[0.06] p-3 font-mono text-xs text-gray-400">
            <code>{chart}</code>
          </pre>
        </details>
      </div>
    );
  }

  return (
    <div
      ref={wrapperRef}
      className={`${isArch ? '' : 'my-4'} ${isFullscreen ? 'flex h-screen flex-col bg-gray-950 p-4' : ''} ${className}`.trim()}
    >
      <div
        className={
          isArch
            ? 'overflow-hidden rounded-xl border border-slate-200/90 bg-white shadow-sm ring-1 ring-slate-900/[0.04] dark:border-cyan-500/15 dark:bg-[#050810] dark:shadow-[0_24px_60px_-28px_rgba(34,211,238,0.12)] dark:shadow-black/60 dark:ring-cyan-400/10'
            : 'overflow-hidden rounded-2xl border border-cyan-500/25 bg-gradient-to-br from-[#030712] via-[#070b1a] to-[#050818] shadow-[0_24px_64px_-28px_rgba(34,211,238,0.2),0_20px_50px_-30px_rgba(109,40,217,0.28)] ring-1 ring-violet-500/15'
        }
      >
        {isArch ? (
          <>
            <div className="h-px w-full bg-gradient-to-r from-transparent via-slate-400/50 to-transparent dark:via-slate-500/40" />
            <div className="flex flex-col gap-2 border-b border-slate-200/80 px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between sm:gap-3 dark:border-white/[0.06] dark:bg-black/20">
              <div className="flex min-w-0 flex-1 items-center gap-2.5">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100 dark:bg-slate-800/90 dark:ring-1 dark:ring-white/[0.06]">
                  <Layers className="h-4 w-4 text-slate-600 dark:text-slate-300" />
                </div>
                <div className="min-w-0">
                  <p className="font-body text-xs font-semibold tracking-tight text-slate-800 dark:text-slate-100">
                    {headerTitle}
                  </p>
                  <p className="font-body text-[10px] leading-snug text-slate-500 dark:text-slate-500">{headerSubtitle}</p>
                </div>
              </div>
              <div
                className="flex flex-wrap items-center justify-end gap-0.5 rounded-lg border border-slate-200/90 bg-slate-50/90 p-0.5 dark:border-white/[0.08] dark:bg-slate-950/60"
                role="toolbar"
                aria-label="Diagram controls"
              >
                {onRegenerate && (
                  <button
                    type="button"
                    onClick={onRegenerate}
                    disabled={isRegenerating}
                    className="rounded-md p-2 text-slate-500 transition-colors hover:bg-slate-200/80 hover:text-slate-800 disabled:cursor-not-allowed disabled:opacity-40 dark:text-slate-400 dark:hover:bg-white/[0.08] dark:hover:text-slate-100"
                    title={isRegenerating ? 'Regenerating…' : 'Regenerate from steps'}
                  >
                    <RefreshCw className={`h-3.5 w-3.5 ${isRegenerating ? 'animate-spin' : ''}`} />
                  </button>
                )}
                {onRegenerate && <div className="mx-0.5 hidden h-4 w-px self-center bg-slate-200 dark:bg-white/[0.1] sm:block" />}
                <div className="flex items-center gap-px">
                  <button
                    type="button"
                    onClick={zoomOut}
                    className="rounded-md p-2 text-slate-500 transition-colors hover:bg-slate-200/80 hover:text-slate-800 dark:text-slate-400 dark:hover:bg-white/[0.08] dark:hover:text-slate-100"
                    title="Zoom out"
                  >
                    <ZoomOut className="h-3.5 w-3.5" />
                  </button>
                  <span
                    className="flex min-w-[2.75rem] items-center justify-center font-mono text-[10px] tabular-nums text-slate-500 dark:text-slate-500"
                    title="Zoom level"
                  >
                    {Math.round(scale * 100)}%
                  </span>
                  <button
                    type="button"
                    onClick={zoomIn}
                    className="rounded-md p-2 text-slate-500 transition-colors hover:bg-slate-200/80 hover:text-slate-800 dark:text-slate-400 dark:hover:bg-white/[0.08] dark:hover:text-slate-100"
                    title="Zoom in"
                  >
                    <ZoomIn className="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    onClick={resetView}
                    className="rounded-md p-2 text-slate-500 transition-colors hover:bg-slate-200/80 hover:text-slate-800 dark:text-slate-400 dark:hover:bg-white/[0.08] dark:hover:text-slate-100"
                    title="Reset view"
                  >
                    <RotateCcw className="h-3.5 w-3.5" />
                  </button>
                </div>
                <div className="mx-0.5 h-4 w-px self-center bg-slate-200 dark:bg-white/[0.1]" />
                <div className="flex items-center gap-px">
                  <button
                    type="button"
                    onClick={handleCopyCode}
                    className="rounded-md p-2 text-slate-500 transition-colors hover:bg-slate-200/80 hover:text-slate-800 dark:text-slate-400 dark:hover:bg-white/[0.08] dark:hover:text-slate-100"
                    title="Copy Mermaid source"
                  >
                    {copied ? <Check className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
                  </button>
                  <button
                    type="button"
                    onClick={handleDownload}
                    className="rounded-md p-2 text-slate-500 transition-colors hover:bg-slate-200/80 hover:text-slate-800 dark:text-slate-400 dark:hover:bg-white/[0.08] dark:hover:text-slate-100"
                    title="Download SVG"
                  >
                    <Download className="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    onClick={toggleFullscreen}
                    className="rounded-md p-2 text-slate-500 transition-colors hover:bg-slate-200/80 hover:text-slate-800 dark:text-slate-400 dark:hover:bg-white/[0.08] dark:hover:text-slate-100"
                    title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
                  >
                    {isFullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
                  </button>
                </div>
              </div>
            </div>
          </>
        ) : (
          <div className="flex flex-col gap-3 border-b border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-black/35 px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between sm:gap-2">
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2.5">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-cyan-500/20 to-violet-600/15 ring-1 ring-cyan-400/25">
                <Bot className="h-4 w-4 text-cyan-200" />
              </div>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-body text-xs font-semibold tracking-tight text-gray-900 dark:text-white">{headerTitle}</span>
                  {isLive && (
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2 py-0.5 font-body text-[10px] font-semibold uppercase tracking-wide text-emerald-400 ring-1 ring-emerald-500/25">
                      <span className="relative flex h-1.5 w-1.5">
                        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
                        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400" />
                      </span>
                      Live · SSE
                    </span>
                  )}
                </div>
                <p className="font-body text-[10px] leading-snug text-gray-600">{headerSubtitle}</p>
              </div>
            </div>
            <div className="flex flex-wrap items-center justify-end gap-0.5 rounded-lg border border-cyan-500/15 bg-white dark:bg-gray-950/70 p-0.5 ring-1 ring-white/[0.04]">
              {onRegenerate && (
                <button
                  type="button"
                  onClick={onRegenerate}
                  disabled={isRegenerating}
                  className="rounded-md p-1.5 text-gray-500 transition-colors hover:bg-gray-100 dark:hover:bg-white/[0.06] hover:text-gray-900 dark:hover:text-white disabled:cursor-not-allowed disabled:text-gray-700"
                  title={isRegenerating ? 'Regenerating…' : 'Regenerate from steps'}
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${isRegenerating ? 'animate-spin' : ''}`} />
                </button>
              )}
              {onRegenerate && <div className="mx-0.5 h-4 w-px bg-white/[0.08]" />}
              <button
                type="button"
                onClick={zoomOut}
                className="rounded-md p-1.5 text-gray-500 transition-colors hover:bg-gray-100 dark:hover:bg-white/[0.06] hover:text-gray-900 dark:hover:text-white"
                title="Zoom out"
              >
                <ZoomOut className="h-3.5 w-3.5" />
              </button>
              <span className="min-w-[2.25rem] text-center font-mono text-[10px] tabular-nums text-gray-500">
                {Math.round(scale * 100)}%
              </span>
              <button
                type="button"
                onClick={zoomIn}
                className="rounded-md p-1.5 text-gray-500 transition-colors hover:bg-gray-100 dark:hover:bg-white/[0.06] hover:text-gray-900 dark:hover:text-white"
                title="Zoom in"
              >
                <ZoomIn className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                onClick={resetView}
                className="rounded-md p-1.5 text-gray-500 transition-colors hover:bg-gray-100 dark:hover:bg-white/[0.06] hover:text-gray-900 dark:hover:text-white"
                title="Reset view"
              >
                <RotateCcw className="h-3.5 w-3.5" />
              </button>
              <div className="mx-0.5 h-4 w-px bg-white/[0.08]" />
              <button
                type="button"
                onClick={handleCopyCode}
                className="rounded-md p-1.5 text-gray-500 transition-colors hover:bg-gray-100 dark:hover:bg-white/[0.06] hover:text-gray-900 dark:hover:text-white"
                title="Copy Mermaid"
              >
                {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
              </button>
              <button
                type="button"
                onClick={handleDownload}
                className="rounded-md p-1.5 text-gray-500 transition-colors hover:bg-gray-100 dark:hover:bg-white/[0.06] hover:text-gray-900 dark:hover:text-white"
                title="Download SVG"
              >
                <Download className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                onClick={toggleFullscreen}
                className="rounded-md p-1.5 text-gray-500 transition-colors hover:bg-gray-100 dark:hover:bg-white/[0.06] hover:text-gray-900 dark:hover:text-white"
                title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
              >
                {isFullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
              </button>
            </div>
          </div>
        )}

        <div
          ref={containerRef}
          className={`relative overflow-auto overscroll-contain ${
            isArch
              ? 'bg-slate-100/90 dark:bg-gradient-to-b dark:from-[#040a10] dark:via-[#060818] dark:to-[#030508]'
              : 'bg-gradient-to-b from-[#030712] via-[#050a14] to-[#020508]'
          } ${isFullscreen ? 'min-h-0 flex-1' : 'max-h-[min(560px,70vh)]'} ${isDragging ? 'cursor-grabbing' : 'cursor-grab'}`}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onWheel={handleWheel}
          style={{ touchAction: 'none' }}
        >
          <div
            className="pointer-events-none absolute inset-0 opacity-[0.4]"
            style={{
              backgroundImage: isArch
                ? 'radial-gradient(ellipse 85% 42% at 50% -12%, rgba(34, 211, 238, 0.12), transparent 50%), radial-gradient(ellipse 55% 38% at 100% 100%, rgba(100, 116, 139, 0.1), transparent 48%), linear-gradient(rgba(34,211,238,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(139,92,246,0.05) 1px, transparent 1px)'
                : 'radial-gradient(ellipse 78% 48% at 14% 6%, rgba(34, 211, 238, 0.2), transparent 55%), radial-gradient(ellipse 68% 42% at 90% 10%, rgba(139, 92, 246, 0.22), transparent 52%), radial-gradient(ellipse 52% 36% at 50% 100%, rgba(16, 185, 129, 0.1), transparent 50%), linear-gradient(rgba(34,211,238,0.055) 1px, transparent 1px), linear-gradient(90deg, rgba(139,92,246,0.06) 1px, transparent 1px)',
              backgroundSize: isArch ? '100% 100%, 100% 100%, 28px 28px, 28px 28px' : '100% 100%, 100% 100%, 100% 100%, 26px 26px, 26px 26px',
            }}
          />
          {isArch && (
            <div className="pointer-events-none absolute left-3 top-3 z-10 flex select-none items-center gap-1.5 text-slate-500 dark:text-slate-500">
              <Move className="h-3 w-3 opacity-80" />
              <span className="font-body text-[9px] font-medium uppercase tracking-wider">
                Drag to pan · scroll if clipped · Ctrl+wheel zoom
              </span>
            </div>
          )}
          {!isArch && (
            <div className="pointer-events-none absolute left-3 top-3 z-10 flex select-none items-center gap-1.5 text-cyan-500/70">
              <Move className="h-3 w-3" />
              <span className="font-body text-[9px] font-medium uppercase tracking-[0.12em]">
                Pan · scroll · Ctrl+wheel zoom
              </span>
            </div>
          )}
          <div
            ref={svgContainerRef}
            className={`relative flex items-center justify-center [&_svg]:max-w-none [&_.edgeLabel]:font-semibold [&_.edgePath_.path]:stroke-linecap-round [&_.flowchart-link]:stroke-linecap-round ${
              isArch
                ? 'min-h-[200px] p-3 sm:min-h-[220px] sm:p-4 [&_.node rect]:rx-[14px] [&_.node rect]:ry-[14px]'
                : 'min-h-[300px] p-6 sm:min-h-[320px] sm:p-8 [&_.node rect]:rx-[20px] [&_.node rect]:ry-[20px] [&_rect.label-container]:rx-[18px] [&_rect.label-container]:ry-[18px] [&_.node polygon]:rx-[16px] [&_.node polygon]:ry-[16px]'
            }`}
            style={{
              transform: `translate(${translate.x}px, ${translate.y}px) scale(${scale})`,
              transformOrigin: 'center center',
              transition: isDragging ? 'none' : 'transform 0.15s ease-out',
            }}
            dangerouslySetInnerHTML={{ __html: svg }}
          />
        </div>
      </div>

      {!isFullscreen && (
        <details
          className={
            isArch
              ? 'mt-2 overflow-hidden rounded-lg border border-slate-200/90 bg-slate-50/80 ring-1 ring-slate-900/[0.03] dark:border-white/[0.08] dark:bg-slate-950/50 dark:ring-white/[0.04]'
              : 'mt-2 overflow-hidden rounded-lg border border-white/[0.06] bg-gray-900/30 ring-1 ring-white/[0.03]'
          }
        >
          <summary
            className={`cursor-pointer select-none px-3 py-2 font-body text-[11px] font-medium ${
              isArch
                ? 'text-slate-600 hover:text-slate-900 dark:text-slate-500 dark:hover:text-slate-200'
                : 'text-gray-500 hover:text-gray-300'
            }`}
          >
            {isArch ? 'View Mermaid source' : 'Mermaid source'}
          </summary>
          <pre
            className={`overflow-auto border-t p-3 font-mono text-[10px] leading-relaxed ${
              isArch
                ? 'max-h-36 border-slate-200/80 text-slate-600 dark:border-white/[0.06] dark:text-slate-500'
                : 'max-h-40 border-white/[0.06] text-gray-500'
            }`}
          >
            <code>{chart}</code>
          </pre>
        </details>
      )}
    </div>
  );
}
