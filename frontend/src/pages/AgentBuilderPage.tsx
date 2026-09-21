import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft, Save, Loader2, Bot, Sparkles, Wrench,
  Settings, Play, Rocket, CheckCircle, ChevronRight,
  AlertCircle, Plus, Search, Copy, Trash2, AlertTriangle,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import {
  createAgent, getMyAgent, updateAgent, listMyAgents, deleteAgent, cloneAgent,
  listTools,
  VersionConflictError,
  type CustomAgent, type ToolDefinition,
} from '../services/agentBuilder';
import IdentityStep from '../components/agent-builder/IdentityStep';
import PromptEditor from '../components/agent-builder/PromptEditor';
import ToolSelector from '../components/agent-builder/ToolSelector';
import ConfigStep from '../components/agent-builder/ConfigStep';
import TestPlayground from '../components/agent-builder/TestPlayground';
import DeployStep from '../components/agent-builder/DeployStep';
import ConfirmDialog from '../components/agent-builder/ConfirmDialog';
import {
  validateIdentity, validatePrompt, validateTools, validateConfig,
  validateTest, validateDeploy, isAgentDirty,
  type StepValidation,
} from '../components/agent-builder/stepValidation';

const STEPS = [
  { id: 'identity', label: 'Identity', icon: Bot },
  { id: 'prompt', label: 'System Prompt', icon: Sparkles },
  { id: 'tools', label: 'Tools', icon: Wrench },
  { id: 'config', label: 'Configuration', icon: Settings },
  { id: 'test', label: 'Test', icon: Play },
  { id: 'deploy', label: 'Deploy & Publish', icon: Rocket },
] as const;

type StepId = (typeof STEPS)[number]['id'];

const DEFAULT_AGENT: Partial<CustomAgent> = {
  name: '',
  description: '',
  category_id: 'general',
  logo_url: '',
  system_prompt: '',
  llm_provider: 'pwc_genai',
  llm_model: '',
  temperature: 0.7,
  max_tokens: 4096,
  tools_config: [],
  capabilities: [],
  example_prompts: [''],
  required_env_keys: [],
  default_config: {},
  visibility: 'private',
};

const AUTOSAVE_DEBOUNCE_MS = 1500;
const PAGE_SIZE = 24;

type SaveState = 'idle' | 'dirty' | 'saving' | 'saved' | 'error' | 'conflict';

export default function AgentBuilderPage() {
  const { id } = useParams<{ id?: string }>();
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();

  const [activeStep, setActiveStep] = useState<StepId>('identity');
  const [agent, setAgent] = useState<Partial<CustomAgent>>(DEFAULT_AGENT);
  const [savedAgent, setSavedAgent] = useState<Partial<CustomAgent>>(DEFAULT_AGENT);
  const [agentId, setAgentId] = useState<string | null>(id || null);
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const [saveError, setSaveError] = useState('');
  const [conflictAt, setConflictAt] = useState<string | null>(null);
  const [myAgents, setMyAgents] = useState<CustomAgent[]>([]);
  const [agentTotal, setAgentTotal] = useState(0);
  const [agentSearch, setAgentSearch] = useState('');
  const [agentPage, setAgentPage] = useState(0);
  const [showList, setShowList] = useState(!id);
  const [loading, setLoading] = useState(!!id);
  const [tools, setTools] = useState<ToolDefinition[]>([]);
  const [unconfiguredTools, setUnconfiguredTools] = useState<string[]>([]);
  const [confirmDelete, setConfirmDelete] = useState<{ id: string; name: string } | null>(null);

  // Refs to avoid stale closures inside autosave
  const agentRef = useRef(agent);
  const savedRef = useRef(savedAgent);
  const idRef = useRef(agentId);
  useEffect(() => { agentRef.current = agent; }, [agent]);
  useEffect(() => { savedRef.current = savedAgent; }, [savedAgent]);
  useEffect(() => { idRef.current = agentId; }, [agentId]);

  // Tool catalogue for validation
  useEffect(() => {
    listTools()
      .then(({ tools: t }) => setTools(t))
      .catch(() => {});
  }, []);

  const toolMetaById = useMemo(() => {
    const m = new Map<string, ToolDefinition>();
    tools.forEach((t) => m.set(t.id, t));
    return m;
  }, [tools]);

  // Load existing agent
  useEffect(() => {
    if (!id) return;
    setLoading(true);
    getMyAgent(id)
      .then(({ agent: a }) => {
        setAgent(a);
        setSavedAgent(a);
        setAgentId(a.id);
        setShowList(false);
        setSaveState('idle');
      })
      .catch((e) => setSaveError(e.message))
      .finally(() => setLoading(false));
  }, [id]);

  // Load list (debounced search)
  const loadMyAgents = useCallback((opts?: { search?: string; offset?: number }) => {
    const search = opts?.search ?? agentSearch;
    const offset = opts?.offset ?? agentPage * PAGE_SIZE;
    listMyAgents({ search: search || undefined, limit: PAGE_SIZE, offset })
      .then(({ agents, total }) => {
        setMyAgents(agents);
        setAgentTotal(total || 0);
      })
      .catch(() => {});
  }, [agentSearch, agentPage]);

  useEffect(() => {
    if (!isAuthenticated) return;
    const t = setTimeout(() => loadMyAgents(), 200);
    return () => clearTimeout(t);
  }, [isAuthenticated, loadMyAgents]);

  // Autosave + dirty detection
  const dirty = useMemo(() => isAgentDirty(agent, savedAgent), [agent, savedAgent]);

  useEffect(() => {
    if (saveState === 'saving' || saveState === 'conflict') return;
    if (dirty) {
      setSaveState('dirty');
    } else if (saveState === 'dirty') {
      setSaveState('idle');
    }
  }, [dirty, saveState]);

  // beforeunload guard
  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [dirty]);

  const performSave = useCallback(async (opts?: { force?: boolean }): Promise<CustomAgent | null> => {
    const current = agentRef.current;
    const currentId = idRef.current;
    if (!current.name || !current.name.trim()) return null;
    setSaveState('saving');
    setSaveError('');
    try {
      if (currentId) {
        const ifMatch = opts?.force ? undefined : (savedRef.current as CustomAgent).updated_at;
        const { agent: updated } = await updateAgent(currentId, current, ifMatch);
        setSavedAgent(updated);
        setAgent((prev) => ({ ...updated, ...nonServerFields(prev, updated) }));
        setSaveState('saved');
        setConflictAt(null);
        setTimeout(() => setSaveState((s) => (s === 'saved' ? 'idle' : s)), 1800);
        return updated;
      }
      const { agent: created } = await createAgent(current);
      setSavedAgent(created);
      setAgent(created);
      setAgentId(created.id);
      navigate(`/create-agent/${created.id}`, { replace: true });
      setSaveState('saved');
      setTimeout(() => setSaveState((s) => (s === 'saved' ? 'idle' : s)), 1800);
      loadMyAgents();
      return created;
    } catch (e) {
      if (e instanceof VersionConflictError) {
        setSaveState('conflict');
        setConflictAt(e.current_updated_at);
        setSaveError(e.message);
      } else {
        setSaveState('error');
        setSaveError((e as Error).message || 'Save failed');
      }
      return null;
    }
  }, [navigate, loadMyAgents]);

  // Debounced autosave: only when there's already an id (creates need explicit save)
  useEffect(() => {
    if (saveState !== 'dirty') return;
    if (!agentId) return;
    const t = setTimeout(() => {
      void performSave();
    }, AUTOSAVE_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [saveState, agentId, performSave]);

  // Reload (after a conflict): drop local changes and refetch
  const handleReload = useCallback(async () => {
    if (!agentId) return;
    setLoading(true);
    try {
      const { agent: a } = await getMyAgent(agentId);
      setAgent(a);
      setSavedAgent(a);
      setSaveState('idle');
      setConflictAt(null);
      setSaveError('');
    } catch (e) {
      setSaveError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  const handleForceSave = useCallback(async () => {
    await performSave({ force: true });
  }, [performSave]);

  const handleManualSave = useCallback(async (): Promise<void> => {
    await performSave();
  }, [performSave]);

  // Cmd/Ctrl+S
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') {
        e.preventDefault();
        if (dirty) handleManualSave();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [dirty, handleManualSave]);

  const handleDelete = async (delId: string) => {
    try {
      await deleteAgent(delId);
      if (delId === agentId) {
        setAgent(DEFAULT_AGENT);
        setSavedAgent(DEFAULT_AGENT);
        setAgentId(null);
        setShowList(true);
        navigate('/create-agent', { replace: true });
      }
      loadMyAgents();
    } catch (e) {
      setSaveError((e as Error).message);
    } finally {
      setConfirmDelete(null);
    }
  };

  const handleClone = async (sourceId: string) => {
    try {
      const { agent: cloned } = await cloneAgent(sourceId);
      navigate(`/create-agent/${cloned.id}`);
      setAgent(cloned);
      setSavedAgent(cloned);
      setAgentId(cloned.id);
      setShowList(false);
      setActiveStep('identity');
      loadMyAgents();
    } catch (e) {
      setSaveError((e as Error).message);
    }
  };

  const updateField = useCallback(
    <K extends keyof CustomAgent>(key: K, value: CustomAgent[K]) => {
      setAgent((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  // Step validation
  const stepValidation: Record<StepId, StepValidation> = useMemo(() => ({
    identity: validateIdentity(agent),
    prompt: validatePrompt(agent),
    tools: validateTools(agent, toolMetaById),
    config: validateConfig(agent),
    test: validateTest(agent, agentId),
    deploy: validateDeploy(agent),
  }), [agent, toolMetaById, agentId]);

  // Filter agents client-side too (we already query server-side, but a fast filter helps)
  const totalPages = Math.max(1, Math.ceil(agentTotal / PAGE_SIZE));

  if (!isAuthenticated) {
    return (
      <div className="min-h-[calc(100vh-4.25rem)] flex items-center justify-center bg-white dark:bg-zinc-950">
        <div className="text-center space-y-4 max-w-md px-6">
          <div className="w-16 h-16 mx-auto rounded-2xl bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center">
            <Bot className="w-8 h-8 text-white" />
          </div>
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">Sign in to Create Agents</h2>
          <p className="text-gray-600 dark:text-gray-400">You need to be authenticated to create and deploy custom agents.</p>
          <button
            onClick={() => navigate('/admin/login')}
            className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-violet-600 hover:bg-violet-700 text-white font-semibold transition-colors"
          >
            Sign In <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="min-h-[calc(100vh-4.25rem)] flex items-center justify-center bg-white dark:bg-zinc-950">
        <Loader2 className="w-8 h-8 text-violet-500 dark:text-violet-400 animate-spin" />
      </div>
    );
  }

  // ── My Agents list ──────────────────────────────────────────────────────────
  if (showList && !agentId) {
    return (
      <>
        <div className="min-h-[calc(100vh-4.25rem)] bg-white dark:bg-zinc-950 text-gray-900 dark:text-white">
          <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
            <div className="flex items-center justify-between mb-6 gap-4 flex-wrap">
              <div>
                <h1 className="text-3xl font-bold tracking-tight">My Agents</h1>
                <p className="text-gray-600 dark:text-gray-400 mt-1">Create, manage, and deploy your custom AI agents</p>
              </div>
              <button
                onClick={() => {
                  setAgent(DEFAULT_AGENT);
                  setSavedAgent(DEFAULT_AGENT);
                  setAgentId(null);
                  setShowList(false);
                  setActiveStep('identity');
                }}
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-violet-600 hover:bg-violet-700 text-white font-semibold transition-colors"
              >
                <Plus className="w-4 h-4" /> New Agent
              </button>
            </div>

            <div className="relative mb-6">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
              <input
                type="search"
                value={agentSearch}
                onChange={(e) => { setAgentSearch(e.target.value); setAgentPage(0); }}
                placeholder="Search by name or description…"
                className="w-full pl-10 pr-4 py-2.5 rounded-xl bg-gray-100 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-violet-500/40 text-sm transition-colors"
              />
            </div>

            {myAgents.length === 0 ? (
              <div className="text-center py-24 space-y-4">
                <div className="w-20 h-20 mx-auto rounded-2xl bg-gray-100 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.06] flex items-center justify-center">
                  <Bot className="w-10 h-10 text-gray-400 dark:text-gray-600" />
                </div>
                <p className="text-gray-500 text-lg">
                  {agentSearch ? `No agents match “${agentSearch}”` : 'No agents yet. Create your first one!'}
                </p>
              </div>
            ) : (
              <>
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {myAgents.map((a) => (
                    <div
                      key={a.id}
                      className="group relative rounded-2xl border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-white/[0.02] p-5 hover:border-violet-500/30 hover:bg-gray-100 dark:hover:bg-white/[0.04] transition-all cursor-pointer"
                      onClick={() => {
                        navigate(`/create-agent/${a.id}`);
                        setAgent(a);
                        setSavedAgent(a);
                        setAgentId(a.id);
                        setShowList(false);
                        setActiveStep('identity');
                      }}
                    >
                      <div className="flex items-start justify-between mb-3">
                        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-500/20 to-indigo-500/20 border border-violet-500/20 flex items-center justify-center text-lg">
                          {a.logo_url ? (
                            <img src={a.logo_url} alt="" className="w-6 h-6 rounded" />
                          ) : (
                            <Bot className="w-5 h-5 text-violet-400" />
                          )}
                        </div>
                        <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${
                          a.status === 'published' ? 'bg-green-500/10 text-green-400 ring-1 ring-green-500/20' :
                          a.status === 'deployed' ? 'bg-blue-500/10 text-blue-400 ring-1 ring-blue-500/20' :
                          a.status === 'testing' ? 'bg-amber-500/10 text-amber-400 ring-1 ring-amber-500/20' :
                          'bg-gray-500/10 text-gray-400 ring-1 ring-gray-500/20'
                        }`}>
                          {a.status}
                        </span>
                      </div>
                      <h3 className="font-semibold text-gray-900 dark:text-white truncate">{a.name || 'Untitled Agent'}</h3>
                      <p className="text-sm text-gray-500 mt-1 line-clamp-2">{a.description || 'No description'}</p>
                      <div className="mt-3 flex items-center gap-3 text-xs text-gray-500 dark:text-gray-600">
                        <span>{a.category_id}</span>
                        <span>v{a.version}</span>
                      </div>
                      <div className="absolute top-3 right-3 opacity-0 group-hover:opacity-100 flex gap-1 transition-all">
                        <button
                          onClick={(e) => { e.stopPropagation(); handleClone(a.id); }}
                          className="p-1.5 rounded-lg hover:bg-violet-500/10 text-violet-400 transition-colors"
                          title="Clone"
                        >
                          <Copy className="w-4 h-4" />
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); setConfirmDelete({ id: a.id, name: a.name || 'this agent' }); }}
                          className="p-1.5 rounded-lg hover:bg-red-500/10 text-red-400 transition-colors"
                          title="Delete"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>

                {totalPages > 1 && (
                  <div className="flex items-center justify-between mt-8 text-sm">
                    <span className="text-gray-500">
                      Showing {agentPage * PAGE_SIZE + 1}–{Math.min((agentPage + 1) * PAGE_SIZE, agentTotal)} of {agentTotal}
                    </span>
                    <div className="flex gap-2">
                      <button
                        onClick={() => setAgentPage((p) => Math.max(0, p - 1))}
                        disabled={agentPage === 0}
                        className="px-3 py-1.5 rounded-lg border border-gray-200 dark:border-white/[0.08] text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white disabled:opacity-30 disabled:cursor-not-allowed"
                      >
                        Previous
                      </button>
                      <span className="px-3 py-1.5 text-gray-500">
                        Page {agentPage + 1} / {totalPages}
                      </span>
                      <button
                        onClick={() => setAgentPage((p) => Math.min(totalPages - 1, p + 1))}
                        disabled={agentPage >= totalPages - 1}
                        className="px-3 py-1.5 rounded-lg border border-gray-200 dark:border-white/[0.08] text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white disabled:opacity-30 disabled:cursor-not-allowed"
                      >
                        Next
                      </button>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>

        <ConfirmDialog
          open={!!confirmDelete}
          title="Delete agent permanently?"
          message={`This will permanently remove “${confirmDelete?.name || ''}” and all its versions, submissions, and usage history. This cannot be undone.`}
          confirmLabel="Delete"
          destructive
          onConfirm={() => confirmDelete && handleDelete(confirmDelete.id)}
          onCancel={() => setConfirmDelete(null)}
        />
      </>
    );
  }

  const stepIdx = STEPS.findIndex((s) => s.id === activeStep);

  return (
    <>
      <div className="min-h-[calc(100vh-4.25rem)] bg-white dark:bg-zinc-950 text-gray-900 dark:text-white">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          {/* Top bar */}
          <div className="flex items-center justify-between mb-6 gap-3">
            <div className="flex items-center gap-3 min-w-0">
              <button
                onClick={() => {
                  if (dirty) {
                    if (!window.confirm('You have unsaved changes. Leave anyway?')) return;
                  }
                  setShowList(true);
                  navigate('/create-agent', { replace: true });
                }}
                className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-white/[0.06] transition-colors flex-shrink-0"
              >
                <ArrowLeft className="w-5 h-5 text-gray-600 dark:text-gray-400" />
              </button>
              <h1 className="text-xl font-bold truncate max-w-xs sm:max-w-md">
                {agent.name || 'New Agent'}
              </h1>
              {agent.status && agent.status !== 'draft' && (
                <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium flex-shrink-0 ${
                  agent.status === 'published' ? 'bg-green-500/10 text-green-400' :
                  agent.status === 'deployed' ? 'bg-blue-500/10 text-blue-400' :
                  'bg-amber-500/10 text-amber-400'
                }`}>
                  {agent.status}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              <SaveIndicator state={saveState} />
              <button
                onClick={handleManualSave}
                disabled={saveState === 'saving' || !agent.name}
                className="inline-flex items-center gap-2 px-5 py-2 rounded-xl bg-violet-600 hover:bg-violet-700 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold transition-colors text-sm"
              >
                {saveState === 'saving' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                Save
              </button>
            </div>
          </div>

          {/* Conflict / error banner */}
          {saveState === 'conflict' && (
            <div className="mb-4 rounded-xl bg-amber-500/8 border border-amber-500/20 p-4 flex items-start gap-3">
              <AlertTriangle className="w-5 h-5 text-amber-500 dark:text-amber-400 flex-shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-amber-700 dark:text-amber-300">This agent was modified elsewhere</p>
                <p className="text-xs text-amber-700/80 dark:text-amber-300/70 mt-0.5">
                  Another tab or user updated this agent {conflictAt ? `at ${new Date(conflictAt).toLocaleTimeString()}` : ''}.
                  Reload to merge, or save anyway to overwrite.
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={handleReload}
                  className="px-3 py-1.5 rounded-lg bg-gray-100 dark:bg-white/[0.06] hover:bg-gray-200 dark:hover:bg-white/[0.1] text-gray-900 dark:text-white text-xs font-medium"
                >
                  Reload
                </button>
                <button
                  onClick={handleForceSave}
                  className="px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-700 text-white text-xs font-medium"
                >
                  Save anyway
                </button>
              </div>
            </div>
          )}

          {saveState === 'error' && saveError && (
            <div className="mb-4 rounded-xl bg-red-500/8 border border-red-500/20 px-4 py-3 flex items-center gap-2 text-sm">
              <AlertCircle className="w-4 h-4 text-red-500 dark:text-red-400 flex-shrink-0" />
              <span className="text-red-700 dark:text-red-300 flex-1">{saveError}</span>
              <button
                onClick={() => { setSaveState('idle'); setSaveError(''); }}
                className="text-red-600 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300 text-xs"
              >
                Dismiss
              </button>
            </div>
          )}

          <div className="flex gap-6">
            {/* Step sidebar */}
            <nav className="hidden lg:block w-60 flex-shrink-0">
              <div className="sticky top-24 space-y-1">
                {STEPS.map((step, idx) => {
                  const Icon = step.icon;
                  const isCurrent = step.id === activeStep;
                  const v = stepValidation[step.id];
                  return (
                    <button
                      key={step.id}
                      onClick={() => setActiveStep(step.id)}
                      title={v.reason}
                      className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-all ${
                        isCurrent
                          ? 'bg-violet-500/10 text-violet-600 dark:text-violet-400 ring-1 ring-violet-500/20'
                          : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-white/[0.04] hover:text-gray-900 dark:hover:text-gray-200'
                      }`}
                    >
                      <Icon className="w-4 h-4 flex-shrink-0" />
                      <span className="flex-1 text-left">{step.label}</span>
                      <StepStatusDot status={v.status} idx={idx} />
                    </button>
                  );
                })}

                {/* Sidebar reasons summary */}
                <div className="mt-3 px-4 py-3 rounded-xl bg-gray-50 dark:bg-white/[0.02] border border-gray-200 dark:border-white/[0.04] text-[11px] text-gray-500 leading-relaxed">
                  <strong className="text-gray-600 dark:text-gray-400 block mb-1">Cmd/Ctrl + S</strong>
                  Save manually. Edits autosave 1.5s after you stop typing.
                </div>
              </div>
            </nav>

            {/* Mobile step tabs */}
            <div className="lg:hidden flex gap-1 overflow-x-auto pb-4 mb-4 -mx-4 px-4 w-full">
              {STEPS.map((step) => {
                const Icon = step.icon;
                const v = stepValidation[step.id];
                return (
                  <button
                    key={step.id}
                    onClick={() => setActiveStep(step.id)}
                    className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium whitespace-nowrap transition-colors ${
                      step.id === activeStep
                        ? 'bg-violet-500/10 text-violet-600 dark:text-violet-400 ring-1 ring-violet-500/20'
                        : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
                    }`}
                  >
                    <Icon className="w-3.5 h-3.5" />
                    {step.label}
                    <StepStatusDot status={v.status} compact />
                  </button>
                );
              })}
            </div>

            {/* Step content */}
            <div className="flex-1 min-w-0">
              <div className="rounded-2xl border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-white/[0.02] p-6 sm:p-8">
                {activeStep === 'identity' && (
                  <IdentityStep agent={agent} updateField={updateField} />
                )}
                {activeStep === 'prompt' && (
                  <PromptEditor agent={agent} updateField={updateField} />
                )}
                {activeStep === 'tools' && (
                  <ToolSelector
                    agent={agent}
                    updateField={updateField}
                    onUnconfiguredTools={setUnconfiguredTools}
                  />
                )}
                {activeStep === 'config' && (
                  <ConfigStep agent={agent} updateField={updateField} />
                )}
                {activeStep === 'test' && (
                  <TestPlayground agentId={agentId} agent={agent} onSave={handleManualSave} />
                )}
                {activeStep === 'deploy' && (
                  <DeployStep agentId={agentId} agent={agent} onRefresh={() => {
                    if (agentId) {
                      getMyAgent(agentId).then(({ agent: a }) => {
                        setAgent(a);
                        setSavedAgent(a);
                      });
                    }
                  }} />
                )}
              </div>

              {/* Step navigation */}
              <div className="space-y-3 mt-6">
                {activeStep === 'tools' && unconfiguredTools.length > 0 && (
                  <div className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-amber-500/10 border border-amber-500/20">
                    <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0" />
                    <p className="text-xs text-amber-400 flex-1">
                      <strong>{unconfiguredTools.join(', ')}</strong>{' '}
                      {unconfiguredTools.length === 1 ? 'needs' : 'need'} API keys before proceeding.
                      Click <strong>Configure</strong> on each tool above.
                    </p>
                  </div>
                )}
                <div className="flex justify-between">
                  <button
                    onClick={() => stepIdx > 0 && setActiveStep(STEPS[stepIdx - 1].id)}
                    disabled={stepIdx === 0}
                    className="px-4 py-2 rounded-xl border border-gray-200 dark:border-white/[0.08] text-sm font-medium text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:border-gray-300 dark:hover:border-white/[0.15] disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                  >
                    Previous
                  </button>
                  <button
                    onClick={() => stepIdx < STEPS.length - 1 && setActiveStep(STEPS[stepIdx + 1].id)}
                    disabled={stepIdx === STEPS.length - 1 || (activeStep === 'tools' && unconfiguredTools.length > 0)}
                    title={activeStep === 'tools' && unconfiguredTools.length > 0 ? `Configure ${unconfiguredTools.join(', ')} before proceeding` : undefined}
                    className="inline-flex items-center gap-1 px-4 py-2 rounded-xl bg-violet-600/80 hover:bg-violet-600 text-sm font-medium text-white disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                  >
                    Next <ChevronRight className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

// ─── Local helpers ────────────────────────────────────────────────────────────

function SaveIndicator({ state }: { state: SaveState }) {
  if (state === 'saving') {
    return (
      <span className="flex items-center gap-1.5 text-xs text-gray-600 dark:text-gray-400">
        <Loader2 className="w-3 h-3 animate-spin" /> Saving…
      </span>
    );
  }
  if (state === 'saved') {
    return (
      <span className="flex items-center gap-1.5 text-xs text-green-600 dark:text-green-400">
        <CheckCircle className="w-3.5 h-3.5" /> Saved
      </span>
    );
  }
  if (state === 'dirty') {
    return (
      <span className="flex items-center gap-1.5 text-xs text-amber-600 dark:text-amber-400">
        <span className="w-1.5 h-1.5 rounded-full bg-amber-500 dark:bg-amber-400" /> Unsaved
      </span>
    );
  }
  if (state === 'error') {
    return (
      <span className="flex items-center gap-1.5 text-xs text-red-600 dark:text-red-400">
        <AlertCircle className="w-3.5 h-3.5" /> Save failed
      </span>
    );
  }
  if (state === 'conflict') {
    return (
      <span className="flex items-center gap-1.5 text-xs text-amber-600 dark:text-amber-400">
        <AlertTriangle className="w-3.5 h-3.5" /> Conflict
      </span>
    );
  }
  return null;
}

function StepStatusDot({ status, idx, compact }: { status: 'incomplete' | 'warning' | 'complete'; idx?: number; compact?: boolean }) {
  if (status === 'complete') {
    return <CheckCircle className={compact ? 'w-3.5 h-3.5 text-green-500' : 'w-4 h-4 text-green-500'} />;
  }
  if (status === 'warning') {
    return <span className={compact ? 'w-1.5 h-1.5 rounded-full bg-amber-400' : 'w-2 h-2 rounded-full bg-amber-400'} title="Optional or partial" />;
  }
  // incomplete — show a soft dot or step number
  if (compact) return <span className="w-1.5 h-1.5 rounded-full bg-gray-400 dark:bg-gray-600" />;
  return (
    <span className="w-5 h-5 rounded-full bg-gray-100 dark:bg-white/[0.04] text-gray-500 text-[10px] font-bold flex items-center justify-center">
      {(idx ?? 0) + 1}
    </span>
  );
}

/** Carry over fields the server doesn't echo back unchanged (e.g. unsaved edits to local-only state). */
function nonServerFields(prev: Partial<CustomAgent>, server: CustomAgent): Partial<CustomAgent> {
  // Currently no client-only fields; placeholder for future use.
  void prev;
  void server;
  return {};
}
