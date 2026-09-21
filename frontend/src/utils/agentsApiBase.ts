/**
 * Public base URL of the Agent Marketplace **API** (FastAPI) for `AGENTS_API_BASE` and MCP `url`.
 *
 * Vite dev often serves the SPA on :5000 / :5173 and proxies `/api` to :8000. Cursor and MCP
 * call the API (and `/mcp`) directly, so defaults must not use the dev-server origin.
 */
export function getAgentsMarketplaceApiBase(): string {
  const raw = import.meta.env?.VITE_AGENTS_API_BASE;
  const fromEnv = typeof raw === 'string' ? raw.trim() : '';
  if (fromEnv) return fromEnv.replace(/\/$/, '');

  if (typeof window !== 'undefined') {
    const { protocol, hostname, port } = window.location;
    const p = port || '';
    if (p === '5000' || p === '5173') {
      return `${protocol}//${hostname}:8000`;
    }
    return window.location.origin;
  }

  return 'http://localhost:8000';
}

/**
 * Default or migrate stored `AGENTS_API_BASE` (e.g. old drafts that saved the Vite port by mistake).
 */
export function resolveAgentsApiBaseInput(stored: string | undefined): string {
  const canonical = getAgentsMarketplaceApiBase();
  const t = (stored ?? '').trim();
  if (!t) return canonical;
  try {
    const u = new URL(t);
    if (u.port === '5000' || u.port === '5173') {
      return `${u.protocol}//${u.hostname}:8000`;
    }
  } catch {
    /* ignore */
  }
  return t;
}
