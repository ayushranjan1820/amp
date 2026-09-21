import { useState } from 'react';
import { Wand2, Copy, CheckCircle } from 'lucide-react';
import type { CustomAgent } from '../../services/agentBuilder';

const TEMPLATES = [
  {
    name: 'Customer Support',
    prompt: `You are a helpful customer support agent. Your role is to:
- Assist customers with their inquiries professionally and empathetically
- Provide accurate information about products and services
- Escalate complex issues when needed
- Always maintain a friendly, patient tone

When you don't know an answer, be honest and offer to find out or escalate to a human agent.`,
  },
  {
    name: 'Data Analyst',
    prompt: `You are an expert data analyst AI assistant. Your role is to:
- Help users analyze and interpret data
- Generate SQL queries, Python code, or statistical analyses
- Create clear explanations of data patterns and insights
- Suggest data visualizations and reporting approaches

Always validate data assumptions and explain your methodology clearly.`,
  },
  {
    name: 'Code Reviewer',
    prompt: `You are a senior software engineer conducting code reviews. Your role is to:
- Review code for bugs, security issues, and performance problems
- Suggest improvements following best practices and design patterns
- Explain the reasoning behind your suggestions
- Be constructive and educational in your feedback

Focus on correctness first, then readability, then performance.`,
  },
  {
    name: 'Research Assistant',
    prompt: `You are a thorough research assistant. Your role is to:
- Search for and synthesize information from multiple sources
- Provide well-structured, factual summaries
- Cite sources and note confidence levels
- Ask clarifying questions when the research scope is ambiguous

Always distinguish between established facts and your analysis/interpretation.`,
  },
  {
    name: 'Writing Assistant',
    prompt: `You are a skilled writing assistant. Your role is to:
- Help draft, edit, and improve written content
- Adapt tone and style to the target audience
- Provide grammar, clarity, and structure suggestions
- Offer creative alternatives and improvements

Maintain the author's voice while enhancing clarity and impact.`,
  },
];

interface Props {
  agent: Partial<CustomAgent>;
  updateField: <K extends keyof CustomAgent>(key: K, value: CustomAgent[K]) => void;
}

export default function PromptEditor({ agent, updateField }: Props) {
  const [showTemplates, setShowTemplates] = useState(false);
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(agent.system_prompt || '');
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const charCount = (agent.system_prompt || '').length;

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-1">System Prompt</h2>
          <p className="text-sm text-gray-500">
            Define your agent's personality, behavior, and capabilities.
          </p>
        </div>
        <button
          onClick={() => setShowTemplates(!showTemplates)}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-violet-500/10 text-violet-400 text-sm font-medium hover:bg-violet-500/20 transition-colors"
        >
          <Wand2 className="w-3.5 h-3.5" /> Templates
        </button>
      </div>

      {showTemplates && (
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 animate-fadeIn">
          {TEMPLATES.map((t) => (
            <button
              key={t.name}
              onClick={() => {
                updateField('system_prompt', t.prompt);
                setShowTemplates(false);
              }}
              className="text-left p-3 rounded-xl border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-white/[0.02] hover:border-violet-500/30 hover:bg-violet-500/5 transition-all"
            >
              <span className="text-sm font-medium text-gray-900 dark:text-white">{t.name}</span>
              <p className="text-xs text-gray-500 mt-1 line-clamp-2">{t.prompt.slice(0, 80)}...</p>
            </button>
          ))}
        </div>
      )}

      <div className="relative">
        <textarea
          value={agent.system_prompt || ''}
          onChange={(e) => updateField('system_prompt', e.target.value)}
          rows={16}
          placeholder="You are a helpful AI assistant that..."
          className="w-full px-4 py-3 rounded-xl bg-gray-100 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-violet-500/40 font-mono text-sm leading-relaxed resize-y transition-colors"
        />
        <div className="absolute bottom-3 right-3 flex items-center gap-2">
          <span className="text-xs text-gray-400 dark:text-gray-600">{charCount} chars</span>
          <button onClick={handleCopy} className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-white/[0.06] text-gray-500 hover:text-gray-700 dark:text-gray-300 transition-colors">
            {copied ? <CheckCircle className="w-4 h-4 text-green-400" /> : <Copy className="w-4 h-4" />}
          </button>
        </div>
      </div>

      <div className="rounded-xl bg-amber-500/5 border border-amber-500/10 p-4">
        <p className="text-sm text-amber-400/80">
          <strong>Tip:</strong> A good system prompt should define the agent's role, scope, tone,
          and any constraints. Be specific about what the agent should and should not do.
        </p>
      </div>
    </div>
  );
}
