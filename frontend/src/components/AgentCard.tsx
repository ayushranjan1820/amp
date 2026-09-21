import { Link } from 'react-router-dom';
import { ArrowRight, Zap } from 'lucide-react';
import { useState, useRef, useEffect } from 'react';
import type { Agent } from '../services/api';

interface AgentCardProps {
  agent: Agent;
}

function getAutonomyColor(quotient: number): string {
  if (quotient >= 80) return '#10b981';
  if (quotient >= 60) return '#E88D14';
  return '#D85604';
}

function statusAccent(status: string): { label: string; dotClass: string; textClass: string; ringClass: string } {
  const s = (status || '').toLowerCase();
  if (s.includes('active') || s.includes('ready') || s.includes('live') || s.includes('online')) {
    return { label: status || 'Ready', dotClass: 'bg-emerald-400', textClass: 'text-emerald-300', ringClass: 'ring-emerald-400/20' };
  }
  if (s.includes('beta') || s.includes('preview')) {
    return { label: status || 'Preview', dotClass: 'bg-sky-400', textClass: 'text-sky-300', ringClass: 'ring-sky-400/20' };
  }
  if (s.includes('deprecat') || s.includes('maintenance')) {
    return { label: status || 'Limited', dotClass: 'bg-amber-400', textClass: 'text-amber-300', ringClass: 'ring-amber-400/20' };
  }
  return { label: status || 'Agent', dotClass: 'bg-primary-400', textClass: 'text-primary-300', ringClass: 'ring-primary-400/20' };
}

export default function AgentCard({ agent }: AgentCardProps) {
  const autonomy = agent.autonomy_quotient || 50;
  const [showAllCapabilities, setShowAllCapabilities] = useState(false);
  const popupRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (popupRef.current && !popupRef.current.contains(event.target as Node)) {
        setShowAllCapabilities(false);
      }
    };

    if (showAllCapabilities) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [showAllCapabilities]);

  const barColor = getAutonomyColor(autonomy);
  const categoryLabel = (agent.category || agent.type || 'Agent').toString();
  const caps = Array.isArray(agent.capabilities) ? agent.capabilities : [];
  const previewCapabilities = caps.slice(0, 2);
  const status = statusAccent(agent.status);

  return (
    <div className={`group/card relative ${showAllCapabilities ? 'z-50' : ''}`}>
      <div className="relative flex min-h-[360px] flex-col overflow-hidden rounded-2xl border border-gray-200 dark:border-white/[0.07] bg-gradient-to-b from-white to-gray-50 dark:from-gray-900/90 dark:to-[#0a0a0c] shadow-[0_2px_32px_-12px_rgba(0,0,0,0.15)] dark:shadow-[0_2px_32px_-12px_rgba(0,0,0,0.6)] transition-all duration-200 ease-out hover:-translate-y-0.5 hover:border-primary-500/30 hover:shadow-[0_24px_48px_-20px_rgba(216,86,4,0.25)]">
        <div
          className="pointer-events-none absolute -right-20 -top-20 h-44 w-44 rounded-full bg-primary-500/15 blur-3xl transition-opacity duration-300 group-hover/card:bg-primary-500/25"
          aria-hidden
        />
        <div
          className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-primary-400/40 to-transparent"
          aria-hidden
        />

        <div className="relative z-10 flex min-h-0 flex-1 flex-col px-5 pb-5 pt-4">
          <div className="mb-4 flex items-center justify-between gap-2">
            <div className={`inline-flex items-center gap-1.5 rounded-full border border-gray-200 dark:border-white/[0.08] bg-gray-100 dark:bg-white/[0.04] px-2.5 py-0.5 ring-1 ring-inset ${status.ringClass}`}>
              <span className="relative flex h-1.5 w-1.5">
                <span className={`absolute inline-flex h-full w-full rounded-full opacity-60 ${status.dotClass} animate-ping`} style={{ animationDuration: '2.4s' }} />
                <span className={`relative inline-flex h-1.5 w-1.5 rounded-full ${status.dotClass}`} />
              </span>
              <span className={`font-body text-[0.625rem] font-semibold uppercase tracking-wider ${status.textClass}`}>
                {status.label}
              </span>
            </div>
            {agent.version ? (
              <span className="font-mono text-[0.625rem] tabular-nums text-gray-500">
                v{agent.version}
              </span>
            ) : null}
          </div>

          <div className="flex items-start gap-3.5">
            <div className="relative shrink-0">
              <div className="absolute -inset-0.5 rounded-xl bg-gradient-to-br from-primary-500/40 to-primary-700/20 opacity-0 blur-sm transition-opacity duration-300 group-hover/card:opacity-100" />
              <div className="relative flex h-12 w-12 items-center justify-center overflow-hidden rounded-xl border border-gray-200 dark:border-white/15 bg-white p-2 shadow-md shadow-black/10 dark:shadow-black/30">
                {agent.logo.startsWith('/') || agent.logo.startsWith('http') ? (
                  <img
                    src={agent.logo}
                    alt=""
                    className="max-h-full max-w-full object-contain object-center"
                  />
                ) : (
                  <span className="text-2xl leading-none" aria-hidden>
                    {agent.logo}
                  </span>
                )}
              </div>
            </div>
            <div className="min-w-0 flex-1 pt-0.5">
              <h3 className="truncate font-heading text-[0.9375rem] font-semibold leading-tight tracking-tight text-gray-900 dark:text-white">
                {agent.name}
              </h3>
              <p className="mt-1 truncate font-body text-[0.6875rem] font-medium text-primary-300/80">
                {categoryLabel}
              </p>
            </div>
          </div>

          <p className="mt-3 line-clamp-3 font-body text-[0.75rem] leading-relaxed text-gray-600 dark:text-gray-400">
            {agent.description}
          </p>

          <div className="mt-3.5">
            <div className="mb-1.5 flex items-center justify-between">
              <span className="font-body text-[0.625rem] font-semibold uppercase tracking-wider text-gray-500">
                Autonomy
              </span>
              <span className="font-mono text-[0.6875rem] font-semibold tabular-nums" style={{ color: barColor }}>
                {autonomy}%
              </span>
            </div>
            <div className="relative h-1 w-full overflow-hidden rounded-full bg-gray-100 dark:bg-white/[0.06]">
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{
                  width: `${autonomy}%`,
                  background: `linear-gradient(90deg, ${barColor}, ${barColor}dd)`,
                  boxShadow: `0 0 8px ${barColor}55`,
                }}
              />
            </div>
          </div>

          <div className="mt-3 shrink-0">
            <div className="mb-1.5 flex items-center gap-1.5">
              <Zap className="h-3 w-3 text-primary-400" aria-hidden />
              <span className="font-body text-[0.625rem] font-semibold uppercase tracking-wider text-gray-500">
                Capabilities
              </span>
            </div>
            <div className="flex min-w-0 items-center gap-1.5">
              <div className="flex min-w-0 flex-1 items-center gap-1.5">
                {previewCapabilities.map((cap, index) => (
                  <span
                    key={index}
                    className="min-w-0 flex-1 truncate rounded-md border border-gray-200 dark:border-white/[0.08] bg-gray-50 dark:bg-white/[0.03] px-2 py-1 font-body text-[0.625rem] font-medium text-gray-700 dark:text-gray-300"
                    title={cap}
                  >
                    {cap}
                  </span>
                ))}
              </div>
              {caps.length > 2 && (
                <div className="relative shrink-0" ref={popupRef}>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setShowAllCapabilities(!showAllCapabilities);
                    }}
                    className="whitespace-nowrap rounded-md border border-primary-500/30 bg-primary-500/10 px-2 py-1 font-body text-[0.625rem] font-semibold text-primary-200 transition-colors hover:border-primary-400/50 hover:bg-primary-500/20"
                  >
                    +{caps.length - 2}
                  </button>

                  {showAllCapabilities && (
                    <div className="absolute bottom-full right-0 z-[100] mb-2 w-[15.5rem] rounded-xl border border-gray-200 dark:border-white/10 bg-white dark:bg-[#0a0a0c] p-3 shadow-2xl shadow-black/20 dark:shadow-black/60 sm:left-0 sm:right-auto">
                      <div className="mb-2 border-b border-gray-200 dark:border-white/10 pb-2">
                        <span className="font-body text-[0.625rem] font-semibold uppercase tracking-wider text-gray-600 dark:text-gray-400">
                          All capabilities
                        </span>
                      </div>
                      <div className="flex max-h-40 flex-wrap gap-1.5 overflow-y-auto [scrollbar-width:thin]">
                        {caps.map((cap, index) => (
                          <span
                            key={index}
                            className="rounded-md border border-gray-200 dark:border-white/[0.08] bg-gray-50 dark:bg-white/[0.03] px-2 py-0.5 font-body text-[0.625rem] font-medium text-gray-600 dark:text-gray-400"
                          >
                            {cap}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          <div className="mt-auto pt-4">
            <Link
              to={`/agent/${agent.id}`}
              className="btn-primary group/btn inline-flex w-full items-center justify-center gap-2 rounded-lg py-2.5 px-5 text-[0.8125rem]"
            >
              <span>Run agent</span>
              <ArrowRight className="h-3.5 w-3.5 shrink-0 transition-transform group-hover/btn:translate-x-0.5" />
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
