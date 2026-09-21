import { useState, useEffect } from 'react';
import { CheckCircle, XCircle, Clock, Loader2, Bot, AlertCircle, Eye } from 'lucide-react';
import {
  listSubmissions, reviewSubmission,
  getMyAgent, type Submission, type CustomAgent,
} from '../services/agentBuilder';

export default function ReviewQueueTab() {
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<'pending' | 'approved' | 'rejected' | ''>('pending');
  const [reviewing, setReviewing] = useState<string | null>(null);
  const [notes, setNotes] = useState('');
  const [error, setError] = useState('');
  const [previewAgent, setPreviewAgent] = useState<CustomAgent | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const load = () => {
    setLoading(true);
    listSubmissions(filter || undefined)
      .then(({ submissions: s }) => setSubmissions(s))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, [filter]);

  const handleReview = async (subId: string, approved: boolean) => {
    setReviewing(subId);
    try {
      await reviewSubmission(subId, approved, notes);
      setNotes('');
      load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setReviewing(null);
    }
  };

  const handlePreview = async (agentId: string) => {
    setPreviewLoading(true);
    try {
      const { agent } = await getMyAgent(agentId);
      setPreviewAgent(agent);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setPreviewLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-gray-900 dark:text-white">Agent Review Queue</h2>
          <p className="text-sm text-gray-500">Review and approve community-submitted agents for the marketplace.</p>
        </div>
        <div className="flex gap-1 rounded-full border border-gray-200 dark:border-white/[0.08] bg-gray-50 dark:bg-white/[0.02] p-0.5">
          {[
            { value: 'pending', label: 'Pending' },
            { value: 'approved', label: 'Approved' },
            { value: 'rejected', label: 'Rejected' },
            { value: '', label: 'All' },
          ].map((f) => (
            <button
              key={f.value}
              onClick={() => setFilter(f.value as any)}
              className={`px-3 py-1.5 rounded-full text-xs font-medium transition-all ${
                filter === f.value
                  ? 'bg-violet-500/15 text-violet-400 ring-1 ring-violet-500/20'
                  : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="rounded-xl bg-red-500/5 border border-red-500/10 p-3 flex items-center gap-2 text-sm text-red-400">
          <AlertCircle className="w-4 h-4" /> {error}
          <button onClick={() => setError('')} className="ml-auto text-xs underline">dismiss</button>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="w-6 h-6 text-violet-400 animate-spin" />
        </div>
      ) : submissions.length === 0 ? (
        <div className="text-center py-16 space-y-3">
          <Clock className="w-10 h-10 text-gray-400 dark:text-gray-600 mx-auto" />
          <p className="text-gray-500">No {filter || ''} submissions.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {submissions.map((sub) => (
            <div key={sub.id} className="rounded-xl border border-gray-200 dark:border-white/[0.06] bg-white dark:bg-white/[0.02] p-4">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-violet-500/10 flex items-center justify-center">
                    <Bot className="w-5 h-5 text-violet-400" />
                  </div>
                  <div>
                    <h3 className="font-semibold text-gray-900 dark:text-white">{sub.agent_name || sub.agent_id}</h3>
                    <p className="text-xs text-gray-500 mt-0.5">{sub.agent_description?.slice(0, 100) || 'No description'}</p>
                  </div>
                </div>
                <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium ring-1 ${
                  sub.status === 'pending' ? 'text-amber-400 bg-amber-500/10 ring-amber-500/20' :
                  sub.status === 'approved' ? 'text-green-400 bg-green-500/10 ring-green-500/20' :
                  'text-red-400 bg-red-500/10 ring-red-500/20'
                }`}>
                  {sub.status}
                </span>
              </div>

              <div className="mt-3 flex items-center gap-2 text-xs text-gray-400 dark:text-gray-600">
                <span>Submitted {new Date(sub.submitted_at).toLocaleDateString()}</span>
                {sub.reviewed_at && (
                  <>
                    <span>·</span>
                    <span>Reviewed {new Date(sub.reviewed_at).toLocaleDateString()}</span>
                  </>
                )}
                {sub.review_notes && (
                  <>
                    <span>·</span>
                    <span className="text-gray-600 dark:text-gray-400 italic">"{sub.review_notes}"</span>
                  </>
                )}
              </div>

              {sub.status === 'pending' && (
                <div className="mt-4 border-t border-gray-200 dark:border-white/[0.06] pt-3 space-y-3">
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => handlePreview(sub.agent_id)}
                      disabled={previewLoading}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-200 dark:border-white/[0.08] text-xs text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:border-gray-300 dark:hover:border-white/[0.15] transition-colors"
                    >
                      {previewLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Eye className="w-3 h-3" />}
                      Preview
                    </button>
                  </div>
                  <textarea
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    placeholder="Review notes (optional)..."
                    rows={2}
                    className="w-full px-3 py-2 rounded-lg bg-gray-100 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-sm text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-violet-500/40 resize-none"
                  />
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleReview(sub.id, true)}
                      disabled={reviewing === sub.id}
                      className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-green-600 hover:bg-green-700 text-white text-sm font-medium transition-colors disabled:opacity-50"
                    >
                      {reviewing === sub.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle className="w-3.5 h-3.5" />}
                      Approve
                    </button>
                    <button
                      onClick={() => handleReview(sub.id, false)}
                      disabled={reviewing === sub.id}
                      className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-red-600 hover:bg-red-700 text-white text-sm font-medium transition-colors disabled:opacity-50"
                    >
                      {reviewing === sub.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <XCircle className="w-3.5 h-3.5" />}
                      Reject
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Preview modal */}
      {previewAgent && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/40 dark:bg-black/60 backdrop-blur-sm" onClick={() => setPreviewAgent(null)}>
          <div className="w-full max-w-lg mx-4 rounded-2xl border border-gray-200 dark:border-white/[0.08] bg-white dark:bg-zinc-900 p-6 max-h-[80vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-bold text-gray-900 dark:text-white">{previewAgent.name}</h3>
              <button onClick={() => setPreviewAgent(null)} className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-white/[0.06] text-gray-600 dark:text-gray-400">
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
              </button>
            </div>
            <div className="space-y-3 text-sm">
              <div>
                <span className="text-gray-500">Description:</span>
                <p className="text-gray-700 dark:text-gray-300 mt-0.5">{previewAgent.description || 'None'}</p>
              </div>
              <div>
                <span className="text-gray-500">Category:</span>
                <span className="text-gray-700 dark:text-gray-300 ml-2">{previewAgent.category_id}</span>
              </div>
              <div>
                <span className="text-gray-500">Model:</span>
                <span className="text-gray-700 dark:text-gray-300 ml-2 font-mono text-xs">{previewAgent.llm_model}</span>
              </div>
              <div>
                <span className="text-gray-500">System Prompt:</span>
                <pre className="mt-1 p-3 rounded-lg bg-gray-100 dark:bg-black/30 text-xs text-gray-700 dark:text-gray-300 whitespace-pre-wrap overflow-x-auto max-h-48 overflow-y-auto">
                  {previewAgent.system_prompt || 'None'}
                </pre>
              </div>
              <div>
                <span className="text-gray-500">Tools:</span>
                <div className="flex flex-wrap gap-1 mt-1">
                  {(previewAgent.tools_config || []).map((t: any, i: number) => (
                    <span key={i} className="px-2 py-0.5 rounded-full bg-gray-100 dark:bg-white/[0.06] text-xs text-gray-600 dark:text-gray-400">
                      {typeof t === 'string' ? t : t.name}
                    </span>
                  ))}
                  {(previewAgent.tools_config || []).length === 0 && <span className="text-gray-400 dark:text-gray-600">None</span>}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
