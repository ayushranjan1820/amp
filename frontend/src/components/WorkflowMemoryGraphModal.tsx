import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import {
  X,
  Brain,
  RefreshCw,
  Loader2,
  Search,
  AlertCircle,
  User as UserIcon,
  ZoomIn,
  ZoomOut,
  Expand,
  Network,
} from 'lucide-react';
import {
  getWorkflowMemories,
  getWorkflowMemoryUsers,
  type WorkflowMemoryItem,
  type WorkflowMemoriesResponse,
  type WorkflowMemoryUser,
} from '../services/api';

interface WorkflowMemoryGraphModalProps {
  open: boolean;
  workflowId: string | undefined;
  workflowName: string;
  onClose: () => void;
}

interface Node {
  id: string;
  kind: 'workflow' | 'agent' | 'memory';
  label: string;
  x: number;
  y: number;
  r: number;
  raw?: WorkflowMemoryItem;
  agentId?: string;
  /** Per-agent ordinal for memory badges (1-based). */
  memorySlot?: number;
}

interface Edge {
  from: string;
  to: string;
}

const COLORS: Record<Node['kind'], { fill: string; stroke: string; text: string; ring: string }> = {
  workflow: {
    fill: 'url(#wf-grad)',
    stroke: 'rgb(251 191 36)',
    text: 'rgb(254 243 199)',
    ring: 'rgba(251,191,36,0.35)',
  },
  agent: {
    fill: 'url(#agent-grad)',
    stroke: 'rgb(125 211 252)',
    text: 'rgb(224 242 254)',
    ring: 'rgba(56,189,248,0.30)',
  },
  memory: {
    fill: 'url(#mem-grad)',
    stroke: 'rgb(110 231 183)',
    text: 'rgb(209 250 229)',
    ring: 'rgba(16,185,129,0.28)',
  },
};

function getMemoryText(m: WorkflowMemoryItem): string {
  return String(m.memory ?? m.text ?? m.content ?? '').trim();
}

function getAgentId(m: WorkflowMemoryItem): string {
  const md = (m.metadata as Record<string, unknown> | null | undefined) || {};
  return (
    (typeof md.agent_id === 'string' && md.agent_id) ||
    (typeof md.agent_name === 'string' && md.agent_name) ||
    'unknown'
  );
}

function getAgentLabel(m: WorkflowMemoryItem): string {
  const md = (m.metadata as Record<string, unknown> | null | undefined) || {};
  if (typeof md.agent_name === 'string' && md.agent_name) return md.agent_name;
  if (typeof md.agent_id === 'string' && md.agent_id) return md.agent_id;
  return 'unknown agent';
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

function formatDate(iso?: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

const WIDTH = 1100;
const HEIGHT = 640;

/** Curved connector: quadratic bend perpendicular to chord (readable org-chart style). */
function curvedConnector(
  ax: number,
  ay: number,
  bx: number,
  by: number,
  bendStrength = 0.22,
): string {
  const mx = (ax + bx) / 2;
  const my = (ay + by) / 2;
  const dx = bx - ax;
  const dy = by - ay;
  const len = Math.hypot(dx, dy) || 1;
  const ux = -dy / len;
  const uy = dx / len;
  const k = len * bendStrength;
  const cx = mx + ux * k;
  const cy = my + uy * k;
  return `M ${ax} ${ay} Q ${cx} ${cy} ${bx} ${by}`;
}

export default function WorkflowMemoryGraphModal({
  open,
  workflowId,
  workflowName,
  onClose,
}: WorkflowMemoryGraphModalProps) {
  const [data, setData] = useState<WorkflowMemoriesResponse | null>(null);
  const [users, setUsers] = useState<WorkflowMemoryUser[]>([]);
  const [ownerUserId, setOwnerUserId] = useState<number | null>(null);
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [usersLoading, setUsersLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const draggingRef = useRef<{ x: number; y: number } | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  const fetchMemories = useCallback(
    async (targetUserId: number | null) => {
      if (!workflowId) return;
      if (targetUserId === null) {
        setData({ success: true, results: [], available: true });
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const res = await getWorkflowMemories(workflowId, {
          page: 1,
          pageSize: 100,
          targetUserId,
        });
        setData(res);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    },
    [workflowId],
  );

  // Load the user list when the modal opens.
  useEffect(() => {
    if (!open || !workflowId) return;
    let cancelled = false;
    setUsersLoading(true);
    getWorkflowMemoryUsers(workflowId)
      .then((res) => {
        if (cancelled) return;
        setUsers(res.users || []);
        setOwnerUserId(res.owner_user_id ?? null);
        const initial =
          res.owner_user_id ?? (res.users && res.users.length ? res.users[0].user_id : null);
        setSelectedUserId(initial);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setUsersLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, workflowId]);

  // Re-fetch memories whenever the selected user changes.
  useEffect(() => {
    if (!open || !workflowId) return;
    void fetchMemories(selectedUserId);
  }, [open, workflowId, selectedUserId, fetchMemories]);

  // Reset transient UI state when the modal closes.
  useEffect(() => {
    if (!open) {
      setData(null);
      setUsers([]);
      setOwnerUserId(null);
      setSelectedUserId(null);
      setSelectedNode(null);
      setFilter('');
      setZoom(1);
      setPan({ x: 0, y: 0 });
      setError(null);
    }
  }, [open]);

  /** Build the radial graph layout. */
  const { nodes, edges } = useMemo<{ nodes: Node[]; edges: Edge[] }>(() => {
    if (!data?.results?.length) {
      return { nodes: [], edges: [] };
    }
    const filterLc = filter.trim().toLowerCase();
    const memoriesAll = data.results.filter((m) => {
      if (!filterLc) return true;
      const text = getMemoryText(m).toLowerCase();
      const agentLbl = getAgentLabel(m).toLowerCase();
      return text.includes(filterLc) || agentLbl.includes(filterLc);
    });

    const cx = WIDTH / 2;
    const cy = HEIGHT / 2;
    const _nodes: Node[] = [];
    const _edges: Edge[] = [];

    _nodes.push({
      id: 'workflow',
      kind: 'workflow',
      label: workflowName || 'Workflow',
      x: cx,
      y: cy,
      r: 46,
    });

    // Group memories by agent.
    const byAgent = new Map<string, { label: string; items: WorkflowMemoryItem[] }>();
    for (const m of memoriesAll) {
      const aid = getAgentId(m);
      const lbl = getAgentLabel(m);
      const bucket = byAgent.get(aid) || { label: lbl, items: [] };
      bucket.items.push(m);
      byAgent.set(aid, bucket);
    }

    const agentEntries = Array.from(byAgent.entries());
    const agentRadius = 230;
    const memRadius = 130;

    agentEntries.forEach(([aid, bucket], i) => {
      const angle = (2 * Math.PI * i) / Math.max(agentEntries.length, 1) - Math.PI / 2;
      const ax = cx + agentRadius * Math.cos(angle);
      const ay = cy + agentRadius * Math.sin(angle);
      const agentNodeId = `agent-${aid}`;
      _nodes.push({
        id: agentNodeId,
        kind: 'agent',
        label: bucket.label,
        x: ax,
        y: ay,
        r: 30,
        agentId: aid,
      });
      _edges.push({ from: 'workflow', to: agentNodeId });

      // Place memory nodes around the agent in a partial fan facing outward.
      const n = bucket.items.length;
      const spread = Math.min(Math.PI * 1.2, 0.6 + n * 0.18);
      const startAngle = angle - spread / 2;
      bucket.items.forEach((m, j) => {
        const t = n === 1 ? 0.5 : j / (n - 1);
        const a = startAngle + t * spread;
        const r = memRadius + (j % 2 === 0 ? 0 : 32);
        const mx = ax + r * Math.cos(a);
        const my = ay + r * Math.sin(a);
        const mid = m.id ? `mem-${m.id}` : `mem-${aid}-${j}`;
        _nodes.push({
          id: mid,
          kind: 'memory',
          label: truncate(getMemoryText(m), 38) || '(empty)',
          x: mx,
          y: my,
          r: 17,
          raw: m,
          agentId: aid,
          memorySlot: j + 1,
        });
        _edges.push({ from: agentNodeId, to: mid });
      });
    });

    return { nodes: _nodes, edges: _edges };
  }, [data, filter, workflowName]);

  const nodeIndex = useMemo(() => {
    const map = new Map<string, Node>();
    for (const n of nodes) map.set(n.id, n);
    return map;
  }, [nodes]);

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    setZoom((z) => Math.min(3, Math.max(0.4, z * delta)));
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    draggingRef.current = { x: e.clientX - pan.x, y: e.clientY - pan.y };
  };
  const handleMouseMove = (e: React.MouseEvent) => {
    if (!draggingRef.current) return;
    setPan({ x: e.clientX - draggingRef.current.x, y: e.clientY - draggingRef.current.y });
  };
  const handleMouseUp = () => {
    draggingRef.current = null;
  };

  const resetView = () => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  };

  const fitGraphInView = useCallback(() => {
    if (!nodes.length) {
      setZoom(1);
      setPan({ x: 0, y: 0 });
      return;
    }
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const n of nodes) {
      const lateral = n.kind === 'workflow' ? 72 : n.kind === 'agent' ? 96 : 40;
      const top = n.kind === 'agent' ? 28 : 24;
      minX = Math.min(minX, n.x - n.r - lateral);
      maxX = Math.max(maxX, n.x + n.r + lateral);
      minY = Math.min(minY, n.y - n.r - top);
      let bottom = n.y + n.r + (n.kind === 'memory' ? 36 : 32);
      if (n.kind === 'agent') bottom = Math.max(bottom, n.y + n.r + 26);
      maxY = Math.max(maxY, bottom);
    }
    const gw = Math.max(maxX - minX, 200);
    const gh = Math.max(maxY - minY, 200);
    const gcX = (minX + maxX) / 2;
    const gcY = (minY + maxY) / 2;
    const s = Math.min((WIDTH - 56) / gw, (HEIGHT - 56) / gh) * 0.9;
    const clamped = Math.min(3, Math.max(0.38, s));
    setZoom(clamped);
    setPan({
      x: WIDTH / 2 - clamped * gcX,
      y: HEIGHT / 2 - clamped * gcY,
    });
  }, [nodes]);

  if (!open) return null;

  const total = data?.results?.length ?? 0;
  const memoryCount = nodes.filter((n) => n.kind === 'memory').length;
  const agentCount = nodes.filter((n) => n.kind === 'agent').length;
  const selectedUser = users.find((u) => u.user_id === selectedUserId) || null;
  const selectedUserLabel =
    selectedUser?.username ||
    (selectedUserId !== null ? `user #${selectedUserId}` : 'no user selected');

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 p-3 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="relative flex h-[92vh] w-full max-w-[1280px] flex-col overflow-hidden rounded-3xl border border-gray-200 dark:border-white/[0.08] bg-zinc-950/95 shadow-[0_30px_80px_-30px_rgba(0,0,0,0.9)] ring-1 ring-white/[0.04]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-200 dark:border-white/[0.06] bg-gradient-to-b from-zinc-900/90 to-zinc-950/90 px-5 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500/20 to-teal-600/15 ring-1 ring-emerald-400/30">
              <Network className="h-5 w-5 text-emerald-300" aria-hidden />
            </div>
            <div>
              <h3 className="font-heading text-base font-semibold tracking-tight text-gray-900 dark:text-white">
                Knowledge graph
              </h3>
              <p className="font-body text-xs text-zinc-500">
                Workflow memory · {workflowName ? `${workflowName} · ` : ''}
                <span className="text-zinc-400">{memoryCount}</span> memories ·{' '}
                <span className="text-zinc-400">{agentCount}</span> agents
                <span className="ml-2 inline-flex items-center gap-1 rounded-md border border-emerald-500/15 bg-emerald-500/[0.08] px-1.5 py-0.5 text-[10px] font-medium text-emerald-200">
                  <UserIcon className="h-2.5 w-2.5" />
                  {selectedUserLabel}
                </span>
                {data?.mem_user_id ? (
                  <span className="ml-2 rounded-md border border-gray-200 dark:border-white/[0.06] bg-black/30 px-1.5 py-0.5 font-mono text-[10px] text-zinc-500">
                    {data.mem_user_id}
                  </span>
                ) : null}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <div className="hidden items-center gap-1.5 rounded-lg border border-gray-200 dark:border-white/[0.06] bg-zinc-900/60 px-2 py-1.5 sm:flex">
              <Search className="h-3.5 w-3.5 text-zinc-500" />
              <input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Filter memories..."
                className="w-44 bg-transparent text-xs text-gray-900 dark:text-white placeholder:text-zinc-500 focus:outline-none"
              />
            </div>
            <button
              type="button"
              onClick={resetView}
              className="rounded-lg border border-gray-200 dark:border-white/[0.06] bg-zinc-900/60 px-2.5 py-1.5 text-xs font-medium text-zinc-300 hover:bg-zinc-800/60"
              title="Reset view"
            >
              Reset
            </button>
            <button
              type="button"
              onClick={() => fetchMemories(selectedUserId)}
              disabled={loading || selectedUserId === null}
              className="flex items-center gap-1.5 rounded-lg border border-gray-200 dark:border-white/[0.08] bg-zinc-900/60 px-2.5 py-1.5 text-xs font-medium text-zinc-200 hover:bg-zinc-800/60 disabled:opacity-50"
            >
              {loading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
              Refresh
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-gray-200 dark:border-white/[0.06] bg-zinc-900/60 p-1.5 text-zinc-400 hover:bg-zinc-800/60 hover:text-gray-900 dark:hover:text-white"
              aria-label="Close"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* User picker strip — memory is per-user, so admin chooses whose bucket to view */}
        <div className="flex items-center gap-2 overflow-x-auto border-b border-gray-200 dark:border-white/[0.06] bg-zinc-950/70 px-5 py-2.5">
          <span className="shrink-0 font-body text-[11px] uppercase tracking-wider text-zinc-500">
            User memory
          </span>
          {usersLoading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-zinc-500" />
          ) : users.length === 0 ? (
            <span className="font-body text-[11px] text-zinc-500">
              No users have run this workflow yet
            </span>
          ) : (
            <div className="flex items-center gap-1.5">
              {users.map((u) => {
                const active = u.user_id === selectedUserId;
                return (
                  <button
                    key={u.user_id}
                    type="button"
                    onClick={() => setSelectedUserId(u.user_id)}
                    title={`Show memories for user #${u.user_id}${u.is_owner ? ' (owner)' : ''}`}
                    className={`group inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-body text-[11px] font-medium transition-all ${
                      active
                        ? 'border-emerald-500/40 bg-emerald-500/[0.14] text-emerald-100'
                        : 'border-gray-200 dark:border-white/[0.06] bg-zinc-900/60 text-zinc-300 hover:bg-zinc-800/60 hover:text-gray-900 dark:hover:text-white'
                    }`}
                  >
                    <UserIcon
                      className={`h-3 w-3 ${active ? 'text-emerald-300' : 'text-zinc-500'}`}
                    />
                    <span className="max-w-[160px] truncate">
                      {u.username || `user #${u.user_id}`}
                    </span>
                    {u.is_owner && (
                      <span className="rounded-md border border-amber-500/25 bg-amber-500/[0.10] px-1 py-0.5 font-mono text-[9px] uppercase tracking-wider text-amber-200">
                        owner
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          )}
          {ownerUserId !== null && users.length > 0 && (
            <button
              type="button"
              onClick={() => setSelectedUserId(ownerUserId)}
              disabled={selectedUserId === ownerUserId}
              className="ml-auto shrink-0 rounded-md border border-gray-200 dark:border-white/[0.06] bg-zinc-900/60 px-2 py-1 font-body text-[10px] font-medium text-zinc-400 hover:text-gray-900 dark:hover:text-white disabled:opacity-40"
            >
              Reset to owner
            </button>
          )}
        </div>

        {/* Body */}
        <div className="flex flex-1 min-h-0">
          {/* Graph canvas */}
          <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden bg-[radial-gradient(ellipse_85%_60%_at_50%_38%,rgba(16,185,129,0.085)_0%,rgba(0,0,0,0)_50%),linear-gradient(180deg,#06080c_0%,#0c1018_100%)]">
            {data && !loading && data.available === false && (
              <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 p-6 text-center">
                <AlertCircle className="h-8 w-8 text-amber-300" />
                <p className="font-heading text-sm font-semibold text-gray-900 dark:text-white">
                  Memory backend not configured
                </p>
                <p className="max-w-md font-body text-xs text-zinc-400">
                  mem0 isn't initialised on the server. Set{' '}
                  <code className="rounded bg-black/40 px-1 py-0.5 font-mono text-[10px] text-emerald-300">
                    MEMO_GRAPH_MEMEORY_API_KEY
                  </code>{' '}
                  and install{' '}
                  <code className="rounded bg-black/40 px-1 py-0.5 font-mono text-[10px] text-emerald-300">
                    mem0ai
                  </code>
                  .
                </p>
              </div>
            )}
            {error && !loading && (
              <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 p-6 text-center">
                <AlertCircle className="h-8 w-8 text-rose-400" />
                <p className="font-heading text-sm font-semibold text-gray-900 dark:text-white">Failed to load memories</p>
                <p className="max-w-md font-body text-xs text-rose-300">{error}</p>
              </div>
            )}
            {loading && (
              <div className="absolute inset-0 z-10 flex items-center justify-center">
                <Loader2 className="h-8 w-8 animate-spin text-emerald-300" />
              </div>
            )}
            {!loading && !error && data && total === 0 && (
              <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 p-6 text-center">
                <Brain className="h-9 w-9 text-zinc-600" />
                <p className="font-heading text-sm font-semibold text-gray-900 dark:text-white">
                  {selectedUserId === null
                    ? 'Pick a user'
                    : `No memories for ${selectedUserLabel}`}
                </p>
                <p className="max-w-md font-body text-xs text-zinc-400">
                  {selectedUserId === null
                    ? 'Memory is stored per-user. Pick a user above to view their bucket — each user keeps an isolated set of memories for this workflow.'
                    : "This user hasn't accumulated any memories yet. Turn the Memory toggle on and run the workflow as this user — each step's query/response pair is stored in mem0 under their personal namespace."}
                </p>
              </div>
            )}

            {/* Viewport frame */}
            <div className="relative z-[1] m-3 min-h-0 flex-1 overflow-hidden rounded-2xl border border-gray-200 dark:border-white/[0.06] bg-[#070a10]/70 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)] ring-1 ring-black/30">
              <svg
                ref={svgRef}
                viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
                className="h-full min-h-[280px] w-full cursor-grab touch-none selection:bg-transparent active:cursor-grabbing"
                onWheel={handleWheel}
                onMouseDown={handleMouseDown}
                onMouseMove={handleMouseMove}
                onMouseUp={handleMouseUp}
                onMouseLeave={handleMouseUp}
              >
                <defs>
                  <radialGradient id="wf-mem-graph-wf-grad" cx="50%" cy="40%" r="65%">
                    <stop offset="0%" stopColor="rgb(253 224 171)" stopOpacity="0.98" />
                    <stop offset="100%" stopColor="rgb(180 83 9)" stopOpacity="0.82" />
                  </radialGradient>
                  <radialGradient id="wf-mem-graph-agent-grad" cx="45%" cy="35%" r="68%">
                    <stop offset="0%" stopColor="rgb(186 230 253)" stopOpacity="0.95" />
                    <stop offset="100%" stopColor="rgb(2 132 199)" stopOpacity="0.82" />
                  </radialGradient>
                  <radialGradient id="wf-mem-graph-mem-grad" cx="40%" cy="30%" r="70%">
                    <stop offset="0%" stopColor="rgb(167 243 208)" stopOpacity="0.98" />
                    <stop offset="100%" stopColor="rgb(4 120 87)" stopOpacity="0.88" />
                  </radialGradient>
                  <radialGradient id="wf-mem-graph-vignette" cx="50%" cy="42%" r="72%">
                    <stop offset="0%" stopColor="rgb(0 0 0)" stopOpacity="0" />
                    <stop offset="100%" stopColor="rgb(0 0 0)" stopOpacity="0.62" />
                  </radialGradient>
                  <filter id="wf-mem-graph-soft-glow">
                    <feGaussianBlur stdDeviation="2.2" result="b" />
                    <feMerge>
                      <feMergeNode in="b" />
                      <feMergeNode in="SourceGraphic" />
                    </feMerge>
                  </filter>
                  <filter id="wf-mem-graph-node-shadow">
                    <feDropShadow dx="0" dy="3" stdDeviation="3" floodOpacity="0.45" floodColor="#000000" />
                  </filter>
                  <pattern id="wf-mem-graph-dot" width="22" height="22" patternUnits="userSpaceOnUse">
                    <circle cx="1.2" cy="1.2" r="0.9" fill="rgba(148,163,184,0.05)" />
                  </pattern>
                </defs>

                <rect width={WIDTH} height={HEIGHT} fill="url(#wf-mem-graph-dot)" />

                <g transform={`translate(${pan.x}, ${pan.y}) scale(${zoom})`}>
                  {edges.map((e, idx) => {
                    const a = nodeIndex.get(e.from);
                    const b = nodeIndex.get(e.to);
                    if (!a || !b) return null;
                    const isMemEdge = b.kind === 'memory';
                    const bent = isMemEdge ? 0.11 : a.kind === 'workflow' ? 0.28 : 0.2;
                    const d = curvedConnector(a.x, a.y, b.x, b.y, bent);
                    const edgeLit =
                      !selectedNode ||
                      selectedNode.id === e.from ||
                      selectedNode.id === e.to;
                    const opacity = edgeLit ? 1 : 0.22;
                    return (
                      <path
                        key={`${e.from}-${e.to}-${idx}`}
                        d={d}
                        fill="none"
                        stroke={isMemEdge ? 'rgba(16,185,129,0.38)' : 'rgba(56,189,248,0.42)'}
                        strokeWidth={isMemEdge ? 1.05 : 1.5}
                        strokeLinecap="round"
                        strokeDasharray={isMemEdge ? '2 6' : undefined}
                        opacity={opacity}
                      />
                    );
                  })}

                  {nodes.map((n) => {
                    const c =
                      n.kind === 'workflow'
                        ? {
                            ...COLORS.workflow,
                            fill: 'url(#wf-mem-graph-wf-grad)',
                          }
                        : n.kind === 'agent'
                          ? {
                              ...COLORS.agent,
                              fill: 'url(#wf-mem-graph-agent-grad)',
                            }
                          : {
                              ...COLORS.memory,
                              fill: 'url(#wf-mem-graph-mem-grad)',
                            };
                    const isSelected = selectedNode?.id === n.id;
                    const tip =
                      n.kind === 'memory' && n.raw
                        ? getMemoryText(n.raw).slice(0, 560) || '(empty)'
                        : n.label;
                    return (
                      <g
                        key={n.id}
                        transform={`translate(${n.x}, ${n.y})`}
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedNode(n);
                        }}
                        style={{ cursor: 'pointer' }}
                      >
                        <title>{tip}</title>
                        {isSelected && (
                          <circle
                            r={n.r + 9}
                            fill="none"
                            stroke={c.stroke}
                            strokeOpacity="0.5"
                            strokeWidth="2.5"
                          />
                        )}
                        <circle r={n.r + 5} fill={c.ring} opacity={isSelected ? 0.75 : 0.45} />
                        <circle
                          r={n.r}
                          fill={c.fill}
                          stroke={c.stroke}
                          strokeWidth={isSelected ? 2 : 1.35}
                          filter={
                            n.kind === 'workflow'
                              ? 'url(#wf-mem-graph-soft-glow)'
                              : 'url(#wf-mem-graph-node-shadow)'
                          }
                          opacity={0.97}
                        />
                        {n.kind === 'workflow' && (
                          <text
                            y="6"
                            textAnchor="middle"
                            dominantBaseline="middle"
                            fill={c.text}
                            fontSize="12.5"
                            fontWeight="700"
                            letterSpacing="-0.02em"
                            style={{ pointerEvents: 'none' }}
                          >
                            {truncate(n.label, 13)}
                          </text>
                        )}
                        {n.kind === 'agent' && (
                          <text
                            y={n.r + 18}
                            textAnchor="middle"
                            fill={c.text}
                            fontSize="10.5"
                            fontWeight="600"
                            letterSpacing="-0.01em"
                            style={{ pointerEvents: 'none' }}
                            opacity="0.95"
                          >
                            {truncate(n.label, 20)}
                          </text>
                        )}
                        {n.kind === 'memory' && n.memorySlot != null && (
                          <text
                            y="4.5"
                            textAnchor="middle"
                            dominantBaseline="middle"
                            fill="rgb(6 53 42)"
                            fontSize="11"
                            fontWeight="800"
                            style={{ pointerEvents: 'none' }}
                          >
                            {n.memorySlot > 99 ? '·' : String(n.memorySlot)}
                          </text>
                        )}
                      </g>
                    );
                  })}
                </g>

                <rect width={WIDTH} height={HEIGHT} fill="url(#wf-mem-graph-vignette)" pointerEvents="none" />
              </svg>

              {/* Graph HUD */}
              {nodes.length > 0 && !loading && !error && (
                <>
                  <div className="absolute left-3 top-3 z-20 flex flex-col gap-1 rounded-xl border border-gray-200 dark:border-white/[0.08] bg-zinc-950/90 p-1 shadow-xl shadow-black/50 backdrop-blur-md">
                    <button
                      type="button"
                      onClick={() =>
                        setZoom((z) => Math.min(3, Math.round(z * 1.18 * 100) / 100))
                      }
                      className="flex h-8 w-8 items-center justify-center rounded-lg text-zinc-400 transition-colors hover:bg-gray-100 dark:hover:bg-white/[0.06] hover:text-gray-900 dark:hover:text-white"
                      title="Zoom in"
                      aria-label="Zoom in"
                    >
                      <ZoomIn className="h-4 w-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        setZoom((z) => Math.max(0.38, Math.round(z * 0.85 * 100) / 100))
                      }
                      className="flex h-8 w-8 items-center justify-center rounded-lg text-zinc-400 transition-colors hover:bg-gray-100 dark:hover:bg-white/[0.06] hover:text-gray-900 dark:hover:text-white"
                      title="Zoom out"
                      aria-label="Zoom out"
                    >
                      <ZoomOut className="h-4 w-4" />
                    </button>
                    <div className="border-t border-gray-200 dark:border-white/[0.06] pt-1">
                      <button
                        type="button"
                        onClick={fitGraphInView}
                        className="flex h-8 w-8 items-center justify-center rounded-lg text-zinc-400 transition-colors hover:bg-gray-100 dark:hover:bg-white/[0.06] hover:text-gray-900 dark:hover:text-white"
                        title="Fit graph in view"
                        aria-label="Fit graph in view"
                      >
                        <Expand className="h-4 w-4" />
                      </button>
                    </div>
                    <span className="block border-t border-gray-200 dark:border-white/[0.06] px-1 py-2 text-center font-mono text-[10px] font-medium tabular-nums text-zinc-500">
                      {Math.round(zoom * 100)}%
                    </span>
                  </div>

                  <div className="pointer-events-none absolute bottom-3 left-1/2 z-10 flex max-w-[min(96%,760px)] -translate-x-1/2 flex-col items-center gap-2 px-4 sm:flex-row sm:gap-6">
                    <div className="flex flex-wrap items-center justify-center gap-2 rounded-2xl border border-gray-200 dark:border-white/[0.07] bg-white dark:bg-zinc-950/88 px-3 py-2 shadow-lg shadow-black/40 backdrop-blur-md">
                      <span className="mr-1 hidden shrink-0 items-center gap-1 font-body text-[9px] font-semibold uppercase tracking-wider text-zinc-500 sm:inline-flex">
                        <Network className="h-3 w-3 text-emerald-500/80" />
                        Key
                      </span>
                      <LegendChip
                        gradient="from-amber-400 to-amber-700"
                        stroke="rgba(251,191,36,0.8)"
                        label="Workflow"
                      />
                      <LegendChip
                        gradient="from-sky-400 to-sky-700"
                        stroke="rgba(56,189,248,0.75)"
                        label="Agent"
                      />
                      <LegendChip
                        gradient="from-emerald-400 to-emerald-700"
                        stroke="rgba(52,211,153,0.75)"
                        label="Memory"
                      />
                    </div>
                    <p className="text-center font-body text-[10px] tabular-nums leading-relaxed text-zinc-500 sm:max-w-[220px] sm:text-left">
                      <span className="text-zinc-400">Scroll</span> zoom ·{' '}
                      <span className="text-zinc-400">Drag</span> pan ·{' '}
                      <span className="text-zinc-400">Click</span> inspect
                    </p>
                  </div>
                </>
              )}
            </div>
          </div>

          {/* Detail panel */}
          <div className="hidden w-[340px] shrink-0 flex-col border-l border-gray-200 dark:border-white/[0.06] bg-zinc-950/85 md:flex">
            <DetailPanel selected={selectedNode} total={total} />
          </div>
        </div>
      </div>
    </div>
  );
}

function LegendChip({
  label,
  gradient,
  stroke,
}: {
  label: string;
  /** Tailwind color stops only, combined with bg-gradient-to-br in the span. */
  gradient: string;
  stroke: string;
}) {
  return (
    <span className="inline-flex items-center gap-2 rounded-xl border border-gray-200 dark:border-white/[0.07] bg-white dark:bg-zinc-950/80 px-2.5 py-1 shadow-inner shadow-black/30">
      <span
        className={`relative size-3 shrink-0 rounded-full bg-gradient-to-br shadow-sm ${gradient}`}
        style={{ boxShadow: `0 0 12px ${stroke}`, borderWidth: 1, borderStyle: 'solid', borderColor: stroke }}
      />
      <span className="font-body text-[10px] font-semibold uppercase tracking-wide text-zinc-200">
        {label}
      </span>
    </span>
  );
}
function DetailPanel({ selected, total }: { selected: Node | null; total: number }) {
  if (!selected) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center">
        <Brain className="h-7 w-7 text-zinc-600" />
        <p className="font-heading text-sm font-semibold text-gray-900 dark:text-white">Select a node</p>
        <p className="font-body text-xs text-zinc-500">
          Click any node in the graph to inspect its memory entry, agent context, and metadata.
        </p>
        <p className="mt-3 rounded-md border border-gray-200 dark:border-white/[0.06] bg-black/30 px-2 py-1 font-mono text-[10px] text-zinc-400">
          {total} memories total
        </p>
      </div>
    );
  }

  if (selected.kind === 'workflow') {
    return (
      <div className="flex h-full flex-col gap-3 p-5">
        <div>
          <span className="rounded-full border border-amber-500/30 bg-amber-500/[0.12] px-2 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wider text-amber-200">
            Workflow
          </span>
        </div>
        <h4 className="font-heading text-base font-semibold text-gray-900 dark:text-white">{selected.label}</h4>
        <p className="font-body text-xs text-zinc-400">
          Root of this memory graph. All agent activity for runs of this workflow accumulates
          beneath it.
        </p>
      </div>
    );
  }

  if (selected.kind === 'agent') {
    return (
      <div className="flex h-full flex-col gap-3 p-5">
        <div>
          <span className="rounded-full border border-sky-500/30 bg-sky-500/[0.12] px-2 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wider text-sky-200">
            Agent
          </span>
        </div>
        <h4 className="font-heading text-base font-semibold text-gray-900 dark:text-white">{selected.label}</h4>
        <p className="font-body text-[11px] text-zinc-500">
          Memories below this node were captured from this agent's steps in past runs.
        </p>
        {selected.agentId ? (
          <div className="mt-1 rounded-lg border border-gray-200 dark:border-white/[0.06] bg-black/30 p-2.5">
            <p className="font-body text-[10px] uppercase tracking-wider text-zinc-500">Agent id</p>
            <p className="mt-1 break-all font-mono text-xs text-zinc-200">{selected.agentId}</p>
          </div>
        ) : null}
      </div>
    );
  }

  // Memory node
  const m = selected.raw;
  const text = m ? getMemoryText(m) : '';
  const md = (m?.metadata as Record<string, unknown> | null | undefined) || {};
  const categories = Array.isArray(m?.categories) ? (m?.categories as string[]) : [];

  return (
    <div className="flex h-full flex-col gap-3 overflow-hidden p-5">
      <div className="flex items-center justify-between">
        <span className="rounded-full border border-emerald-500/30 bg-emerald-500/[0.12] px-2 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wider text-emerald-200">
          Memory
        </span>
        {m?.created_at && (
          <span className="font-mono text-[10px] text-zinc-500">{formatDate(m.created_at)}</span>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-gray-200 dark:border-white/[0.06] bg-black/30 p-3">
        <p className="whitespace-pre-wrap font-body text-xs leading-relaxed text-zinc-100">
          {text || '(empty memory)'}
        </p>
      </div>
      {categories.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {categories.map((c) => (
            <span
              key={c}
              className="rounded-full border border-gray-200 dark:border-white/[0.06] bg-zinc-900/70 px-2 py-0.5 font-mono text-[10px] text-zinc-300"
            >
              {c}
            </span>
          ))}
        </div>
      )}
      {Object.keys(md).length > 0 && (
        <div className="rounded-lg border border-gray-200 dark:border-white/[0.06] bg-black/30 p-2.5">
          <p className="font-body text-[10px] uppercase tracking-wider text-zinc-500">Metadata</p>
          <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap break-all font-mono text-[10px] text-zinc-300">
            {JSON.stringify(md, null, 2)}
          </pre>
        </div>
      )}
      {m?.id && (
        <p className="break-all font-mono text-[10px] text-zinc-500">id: {String(m.id)}</p>
      )}
    </div>
  );
}
