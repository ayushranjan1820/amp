import { useEffect, useState } from 'react';
import {
  Rocket, Globe, CheckCircle, AlertCircle, Loader2,
  Eye, Lock, Link as LinkIcon, Send, Clock, Shield, GitCompare,
} from 'lucide-react';
import {
  deployAgent, publishAgent, listVersions,
  type CustomAgent, type AgentVersion
} from '../../services/agentBuilder';
import UsagePanel from './UsagePanel';
import VersionDiffModal from './VersionDiffModal';

const STATUS_CONFIG: Record<string, { label: string; color: string; icon: React.ReactNode; desc: string }> = {
  draft: {
    label: 'Draft',
    color: 'text-gray-600 dark:text-gray-400 bg-gray-500/10 ring-gray-500/20',
    icon: <Clock className="w-4 h-4" />,
    desc: 'Agent is in development. Only you can see it.',
  },
  testing: {
    label: 'Testing',
    color: 'text-amber-400 bg-amber-500/10 ring-amber-500/20',
    icon: <Eye className="w-4 h-4" />,
    desc: 'Agent is being tested in the playground.',
  },
  deployed: {
    label: 'Deployed',
    color: 'text-blue-400 bg-blue-500/10 ring-blue-500/20',
    icon: <Rocket className="w-4 h-4" />,
    desc: 'Agent is live and can be invoked via API.',
  },
  published: {
    label: 'Published',
    color: 'text-green-400 bg-green-500/10 ring-green-500/20',
    icon: <Globe className="w-4 h-4" />,
    desc: 'Agent is visible on the marketplace for everyone.',
  },
  archived: {
    label: 'Archived',
    color: 'text-gray-500 bg-gray-500/10 ring-gray-500/20',
    icon: <Lock className="w-4 h-4" />,
    desc: 'Agent is deactivated.',
  },
};

interface Props {
  agentId: string | null;
  agent: Partial<CustomAgent>;
  onRefresh: () => void;
}

export default function DeployStep({ agentId, agent, onRefresh }: Props) {
  const [deploying, setDeploying] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [versions, setVersions] = useState<AgentVersion[]>([]);
  const [diffVersion, setDiffVersion] = useState<string | null>(null);

  const refreshVersions = () => {
    if (!agentId) return;
    listVersions(agentId)
      .then(({ versions: v }) => setVersions(v))
      .catch(() => {});
  };

  useEffect(() => {
    refreshVersions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId, agent.status, agent.version]);

  const handleDeploy = async () => {
    if (!agentId) return;
    setDeploying(true);
    setError('');
    setMessage('');
    try {
      await deployAgent(agentId);
      setMessage('Agent deployed successfully!');
      onRefresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setDeploying(false);
    }
  };

  const handlePublish = async () => {
    if (!agentId) return;
    setPublishing(true);
    setError('');
    setMessage('');
    try {
      const result = await publishAgent(agentId);
      if ((result as any).auto_approved) {
        setMessage('Your agent is now live on the marketplace!');
      } else {
        setMessage('Submitted for review! An admin will review your agent shortly.');
      }
      onRefresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setPublishing(false);
    }
  };

  const status = agent.status || 'draft';
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.draft;
  const canDeploy = !!agentId && ['draft', 'testing'].includes(status);
  // Allow publishing from deployed OR testing (skip deploy step for simplicity)
  const canPublish = !!agentId && ['deployed', 'testing', 'draft'].includes(status) && status !== 'published';
  const isPublished = status === 'published';

  const invocationUrl = agent.slug
    ? `${window.location.origin}/api/agent-builder/invoke/${agent.slug}`
    : null;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-1">Deploy & Publish</h2>
        <p className="text-sm text-gray-500">
          Deploy your agent to make it live, then publish it to the marketplace.
        </p>
      </div>

      {/* Current Status */}
      <div className="rounded-xl border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-white/[0.02] p-5">
        <div className="flex items-center gap-3 mb-3">
          <div className={`w-10 h-10 rounded-xl flex items-center justify-center ring-1 ${cfg.color}`}>
            {cfg.icon}
          </div>
          <div>
            <span className={`px-2.5 py-0.5 rounded-full text-xs font-semibold ring-1 ${cfg.color}`}>
              {cfg.label}
            </span>
            <p className="text-sm text-gray-600 dark:text-gray-400 mt-0.5">{cfg.desc}</p>
          </div>
        </div>

        {/* Deployment pipeline */}
        <div className="flex items-center gap-1 mt-4">
          {['draft', 'testing', 'deployed', 'published'].map((s, i) => {
            const steps = ['draft', 'testing', 'deployed', 'published'];
            const currentIdx = steps.indexOf(status);
            const isPassed = i <= currentIdx;
            return (
              <div key={s} className="flex items-center flex-1">
                <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${
                  isPassed ? 'bg-violet-500 text-gray-900 dark:text-white' : 'bg-gray-100 dark:bg-white/[0.06] text-gray-400 dark:text-gray-600'
                }`}>
                  {isPassed ? '✓' : i + 1}
                </div>
                {i < steps.length - 1 && (
                  <div className={`flex-1 h-0.5 mx-1 ${
                    i < currentIdx ? 'bg-violet-500' : 'bg-gray-100 dark:bg-white/[0.06]'
                  }`} />
                )}
              </div>
            );
          })}
        </div>
        <div className="flex justify-between mt-1">
          {['Draft', 'Test', 'Deploy', 'Publish'].map((l) => (
            <span key={l} className="text-[10px] text-gray-400 dark:text-gray-600 text-center flex-1">{l}</span>
          ))}
        </div>
      </div>

      {/* Validation */}
      {!agentId && (
        <div className="rounded-xl bg-amber-500/5 border border-amber-500/10 p-4">
          <p className="text-sm text-amber-400 flex items-center gap-2">
            <AlertCircle className="w-4 h-4" />
            Save your agent first to enable deployment.
          </p>
        </div>
      )}

      {agentId && !agent.system_prompt && (
        <div className="rounded-xl bg-amber-500/5 border border-amber-500/10 p-4">
          <p className="text-sm text-amber-400 flex items-center gap-2">
            <AlertCircle className="w-4 h-4" />
            Add a system prompt before deploying.
          </p>
        </div>
      )}

      {/* Messages */}
      {message && (
        <div className="rounded-xl bg-green-500/5 border border-green-500/10 p-4 flex items-center gap-2 text-sm text-green-400">
          <CheckCircle className="w-4 h-4 flex-shrink-0" /> {message}
        </div>
      )}
      {error && (
        <div className="rounded-xl bg-red-500/5 border border-red-500/10 p-4 flex items-center gap-2 text-sm text-red-400">
          <AlertCircle className="w-4 h-4 flex-shrink-0" /> {error}
        </div>
      )}

      {/* Actions */}
      <div className="grid gap-3 sm:grid-cols-2">
        <button
          onClick={handleDeploy}
          disabled={!canDeploy || deploying || !agent.system_prompt}
          className="flex items-center justify-center gap-2 px-5 py-3 rounded-xl bg-blue-600 hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed text-gray-900 dark:text-white font-semibold transition-colors"
        >
          {deploying ? <Loader2 className="w-4 h-4 animate-spin" /> : <Rocket className="w-4 h-4" />}
          Deploy Agent
        </button>
        <button
          onClick={handlePublish}
          disabled={!canPublish || publishing}
          className="flex items-center justify-center gap-2 px-5 py-3 rounded-xl bg-green-600 hover:bg-green-700 disabled:opacity-40 disabled:cursor-not-allowed text-gray-900 dark:text-white font-semibold transition-colors"
        >
          {publishing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          Publish to Marketplace
        </button>
      </div>

      {isPublished && (
        <div className="rounded-xl bg-green-500/5 border border-green-500/10 p-4">
          <p className="text-sm text-green-400 flex items-center gap-2 font-medium">
            <Globe className="w-4 h-4" />
            Your agent is live on the marketplace!
          </p>
        </div>
      )}

      {/* API Endpoint */}
      {invocationUrl && ['deployed', 'published'].includes(status) && (
        <div className="rounded-xl border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-white/[0.02] p-4">
          <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2">
            <LinkIcon className="w-4 h-4" /> API Endpoint
          </h4>
          <div className="flex items-center gap-2">
            <code className="flex-1 px-3 py-2 rounded-lg bg-gray-100 dark:bg-black/30 text-xs font-mono text-violet-400 overflow-x-auto">
              POST {invocationUrl}
            </code>
            <button
              onClick={() => navigator.clipboard.writeText(invocationUrl)}
              className="px-3 py-2 rounded-lg bg-gray-100 dark:bg-white/[0.06] hover:bg-gray-200 dark:hover:bg-white/[0.1] text-xs text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-colors"
            >
              Copy
            </button>
          </div>
          <p className="text-xs text-gray-400 dark:text-gray-600 mt-2">
            Send a POST request with <code className="text-gray-600 dark:text-gray-400">{`{"query": "your message"}`}</code> to invoke your agent.
          </p>
        </div>
      )}

      {/* Usage telemetry */}
      {agentId && ['testing', 'deployed', 'published'].includes(agent.status || '') && (
        <UsagePanel agentId={agentId} />
      )}

      {/* Version History */}
      {versions.length > 0 && (
        <div>
          <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3 flex items-center gap-2">
            <Shield className="w-4 h-4" /> Version History
          </h4>
          <div className="space-y-2">
            {versions.map((v) => (
              <div key={v.id} className="flex items-center justify-between px-4 py-2.5 rounded-xl bg-gray-50 dark:bg-white/[0.02] border border-gray-200 dark:border-white/[0.06] hover:border-gray-300 dark:hover:border-white/[0.12] transition-colors">
                <div className="min-w-0 flex-1">
                  <span className="text-sm font-mono text-gray-900 dark:text-white">v{v.version}</span>
                  {v.changelog && <span className="text-xs text-gray-500 ml-2 truncate">— {v.changelog}</span>}
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  <span className="text-xs text-gray-400 dark:text-gray-600">
                    {new Date(v.created_at).toLocaleDateString()}
                  </span>
                  {agentId && v.version !== agent.version && (
                    <button
                      onClick={() => setDiffVersion(v.version)}
                      className="inline-flex items-center gap-1 px-2 py-1 rounded-lg bg-gray-100 dark:bg-white/[0.04] hover:bg-gray-100 dark:hover:bg-white/[0.08] text-xs text-violet-400 hover:text-violet-300 transition-colors"
                      title="Compare with current"
                    >
                      <GitCompare className="w-3.5 h-3.5" /> Diff
                    </button>
                  )}
                  {v.version === agent.version && (
                    <span className="px-2 py-0.5 rounded-full bg-violet-500/15 text-violet-400 text-[10px] font-bold uppercase tracking-wide">
                      Current
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {agentId && diffVersion && (
        <VersionDiffModal
          agentId={agentId}
          version={diffVersion}
          onClose={() => setDiffVersion(null)}
          onRollback={() => {
            setDiffVersion(null);
            onRefresh();
            refreshVersions();
          }}
        />
      )}
    </div>
  );
}
