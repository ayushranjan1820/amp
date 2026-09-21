import { useState, useRef, useEffect, useCallback } from 'react';
import {
  Send, Loader2, AlertCircle, Save, Bot, User,
  Wrench, ChevronDown, ChevronRight, RotateCcw, Zap, CheckCircle, Square,
} from 'lucide-react';
import { testAgentStream, clearTestSession, type CustomAgent } from '../../services/agentBuilder';

// ─── Types ────────────────────────────────────────────────────────────────────

interface ThinkingStep {
  type: 'thinking' | 'tool_call' | 'tool_result' | 'info';
  content: string;
  tool_name?: string;
  tool_input?: string;
}

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  thinking?: ThinkingStep[];
  isStreaming?: boolean;
}

// ─── ThinkingBlock — collapsible thinking/tool trace ─────────────────────────

function ThinkingBlock({ steps }: { steps: ThinkingStep[] }) {
  const [open, setOpen] = useState(false);
  const toolSteps = steps.filter(s => s.type === 'tool_call' || s.type === 'tool_result');
  const hasTools = toolSteps.length > 0;

  if (steps.length === 0) return null;

  return (
    <div className="mt-2 rounded-lg border border-gray-200 dark:border-white/[0.06] overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-3 py-2 bg-gray-50 dark:bg-white/[0.03] hover:bg-gray-100 dark:hover:bg-white/[0.05] transition-colors text-left"
      >
        {hasTools ? (
          <Wrench className="w-3.5 h-3.5 text-violet-400 flex-shrink-0" />
        ) : (
          <Zap className="w-3.5 h-3.5 text-gray-500 flex-shrink-0" />
        )}
        <span className="text-xs text-gray-600 dark:text-gray-400 flex-1">
          {hasTools
            ? `Used ${toolSteps.filter(s => s.type === 'tool_call').length} tool${toolSteps.filter(s => s.type === 'tool_call').length > 1 ? 's' : ''}`
            : 'Agent reasoning'}
        </span>
        {open
          ? <ChevronDown className="w-3.5 h-3.5 text-gray-400 dark:text-gray-600" />
          : <ChevronRight className="w-3.5 h-3.5 text-gray-400 dark:text-gray-600" />}
      </button>

      {open && (
        <div className="px-3 py-2 space-y-2 border-t border-gray-200 dark:border-white/[0.06] max-h-64 overflow-y-auto">
          {steps.map((step, i) => (
            <div key={i} className={`text-[11px] leading-relaxed ${
              step.type === 'tool_call'    ? 'text-violet-300'
              : step.type === 'tool_result' ? 'text-emerald-300'
              : 'text-gray-500'
            }`}>
              {step.type === 'tool_call' && (
                <div>
                  <span className="font-semibold text-violet-400">▶ {step.tool_name}</span>
                  {step.tool_input && (
                    <pre className="mt-1 font-mono text-[10px] text-violet-300/70 whitespace-pre-wrap break-all">
                      {step.tool_input.slice(0, 400)}
                    </pre>
                  )}
                </div>
              )}
              {step.type === 'tool_result' && (
                <div>
                  <span className="font-semibold text-emerald-400">◀ {step.tool_name} result</span>
                  <pre className="mt-1 font-mono text-[10px] text-emerald-300/70 whitespace-pre-wrap break-all">
                    {step.content.slice(0, 600)}
                    {step.content.length > 600 ? '\n… (truncated)' : ''}
                  </pre>
                </div>
              )}
              {(step.type === 'thinking' || step.type === 'info') && (
                <span className="italic">{step.content}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Props ────────────────────────────────────────────────────────────────────

interface Props {
  agentId: string | null;
  agent: Partial<CustomAgent>;
  onSave: () => Promise<void>;
}

// ─── Main component ──────────────────────────────────────────────────────────

export default function TestPlayground({ agentId, agent, onSave }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState('');
  const [needsSave, setNeedsSave] = useState(!agentId);
  const [sessionId] = useState(() => `test_${Date.now()}_${Math.random().toString(36).slice(2)}`);
  const [turnCount, setTurnCount] = useState(0);
  const chatRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Abort any in-flight stream when the component unmounts
  useEffect(() => () => abortRef.current?.abort(), []);

  // Auto-scroll on new content
  useEffect(() => {
    if (chatRef.current) {
      chatRef.current.scrollTop = chatRef.current.scrollHeight;
    }
  }, [messages]);

  const handleSaveFirst = async () => {
    setNeedsSave(false);
    await onSave();
  };

  const handleNewChat = useCallback(async () => {
    abortRef.current?.abort();
    if (agentId) {
      try { await clearTestSession(agentId, sessionId); } catch {
        // Best-effort: server may have already cleaned up
      }
    }
    setMessages([]);
    setError('');
    setTurnCount(0);
    inputRef.current?.focus();
  }, [agentId, sessionId]);

  const handleStop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  const handleSend = async () => {
    if (!input.trim() || streaming) return;
    if (!agentId) {
      setError('Save your agent first before testing.');
      setNeedsSave(true);
      return;
    }

    const userText = input.trim();
    setInput('');
    setError('');

    // Add user message
    setMessages(prev => [...prev, { role: 'user', content: userText }]);
    // Add empty assistant placeholder
    setMessages(prev => [...prev, { role: 'assistant', content: '', thinking: [], isStreaming: true }]);
    setStreaming(true);

    let assistantContent = '';
    const thinkingSteps: ThinkingStep[] = [];

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await testAgentStream(agentId, userText, sessionId, (evt) => {
        const data = evt.data as any;

        if (evt.event === 'thinking') {
          thinkingSteps.push({
            type: data?.type || 'thinking',
            content: data?.content || '',
            tool_name: data?.tool_name,
            tool_input: data?.tool_input,
          });
          // Update the last assistant message's thinking steps in real time
          setMessages(prev => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last?.role === 'assistant') {
              updated[updated.length - 1] = { ...last, thinking: [...thinkingSteps] };
            }
            return updated;
          });

        } else if (evt.event === 'response_chunk') {
          const chunk = data?.chunk || '';
          assistantContent += chunk;
          setMessages(prev => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last?.role === 'assistant') {
              updated[updated.length - 1] = { ...last, content: assistantContent };
            }
            return updated;
          });

        } else if (evt.event === 'done') {
          // Finalise — use streamed content if available, fall back to done payload
          const finalResponse = assistantContent || data?.response || '';
          const turn = data?.turn ?? turnCount + 1;
          setTurnCount(turn);
          setMessages(prev => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last?.role === 'assistant') {
              updated[updated.length - 1] = {
                ...last,
                content: finalResponse,
                thinking: [...thinkingSteps],
                isStreaming: false,
              };
            }
            return updated;
          });

        } else if (evt.event === 'error') {
          setError(data?.message || 'Something went wrong');
          setMessages(prev => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last?.role === 'assistant' && !last.content) {
              updated.pop(); // remove empty placeholder
            }
            return updated;
          });
        }
      }, controller.signal);
    } catch (e: any) {
      // AbortError is expected when the user clicks Stop — don't treat as failure
      if (e?.name !== 'AbortError') {
        setError(e.message);
      }
      setMessages(prev => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last?.role === 'assistant' && !last.content) updated.pop();
        return updated;
      });
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      setStreaming(false);
      // Mark last message as done streaming
      setMessages(prev => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last?.role === 'assistant') {
          updated[updated.length - 1] = { ...last, isStreaming: false };
        }
        return updated;
      });
      inputRef.current?.focus();
    }
  };

  // ─── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-1">Test Playground</h2>
          <p className="text-sm text-gray-500">
            Chat with your agent in real-time. Full conversation context is preserved across messages.
          </p>
        </div>
        {messages.length > 0 && (
          <button
            onClick={handleNewChat}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-200 dark:border-white/[0.08] text-xs font-medium text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:border-gray-300 dark:hover:border-white/[0.15] transition-colors"
          >
            <RotateCcw className="w-3.5 h-3.5" /> New Chat
          </button>
        )}
      </div>

      {/* Save prompt */}
      {needsSave && !agentId && (
        <div className="rounded-xl bg-amber-500/5 border border-amber-500/10 p-4 flex items-center justify-between">
          <p className="text-sm text-amber-400">Save your agent first to enable testing.</p>
          <button
            onClick={handleSaveFirst}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-500/10 text-amber-400 text-sm font-medium hover:bg-amber-500/20 transition-colors"
          >
            <Save className="w-3.5 h-3.5" /> Save Now
          </button>
        </div>
      )}

      {/* Context counter */}
      {turnCount > 0 && (
        <div className="flex items-center gap-2 text-xs text-gray-400 dark:text-gray-600">
          <CheckCircle className="w-3.5 h-3.5 text-green-500" />
          {turnCount} turn{turnCount > 1 ? 's' : ''} in context — agent remembers the full conversation
        </div>
      )}

      {/* Chat window */}
      <div className="rounded-xl border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-black/20 flex flex-col" style={{ height: '500px' }}>
        {/* Messages */}
        <div ref={chatRef} className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-center space-y-4">
              <div className="w-14 h-14 rounded-2xl bg-violet-500/10 flex items-center justify-center">
                <Bot className="w-7 h-7 text-violet-400" />
              </div>
              <div>
                <p className="text-gray-600 dark:text-gray-400 text-sm font-medium">
                  {agent.name || 'Your Agent'} is ready
                </p>
                <p className="text-gray-400 dark:text-gray-600 text-xs mt-1">
                  {(agent.tools_config || []).length > 0
                    ? `${(agent.tools_config || []).length} tool${(agent.tools_config || []).length > 1 ? 's' : ''} available`
                    : 'No tools configured'}
                  {' · '}conversation context is preserved
                </p>
              </div>
              {(agent.example_prompts || []).filter(Boolean).length > 0 && (
                <div className="flex flex-wrap gap-2 justify-center max-w-md">
                  {(agent.example_prompts || []).filter(Boolean).map((p, i) => (
                    <button
                      key={i}
                      onClick={() => { setInput(p); inputRef.current?.focus(); }}
                      className="px-3 py-1.5 rounded-full bg-gray-100 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.06] text-xs text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:border-violet-500/30 transition-all"
                    >
                      {p}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {messages.map((msg, i) => (
            <div key={i} className={`flex gap-3 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              {msg.role === 'assistant' && (
                <div className="w-7 h-7 rounded-lg bg-violet-500/20 flex items-center justify-center flex-shrink-0 mt-0.5">
                  <Bot className="w-4 h-4 text-violet-400" />
                </div>
              )}

              <div className={`max-w-[82%] ${msg.role === 'user' ? '' : 'flex-1'}`}>
                {/* Bubble */}
                <div className={`px-4 py-2.5 rounded-2xl text-sm whitespace-pre-wrap break-words ${
                  msg.role === 'user'
                    ? 'bg-violet-600 text-gray-900 dark:text-white rounded-br-md'
                    : 'bg-gray-100 dark:bg-white/[0.04] text-gray-800 dark:text-gray-200 border border-gray-200 dark:border-white/[0.06] rounded-bl-md'
                }`}>
                  {msg.content || (msg.isStreaming ? (
                    <span className="inline-flex items-center gap-1.5 text-gray-500">
                      <Loader2 className="w-3 h-3 animate-spin" />
                      <span className="text-xs">Thinking…</span>
                    </span>
                  ) : null)}
                </div>

                {/* Thinking steps (assistant only) */}
                {msg.role === 'assistant' && (msg.thinking?.length ?? 0) > 0 && (
                  <ThinkingBlock steps={msg.thinking!} />
                )}
              </div>

              {msg.role === 'user' && (
                <div className="w-7 h-7 rounded-lg bg-gray-200 dark:bg-white/[0.08] flex items-center justify-center flex-shrink-0 mt-0.5">
                  <User className="w-4 h-4 text-gray-600 dark:text-gray-400" />
                </div>
              )}
            </div>
          ))}

          {/* Live tool activity during streaming */}
          {streaming && messages[messages.length - 1]?.role === 'assistant' && (
            (() => {
              const lastMsg = messages[messages.length - 1];
              const lastThinking = lastMsg?.thinking || [];
              const lastToolCall = [...lastThinking].reverse().find(s => s.type === 'tool_call');
              if (lastToolCall && !lastMsg.content) {
                return (
                  <div className="flex items-center gap-2 text-xs text-violet-400/70 pl-10">
                    <Loader2 className="w-3 h-3 animate-spin" />
                    Running {lastToolCall.tool_name}…
                  </div>
                );
              }
              return null;
            })()
          )}
        </div>

        {/* Error bar */}
        {error && (
          <div className="px-4 py-2 bg-red-500/5 border-t border-red-500/10 flex items-center gap-2">
            <AlertCircle className="w-3.5 h-3.5 text-red-400 flex-shrink-0" />
            <p className="text-xs text-red-400 flex-1">{error}</p>
            <button onClick={() => setError('')} className="text-xs text-gray-500 hover:text-gray-700 dark:text-gray-300">×</button>
          </div>
        )}

        {/* Input */}
        <div className="p-3 border-t border-gray-200 dark:border-white/[0.06]">
          <form onSubmit={(e) => { e.preventDefault(); handleSend(); }} className="flex gap-2">
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={streaming ? 'Agent is responding…' : 'Type a message…'}
              disabled={streaming || !agentId}
              className="flex-1 px-4 py-2.5 rounded-xl bg-gray-100 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-violet-500/40 text-sm disabled:opacity-50 transition-colors"
            />
            {streaming ? (
              <button
                type="button"
                onClick={handleStop}
                title="Stop generating"
                className="px-4 py-2.5 rounded-xl bg-red-600 hover:bg-red-700 text-gray-900 dark:text-white transition-colors"
              >
                <Square className="w-4 h-4" fill="currentColor" />
              </button>
            ) : (
              <button
                type="submit"
                disabled={!input.trim() || !agentId}
                className="px-4 py-2.5 rounded-xl bg-violet-600 hover:bg-violet-700 disabled:opacity-40 disabled:cursor-not-allowed text-gray-900 dark:text-white transition-colors"
              >
                <Send className="w-4 h-4" />
              </button>
            )}
          </form>
        </div>
      </div>
    </div>
  );
}
