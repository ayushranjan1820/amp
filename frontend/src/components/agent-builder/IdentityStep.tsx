import { useState } from 'react';
import { Bot, ChevronDown, ChevronUp } from 'lucide-react';
import type { CustomAgent } from '../../services/agentBuilder';

const CATEGORIES = [
  { id: 'assistant',        label: 'Assistant',               desc: 'General-purpose conversational agent' },
  { id: 'customer_support', label: 'Customer Support',        desc: 'Handle queries, tickets, and FAQs' },
  { id: 'research',         label: 'Research & Analysis',     desc: 'Web search, summarisation, insights' },
  { id: 'data_analyst',     label: 'Data Analyst',            desc: 'Query databases, analyse CSV/Excel' },
  { id: 'code',             label: 'Code & DevOps',           desc: 'Write, review, and execute code' },
  { id: 'content',          label: 'Content & Marketing',     desc: 'Generate copy, emails, presentations' },
  { id: 'automation',       label: 'Workflow Automation',     desc: 'Multi-step tasks and integrations' },
  { id: 'hr',               label: 'HR & People Ops',         desc: 'Onboarding, policies, recruiting' },
  { id: 'finance_ops',      label: 'Finance & Accounting',    desc: 'Reports, invoices, budget analysis' },
  { id: 'legal',            label: 'Legal & Compliance',      desc: 'Document review, policy checks' },
  { id: 'sales',            label: 'Sales & CRM',             desc: 'Lead research, pipeline management' },
  { id: 'devtools',         label: 'Developer Tools',         desc: 'JIRA, GitHub, CI/CD integrations' },
  { id: 'other',            label: 'Other',                   desc: 'Something that doesn\'t fit above' },
];

interface Props {
  agent: Partial<CustomAgent>;
  updateField: <K extends keyof CustomAgent>(key: K, value: CustomAgent[K]) => void;
}

export default function IdentityStep({ agent, updateField }: Props) {
  const [catOpen, setCatOpen] = useState(false);
  const selectedCat = CATEGORIES.find(c => c.id === (agent.category_id || 'assistant')) || CATEGORIES[0];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-1">Agent Identity</h2>
        <p className="text-sm text-gray-500">Define who your agent is and what it does.</p>
      </div>

      <div className="grid gap-5 sm:grid-cols-2">
        {/* Name */}
        <div className="sm:col-span-2">
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
            Name <span className="text-red-400">*</span>
          </label>
          <input
            type="text"
            value={agent.name || ''}
            onChange={(e) => updateField('name', e.target.value)}
            placeholder="e.g. Customer Support Bot"
            className="w-full px-4 py-2.5 rounded-xl bg-gray-100 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-violet-500/40 focus:border-violet-500/40 transition-colors"
          />
        </div>

        {/* Description */}
        <div className="sm:col-span-2">
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">Description</label>
          <textarea
            value={agent.description || ''}
            onChange={(e) => updateField('description', e.target.value)}
            rows={3}
            placeholder="Describe what your agent does, who it's for, and its key capabilities..."
            className="w-full px-4 py-2.5 rounded-xl bg-gray-100 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-violet-500/40 focus:border-violet-500/40 transition-colors resize-none"
          />
        </div>

        {/* Category */}
        <div className="sm:col-span-2">
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">Category</label>

          {/* Selected display / toggle */}
          <button
            type="button"
            onClick={() => setCatOpen(o => !o)}
            className="w-full flex items-center justify-between px-4 py-2.5 rounded-xl bg-gray-100 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] hover:border-gray-300 dark:hover:border-white/[0.14] text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500/40 transition-colors"
          >
            <span className="flex items-baseline gap-2">
              <span className="font-medium text-sm">{selectedCat.label}</span>
              <span className="text-xs text-gray-500">{selectedCat.desc}</span>
            </span>
            {catOpen
              ? <ChevronUp className="w-4 h-4 text-gray-500 flex-shrink-0" />
              : <ChevronDown className="w-4 h-4 text-gray-500 flex-shrink-0" />}
          </button>

          {/* Category grid */}
          {catOpen && (
            <div className="mt-2 grid grid-cols-2 sm:grid-cols-3 gap-1.5 p-3 rounded-xl border border-gray-200 dark:border-white/[0.08] bg-gray-50 dark:bg-white/[0.02]">
              {CATEGORIES.map((c) => {
                const isActive = (agent.category_id || 'assistant') === c.id;
                return (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => { updateField('category_id', c.id); setCatOpen(false); }}
                    className={`text-left px-3 py-2 rounded-lg transition-all ${
                      isActive
                        ? 'bg-violet-500/15 ring-1 ring-violet-500/30 text-violet-300'
                        : 'hover:bg-gray-100 dark:hover:bg-white/[0.05] text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white'
                    }`}
                  >
                    <span className="block text-xs font-semibold leading-tight">{c.label}</span>
                    <span className="block text-[10px] text-gray-500 mt-0.5 leading-tight">{c.desc}</span>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* Visibility */}
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">Visibility</label>
          <select
            value={agent.visibility || 'private'}
            onChange={(e) => updateField('visibility', e.target.value as CustomAgent['visibility'])}
            className="w-full px-4 py-2.5 rounded-xl bg-gray-100 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500/40 appearance-none"
          >
            <option value="private" className="bg-white dark:bg-zinc-900">Private — only you</option>
            <option value="unlisted" className="bg-white dark:bg-zinc-900">Unlisted — anyone with the link</option>
            <option value="public" className="bg-white dark:bg-zinc-900">Public — visible on marketplace</option>
          </select>
        </div>

        {/* Logo URL */}
        <div className="sm:col-span-2">
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">Logo URL</label>
          <div className="flex items-center gap-4">
            <div className="w-14 h-14 rounded-xl bg-gradient-to-br from-violet-500/20 to-indigo-500/20 border border-violet-500/20 flex items-center justify-center flex-shrink-0">
              {agent.logo_url ? (
                <img src={agent.logo_url} alt="" className="w-10 h-10 rounded-lg object-cover" />
              ) : (
                <Bot className="w-7 h-7 text-violet-400" />
              )}
            </div>
            <input
              type="url"
              value={agent.logo_url || ''}
              onChange={(e) => updateField('logo_url', e.target.value)}
              placeholder="https://example.com/logo.png"
              className="flex-1 px-4 py-2.5 rounded-xl bg-gray-100 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-violet-500/40 transition-colors"
            />
          </div>
        </div>

        {/* Example Prompts */}
        <div className="sm:col-span-2">
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
            Example Prompts <span className="text-gray-400 dark:text-gray-600 font-normal">— shown to users as conversation starters</span>
          </label>
          <div className="space-y-2">
            {(agent.example_prompts || ['']).map((prompt, i) => (
              <div key={i} className="flex gap-2">
                <input
                  type="text"
                  value={prompt}
                  onChange={(e) => {
                    const updated = [...(agent.example_prompts || [''])];
                    updated[i] = e.target.value;
                    updateField('example_prompts', updated);
                  }}
                  placeholder={`Example prompt ${i + 1}`}
                  className="flex-1 px-4 py-2 rounded-xl bg-gray-100 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-violet-500/40 text-sm transition-colors"
                />
                {(agent.example_prompts || []).length > 1 && (
                  <button
                    onClick={() => {
                      const updated = (agent.example_prompts || []).filter((_, j) => j !== i);
                      updateField('example_prompts', updated);
                    }}
                    className="p-2 rounded-lg hover:bg-red-500/10 text-gray-500 hover:text-red-400 transition-colors"
                  >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
                  </button>
                )}
              </div>
            ))}
            <button
              onClick={() => updateField('example_prompts', [...(agent.example_prompts || []), ''])}
              className="text-sm text-violet-400 hover:text-violet-300 transition-colors"
            >
              + Add prompt
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
