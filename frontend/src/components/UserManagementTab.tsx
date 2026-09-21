import { useState, useEffect } from 'react';
import {
  Plus, Trash2, Edit2, Save, X, User, Shield, Eye, EyeOff,
  CheckCircle, AlertCircle, Loader2, Users, Key, Crown, Bot,
} from 'lucide-react';
import { listUsers, createUser, updateUser, deleteUser, getAgents, type AdminUser, type Agent } from '../services/api';
import { useAuth } from '../context/AuthContext';
import { useLoading } from '../context/LoadingContext';

const ALL_MENU_OPTIONS = [
  { id: 'overview', label: 'Overview' },
  { id: 'agents', label: 'Agents' },
  { id: 'sessions', label: 'Chat Sessions' },
  { id: 'costs', label: 'Cost Analytics' },
  { id: 'usage', label: 'Usage Tracker' },
  { id: 'agent-studio', label: 'Agent Studio' },
  { id: 'knowledge-base', label: 'Knowledge Base' },
  { id: 'settings', label: 'Settings' },
  { id: 'chat', label: 'Chat' },
  { id: 'agent-architecture', label: 'Agent architecture diagrams' },
];

function packAgentPermissions(selectedIds: string[], allIds: string[]): string[] | null {
  if (selectedIds.length === 0) return [];
  if (allIds.length > 0 && selectedIds.length === allIds.length) return null;
  return selectedIds;
}

function storedAgentIdsToSelection(stored: string[] | null | undefined, allIds: string[]): string[] {
  if (stored === null || stored === undefined) return [...allIds];
  return [...stored];
}

export default function UserManagementTab() {
  const { role: currentRole } = useAuth();
  const isSuperAdmin = currentRole === 'super_admin';
  const { withLoader } = useLoading();

  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [editingUser, setEditingUser] = useState<number | null>(null);
  const [editPermissions, setEditPermissions] = useState<string[]>([]);
  const [editRole, setEditRole] = useState('user');
  const [editActive, setEditActive] = useState(true);
  const [resetPasswordId, setResetPasswordId] = useState<number | null>(null);
  const [newPassword, setNewPassword] = useState('');
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<number | null>(null);

  const [createUsername, setCreateUsername] = useState('');
  const [createPassword, setCreatePassword] = useState('');
  const [showCreatePassword, setShowCreatePassword] = useState(false);
  const [createRole, setCreateRole] = useState('user');
  const [createPermissions, setCreatePermissions] = useState<string[]>([]);
  const [catalogAgents, setCatalogAgents] = useState<Agent[]>([]);
  const [createAgentIds, setCreateAgentIds] = useState<string[]>([]);
  const [editAgentIds, setEditAgentIds] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  const catalogSorted = [...catalogAgents].sort((a, b) => a.name.localeCompare(b.name));
  const allCatalogIds = catalogSorted.map((a) => a.id);

  useEffect(() => {
    if (!isSuperAdmin) return;
    getAgents()
      .then((c) => setCatalogAgents(c.agents))
      .catch(() => setCatalogAgents([]));
  }, [isSuperAdmin]);

  useEffect(() => {
    if (showCreateForm && isSuperAdmin && catalogAgents.length) {
      setCreateAgentIds(catalogAgents.map((a) => a.id));
    }
  }, [showCreateForm, isSuperAdmin, catalogAgents]);

  const fetchUsers = async () => {
    setLoading(true);
    try {
      const res = await withLoader('Loading users...', () => listUsers());
      setUsers(res.users);
      setError('');
    } catch (e: any) {
      setError(e.message || 'Failed to load users');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchUsers(); }, []);

  useEffect(() => {
    if (success) {
      const t = setTimeout(() => setSuccess(''), 3000);
      return () => clearTimeout(t);
    }
  }, [success]);

  const handleCreate = async () => {
    if (!createUsername.trim() || !createPassword.trim()) {
      setError('Username and password are required');
      return;
    }
    setSaving(true);
    try {
      await withLoader('Creating user...', () => createUser({
        username: createUsername.trim(),
        password: createPassword,
        role: createRole,
        menu_permissions: createRole === 'admin'
          ? (createPermissions.length ? createPermissions : ALL_MENU_OPTIONS.map(m => m.id))
          : createPermissions,
        ...(isSuperAdmin
          ? { agent_permissions: packAgentPermissions(createAgentIds, allCatalogIds) }
          : {}),
      }));
      setSuccess(`User "${createUsername}" created successfully`);
      setShowCreateForm(false);
      setCreateUsername('');
      setCreatePassword('');
      setCreateRole('user');
      setCreatePermissions([]);
      if (catalogSorted.length) setCreateAgentIds(catalogSorted.map((a) => a.id));
      fetchUsers();
    } catch (e: any) {
      setError(e.message || 'Failed to create user');
    } finally {
      setSaving(false);
    }
  };

  const handleStartEdit = async (user: AdminUser) => {
    let agents = catalogAgents;
    if (isSuperAdmin && agents.length === 0) {
      try {
        const c = await getAgents();
        setCatalogAgents(c.agents);
        agents = c.agents;
      } catch {
        /* keep empty; agent checkboxes unavailable until catalog loads */
      }
    }
    const ids = [...agents].sort((a, b) => a.name.localeCompare(b.name)).map((a) => a.id);
    setEditingUser(user.id);
    setEditPermissions([...user.menu_permissions]);
    setEditRole(user.role);
    setEditActive(user.is_active);
    setEditAgentIds(storedAgentIdsToSelection(user.agent_permissions, ids));
  };

  const handleSaveEdit = async (userId: number) => {
    setSaving(true);
    try {
      await withLoader('Updating user...', () => updateUser(userId, {
        role: editRole,
        menu_permissions: editPermissions,
        is_active: editActive,
        ...(isSuperAdmin ? { agent_permissions: packAgentPermissions(editAgentIds, allCatalogIds) } : {}),
      }));
      setSuccess('User updated successfully');
      setEditingUser(null);
      fetchUsers();
    } catch (e: any) {
      setError(e.message || 'Failed to update user');
    } finally {
      setSaving(false);
    }
  };

  const handleResetPassword = async (userId: number) => {
    if (!newPassword.trim()) {
      setError('Password cannot be empty');
      return;
    }
    setSaving(true);
    try {
      await withLoader('Resetting password...', () => updateUser(userId, { password: newPassword }));
      setSuccess('Password reset successfully');
      setResetPasswordId(null);
      setNewPassword('');
    } catch (e: any) {
      setError(e.message || 'Failed to reset password');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (userId: number) => {
    setSaving(true);
    try {
      await withLoader('Deleting user...', () => deleteUser(userId));
      setSuccess('User deleted successfully');
      setDeleteConfirm(null);
      fetchUsers();
    } catch (e: any) {
      setError(e.message || 'Failed to delete user');
    } finally {
      setSaving(false);
    }
  };

  const togglePermission = (perms: string[], setPerms: (v: string[]) => void, perm: string) => {
    setPerms(perms.includes(perm) ? perms.filter(p => p !== perm) : [...perms, perm]);
  };

  const selectAllPermissions = (setPerms: (v: string[]) => void) => {
    setPerms(ALL_MENU_OPTIONS.map(m => m.id));
  };

  const clearAllPermissions = (setPerms: (v: string[]) => void) => {
    setPerms([]);
  };

  const toggleAgentId = (ids: string[], setIds: (v: string[]) => void, id: string) => {
    setIds(ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]);
  };

  const selectAllAgentIds = (setIds: (v: string[]) => void) => {
    setIds([...allCatalogIds]);
  };

  const clearAllAgentIds = (setIds: (v: string[]) => void) => {
    setIds([]);
  };

  const getRoleDisplay = (role: string) => {
    if (role === 'super_admin') return { label: 'Super Admin', bg: 'bg-purple-500/10', text: 'text-purple-400', border: 'border-purple-500/20' };
    if (role === 'admin') return { label: 'Admin', bg: 'bg-amber-500/10', text: 'text-amber-400', border: 'border-amber-500/20' };
    return { label: 'User', bg: 'bg-blue-500/10', text: 'text-blue-400', border: 'border-blue-500/20' };
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-primary-400" />
      </div>
    );
  }

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Users className="w-6 h-6 text-primary-400" />
          <h2 className="text-xl font-heading font-bold text-gray-900 dark:text-white">User Management</h2>
          <span className="text-sm text-gray-500 font-body">({users.length} users)</span>
        </div>
        <button
          onClick={() => setShowCreateForm(!showCreateForm)}
          className="flex items-center gap-2 px-4 py-2 bg-primary-500 hover:bg-primary-600 text-white rounded-xl font-body text-sm font-medium transition-all"
        >
          <Plus className="w-4 h-4" />
          Create User
        </button>
      </div>

      {!isSuperAdmin && (
        <div className="flex items-center gap-2 p-3 bg-amber-500/10 border border-amber-500/20 rounded-xl text-amber-400 text-sm font-body">
          <Shield className="w-4 h-4 shrink-0" />
          You can manage regular users. Only the Super Admin can create admins or change feature permissions.
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2 p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm font-body">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {error}
          <button onClick={() => setError('')} className="ml-auto"><X className="w-4 h-4" /></button>
        </div>
      )}
      {success && (
        <div className="flex items-center gap-2 p-3 bg-green-500/10 border border-green-500/20 rounded-xl text-green-400 text-sm font-body">
          <CheckCircle className="w-4 h-4 shrink-0" />
          {success}
        </div>
      )}

      {showCreateForm && (
        <div className="bg-white dark:bg-gray-800/60 border border-gray-200 dark:border-gray-700/60 rounded-2xl p-6 space-y-4">
          <h3 className="text-lg font-heading font-semibold text-gray-900 dark:text-white">Create New User</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-body text-gray-700 dark:text-gray-400 mb-1">Username</label>
              <input
                type="text"
                value={createUsername}
                onChange={(e) => setCreateUsername(e.target.value)}
                className="w-full px-3 py-2 bg-gray-50 dark:bg-gray-900/60 border border-gray-200 dark:border-gray-700/60 rounded-xl text-gray-900 dark:text-white font-body text-sm focus:outline-none focus:border-primary-500/50"
                placeholder="Enter username"
              />
            </div>
            <div>
              <label className="block text-sm font-body text-gray-700 dark:text-gray-400 mb-1">Password</label>
              <div className="relative">
                <input
                  type={showCreatePassword ? 'text' : 'password'}
                  value={createPassword}
                  onChange={(e) => setCreatePassword(e.target.value)}
                  className="w-full px-3 py-2 pr-10 bg-gray-50 dark:bg-gray-900/60 border border-gray-200 dark:border-gray-700/60 rounded-xl text-gray-900 dark:text-white font-body text-sm focus:outline-none focus:border-primary-500/50"
                  placeholder="Enter password"
                />
                <button
                  type="button"
                  onClick={() => setShowCreatePassword(!showCreatePassword)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
                >
                  {showCreatePassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>
          </div>
          <div>
            <label className="block text-sm font-body text-gray-700 dark:text-gray-400 mb-1">Role</label>
            <select
              value={createRole}
              onChange={(e) => {
                const v = e.target.value;
                setCreateRole(v);
                if (v === 'admin' && isSuperAdmin) {
                  setCreatePermissions(ALL_MENU_OPTIONS.map(m => m.id));
                }
              }}
              className="px-3 py-2 bg-gray-50 dark:bg-gray-900/60 border border-gray-200 dark:border-gray-700/60 rounded-xl text-gray-900 dark:text-white font-body text-sm focus:outline-none focus:border-primary-500/50"
            >
              <option value="user">User</option>
              {isSuperAdmin && <option value="admin">Admin</option>}
            </select>
            {!isSuperAdmin && (
              <p className="text-xs text-gray-500 mt-1 font-body">Only the Super Admin can create admin accounts.</p>
            )}
          </div>
          {isSuperAdmin && catalogSorted.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-sm font-body text-gray-700 dark:text-gray-400 flex items-center gap-2">
                  <Bot className="w-4 h-4 text-primary-400" />
                  Agent access
                </label>
                <div className="flex gap-2">
                  <button type="button" onClick={() => selectAllAgentIds(setCreateAgentIds)} className="text-xs text-primary-400 hover:text-primary-300 font-body">Select All</button>
                  <button type="button" onClick={() => clearAllAgentIds(setCreateAgentIds)} className="text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 font-body">Clear All</button>
                </div>
              </div>
              <p className="text-xs text-gray-500 font-body mb-2">Choose which marketplace agents this account may use (applies to User and Admin roles).</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 max-h-56 overflow-y-auto pr-1">
                {catalogSorted.map((agent) => (
                  <label
                    key={agent.id}
                    className={`flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer transition-all text-sm font-body ${
                      createAgentIds.includes(agent.id)
                        ? 'bg-primary-500/10 border border-primary-500/30 text-primary-300'
                        : 'bg-gray-50 dark:bg-gray-900/40 border border-gray-200 dark:border-gray-700/40 text-gray-700 dark:text-gray-400 hover:border-gray-300 dark:hover:border-gray-600'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={createAgentIds.includes(agent.id)}
                      onChange={() => toggleAgentId(createAgentIds, setCreateAgentIds, agent.id)}
                      className="sr-only"
                    />
                    <div className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 ${
                      createAgentIds.includes(agent.id) ? 'bg-primary-500 border-primary-500' : 'border-gray-300 dark:border-gray-600'
                    }`}>
                      {createAgentIds.includes(agent.id) && <CheckCircle className="w-3 h-3 text-white" />}
                    </div>
                    <span className="truncate">{agent.name}</span>
                  </label>
                ))}
              </div>
            </div>
          )}
          {(createRole === 'user' || (createRole === 'admin' && isSuperAdmin)) && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-sm font-body text-gray-700 dark:text-gray-400">Menu Permissions</label>
                <div className="flex gap-2">
                  <button onClick={() => selectAllPermissions(setCreatePermissions)} className="text-xs text-primary-400 hover:text-primary-300 font-body">Select All</button>
                  <button onClick={() => clearAllPermissions(setCreatePermissions)} className="text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 font-body">Clear All</button>
                </div>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                {ALL_MENU_OPTIONS.map(menu => (
                  <label
                    key={menu.id}
                    className={`flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer transition-all text-sm font-body ${
                      createPermissions.includes(menu.id)
                        ? 'bg-primary-500/10 border border-primary-500/30 text-primary-300'
                        : 'bg-gray-50 dark:bg-gray-900/40 border border-gray-200 dark:border-gray-700/40 text-gray-700 dark:text-gray-400 hover:border-gray-300 dark:hover:border-gray-600'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={createPermissions.includes(menu.id)}
                      onChange={() => togglePermission(createPermissions, setCreatePermissions, menu.id)}
                      className="sr-only"
                    />
                    <div className={`w-4 h-4 rounded border flex items-center justify-center ${
                      createPermissions.includes(menu.id) ? 'bg-primary-500 border-primary-500' : 'border-gray-300 dark:border-gray-600'
                    }`}>
                      {createPermissions.includes(menu.id) && <CheckCircle className="w-3 h-3 text-white" />}
                    </div>
                    {menu.label}
                  </label>
                ))}
              </div>
            </div>
          )}
          <div className="flex gap-3 pt-2">
            <button
              onClick={handleCreate}
              disabled={saving}
              className="flex items-center gap-2 px-4 py-2 bg-primary-500 hover:bg-primary-600 disabled:opacity-50 text-white rounded-xl font-body text-sm font-medium transition-all"
            >
              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
              Create User
            </button>
            <button
              onClick={() => { setShowCreateForm(false); setError(''); }}
              className="px-4 py-2 bg-gray-200 dark:bg-gray-700/60 hover:bg-gray-300 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-xl font-body text-sm font-medium transition-all"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="space-y-3">
        {users.map(user => {
          const isSuperAdminAccount = user.role === 'super_admin';
          const roleDisplay = getRoleDisplay(user.role);
          const canEdit = !isSuperAdminAccount || isSuperAdmin;
          const canDelete = !isSuperAdminAccount;

          return (
            <div key={user.id} className="bg-white dark:bg-gray-800/60 border border-gray-200 dark:border-gray-700/60 rounded-2xl p-5 space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${roleDisplay.bg} border ${roleDisplay.border}`}>
                    {isSuperAdminAccount
                      ? <Crown className={`w-5 h-5 ${roleDisplay.text}`} />
                      : user.role === 'admin'
                        ? <Shield className={`w-5 h-5 ${roleDisplay.text}`} />
                        : <User className={`w-5 h-5 ${roleDisplay.text}`} />
                    }
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-gray-900 dark:text-white font-heading font-semibold">{user.username}</span>
                      <span className={`text-xs px-2 py-0.5 rounded-full font-body ${roleDisplay.bg} ${roleDisplay.text} border ${roleDisplay.border}`}>
                        {roleDisplay.label}
                      </span>
                      {!user.is_active && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-red-500/10 text-red-400 border border-red-500/20 font-body">
                          Inactive
                        </span>
                      )}
                    </div>
                    <span className="text-xs text-gray-500 font-body">
                      Created {new Date(user.created_at).toLocaleDateString()}
                    </span>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {editingUser !== user.id && (
                    <>
                      {canEdit && (
                        <button
                          onClick={() => handleStartEdit(user)}
                          className="p-2 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-700/60 rounded-lg transition-all"
                          title="Edit user"
                        >
                          <Edit2 className="w-4 h-4" />
                        </button>
                      )}
                      <button
                        onClick={() => { setResetPasswordId(user.id); setNewPassword(''); }}
                        className="p-2 text-gray-600 dark:text-gray-400 hover:text-amber-400 hover:bg-amber-500/10 rounded-lg transition-all"
                        title="Reset password"
                      >
                        <Key className="w-4 h-4" />
                      </button>
                      {canDelete && (
                        <button
                          onClick={() => setDeleteConfirm(user.id)}
                          className="p-2 text-gray-600 dark:text-gray-400 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-all"
                          title="Delete user"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      )}
                    </>
                  )}
                </div>
              </div>

              {editingUser === user.id && (
                <div className="border-t border-gray-200 dark:border-gray-700/60 pt-4 space-y-3">
                  <div className="flex items-center gap-4">
                    {isSuperAdmin && !isSuperAdminAccount && (
                      <div>
                        <label className="text-sm font-body text-gray-700 dark:text-gray-400 mb-1 block">Role</label>
                        <select
                          value={editRole}
                          onChange={(e) => setEditRole(e.target.value)}
                          className="px-3 py-2 bg-gray-50 dark:bg-gray-900/60 border border-gray-200 dark:border-gray-700/60 rounded-xl text-gray-900 dark:text-white font-body text-sm"
                        >
                          <option value="user">User</option>
                          <option value="admin">Admin</option>
                        </select>
                      </div>
                    )}
                    {!isSuperAdminAccount && (
                      <div>
                        <label className="text-sm font-body text-gray-700 dark:text-gray-400 mb-1 block">Status</label>
                        <select
                          value={editActive ? 'active' : 'inactive'}
                          onChange={(e) => setEditActive(e.target.value === 'active')}
                          className="px-3 py-2 bg-gray-50 dark:bg-gray-900/60 border border-gray-200 dark:border-gray-700/60 rounded-xl text-gray-900 dark:text-white font-body text-sm"
                        >
                          <option value="active">Active</option>
                          <option value="inactive">Inactive</option>
                        </select>
                      </div>
                    )}
                  </div>
                  {isSuperAdmin && !isSuperAdminAccount && catalogSorted.length > 0 && (
                    <div>
                      <div className="flex items-center justify-between mb-2">
                        <label className="text-sm font-body text-gray-700 dark:text-gray-400 flex items-center gap-2">
                          <Bot className="w-4 h-4 text-primary-400" />
                          Agent access
                        </label>
                        <div className="flex gap-2">
                          <button type="button" onClick={() => selectAllAgentIds(setEditAgentIds)} className="text-xs text-primary-400 hover:text-primary-300 font-body">Select All</button>
                          <button type="button" onClick={() => clearAllAgentIds(setEditAgentIds)} className="text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 font-body">Clear All</button>
                        </div>
                      </div>
                      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 max-h-56 overflow-y-auto pr-1">
                        {catalogSorted.map((agent) => (
                          <label
                            key={agent.id}
                            className={`flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer transition-all text-sm font-body ${
                              editAgentIds.includes(agent.id)
                                ? 'bg-primary-500/10 border border-primary-500/30 text-primary-300'
                                : 'bg-gray-50 dark:bg-gray-900/40 border border-gray-200 dark:border-gray-700/40 text-gray-700 dark:text-gray-400 hover:border-gray-300 dark:hover:border-gray-600'
                            }`}
                          >
                            <input
                              type="checkbox"
                              checked={editAgentIds.includes(agent.id)}
                              onChange={() => toggleAgentId(editAgentIds, setEditAgentIds, agent.id)}
                              className="sr-only"
                            />
                            <div className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 ${
                              editAgentIds.includes(agent.id) ? 'bg-primary-500 border-primary-500' : 'border-gray-300 dark:border-gray-600'
                            }`}>
                              {editAgentIds.includes(agent.id) && <CheckCircle className="w-3 h-3 text-white" />}
                            </div>
                            <span className="truncate">{agent.name}</span>
                          </label>
                        ))}
                      </div>
                    </div>
                  )}
                  {isSuperAdmin && !isSuperAdminAccount && (editRole === 'user' || editRole === 'admin') && (
                    <div>
                      <div className="flex items-center justify-between mb-2">
                        <label className="text-sm font-body text-gray-700 dark:text-gray-400">Menu Permissions</label>
                        <div className="flex gap-2">
                          <button onClick={() => selectAllPermissions(setEditPermissions)} className="text-xs text-primary-400 hover:text-primary-300 font-body">Select All</button>
                          <button onClick={() => clearAllPermissions(setEditPermissions)} className="text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 font-body">Clear All</button>
                        </div>
                      </div>
                      <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                        {ALL_MENU_OPTIONS.map(menu => (
                          <label
                            key={menu.id}
                            className={`flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer transition-all text-sm font-body ${
                              editPermissions.includes(menu.id)
                                ? 'bg-primary-500/10 border border-primary-500/30 text-primary-300'
                                : 'bg-gray-50 dark:bg-gray-900/40 border border-gray-200 dark:border-gray-700/40 text-gray-700 dark:text-gray-400 hover:border-gray-300 dark:hover:border-gray-600'
                            }`}
                          >
                            <input
                              type="checkbox"
                              checked={editPermissions.includes(menu.id)}
                              onChange={() => togglePermission(editPermissions, setEditPermissions, menu.id)}
                              className="sr-only"
                            />
                            <div className={`w-4 h-4 rounded border flex items-center justify-center ${
                              editPermissions.includes(menu.id) ? 'bg-primary-500 border-primary-500' : 'border-gray-300 dark:border-gray-600'
                            }`}>
                              {editPermissions.includes(menu.id) && <CheckCircle className="w-3 h-3 text-white" />}
                            </div>
                            {menu.label}
                          </label>
                        ))}
                      </div>
                    </div>
                  )}
                  {isSuperAdminAccount && (
                    <p className="text-sm text-purple-400/70 font-body italic">
                      Super admin role and permissions are permanent and cannot be changed.
                    </p>
                  )}
                  {!isSuperAdmin && !isSuperAdminAccount && editRole === 'admin' && (
                    <p className="text-sm text-amber-400/70 font-body italic">
                      Admin accounts use core admin features; only a Super Admin can adjust permissions such as agent architecture diagrams.
                    </p>
                  )}
                  <div className="flex gap-3">
                    <button
                      onClick={() => handleSaveEdit(user.id)}
                      disabled={saving}
                      className="flex items-center gap-2 px-4 py-2 bg-primary-500 hover:bg-primary-600 disabled:opacity-50 text-white rounded-xl font-body text-sm font-medium transition-all"
                    >
                      {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                      Save Changes
                    </button>
                    <button
                      onClick={() => setEditingUser(null)}
                      className="px-4 py-2 bg-gray-200 dark:bg-gray-700/60 hover:bg-gray-300 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-xl font-body text-sm font-medium transition-all"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              {resetPasswordId === user.id && (
                <div className="border-t border-gray-200 dark:border-gray-700/60 pt-4">
                  <div className="flex items-center gap-3">
                    <div className="relative flex-1 max-w-xs">
                      <input
                        type={showNewPassword ? 'text' : 'password'}
                        value={newPassword}
                        onChange={(e) => setNewPassword(e.target.value)}
                        className="w-full px-3 py-2 pr-10 bg-gray-50 dark:bg-gray-900/60 border border-gray-200 dark:border-gray-700/60 rounded-xl text-gray-900 dark:text-white font-body text-sm focus:outline-none focus:border-primary-500/50"
                        placeholder="New password"
                      />
                      <button
                        type="button"
                        onClick={() => setShowNewPassword(!showNewPassword)}
                        className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
                      >
                        {showNewPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                      </button>
                    </div>
                    <button
                      onClick={() => handleResetPassword(user.id)}
                      disabled={saving}
                      className="flex items-center gap-2 px-4 py-2 bg-amber-500/20 hover:bg-amber-500/30 text-amber-400 rounded-xl font-body text-sm font-medium transition-all"
                    >
                      {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Key className="w-4 h-4" />}
                      Reset
                    </button>
                    <button
                      onClick={() => setResetPasswordId(null)}
                      className="px-4 py-2 bg-gray-200 dark:bg-gray-700/60 hover:bg-gray-300 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-xl font-body text-sm font-medium transition-all"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              {deleteConfirm === user.id && (
                <div className="border-t border-gray-200 dark:border-gray-700/60 pt-4">
                  <div className="flex items-center gap-3">
                    <span className="text-sm text-red-400 font-body">Are you sure you want to delete this user?</span>
                    <button
                      onClick={() => handleDelete(user.id)}
                      disabled={saving}
                      className="flex items-center gap-2 px-4 py-2 bg-red-500/20 hover:bg-red-500/30 text-red-400 rounded-xl font-body text-sm font-medium transition-all"
                    >
                      {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
                      Confirm Delete
                    </button>
                    <button
                      onClick={() => setDeleteConfirm(null)}
                      className="px-4 py-2 bg-gray-200 dark:bg-gray-700/60 hover:bg-gray-300 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-xl font-body text-sm font-medium transition-all"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              {editingUser !== user.id && (
                <div className="space-y-2">
                  <div className="flex flex-wrap gap-1.5">
                    {isSuperAdminAccount ? (
                      <span className="text-xs px-2.5 py-1 rounded-full bg-purple-500/10 text-purple-400/80 border border-purple-500/10 font-body">
                        Full Access — Permanent
                      </span>
                    ) : user.role === 'admin' ? (
                      <span className="text-xs px-2.5 py-1 rounded-full bg-amber-500/10 text-amber-400/80 border border-amber-500/10 font-body">
                        Full menu (Admin)
                      </span>
                    ) : user.menu_permissions.length > 0 ? (
                      user.menu_permissions.map(perm => (
                        <span
                          key={perm}
                          className="text-xs px-2.5 py-1 rounded-full bg-gray-100 dark:bg-gray-700/40 text-gray-700 dark:text-gray-400 border border-gray-200 dark:border-gray-700/30 font-body"
                        >
                          {ALL_MENU_OPTIONS.find(m => m.id === perm)?.label || perm}
                        </span>
                      ))
                    ) : (
                      <span className="text-xs text-gray-400 dark:text-gray-600 font-body italic">No menu permissions assigned</span>
                    )}
                  </div>
                  {!isSuperAdminAccount && (
                    <div className="flex flex-wrap items-center gap-1.5 text-xs font-body text-gray-500">
                      <Bot className="w-3.5 h-3.5 text-gray-400 dark:text-gray-600 shrink-0" />
                      <span className="text-gray-400 dark:text-gray-600">Agents:</span>
                      {user.agent_permissions === null || user.agent_permissions === undefined ? (
                        <span className="text-gray-600 dark:text-gray-400">All agents</span>
                      ) : user.agent_permissions.length === 0 ? (
                        <span className="text-amber-400/80 italic">None assigned</span>
                      ) : (
                        user.agent_permissions.slice(0, 6).map((aid) => (
                          <span
                            key={aid}
                            className="px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-700/40 text-gray-700 dark:text-gray-400 border border-gray-200 dark:border-gray-700/30"
                          >
                            {catalogSorted.find((a) => a.id === aid)?.name || aid}
                          </span>
                        ))
                      )}
                      {user.agent_permissions && user.agent_permissions.length > 6 ? (
                        <span className="text-gray-400 dark:text-gray-600">+{user.agent_permissions.length - 6} more</span>
                      ) : null}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
