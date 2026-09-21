import { Link, useParams } from 'react-router-dom';
import { Sparkles, LogIn, ArrowRight } from 'lucide-react';
import { LoadingProvider } from '../context/LoadingContext';
import { WorkflowsTab } from '../components/WorkflowsTab';
import { useAuth } from '../context/AuthContext';

export default function AgentStudioPage() {
  const { isAuthenticated } = useAuth();
  const { workflowId } = useParams<{ workflowId?: string }>();

  return (
    <LoadingProvider>
      <div className="min-h-[calc(100vh-4.25rem)] overflow-x-hidden bg-white dark:bg-zinc-950">
        {!isAuthenticated ? (
          <div className="border-b border-gray-200 dark:border-white/[0.08] bg-gradient-to-r from-amber-500/[0.12] via-violet-500/[0.1] to-sky-500/[0.12] px-4 py-4 sm:px-6 lg:px-8">
            <div className="mx-auto flex max-w-[1600px] flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex min-w-0 items-start gap-3">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gray-100 dark:bg-white/[0.08] ring-1 ring-gray-200 dark:ring-white/[0.1]">
                  <Sparkles className="h-5 w-5 text-amber-500 dark:text-amber-300" aria-hidden />
                </div>
                <div className="min-w-0">
                  <p className="font-heading text-sm font-semibold text-gray-900 dark:text-white sm:text-base">Try the studio without signing in</p>
                  <p className="mt-1 max-w-xl font-body text-xs leading-relaxed text-gray-600 dark:text-zinc-400 sm:text-sm">
                    Generate and run workflows below. Sign in when you want <span className="text-gray-800 dark:text-zinc-300">My agents</span>, server saves, and execution history tied to your account.
                  </p>
                </div>
              </div>
              <Link
                to="/admin/login"
                className="inline-flex shrink-0 items-center justify-center gap-2 self-start rounded-full bg-zinc-900 dark:bg-white px-5 py-2.5 font-body text-sm font-semibold text-white dark:text-zinc-900 shadow-lg shadow-black/20 transition-transform hover:bg-zinc-800 dark:hover:bg-zinc-100 active:scale-[0.99] sm:self-auto"
              >
                <LogIn className="h-4 w-4" aria-hidden />
                Sign in for My agents
                <ArrowRight className="h-4 w-4 opacity-70" aria-hidden />
              </Link>
            </div>
          </div>
        ) : null}
        <WorkflowsTab routeWorkflowId={workflowId} />
      </div>
    </LoadingProvider>
  );
}
