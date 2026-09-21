import { useState, useEffect, useMemo } from 'react';
import { Link } from 'react-router-dom';
import {
  Search,
  Shield,
  ArrowRight,
  Bot,
  MessageSquare,
  Sparkles,
  Code,
  Landmark,
  FlaskConical,
  BookOpen,
  LayoutGrid,
  X,
  Cpu,
  Network,
  Zap,
  Activity,
  GitBranch,
} from 'lucide-react';
import AgentCard from '../components/AgentCard';
import { getAgents, type Agent, type Category } from '../services/api';
import { listPublishedAgents, type CustomAgent } from '../services/agentBuilder';
import { useAuth } from '../context/AuthContext';

const categoryIcons: Record<string, React.ReactNode> = {
  'Bot': <Bot className="w-4 h-4" />,
  'Code': <Code className="w-4 h-4" />,
  'Landmark': <Landmark className="w-4 h-4" />,
  'FlaskConical': <FlaskConical className="w-4 h-4" />,
};

const heroSatelliteAgents: { src: string; alt: string; className: string; delay: string }[] = [
  {
    src: '/images/browser-agent-logo.svg',
    alt: 'Browser agent',
    className: 'left-[2%] top-[10%] sm:left-[0%] sm:top-[12%]',
    delay: '0s',
  },
  {
    src: '/images/code-sandbox-logo.svg',
    alt: 'Code sandbox agent',
    className: 'right-[0%] top-[16%] sm:right-[-2%] sm:top-[20%]',
    delay: '0.6s',
  },
  {
    src: '/images/mongodb-logo.png',
    alt: 'MongoDB Atlas KB agent',
    className: 'left-[4%] bottom-[18%] sm:left-[2%] sm:bottom-[22%]',
    delay: '1.2s',
  },
  {
    src: '/images/web-search-agent-logo.svg',
    alt: 'Web search agent',
    className: 'right-[4%] bottom-[14%] sm:right-[2%] sm:bottom-[18%]',
    delay: '1.8s',
  },
];

/** Lowercased blob of text we match the search query against (defensive for API / custom agents). */
function buildAgentSearchHaystack(agent: Agent): string {
  const parts: string[] = [
    agent.name,
    agent.description,
    agent.type,
    agent.category,
    agent.id,
    ...(Array.isArray(agent.capabilities) ? agent.capabilities : []),
  ];
  if (Array.isArray(agent.tools)) {
    for (const t of agent.tools) {
      if (typeof t === 'string') parts.push(t);
      else if (t && typeof t === 'object') {
        parts.push(t.name, t.description);
      }
    }
  }
  return parts.map((p) => String(p ?? '')).join(' ').toLowerCase();
}

function agentMatchesQuery(agent: Agent, raw: string): boolean {
  const q = raw.trim().toLowerCase();
  if (!q) return true;
  return buildAgentSearchHaystack(agent).includes(q);
}

export default function Home() {
  const { isAuthenticated } = useAuth();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [agentFilter, setAgentFilter] = useState<'all' | 'official' | 'community'>('all');
  const [communityAgents, setCommunityAgents] = useState<Agent[]>([]);

  useEffect(() => {
    async function fetchAgents() {
      try {
        const [catalogData, publishedData] = await Promise.all([
          getAgents(),
          listPublishedAgents().catch(() => ({ agents: [] })),
        ]);
        setAgents(catalogData.agents);
        setCategories(catalogData.categories || []);
        const mapped: Agent[] = (publishedData.agents || []).map((ca: CustomAgent) => ({
          id: ca.id,
          name: ca.name,
          type: 'custom',
          category: ca.category_id,
          status: ca.status,
          autonomy_quotient: 50,
          description: ca.description,
          logo: ca.logo_url || '',
          version: ca.version,
          path: '',
          capabilities: ca.capabilities || [],
          tools: (ca.tools_config || []).map((t: any) => ({
            name: t.name || t,
            description: t.description || '',
            module: '',
          })),
          llm_providers: [],
          usage: {
            entry_point: '',
            class_name: '',
            example_prompts: ca.example_prompts || [],
            api_endpoint: `POST /api/agent-builder/invoke/${ca.slug}`,
          },
        }));
        setCommunityAgents(mapped);
      } catch (err: any) {
        setError(err.message);
      } finally {
        setIsLoading(false);
      }
    }
    fetchAgents();
  }, [isAuthenticated]);

  const allAgents = useMemo(() => {
    return agentFilter === 'community'
      ? communityAgents
      : agentFilter === 'official'
        ? agents
        : [...agents, ...communityAgents];
  }, [agentFilter, agents, communityAgents]);

  const filteredAgents = useMemo(() => {
    return allAgents
      .filter((agent) => {
        const matchesSearch = agentMatchesQuery(agent, searchQuery);
        const matchesCategory = selectedCategory === 'all' || agent.category === selectedCategory;
        const isNotAdminOnly = isAuthenticated || !agent.admin_only;
        return matchesSearch && matchesCategory && isNotAdminOnly;
      })
      .sort((a, b) => (b.autonomy_quotient || 0) - (a.autonomy_quotient || 0));
  }, [allAgents, searchQuery, selectedCategory, isAuthenticated]);

  const sortedCategories = [...categories].sort((a, b) => a.order - b.order);
  const activeCategoryName =
    selectedCategory === 'all'
      ? null
      : sortedCategories.find((c) => c.id === selectedCategory)?.name ?? null;

  return (
    <div className="min-h-screen landing-canvas selection:bg-primary-500/25 selection:text-gray-900 dark:selection:text-white">
      <section className="relative overflow-hidden gradient-hero-modern border-b border-gray-200 dark:border-white/[0.05] bg-grain">
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.35]"
          aria-hidden
        >
          <div className="absolute -left-32 top-1/4 h-72 w-72 rounded-full bg-primary-500/25 blur-[100px] animate-landing-mesh" />
          <div className="absolute -right-24 bottom-1/4 h-80 w-80 rounded-full bg-amber-400/15 blur-[90px] animate-landing-pulse-ring" />
          <div
            className="absolute left-1/2 top-[38%] h-[min(100vw,28rem)] w-[min(100vw,28rem)] -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent-pink/10 blur-[100px] animate-landing-mesh"
            style={{ animationDelay: '-4s' }}
          />
        </div>

        <div className="absolute inset-0 opacity-[0.07] [mask-image:linear-gradient(to_bottom,black,transparent)]" aria-hidden>
          <svg className="h-full w-full" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <pattern id="home-hero-grid" width="48" height="48" patternUnits="userSpaceOnUse">
                <path d="M 48 0 L 0 0 0 48" fill="none" stroke="white" strokeWidth="0.5" />
              </pattern>
            </defs>
            <rect width="100%" height="100%" fill="url(#home-hero-grid)" />
          </svg>
        </div>

        <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-16 sm:py-20 lg:py-28">
          <div className="flex flex-col items-start gap-14 lg:flex-row lg:items-center lg:gap-20 xl:gap-24">
            <div className="w-full lg:w-[46%] xl:w-[44%] lg:max-w-xl">
              <div className="mb-6 inline-flex items-center gap-2.5 rounded-full border border-gray-200 dark:border-white/[0.08] bg-gray-100 dark:bg-white/[0.04] px-4 py-2 shadow-[inset_0_1px_0_rgba(255,255,255,0.05),0_1px_2px_rgba(0,0,0,0.2)] backdrop-blur-2xl">
                <span className="relative flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400/45 opacity-75" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_10px_rgba(52,211,153,0.45)]" />
                </span>
                <span className="font-body text-[0.6875rem] font-semibold uppercase tracking-[0.16em] text-gray-300/90">
                  Multi-agent · Orchestrated · Live catalog
                </span>
              </div>

              <h1 className="font-heading text-balance text-[2.125rem] font-bold leading-[1.04] tracking-[-0.03em] text-gray-900 dark:text-white sm:text-5xl lg:text-[3.5rem] xl:text-[3.75rem]">
                Build with{' '}
                <span className="text-gradient-warm">AI agents</span>
                <br className="hidden sm:block" />
                <span className="text-white/[0.92]">that ship real work</span>
              </h1>
              <p className="mt-6 max-w-lg text-pretty font-body text-base leading-relaxed text-gray-400/95 sm:text-lg">
                Automation that fits your stack: conversational interfaces, enterprise guardrails, and integrations your teams can trust at scale.
              </p>

              <div className="mt-9 flex flex-wrap items-center gap-3">
                <a
                  href="#agents"
                  className="btn-primary group rounded-full py-3.5 px-7 text-sm shadow-lg shadow-primary-600/25 ring-1 ring-white/10 transition-[transform,box-shadow] duration-200 hover:shadow-primary-500/35 sm:text-[0.9375rem]"
                >
                  <span>Browse catalog</span>
                  <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                </a>
                <Link
                  to="/agent-studio"
                  className="inline-flex items-center gap-2 rounded-full border border-white/[0.12] bg-gray-100 dark:bg-white/[0.06] px-6 py-3.5 font-body text-sm font-semibold text-gray-900 dark:text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.06)] backdrop-blur-2xl transition-all hover:border-amber-400/35 hover:bg-white/[0.1] sm:text-[0.9375rem]"
                >
                  <Sparkles className="h-4 w-4 text-amber-200" />
                  Agent Studio
                </Link>
                {isAuthenticated && (
                  <Link
                    to="/docs"
                    className="inline-flex items-center gap-2 rounded-full border border-white/[0.1] bg-transparent px-6 py-3.5 font-body text-sm font-semibold text-gray-200 transition-all hover:border-white/20 hover:bg-white/[0.05] hover:text-gray-900 dark:hover:text-white sm:text-[0.9375rem]"
                  >
                    <BookOpen className="h-4 w-4 text-primary-300" />
                    Documentation
                  </Link>
                )}
              </div>

              <div className="mt-12 grid grid-cols-3 gap-2 sm:max-w-lg sm:gap-3">
                {[
                  { label: 'Agents', value: `${agents.length}+`, sub: 'In catalog' },
                  { label: 'Uptime', value: '99.9%', sub: 'Target SLA' },
                  { label: 'Coverage', value: '24/7', sub: 'Always on' },
                ].map((stat) => (
                  <div
                    key={stat.label}
                    className="rounded-2xl border border-gray-200 dark:border-white/[0.06] bg-white/[0.03] px-3 py-4 text-center shadow-[inset_0_1px_0_rgba(255,255,255,0.04)] backdrop-blur-xl sm:rounded-2xl sm:px-4 sm:py-4"
                  >
                    <div className="font-heading text-lg font-bold tabular-nums text-gray-900 dark:text-white sm:text-2xl">{stat.value}</div>
                    <div className="mt-1 font-body text-[0.6rem] font-semibold uppercase tracking-[0.12em] text-gray-500">
                      {stat.label}
                    </div>
                    <div className="mt-1 hidden font-body text-[0.7rem] text-gray-500 sm:block">{stat.sub}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="relative w-full min-h-[300px] sm:min-h-[380px] lg:min-h-[360px] lg:w-[54%] xl:w-[56%] lg:flex-1 lg:min-w-0">
              <div
                className="pointer-events-none absolute -inset-6 rounded-[2.25rem] bg-gradient-to-br from-primary-500/25 via-accent-pink/10 to-amber-400/15 blur-3xl animate-landing-pulse-ring sm:-inset-8"
                aria-hidden
              />

              <div
                className="pointer-events-none absolute left-1/2 top-[52%] z-0 h-[min(94vw,460px)] w-[min(94vw,460px)] -translate-x-1/2 -translate-y-1/2 sm:h-[min(84vw,540px)] sm:w-[min(84vw,540px)]"
                aria-hidden
              >
                <div className="absolute inset-0 rounded-full border border-dashed border-gray-300 dark:border-white/[0.12] animate-landing-orbit opacity-80" />
                <div className="absolute inset-[9%] rounded-full border border-gray-200 dark:border-white/[0.06] animate-landing-orbit-reverse opacity-70" />
              </div>

              {heroSatelliteAgents.map((sat) => (
                <div
                  key={sat.src}
                  className={`absolute z-20 hidden sm:block ${sat.className}`}
                >
                  <div
                    className="animate-landing-float-drift rounded-2xl border border-gray-200 dark:border-white/15 bg-gray-950/85 p-2 shadow-lg shadow-black/45 backdrop-blur-md ring-1 ring-white/[0.07]"
                    style={{ animationDelay: sat.delay }}
                  >
                    <img src={sat.src} alt={sat.alt} className="h-10 w-10 object-contain sm:h-11 sm:w-11" />
                  </div>
                </div>
              ))}

              <div className="relative z-10 mx-auto max-w-2xl animate-float-soft lg:max-w-none">
                <div className="relative rounded-[1.25rem] bg-gradient-to-br from-white/25 via-white/8 to-transparent p-[1px] shadow-2xl shadow-black/50 sm:rounded-[1.75rem]">
                  <div className="relative overflow-hidden rounded-[1.2rem] bg-white dark:bg-gray-950 ring-1 ring-white/10 sm:rounded-[1.7rem]">
                    <div className="pointer-events-none absolute left-3 top-3 z-20 flex items-center gap-2 rounded-lg border border-gray-200 dark:border-white/10 bg-black/45 px-2 py-1 backdrop-blur-md">
                      <Network className="h-3.5 w-3.5 shrink-0 text-primary-400" aria-hidden />
                      <span className="font-mono text-[0.62rem] font-medium uppercase tracking-[0.12em] text-gray-700 dark:text-gray-300">
                        Orchestration
                      </span>
                    </div>
                    <div className="pointer-events-none absolute right-3 top-3 z-20 flex items-center gap-1.5 rounded-lg border border-emerald-500/25 bg-emerald-950/55 px-2 py-1 backdrop-blur-md">
                      <span className="relative flex h-1.5 w-1.5">
                        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400/40 opacity-75" />
                        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400" />
                      </span>
                      <Cpu className="h-3.5 w-3.5 shrink-0 text-emerald-400" aria-hidden />
                      <span className="font-mono text-[0.62rem] font-medium text-emerald-200/90">Run</span>
                    </div>

                    <div className="pointer-events-none absolute inset-0 z-10 overflow-hidden rounded-[inherit]" aria-hidden>
                      <div className="absolute inset-x-0 -top-1/4 h-28 bg-gradient-to-b from-transparent via-white/18 to-transparent animate-landing-scan" />
                    </div>

                    <img
                      src="/images/ai-agents-hero.png"
                      alt="AI agents coordinating automation workflows"
                      className="animate-landing-image-breathe w-full object-cover"
                    />

                    <div className="pointer-events-none absolute inset-x-0 bottom-0 z-20 border-t border-gray-200 dark:border-white/[0.07] bg-gradient-to-t from-gray-100/95 dark:from-black/75 via-gray-100/40 dark:via-black/35 to-transparent px-3 py-2.5 sm:px-4 sm:py-3">
                      <div className="flex items-center gap-2 font-mono text-[0.62rem] leading-snug text-gray-600 dark:text-gray-400 sm:text-[0.65rem]">
                        <Zap className="h-3.5 w-3.5 shrink-0 text-amber-400" aria-hidden />
                        <span className="min-w-0 truncate">
                          <span className="text-primary-300">Swarm active</span>
                          <span className="text-gray-500"> · route · tools · memory</span>
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div
                className="relative z-10 mt-5 flex justify-center gap-2 px-2 sm:hidden"
                aria-hidden
              >
                {heroSatelliteAgents.map((sat) => (
                  <div
                    key={sat.src}
                    className="animate-landing-float-drift rounded-xl border border-gray-200 dark:border-white/12 bg-white dark:bg-gray-950/90 p-1.5 shadow-md ring-1 ring-gray-200 dark:ring-white/[0.05]"
                    style={{ animationDelay: sat.delay }}
                  >
                    <img src={sat.src} alt="" className="h-8 w-8 object-contain" />
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section
        className="relative overflow-hidden border-b border-gray-200/50 bg-gradient-to-b from-gray-50/95 via-white to-gray-100/40 py-20 dark:border-white/[0.06] dark:from-[#0b0b0d] dark:via-[#09090b] dark:to-[#060607] lg:py-28"
        aria-labelledby="studio-marketing-heading"
      >
        <div className="pointer-events-none absolute inset-0 opacity-[0.45] dark:opacity-[0.28]" aria-hidden>
          <div className="absolute -left-24 top-1/4 h-80 w-80 rounded-full bg-primary-500/18 blur-[110px] animate-landing-mesh dark:bg-primary-500/22" />
          <div className="absolute -right-20 bottom-1/4 h-96 w-96 rounded-full bg-violet-500/14 blur-[100px] animate-landing-pulse-ring dark:bg-violet-500/18" />
          <div
            className="absolute left-1/2 top-[55%] h-[min(90vw,24rem)] w-[min(90vw,24rem)] -translate-x-1/2 -translate-y-1/2 rounded-full bg-sky-500/8 blur-[90px] dark:bg-sky-500/12 animate-landing-mesh"
            style={{ animationDelay: '-6s' }}
          />
        </div>

        <div
          className="pointer-events-none absolute inset-0 opacity-[0.45] [mask-image:linear-gradient(to_bottom,black_40%,transparent)] dark:opacity-[0.14] dark:[mask-image:linear-gradient(to_bottom,black_50%,transparent)]"
          aria-hidden
        >
          <svg className="h-full w-full text-gray-600 dark:text-white" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <pattern id="studio-section-grid" width="56" height="56" patternUnits="userSpaceOnUse">
                <path d="M 56 0 L 0 0 0 56" fill="none" stroke="currentColor" strokeWidth="0.4" className="opacity-[0.35] dark:opacity-[0.2]" />
              </pattern>
            </defs>
            <rect width="100%" height="100%" fill="url(#studio-section-grid)" />
          </svg>
        </div>

        <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-gray-300/70 to-transparent dark:via-white/[0.1]" aria-hidden />

        <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="grid items-start gap-12 lg:grid-cols-12 lg:gap-14 xl:gap-16">
            <div className="lg:col-span-5 xl:col-span-4">
              <div className="inline-flex items-center gap-2.5 rounded-full border border-gray-200/90 bg-white/80 px-3.5 py-1.5 shadow-sm shadow-gray-900/[0.03] backdrop-blur-md dark:border-white/[0.1] dark:bg-white/[0.04] dark:shadow-none">
                <span className="relative flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary-500/35 opacity-75 dark:bg-primary-400/40" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-primary-500 dark:bg-primary-400" />
                </span>
                <span className="font-body text-[0.65rem] font-bold uppercase tracking-[0.18em] text-primary-700 dark:text-primary-300">
                  Orchestration
                </span>
              </div>

              <h2
                id="studio-marketing-heading"
                className="mt-6 text-balance font-heading text-[2rem] font-bold leading-[1.08] tracking-[-0.03em] text-gray-900 dark:text-white sm:text-4xl xl:text-[2.5rem]"
              >
                <span className="block">Agent Studio</span>
                <span className="mt-2 block text-[1.35rem] font-semibold leading-snug tracking-[-0.02em] text-gray-600 dark:text-gray-400 sm:text-2xl xl:text-[1.65rem]">
                  Say it in{' '}
                  <span className="text-gradient-warm">natural language</span>
                  <span className="text-gray-900 dark:text-white"> — ship the work</span>
                </span>
              </h2>

              <p className="mt-5 max-w-md text-pretty font-body text-[0.9375rem] leading-relaxed text-gray-600 dark:text-gray-400 sm:text-base">
                Describe the job in plain language; Agent Studio turns that into specialist agents, a runnable workflow, and execution to completion—with a live trace and no separate IDE.
              </p>

              <div className="mt-3 h-px max-w-xs bg-gradient-to-r from-primary-500/50 via-violet-400/30 to-transparent dark:from-primary-400/45 dark:via-violet-400/25" aria-hidden />

              <Link
                to="/agent-studio"
                className="btn-primary group mt-8 inline-flex items-center gap-2 rounded-full py-3.5 px-7 text-sm font-semibold shadow-lg shadow-primary-600/20 ring-1 ring-gray-900/5 transition-[transform,box-shadow] duration-200 hover:shadow-primary-500/30 dark:ring-white/10 sm:text-[0.9375rem]"
              >
                Open Agent Studio
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
              </Link>
            </div>

            <div className="grid gap-4 sm:grid-cols-2 sm:gap-4 lg:col-span-7 lg:grid-cols-2 xl:col-span-8">
              {[
                {
                  step: '01',
                  icon: Sparkles,
                  title: 'Create from what you say',
                  body: 'One clear description is enough—the studio drafts agents and steps so you are not building flows from a blank canvas.',
                  accent: 'from-primary-500/25 via-amber-500/10 to-transparent',
                  iconWrap: 'from-primary-500/20 to-amber-500/12 text-primary-600 dark:from-primary-500/35 dark:to-amber-500/18 dark:text-primary-300',
                },
                {
                  step: '02',
                  icon: GitBranch,
                  title: 'Refine, then run',
                  body: 'Review the graph, connect outputs and knowledge bases, tweak prompts—then promote the same design straight into execution.',
                  accent: 'from-violet-500/25 via-sky-500/10 to-transparent',
                  iconWrap: 'from-violet-500/20 to-sky-500/12 text-violet-600 dark:from-violet-500/35 dark:to-sky-500/18 dark:text-violet-300',
                },
                {
                  step: '03',
                  icon: Zap,
                  title: 'Get the outcome, not just a diagram',
                  body: 'Stream progress, capture agent I/O, handle interactive prompts, and keep history so finished work is visible and auditable.',
                  accent: 'from-emerald-500/25 via-teal-500/10 to-transparent',
                  iconWrap: 'from-emerald-500/20 to-teal-500/12 text-emerald-600 dark:from-emerald-500/35 dark:to-teal-500/18 dark:text-emerald-300',
                  wide: true,
                },
              ].map(({ step, icon: Icon, title, body, accent, iconWrap, wide }) => (
                <div
                  key={step}
                  className={`group relative overflow-hidden rounded-2xl border border-gray-200/70 bg-white/75 p-6 shadow-[0_2px_32px_-12px_rgba(15,23,42,0.1)] backdrop-blur-xl transition-[transform,box-shadow,border-color] duration-300 hover:-translate-y-0.5 hover:border-primary-500/25 hover:shadow-[0_24px_48px_-20px_rgba(15,23,42,0.14)] dark:border-white/[0.08] dark:bg-white/[0.035] dark:shadow-[0_2px_40px_-12px_rgba(0,0,0,0.45)] dark:hover:border-primary-400/20 dark:hover:shadow-[0_28px_56px_-16px_rgba(0,0,0,0.55)] sm:p-7 ${wide ? 'sm:col-span-2' : ''}`}
                >
                  <div
                    className={`pointer-events-none absolute inset-x-0 top-0 h-24 bg-gradient-to-b ${accent} opacity-80`}
                    aria-hidden
                  />
                  <div className="pointer-events-none absolute inset-x-4 top-0 h-px bg-gradient-to-r from-transparent via-gray-300/80 to-transparent opacity-60 dark:via-white/15" aria-hidden />

                  <div className="relative flex items-start justify-between gap-3">
                    <div
                      className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br shadow-inner shadow-white/10 ring-1 ring-black/[0.03] dark:ring-white/[0.06] ${iconWrap}`}
                    >
                      <Icon className="h-6 w-6" strokeWidth={1.75} aria-hidden />
                    </div>
                    <span className="font-mono text-[0.65rem] font-semibold tabular-nums tracking-widest text-gray-600 dark:text-gray-500">
                      {step}
                    </span>
                  </div>
                  <h3 className="relative mt-5 font-heading text-lg font-semibold tracking-[-0.015em] text-gray-900 dark:text-white">
                    {title}
                  </h3>
                  <p className="relative mt-2 font-body text-sm leading-relaxed text-gray-600 dark:text-gray-400">{body}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section
        id="agents"
        className="relative scroll-mt-20 overflow-hidden bg-gradient-to-b from-gray-100/85 via-gray-50/35 to-transparent py-16 dark:from-[#0a0a0c] dark:via-gray-950/85 dark:to-transparent lg:py-24"
      >
        <div
          className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-gray-300/60 to-transparent dark:via-white/[0.08]"
          aria-hidden
        />
        <div
          className="pointer-events-none absolute -right-24 top-24 h-80 w-80 rounded-full bg-primary-500/10 blur-3xl animate-landing-mesh dark:bg-primary-500/18"
          aria-hidden
        />
        <div
          className="pointer-events-none absolute -left-32 bottom-1/4 h-72 w-72 rounded-full bg-amber-400/10 blur-3xl animate-landing-pulse-ring dark:bg-amber-500/14"
          aria-hidden
        />
        <div
          className="pointer-events-none absolute left-1/2 top-32 h-64 w-[min(90vw,42rem)] -translate-x-1/2 rounded-full bg-blue-500/5 blur-[80px] dark:bg-blue-500/12"
          aria-hidden
        />

        <svg
          className="pointer-events-none absolute left-1/2 top-[4.5rem] w-[min(96vw,52rem)] -translate-x-1/2 text-primary-600/25 dark:text-primary-400/35"
          viewBox="0 0 900 100"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          aria-hidden
        >
          <path
            d="M32 58 C 120 28, 200 72, 290 48 S 460 78, 560 42 S 720 68, 868 52"
            stroke="currentColor"
            strokeWidth="1"
            strokeLinecap="round"
            strokeDasharray="7 11"
            className="catalog-topology-line"
          />
          <circle cx="32" cy="58" r="4" fill="currentColor" opacity="0.5" />
          <circle cx="290" cy="48" r="3.5" fill="currentColor" opacity="0.45" />
          <circle cx="560" cy="42" r="3.5" fill="currentColor" opacity="0.45" />
          <circle cx="868" cy="52" r="4" fill="currentColor" opacity="0.5" />
        </svg>

        <div className="relative z-[1] mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="catalog-agentic-shell shadow-[0_20px_64px_-24px_rgba(15,23,42,0.18)] dark:shadow-[0_24px_72px_-24px_rgba(0,0,0,0.55)]">
            <div className="relative overflow-hidden rounded-[1.5rem] border border-gray-200/60 bg-white/85 p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.7)] backdrop-blur-2xl dark:border-white/[0.06] dark:bg-gray-950/60 dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] sm:p-5 lg:p-6">
              <div
                className="pointer-events-none absolute inset-x-4 top-0 h-px overflow-hidden rounded-full sm:inset-x-6"
                aria-hidden
              >
                <div className="h-full w-full bg-gradient-to-r from-transparent via-gray-300/80 to-transparent dark:via-white/12" />
                <div className="absolute inset-y-0 left-0 w-24 bg-gradient-to-r from-primary-500/90 via-primary-400/50 to-transparent animate-catalog-signal-x" />
              </div>

              <div className="mb-3 flex flex-col gap-1.5 border-b border-gray-200/60 pb-3 dark:border-white/[0.06] sm:flex-row sm:items-center sm:justify-between sm:gap-3">
                <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 font-mono text-[0.6rem] text-gray-500 dark:text-gray-400 sm:text-[0.62rem]">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-primary-500/20 bg-primary-500/[0.08] text-primary-600 dark:border-primary-400/25 dark:bg-primary-500/10 dark:text-primary-400">
                    <Activity className="h-3 w-3" strokeWidth={2.25} aria-hidden />
                  </span>
                  <span className="font-semibold tracking-wide text-gray-700 dark:text-gray-200">Indexer</span>
                  <span className="text-gray-600 dark:text-gray-500">·</span>
                  {isLoading ? (
                    <span className="text-amber-600 dark:text-amber-400/90">syncing</span>
                  ) : error ? (
                    <span className="text-red-600 dark:text-red-400">degraded</span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
                      <span className="relative flex h-1.5 w-1.5">
                        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400/45 opacity-75" />
                        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400" />
                      </span>
                      online
                    </span>
                  )}
                  {!isLoading && !error ? (
                    <>
                      <span className="hidden text-gray-600 sm:inline dark:text-gray-600">·</span>
                      <span className="tabular-nums text-gray-600 dark:text-gray-300">
                        <span className="text-gray-800 dark:text-gray-200">{agents.length}</span> indexed
                      </span>
                    </>
                  ) : null}
                </div>
                {!isLoading && !error ? (
                  <div className="hidden font-mono text-[0.6rem] text-gray-500 md:block dark:text-gray-500">
                    Category &amp; search routing
                  </div>
                ) : null}
              </div>

              <div className="flex flex-col gap-4 sm:gap-5 lg:flex-row lg:items-end lg:justify-between lg:gap-8">
                <div className="min-w-0 lg:flex-1">
                  <div className="mb-2 inline-flex items-center gap-1.5 rounded-full border border-primary-500/25 bg-primary-500/[0.07] px-2.5 py-0.5 dark:border-primary-400/30 dark:bg-primary-500/10">
                    <LayoutGrid className="h-3 w-3 text-primary-600 dark:text-primary-400" aria-hidden />
                    <span className="font-body text-[0.6rem] font-bold uppercase tracking-[0.16em] text-primary-700 dark:text-primary-300">
                      Catalog
                    </span>
                  </div>
                  <h2 className="font-heading text-xl font-bold tracking-[-0.02em] text-gray-900 dark:text-white sm:text-2xl lg:text-[1.625rem] lg:leading-snug">
                    Agents for every workflow
                  </h2>
                  <p className="mt-1.5 max-w-xl font-body text-xs leading-relaxed text-gray-600 dark:text-gray-400 sm:text-[0.8125rem]">
                    Filter by category, then search by name, id, type, tools, or capability text.
                  </p>
                </div>

                <div className="w-full shrink-0 lg:max-w-sm">
                  <label htmlFor="catalog-search" className="sr-only">
                    Search agents
                  </label>
                  <div className="group relative">
                    <Search
                      className="pointer-events-none absolute left-3 top-1/2 z-[1] h-4 w-4 -translate-y-1/2 text-gray-600 dark:text-gray-400 transition-colors group-focus-within:text-primary-500 dark:group-focus-within:text-primary-400"
                      aria-hidden
                    />
                    <input
                      id="catalog-search"
                      type="search"
                      placeholder="Search agents…"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') e.preventDefault();
                      }}
                      className="w-full rounded-xl border border-gray-200/80 bg-white py-2.5 pl-10 pr-10 font-body text-sm text-gray-900 shadow-[0_1px_2px_rgba(15,23,42,0.04)] transition-all placeholder:text-gray-400 focus:border-primary-500/75 focus:shadow-[0_0_0_3px_rgba(216,86,4,0.09),0_1px_2px_rgba(15,23,42,0.04)] focus:ring-0 focus:outline-none dark:border-white/[0.1] dark:bg-gray-950/65 dark:text-white dark:placeholder:text-gray-500 dark:focus:border-primary-500/65 dark:focus:shadow-[0_0_0_3px_rgba(232,141,20,0.08)]"
                      autoComplete="off"
                      autoCorrect="off"
                      autoCapitalize="off"
                      spellCheck={false}
                    />
                    {searchQuery ? (
                      <button
                        type="button"
                        onClick={() => setSearchQuery('')}
                        className="absolute right-1.5 top-1/2 z-[1] flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-md text-gray-500 transition-colors hover:bg-gray-200/80 hover:text-gray-800 dark:hover:bg-gray-800 dark:hover:text-gray-200"
                        aria-label="Clear search"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    ) : null}
                  </div>
                </div>
              </div>

              {categories.length > 0 && (
                <>
                  <div
                    className="my-4 h-px bg-gradient-to-r from-transparent via-gray-200/90 to-transparent dark:via-white/[0.08] sm:my-5"
                    aria-hidden
                  />
                  <div>
                    <p className="mb-2 font-body text-[0.6rem] font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                      Category
                    </p>
                    <div className="relative -mx-1">
                      <div
                        className="pointer-events-none absolute inset-y-0 left-0 z-10 w-8 bg-gradient-to-r from-white to-transparent dark:from-gray-950/95 sm:hidden"
                        aria-hidden
                      />
                      <div
                        className="pointer-events-none absolute inset-y-0 right-0 z-10 w-8 bg-gradient-to-l from-white to-transparent dark:from-gray-950/95 sm:hidden"
                        aria-hidden
                      />
                      <div className="flex gap-1.5 overflow-x-auto pb-0.5 [scrollbar-width:none] [-ms-overflow-style:none] sm:flex-wrap sm:overflow-visible sm:pb-0 [&::-webkit-scrollbar]:hidden">
                        <button
                          type="button"
                          onClick={() => setSelectedCategory('all')}
                          className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 font-body text-xs font-semibold transition-all duration-200 active:scale-[0.98] sm:text-[0.8125rem] ${
                            selectedCategory === 'all'
                              ? 'bg-white dark:bg-gray-900 text-gray-900 dark:text-white shadow-sm shadow-gray-900/15 ring-1 ring-white/10 dark:bg-white dark:text-gray-900 dark:shadow-none dark:ring-black/5'
                              : 'border border-gray-200/80 bg-white text-gray-600 hover:border-gray-300 hover:bg-gray-50 dark:border-white/[0.1] dark:bg-transparent dark:text-gray-400 dark:hover:border-white/20 dark:hover:bg-white/[0.04]'
                          }`}
                        >
                          All
                        </button>
                        {sortedCategories.map((category) => (
                          <button
                            type="button"
                            key={category.id}
                            onClick={() => setSelectedCategory(category.id)}
                            className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 font-body text-xs font-semibold transition-all duration-200 active:scale-[0.98] sm:text-[0.8125rem] ${
                              selectedCategory === category.id
                                ? 'bg-gradient-to-r from-primary-600 to-primary-500 text-gray-900 dark:text-white shadow-sm shadow-primary-600/20 ring-1 ring-white/15'
                                : 'border border-gray-200/80 bg-white text-gray-600 hover:border-primary-200 hover:bg-primary-50/50 dark:border-white/[0.1] dark:bg-transparent dark:text-gray-400 dark:hover:border-primary-500/35 dark:hover:bg-primary-500/10'
                            }`}
                          >
                            <span className="opacity-90 [&_svg]:h-3 [&_svg]:w-3">
                              {categoryIcons[category.icon] || <Bot className="h-3.5 w-3.5" />}
                            </span>
                            {category.name}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>

          {!isLoading && !error ? (
            <div className="mt-5 flex flex-col gap-2 sm:mt-6 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-3">
                <p className="font-body text-sm text-gray-600 dark:text-gray-400">
                  <span className="font-semibold tabular-nums text-gray-900 dark:text-white">
                    {filteredAgents.length}
                  </span>
                  <span className="mx-1.5 text-gray-600 dark:text-gray-500">·</span>
                  {filteredAgents.length === 1 ? 'agent' : 'agents'}
                  {activeCategoryName ? (
                    <>
                      <span className="mx-1.5 text-gray-600 dark:text-gray-500">·</span>
                      <span className="text-gray-500 dark:text-gray-400">{activeCategoryName}</span>
                    </>
                  ) : null}
                </p>
                {communityAgents.length > 0 && (
                  <div className="flex gap-1 rounded-full border border-gray-200 dark:border-white/[0.08] bg-gray-50 dark:bg-white/[0.02] p-0.5">
                    {(['all', 'official', 'community'] as const).map((f) => (
                      <button
                        key={f}
                        onClick={() => setAgentFilter(f)}
                        className={`px-2.5 py-1 rounded-full text-xs font-medium transition-all ${
                          agentFilter === f
                            ? 'bg-violet-500/15 text-violet-400 ring-1 ring-violet-500/20'
                            : 'text-gray-500 hover:text-gray-300'
                        }`}
                      >
                        {f === 'all' ? 'All' : f === 'official' ? 'Official' : `Community (${communityAgents.length})`}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              {(searchQuery || selectedCategory !== 'all') && filteredAgents.length > 0 ? (
                <button
                  type="button"
                  onClick={() => {
                    setSearchQuery('');
                    setSelectedCategory('all');
                  }}
                  className="self-start rounded-full border border-gray-200/90 bg-white px-4 py-2 font-body text-xs font-semibold text-gray-700 shadow-sm transition-all hover:border-primary-300 hover:text-primary-700 dark:border-white/[0.1] dark:bg-gray-950/50 dark:text-gray-300 dark:hover:border-primary-500/50 dark:hover:text-primary-400 sm:self-auto"
                >
                  Reset filters
                </button>
              ) : null}
            </div>
          ) : null}

          {isLoading ? (
            <div className="catalog-skeleton-grid mt-5 grid grid-cols-1 gap-5 sm:mt-6 md:grid-cols-2 md:gap-6 lg:grid-cols-3 xl:grid-cols-4">
              {[1, 2, 3, 4, 5, 6].map((i) => (
                <div
                  key={i}
                  className="flex h-[310px] flex-col rounded-2xl border border-gray-200/90 bg-white/85 p-5 shadow-sm dark:border-gray-800/90 dark:bg-gray-900/65"
                >
                  <div className="mb-4 flex items-start gap-3">
                    <div className="h-10 w-10 shrink-0 rounded-lg bg-gray-200 dark:bg-gray-800" />
                    <div className="min-w-0 flex-1 space-y-2 pt-0.5">
                      <div className="h-4 w-3/4 rounded-md bg-gray-200 dark:bg-gray-800" />
                      <div className="h-3 w-1/3 rounded-md bg-gray-100 dark:bg-gray-800/80" />
                    </div>
                  </div>
                  <div className="mb-4 space-y-2">
                    <div className="h-3 w-full rounded bg-gray-100 dark:bg-gray-800/80" />
                    <div className="h-3 w-5/6 rounded bg-gray-100 dark:bg-gray-800/80" />
                  </div>
                  <div className="mb-4 space-y-2">
                    <div className="h-1.5 w-full rounded-full bg-gray-100 dark:bg-gray-800" />
                  </div>
                  <div className="mb-4 flex gap-2">
                    <div className="h-6 w-14 rounded-full bg-gray-100 dark:bg-gray-800" />
                    <div className="h-6 w-16 rounded-full bg-gray-100 dark:bg-gray-800" />
                  </div>
                  <div className="mt-auto h-10 w-full rounded-xl bg-gray-200 dark:bg-gray-800" />
                </div>
              ))}
            </div>
          ) : error ? (
            <div className="mt-5 text-center sm:mt-6 py-16">
              <div className="inline-flex items-center justify-center w-16 h-16 bg-red-100 dark:bg-red-900/20 rounded-xl mb-4">
                <Sparkles className="w-8 h-8 text-red-600 dark:text-red-400" />
              </div>
              <p className="font-body text-red-600 dark:text-red-400 font-medium mb-4">{error}</p>
              <button onClick={() => window.location.reload()} className="btn-primary">
                Retry
              </button>
            </div>
          ) : filteredAgents.length === 0 ? (
            <div className="mt-5 rounded-2xl border border-dashed border-gray-300/90 bg-gray-50/50 py-14 text-center dark:border-gray-700 dark:bg-gray-900/30 sm:mt-6 sm:py-16">
              <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-white shadow-sm ring-1 ring-gray-200 dark:bg-gray-900 dark:ring-gray-800">
                <Search className="h-7 w-7 text-gray-600 dark:text-gray-400" />
              </div>
              <p className="font-body font-medium text-gray-700 dark:text-gray-300">
                No agents match
                {searchQuery ? (
                  <>
                    {' '}
                    “<span className="text-primary-600 dark:text-primary-400">{searchQuery}</span>”
                  </>
                ) : (
                  ' these filters'
                )}
              </p>
              <button
                type="button"
                onClick={() => {
                  setSearchQuery('');
                  setSelectedCategory('all');
                }}
                className="btn-primary mt-6 py-2.5 px-6 text-sm"
              >
                Clear filters
              </button>
            </div>
          ) : (
            <div
              key={filteredAgents.map((a) => a.id).join('|')}
              className="catalog-agent-grid mt-5 grid grid-cols-1 gap-5 sm:mt-6 md:grid-cols-2 md:gap-6 lg:grid-cols-3 xl:grid-cols-4"
            >
              {filteredAgents.map((agent) => (
                <AgentCard key={agent.id} agent={agent} />
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="relative overflow-hidden border-t border-gray-200 dark:border-white/[0.06] bg-white dark:bg-gray-950 py-20 lg:py-28 bg-grain">
        <div className="pointer-events-none absolute inset-0" aria-hidden>
          <div className="absolute left-[15%] top-1/3 h-80 w-80 -translate-y-1/2 rounded-full bg-primary-600/12 blur-[100px]" />
          <div className="absolute bottom-0 right-[10%] h-[28rem] w-[28rem] rounded-full bg-accent-pink/8 blur-[120px]" />
        </div>

        <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="grid items-center gap-12 lg:grid-cols-12 lg:gap-16">
            <div className="lg:col-span-5">
              <p className="mb-2 font-body text-[0.65rem] font-bold uppercase tracking-[0.2em] text-primary-400">
                Platform
              </p>
              <h2 className="font-heading text-3xl font-bold tracking-[-0.02em] text-gray-900 dark:text-white sm:text-4xl lg:text-[2.5rem] lg:leading-tight">
                Built for serious automation
              </h2>
              <p className="mt-4 max-w-lg font-body text-sm leading-relaxed text-gray-600 dark:text-gray-400 sm:text-base">
                Enterprise workflows, guardrails, and integrations—so teams get reliable outcomes instead of fragile demos.
              </p>
              <div className="mt-8 flex flex-wrap gap-2">
                {[
                  { label: 'Agents live', value: String(agents.length), accent: 'from-primary-500/20 to-primary-600/5 border-primary-500/25 text-primary-300' },
                  { label: 'Tooling', value: '50+', accent: 'from-emerald-500/20 to-emerald-600/5 border-emerald-500/20 text-emerald-300' },
                  { label: 'Categories', value: String(categories.length), accent: 'from-blue-500/20 to-blue-600/5 border-blue-500/25 text-blue-300' },
                  { label: 'Avg. autonomy', value: '82%', accent: 'from-amber-500/20 to-amber-600/5 border-amber-500/25 text-amber-300' },
                ].map((chip) => (
                  <div
                    key={chip.label}
                    className={`rounded-2xl border bg-gradient-to-br px-4 py-3 backdrop-blur-sm ${chip.accent}`}
                  >
                    <div className="font-heading text-xl font-bold tabular-nums text-gray-900 dark:text-white">{chip.value}</div>
                    <div className="mt-0.5 font-body text-[0.6rem] font-semibold uppercase tracking-wider text-gray-500">
                      {chip.label}
                    </div>
                  </div>
                ))}
              </div>
            </div>
            <div className="lg:col-span-7">
              <div className="relative">
                <div
                  className="absolute -inset-1 rounded-[1.35rem] bg-gradient-to-br from-primary-500/30 via-accent-pink/15 to-amber-400/20 blur-xl animate-landing-pulse-ring"
                  aria-hidden
                />
                <div className="relative overflow-hidden rounded-[1.25rem] ring-1 ring-white/10">
                  <div className="relative aspect-[16/10] w-full overflow-hidden sm:aspect-[16/9]">
                    <img
                      src="/images/ai-infographic.png"
                      alt="AI neural network visualization"
                      className="animate-landing-infographic h-full w-full scale-110 object-cover object-center"
                    />
                  </div>
                  <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-gray-950/50 via-transparent to-gray-950/20" aria-hidden />
                  <div className="pointer-events-none absolute inset-0 overflow-hidden rounded-[inherit]" aria-hidden>
                    <div
                      className="absolute inset-x-0 -top-1/4 h-24 bg-gradient-to-b from-transparent via-primary-400/12 to-transparent animate-landing-scan"
                      style={{ animationDelay: '2.5s' }}
                      aria-hidden
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="mt-16 grid gap-4 sm:grid-cols-2 lg:mt-20 lg:grid-cols-3 lg:gap-5">
            {[
              {
                icon: MessageSquare,
                title: 'Natural language',
                body: 'Chat-based interactions with every agent—consistent UX across the catalog.',
                ring: 'hover:border-primary-500/30',
                iconBg: 'bg-primary-500/15 text-primary-300',
              },
              {
                icon: Shield,
                title: 'Enterprise ready',
                body: 'Security, scale, and compliance patterns designed for real deployments.',
                ring: 'hover:border-emerald-500/30',
                iconBg: 'bg-emerald-500/15 text-emerald-300',
              },
              {
                icon: Code,
                title: 'API access',
                body: 'Wire agents into your own workflows with clear integration surfaces.',
                ring: 'hover:border-blue-500/30',
                iconBg: 'bg-blue-500/15 text-blue-300',
              },
            ].map(({ icon: Icon, title, body, ring, iconBg }) => (
              <div
                key={title}
                className={`group flex flex-col gap-4 rounded-3xl border border-white/[0.07] bg-white/[0.025] p-6 shadow-[0_2px_24px_-12px_rgba(0,0,0,0.35)] backdrop-blur-xl transition-all duration-300 hover:bg-white/[0.04] ${ring}`}
              >
                <div className={`flex h-12 w-12 items-center justify-center rounded-xl ${iconBg}`}>
                  <Icon className="h-6 w-6" strokeWidth={2} />
                </div>
                <div>
                  <div className="font-heading text-lg font-bold text-gray-900 dark:text-white">{title}</div>
                  <p className="mt-2 font-body text-sm leading-relaxed text-gray-600 dark:text-gray-400">{body}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
