/**
 * Google Identity Services (GIS) wrapper for the agent builder.
 *
 * Loads the GIS script on demand, opens the OAuth consent popup, and returns
 * the authorization code so the backend can exchange it for tokens.
 */

const GIS_SRC = 'https://accounts.google.com/gsi/client';
const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api/agent-builder` : '/api/agent-builder';

declare global {
  interface Window {
    google?: {
      accounts: {
        oauth2: {
          initCodeClient: (config: {
            client_id: string;
            scope: string;
            ux_mode: 'popup' | 'redirect';
            callback: (resp: { code?: string; error?: string; error_description?: string }) => void;
            redirect_uri?: string;
          }) => { requestCode: () => void };
        };
      };
    };
  }
}

let _gisLoadPromise: Promise<void> | null = null;

function loadGis(): Promise<void> {
  if (window.google?.accounts?.oauth2) return Promise.resolve();
  if (_gisLoadPromise) return _gisLoadPromise;
  _gisLoadPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${GIS_SRC}"]`);
    if (existing) {
      existing.addEventListener('load', () => resolve());
      existing.addEventListener('error', () => reject(new Error('Failed to load Google Identity Services')));
      return;
    }
    const s = document.createElement('script');
    s.src = GIS_SRC;
    s.async = true;
    s.defer = true;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error('Failed to load Google Identity Services'));
    document.head.appendChild(s);
  });
  return _gisLoadPromise;
}

export interface GoogleOAuthConfig {
  configured: boolean;
  client_id: string;
}

let _configCache: GoogleOAuthConfig | null = null;

export async function getGoogleOAuthConfig(): Promise<GoogleOAuthConfig> {
  if (_configCache) return _configCache;
  const token = localStorage.getItem('admin_token');
  const r = await fetch(`${API_BASE}/oauth/google/config`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!r.ok) throw new Error('Could not load Google OAuth config');
  const data = await r.json();
  _configCache = { configured: !!data.configured, client_id: data.client_id || '' };
  return _configCache;
}

/** Open the Google consent popup and resolve with an authorization code. */
export async function requestGoogleAuthCode(scopes: string[]): Promise<string> {
  const cfg = await getGoogleOAuthConfig();
  if (!cfg.client_id) {
    throw new Error(
      'Google OAuth is not configured on the server. Set GOOGLE_OAUTH_CLIENT_ID and ' +
        'GOOGLE_OAUTH_CLIENT_SECRET in the server env (create a Web OAuth client in Google Cloud Console).',
    );
  }
  await loadGis();
  return new Promise((resolve, reject) => {
    const client = window.google!.accounts.oauth2.initCodeClient({
      client_id: cfg.client_id,
      scope: scopes.join(' '),
      ux_mode: 'popup',
      callback: (resp) => {
        if (resp.error) {
          reject(new Error(resp.error_description || resp.error));
          return;
        }
        if (!resp.code) {
          reject(new Error('No authorization code returned by Google'));
          return;
        }
        resolve(resp.code);
      },
    });
    client.requestCode();
  });
}

export interface GoogleConnectResult {
  success: boolean;
  email: string;
  scopes: string[];
  has_refresh_token: boolean;
}

export async function exchangeGoogleAuthCode(
  agentId: string,
  code: string,
  scopes: string[],
): Promise<GoogleConnectResult> {
  const token = localStorage.getItem('admin_token');
  const r = await fetch(`${API_BASE}/oauth/google/exchange`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({
      agent_id: agentId,
      code,
      redirect_uri: 'postmessage',
      scopes,
    }),
  });
  if (!r.ok) {
    const e = await r.json().catch(() => ({}));
    throw new Error(typeof e?.detail === 'string' ? e.detail : `Token exchange failed (${r.status})`);
  }
  return r.json();
}

export async function disconnectGoogle(agentId: string): Promise<void> {
  const token = localStorage.getItem('admin_token');
  const r = await fetch(`${API_BASE}/oauth/google/disconnect?agent_id=${encodeURIComponent(agentId)}`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!r.ok) {
    const e = await r.json().catch(() => ({}));
    throw new Error(typeof e?.detail === 'string' ? e.detail : `Disconnect failed (${r.status})`);
  }
}

/** Connect a Google account end-to-end: popup → exchange → return result. */
export async function connectGoogle(agentId: string, scopes: string[]): Promise<GoogleConnectResult> {
  const code = await requestGoogleAuthCode(scopes);
  return exchangeGoogleAuthCode(agentId, code, scopes);
}

export const GMAIL_SCOPES = [
  'https://www.googleapis.com/auth/gmail.modify',
  'https://www.googleapis.com/auth/userinfo.email',
];

export const DRIVE_SCOPES = [
  'https://www.googleapis.com/auth/drive',
  'https://www.googleapis.com/auth/userinfo.email',
];
