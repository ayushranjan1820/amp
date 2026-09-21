import { createContext, useContext, useState, useEffect, type ReactNode } from 'react';

const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

interface AuthState {
  isAuthenticated: boolean;
  username: string | null;
  role: string | null;
  menuPermissions: string[];
  /** Effective catalog agent IDs the signed-in user may use (from JWT /me). */
  agentPermissions: string[];
  userId: number | null;
  isLoading: boolean;
}

interface AuthContextType extends AuthState {
  login: (username: string, password: string) => Promise<{ success: boolean; error?: string }>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

const TOKEN_KEY = 'admin_token';

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    isAuthenticated: false,
    username: null,
    role: null,
    menuPermissions: [],
    agentPermissions: [],
    userId: null,
    isLoading: true,
  });

  useEffect(() => {
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) {
      setState({ isAuthenticated: false, username: null, role: null, menuPermissions: [], agentPermissions: [], userId: null, isLoading: false });
      return;
    }

    fetch(`${API_BASE}/admin/me`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => {
        if (!res.ok) throw new Error('Invalid token');
        return res.json();
      })
      .then((data) => {
        setState({
          isAuthenticated: true,
          username: data.username,
          role: data.role || 'user',
          menuPermissions: data.menu_permissions || [],
          agentPermissions: data.agent_permissions || [],
          userId: data.id || null,
          isLoading: false,
        });
      })
      .catch(() => {
        localStorage.removeItem(TOKEN_KEY);
        setState({ isAuthenticated: false, username: null, role: null, menuPermissions: [], agentPermissions: [], userId: null, isLoading: false });
      });
  }, []);

  const login = async (username: string, password: string) => {
    try {
      const res = await fetch(`${API_BASE}/admin/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });

      if (!res.ok) {
        const data = await res.json();
        return { success: false, error: data.detail || 'Login failed' };
      }

      const data = await res.json();
      localStorage.setItem(TOKEN_KEY, data.token);
      setState({
        isAuthenticated: true,
        username: data.username,
        role: data.role || 'user',
        menuPermissions: data.menu_permissions || [],
        agentPermissions: data.agent_permissions || [],
        userId: data.id || null,
        isLoading: false,
      });
      return { success: true };
    } catch {
      return { success: false, error: 'Network error. Please try again.' };
    }
  };

  const logout = () => {
    localStorage.removeItem(TOKEN_KEY);
    setState({ isAuthenticated: false, username: null, role: null, menuPermissions: [], agentPermissions: [], userId: null, isLoading: false });
  };

  return (
    <AuthContext.Provider value={{ ...state, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
