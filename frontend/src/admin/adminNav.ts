export type AdminTab =
  | 'overview'
  | 'agents'
  | 'sessions'
  | 'costs'
  | 'usage'
  | 'settings'
  | 'agent-studio'
  | 'knowledge-base'
  | 'users'
  | 'review-queue';

export const ADMIN_TAB_PATHS: Record<AdminTab, string> = {
  overview: '/admin',
  agents: '/admin/agents',
  sessions: '/admin/sessions',
  costs: '/admin/costs',
  usage: '/admin/usage',
  'agent-studio': '/admin/agent-studio',
  'knowledge-base': '/admin/knowledge-base',
  settings: '/admin/settings',
  users: '/admin/users',
  'review-queue': '/admin/review-queue',
};

export function getTabFromPath(path: string): AdminTab {
  if (path.includes('/admin/review-queue')) return 'review-queue';
  if (path.includes('/admin/agent-studio')) return 'agent-studio';
  if (path.includes('/admin/knowledge-base')) return 'knowledge-base';
  if (path.includes('/admin/agents')) return 'agents';
  if (path.includes('/admin/sessions')) return 'sessions';
  if (path.includes('/admin/costs')) return 'costs';
  if (path.includes('/admin/usage')) return 'usage';
  if (path.includes('/admin/settings')) return 'settings';
  if (path.includes('/admin/users')) return 'users';
  return 'overview';
}
