import { useState, useMemo } from 'react';
import { Link, useNavigate, useLocation, Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import {
  LayoutDashboard,
  Bot,
  MessageSquare,
  Settings,
  LogOut,
  ChevronLeft,
  ChevronRight,
  Activity,
  Users,
  Zap,
  ArrowLeft,
  Shield,
  DollarSign,
  Globe,
  Database,
} from 'lucide-react';
import { ADMIN_TAB_PATHS, getTabFromPath, type AdminTab as AdminNavTab } from '../admin/adminNav';

type NavItem = { id: AdminNavTab; label: string; icon: React.ReactNode };

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const { username, logout, role, menuPermissions } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const isAdmin = role === 'admin' || role === 'super_admin';
  const canChat = isAdmin || menuPermissions.includes('chat');
  const isChatRoute = location.pathname === '/chat';
  const activeTab = getTabFromPath(location.pathname);

  const allNavItems: NavItem[] = useMemo(
    () => [
      { id: 'overview', label: 'Overview', icon: <LayoutDashboard className="w-5 h-5" /> },
      { id: 'agents', label: 'Agents', icon: <Bot className="w-5 h-5" /> },
      { id: 'sessions', label: 'Chat Sessions', icon: <MessageSquare className="w-5 h-5" /> },
      { id: 'costs', label: 'Cost Analytics', icon: <DollarSign className="w-5 h-5" /> },
      { id: 'usage', label: 'Usage Tracker', icon: <Globe className="w-5 h-5" /> },
      { id: 'agent-studio', label: 'Agent Studio', icon: <Activity className="w-5 h-5" /> },
      { id: 'knowledge-base', label: 'Knowledge Base', icon: <Database className="w-5 h-5" /> },
      { id: 'settings', label: 'Settings', icon: <Settings className="w-5 h-5" /> },
    ],
    [],
  );

  const navItems = useMemo(() => {
    const items = isAdmin ? [...allNavItems] : allNavItems.filter((item) => menuPermissions.includes(item.id));
    if (isAdmin) {
      items.push({ id: 'review-queue', label: 'Review Queue', icon: <Shield className="w-5 h-5" /> });
      items.push({ id: 'users', label: 'User Management', icon: <Users className="w-5 h-5" /> });
    }
    return items;
  }, [isAdmin, menuPermissions, allNavItems]);

  const handleTabChange = (tab: AdminNavTab) => {
    navigate(ADMIN_TAB_PATHS[tab]);
  };

  const handleLogout = () => {
    logout();
    navigate('/');
  };

  if (isChatRoute && !canChat) {
    return <Navigate to="/admin" replace />;
  }

  const chatActive = isChatRoute;
  const mainClass = isChatRoute
    ? 'relative z-10 flex flex-1 min-h-0 flex-col overflow-hidden pb-20 md:pb-0'
    : 'relative z-10 flex-1 overflow-auto pb-20 md:pb-0';

  return (
    <div
      className={`relative flex w-full flex-row bg-white dark:bg-zinc-950 text-gray-900 dark:text-zinc-100 ${
        isChatRoute ? 'min-h-0 flex-1' : 'min-h-[calc(100vh-64px)]'
      }`}
    >
      <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden>
        <div className="absolute -right-24 -top-32 h-[420px] w-[420px] rounded-full bg-primary-600/12 blur-[100px]" />
        <div className="absolute top-1/2 -left-32 h-[360px] w-[360px] -translate-y-1/2 rounded-full bg-violet-600/10 blur-[90px]" />
        <div className="absolute inset-0 bg-[linear-gradient(to_bottom,transparent,rgba(9,9,11,0.85))]" />
      </div>

      <aside
        className={`${sidebarCollapsed ? 'w-[68px]' : 'w-[260px]'} relative z-10 hidden shrink-0 flex-col border-r border-gray-200 dark:border-white/[0.06] bg-white dark:bg-zinc-950/55 shadow-[inset_-1px_0_0_rgba(255,255,255,0.04)] backdrop-blur-xl transition-[width] duration-300 ease-out md:flex`}
      >
        <div className={`border-b border-gray-200 dark:border-white/[0.06] p-4 ${sidebarCollapsed ? 'px-3' : ''}`}>
          {sidebarCollapsed ? (
            <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-2xl bg-gradient-to-br from-primary-500 via-primary-600 to-violet-600 shadow-lg shadow-primary-500/25 ring-1 ring-gray-200 dark:ring-white/10">
              <Shield className="h-5 w-5 text-gray-900 dark:text-white" />
            </div>
          ) : (
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-gradient-to-br from-primary-500 via-primary-600 to-violet-600 shadow-lg shadow-primary-500/25 ring-1 ring-gray-200 dark:ring-white/10">
                <Shield className="h-5 w-5 text-gray-900 dark:text-white" />
              </div>
              <div className="min-w-0">
                <h2 className="font-heading text-sm font-semibold tracking-tight text-gray-900 dark:text-white">Admin</h2>
                <p className="truncate font-body text-xs text-zinc-500">{username}</p>
              </div>
            </div>
          )}
        </div>

        <nav className="flex-1 space-y-0.5 p-2.5">
          {navItems.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => handleTabChange(item.id)}
              className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 font-body text-sm font-medium transition-all duration-200 ${
                !chatActive && activeTab === item.id
                  ? 'bg-gray-100 dark:bg-white/[0.08] text-gray-900 dark:text-white shadow-sm shadow-black/20 ring-1 ring-primary-500/25'
                  : 'text-gray-600 dark:text-zinc-400 ring-1 ring-transparent hover:bg-gray-100 dark:hover:bg-white/[0.05] hover:text-gray-900 dark:hover:text-white'
              } ${sidebarCollapsed ? 'justify-center px-2' : ''}`}
              title={sidebarCollapsed ? item.label : undefined}
            >
              <span className={!chatActive && activeTab === item.id ? 'text-primary-400' : 'text-zinc-500'}>{item.icon}</span>
              {!sidebarCollapsed && <span className="truncate">{item.label}</span>}
            </button>
          ))}
          {canChat && (
            <Link
              to="/chat"
              className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 font-body text-sm font-medium transition-all duration-200 ${
                chatActive
                  ? 'bg-gray-100 dark:bg-white/[0.08] text-gray-900 dark:text-white shadow-sm shadow-black/20 ring-1 ring-primary-500/25'
                  : 'text-gray-600 dark:text-zinc-400 ring-1 ring-transparent hover:bg-gray-100 dark:hover:bg-white/[0.05] hover:text-gray-900 dark:hover:text-white'
              } ${sidebarCollapsed ? 'justify-center px-2' : ''}`}
              title={sidebarCollapsed ? 'Chat' : undefined}
            >
              <Zap className={`h-5 w-5 ${chatActive ? 'text-primary-400' : 'text-zinc-500'}`} />
              {!sidebarCollapsed && <span>Chat</span>}
            </Link>
          )}
        </nav>

        <div className="space-y-0.5 border-t border-gray-200 dark:border-white/[0.06] p-2.5">
          <Link
            to="/"
            className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 font-body text-sm font-medium text-gray-600 dark:text-zinc-400 transition-all duration-200 hover:bg-gray-100 dark:hover:bg-white/[0.05] hover:text-gray-900 dark:hover:text-white ${sidebarCollapsed ? 'justify-center px-2' : ''}`}
            title={sidebarCollapsed ? 'Back to Marketplace' : undefined}
          >
            <ArrowLeft className="h-5 w-5 text-zinc-500" />
            {!sidebarCollapsed && <span>Marketplace</span>}
          </Link>
          <button
            type="button"
            onClick={handleLogout}
            className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 font-body text-sm font-medium text-red-400/90 transition-all duration-200 hover:bg-red-500/10 hover:text-red-300 ${sidebarCollapsed ? 'justify-center px-2' : ''}`}
            title={sidebarCollapsed ? 'Logout' : undefined}
          >
            <LogOut className="h-5 w-5" />
            {!sidebarCollapsed && <span>Logout</span>}
          </button>
          <button
            type="button"
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            className="flex w-full items-center justify-center rounded-lg p-2 text-zinc-500 transition-all hover:bg-gray-100 dark:hover:bg-white/[0.05] hover:text-gray-700 dark:hover:text-zinc-300"
          >
            {sidebarCollapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
          </button>
        </div>
      </aside>

      <div className="fixed bottom-0 left-0 right-0 z-50 flex border-t border-gray-200 dark:border-white/[0.08] bg-white dark:bg-zinc-950/90 pb-[env(safe-area-inset-bottom)] shadow-[0_-8px_32px_rgba(0,0,0,0.4)] backdrop-blur-xl md:hidden">
        {navItems.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => handleTabChange(item.id)}
            className={`flex flex-1 flex-col items-center gap-0.5 py-2.5 font-body text-[10px] font-medium transition-colors ${
              !chatActive && activeTab === item.id ? 'text-primary-400' : 'text-zinc-500'
            }`}
          >
            <span className={!chatActive && activeTab === item.id ? 'text-primary-400' : 'text-zinc-500'}>{item.icon}</span>
            <span className="line-clamp-2 px-0.5 text-center leading-tight">{item.label}</span>
          </button>
        ))}
        {canChat && (
          <Link
            to="/chat"
            className={`flex flex-1 flex-col items-center gap-0.5 py-2.5 font-body text-[10px] font-medium transition-colors ${
              chatActive ? 'text-primary-400' : 'text-zinc-500'
            }`}
          >
            <Zap className={`h-5 w-5 ${chatActive ? 'text-primary-400' : 'text-zinc-500'}`} />
            <span className="line-clamp-2 px-0.5 text-center leading-tight">Chat</span>
          </Link>
        )}
      </div>

      <main className={mainClass}>{children}</main>
    </div>
  );
}
