import React, { useState, useRef, useEffect } from 'react';
import { useParams, useLocation, useNavigate } from 'react-router-dom';
import { Spinner } from 'react-bootstrap';
import SendIcon from '@mui/icons-material/Send';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import QuestionAnswerIcon from '@mui/icons-material/QuestionAnswer';
import PersonIcon from '@mui/icons-material/Person';
import FlutterDashIcon from '@mui/icons-material/FlutterDash';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import PsychologyIcon from '@mui/icons-material/Psychology';
import BuildIcon from '@mui/icons-material/Build';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import CheckCircleOutlinedIcon from '@mui/icons-material/CheckCircleOutlined';
import { Navbar } from '../components/layout/Navbar';
import { post, get, extractErrorMessage } from '../services/apiWrapper';
import { API_BASE_URL, API_ENDPOINTS } from '../constants';
import type { AgentItem } from '../types/agent';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './ChatPage.css';

export interface TraceStep {
  id?: string;
  kind: 'thought' | 'tool_call' | 'tool_result' | 'subagent_call' | 'subagent_result';
  name?: string;
  input?: any;
  output?: any;
  text?: string;
  status?: string;
  timestamp?: Date;
}

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  traces?: TraceStep[];
  timestamp: Date;
}

interface ApiParam {
  name: string;
  description?: string;
  location?: string;
  data_type?: string;
  required?: boolean;
  default?: any;
}

interface ToolDetail {
  tool_id?: string;
  name: string;
  description?: string;
  tool_type: 'PRECONFIGURED' | 'API' | 'CODE' | 'MCP' | string;
  enabled?: boolean;
  version?: string;
  // Preconfigured
  provider?: string;
  config?: Record<string, any>;
  // API
  url?: string;
  method?: string;
  headers?: Record<string, string>;
  parameters?: ApiParam[];
  timeout_seconds?: number;
  // Code
  function_name?: string;
  source_code?: string;
  // MCP
  mcp_config?: Record<string, any>;
  allowed_tools?: string[];
}

export const ChatPage: React.FC = () => {
  const { agentId } = useParams<{ agentId: string }>();
  const location = useLocation();
  const navigate = useNavigate();

  // Agent can come from router state (instant) or fetched from API
  const [agent, setAgent] = useState<AgentItem | null>(
    (location.state as { agent?: AgentItem })?.agent ?? null
  );
  const [agentLoading, setAgentLoading] = useState(!agent);

  // Left Section Tab: 'overview' | 'tools'
  const [leftTab, setLeftTab] = useState<'overview' | 'tools'>('overview');
  const [toolsList, setToolsList] = useState<ToolDetail[]>([]);
  const [toolsLoading, setToolsLoading] = useState<boolean>(false);
  const [toolsError, setToolsError] = useState<string | null>(null);

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingMessageId, setStreamingMessageId] = useState<string | null>(null);
  const [expandedTraces, setExpandedTraces] = useState<Record<string, boolean>>({});
  const [chatError, setChatError] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const toggleTrace = (msgId: string) => {
    setExpandedTraces((prev) => ({
      ...prev,
      [msgId]: !prev[msgId],
    }));
  };

  const formatPayload = (val: any): string => {
    if (val === undefined || val === null) return '';
    if (typeof val === 'string') {
      try {
        const parsed = JSON.parse(val);
        return JSON.stringify(parsed, null, 2);
      } catch {
        return val;
      }
    }
    try {
      return JSON.stringify(val, null, 2);
    } catch {
      return String(val);
    }
  };

  const renderTraceCard = (trace: TraceStep, index: number) => {
    if (trace.kind === 'thought') {
      return (
        <div key={index} className="trace-item-card trace-thought-card">
          <div className="trace-item-header">
            <div className="trace-item-title-row">
              <PsychologyIcon className="trace-item-icon thought-icon" />
              <span className="trace-item-title">Reasoning & Thought</span>
            </div>
          </div>
          {trace.text && (
            <div className="trace-thought-text">{trace.text}</div>
          )}
        </div>
      );
    }

    if (trace.kind === 'tool_call' || trace.kind === 'subagent_call') {
      const isSub = trace.kind === 'subagent_call';
      return (
        <div key={index} className={`trace-item-card ${isSub ? 'trace-subagent-card' : 'trace-tool-card'}`}>
          <div className="trace-item-header">
            <div className="trace-item-title-row">
              {isSub ? (
                <SmartToyIcon className="trace-item-icon subagent-icon" />
              ) : (
                <BuildIcon className="trace-item-icon tool-icon" />
              )}
              <span className="trace-item-title">
                {isSub ? 'Sub-Agent Call' : 'Tool Call'}: <strong>{trace.name || 'tool'}</strong>
              </span>
            </div>
            <span className="trace-status-pill calling">Calling</span>
          </div>
          {trace.input && (
            <div className="trace-payload-block">
              <span className="trace-payload-label">Input / Parameters:</span>
              <pre className="trace-code-block">{formatPayload(trace.input)}</pre>
            </div>
          )}
        </div>
      );
    }

    if (trace.kind === 'tool_result' || trace.kind === 'subagent_result') {
      const isSub = trace.kind === 'subagent_result';
      const isError = trace.status === 'error';
      return (
        <div key={index} className={`trace-item-card ${isSub ? 'trace-subagent-card' : 'trace-tool-card'} ${isError ? 'trace-error-card' : ''}`}>
          <div className="trace-item-header">
            <div className="trace-item-title-row">
              <CheckCircleOutlinedIcon className={`trace-item-icon ${isError ? 'error-icon' : 'result-icon'}`} />
              <span className="trace-item-title">
                {isSub ? 'Sub-Agent Result' : 'Tool Result'}: <strong>{trace.name || 'tool'}</strong>
              </span>
            </div>
            <span className={`trace-status-pill ${isError ? 'error' : 'completed'}`}>
              {isError ? 'Error' : 'Completed'}
            </span>
          </div>
          {trace.output !== undefined && trace.output !== null && (
            <div className="trace-payload-block">
              <span className="trace-payload-label">Output:</span>
              <pre className="trace-code-block">{formatPayload(trace.output)}</pre>
            </div>
          )}
        </div>
      );
    }

    return null;
  };

  // Fetch agent details if not passed via state
  useEffect(() => {
    if (!agent && agentId) {
      const fetch = async () => {
        try {
          const res: any = await get(`${API_ENDPOINTS.AGENTS.FETCH}${agentId}`);
          const data = res?.data ?? res;
          setAgent(data);
        } catch {
          // If fetch fails, still allow chatting
        } finally {
          setAgentLoading(false);
        }
      };
      fetch();
    }
  }, [agentId]);

  // Fetch tool details when agent.tools are available
  useEffect(() => {
    const rawTools = agent?.tools;
    if (!rawTools || !Array.isArray(rawTools) || rawTools.length === 0) {
      setToolsList([]);
      return;
    }

    const toolIds: string[] = rawTools
      .map((t: any) => (typeof t === 'string' ? t : t?._id || t?.tool_id || t?.id))
      .filter((id): id is string => typeof id === 'string' && id.trim().length > 0);

    if (toolIds.length === 0) {
      setToolsList([]);
      return;
    }

    const fetchTools = async () => {
      setToolsLoading(true);
      setToolsError(null);
      try {
        const res: any = await post(API_ENDPOINTS.AGENTS.FETCH_TOOLS_BY_IDS, { ids: toolIds });
        const list: ToolDetail[] = Array.isArray(res) ? res : res?.data || [];
        setToolsList(list);
      } catch (err) {
        setToolsError(extractErrorMessage(err));
      } finally {
        setToolsLoading(false);
      }
    };

    fetchTools();
  }, [agent?.tools]);

  // Scroll to bottom whenever messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: isStreaming ? 'auto' : 'smooth' });
  }, [messages, isStreaming]);

  const getCapabilities = (): string[] => {
    if (!agent) return [];
    return agent.capabilities ?? [];
  };

  const currentAgentId = agentId || agent?._id || agent?.agent_id || agent?.id || '';

  const handleSend = async () => {
    const text = input.trim();
    if (!text || isSending || !currentAgentId) return;

    setChatError(null);
    const userMsg: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: text,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setIsSending(true);
    setIsStreaming(false);
    setStreamingMessageId(null);

    try {
      const token = sessionStorage.getItem('token');
      const response = await fetch(`${API_BASE_URL}/api/v1/agents/chat/${currentAgentId}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ message: text }),
      });

      if (!response.ok) {
        if (response.status === 401) {
          sessionStorage.removeItem('agentmart_user_session');
          sessionStorage.removeItem('token');
          if (window.location.pathname !== '/login') {
            window.location.href = '/login';
          }
          return;
        }

        let errorMessage = `Request failed with status ${response.status}`;
        try {
          const errData = await response.json();
          errorMessage = errData.error || errData.message || errData.detail || errorMessage;
        } catch {
          const textErr = await response.text();
          if (textErr) errorMessage = textErr;
        }
        throw new Error(errorMessage);
      }

      if (!response.body) {
        throw new Error('Response body is empty');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';
      let currentAssistantId = '';
      let accumulatedContent = '';

      const processParsedChunk = (parsed: any) => {
        if (parsed?.error) {
          throw new Error(parsed.error);
        }

        if (parsed.type === 'trace' && parsed.step) {
          const step: TraceStep = parsed.step;
          if (!currentAssistantId) {
            currentAssistantId = (Date.now() + 1).toString();
            setStreamingMessageId(currentAssistantId);
            setIsStreaming(true);
            setMessages((prev) => [
              ...prev,
              {
                id: currentAssistantId,
                role: 'assistant',
                content: '',
                traces: [step],
                timestamp: new Date(),
              },
            ]);
          } else {
            setMessages((prev) =>
              prev.map((msg) => {
                if (msg.id !== currentAssistantId) return msg;
                const traces = [...(msg.traces || [])];

                if (step.kind === 'thought') {
                  const lastTrace = traces[traces.length - 1];
                  if (lastTrace && lastTrace.kind === 'thought') {
                    lastTrace.text = (lastTrace.text || '') + (step.text || '');
                  } else {
                    traces.push({ ...step });
                  }
                } else if (step.kind === 'tool_call' || step.kind === 'subagent_call') {
                  const existingIdx = step.id
                    ? traces.findIndex((t) => t.id === step.id && t.kind === step.kind)
                    : -1;
                  if (existingIdx >= 0) {
                    traces[existingIdx] = { ...traces[existingIdx], ...step };
                  } else {
                    traces.push({ ...step });
                  }
                } else if (step.kind === 'tool_result' || step.kind === 'subagent_result') {
                  const existingIdx = step.id
                    ? traces.findIndex((t) => t.id === step.id && t.kind === step.kind)
                    : -1;
                  if (existingIdx >= 0) {
                    traces[existingIdx] = { ...traces[existingIdx], ...step };
                  } else {
                    traces.push({ ...step });
                  }
                } else {
                  traces.push({ ...step });
                }

                return { ...msg, traces };
              })
            );
          }
        } else if (parsed.content || parsed.type === 'content') {
          const chunkText = parsed.content ?? '';
          if (chunkText) {
            accumulatedContent += chunkText;

            if (!currentAssistantId) {
              currentAssistantId = (Date.now() + 1).toString();
              setStreamingMessageId(currentAssistantId);
              setIsStreaming(true);
              setMessages((prev) => [
                ...prev,
                {
                  id: currentAssistantId,
                  role: 'assistant',
                  content: accumulatedContent,
                  traces: [],
                  timestamp: new Date(),
                },
              ]);
            } else {
              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === currentAssistantId
                    ? { ...msg, content: accumulatedContent }
                    : msg
                )
              );
            }
          }
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed || trimmed.startsWith(':')) continue;

          if (trimmed.startsWith('data:')) {
            const dataStr = trimmed.slice(5).trim();
            if (dataStr === '[DONE]') {
              continue;
            }

            try {
              const parsed = JSON.parse(dataStr);
              processParsedChunk(parsed);
            } catch (parseErr: any) {
              if (parseErr.message && !parseErr.message.includes('JSON')) {
                throw parseErr;
              }
            }
          }
        }
      }

      // Flush remaining line in buffer if present
      if (buffer.trim().startsWith('data:')) {
        const dataStr = buffer.trim().slice(5).trim();
        if (dataStr && dataStr !== '[DONE]') {
          try {
            const parsed = JSON.parse(dataStr);
            processParsedChunk(parsed);
          } catch {
            // ignore
          }
        }
      }

      if (!accumulatedContent && !currentAssistantId) {
        setMessages((prev) => [
          ...prev,
          {
            id: (Date.now() + 1).toString(),
            role: 'assistant',
            content: 'No response received from agent.',
            timestamp: new Date(),
          },
        ]);
      }
    } catch (err: any) {
      setChatError(extractErrorMessage(err));
    } finally {
      setIsSending(false);
      setIsStreaming(false);
      setStreamingMessageId(null);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const formatTime = (date: Date) =>
    date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  return (
    <div className="chat-page-wrapper bg-deep-dark">
      <Navbar />

      {/* Header: Agent name + description */}
      <div className="chat-header-bar">
        <div className="chat-header-inner">
          <div className="chat-header-left">
            <button
              className="chat-back-btn"
              onClick={() => navigate('/deployed')}
              title="Back to deployed agents"
            >
              <ArrowBackIcon fontSize="small" />
            </button>
            {agentLoading ? (
              <Spinner animation="border" size="sm" style={{ color: 'var(--primary-accent)' }} />
            ) : (
              <div>
                <h1 className="chat-agent-name">{agent?.name ?? 'Agent Chat'}</h1>
                {agent?.description && (
                  <p className="chat-agent-desc">{agent.description}</p>
                )}
              </div>
            )}
          </div>
          <span className="chat-live-badge">
            <span className="chat-live-dot" /> LIVE
          </span>
        </div>
      </div>

      {/* Body: Overview | Chat */}
      <div className="chat-body">
        {/* Left: Overview panel */}
        <aside className="chat-overview-panel">
          {/* Horizontal toggles */}
          <div className="chat-tab-toggle-container">
            <button
              type="button"
              className={`chat-tab-toggle-btn ${leftTab === 'overview' ? 'active' : ''}`}
              onClick={() => setLeftTab('overview')}
            >
              Overview
            </button>
            <button
              type="button"
              className={`chat-tab-toggle-btn ${leftTab === 'tools' ? 'active' : ''}`}
              onClick={() => setLeftTab('tools')}
            >
              Tools {toolsList.length > 0 ? `(${toolsList.length})` : (agent?.tools?.length ? `(${agent.tools.length})` : '')}
            </button>
          </div>

          {leftTab === 'overview' && (
            <div className="overview-tab-content">
              {/* Capabilities */}
              <div className="overview-block">
                <span className="overview-label">Capabilities</span>
                {getCapabilities().length > 0 ? (
                  <ul className="overview-list">
                    {getCapabilities().map((c, i) => (
                      <li key={i} className="overview-list-item">{c}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="overview-empty">No capabilities specified</p>
                )}
              </div>

              {/* LLM Provider */}
              <div className="overview-block">
                <span className="overview-label">LLM Provider</span>
                {agent?.model ? (
                  <div className="llm-provider-card">
                    <div className="llm-provider-row">
                      <span className="llm-label">Provider</span>
                      <span className="llm-badge">
                        {typeof agent.model === 'string'
                          ? agent.model
                          : agent.model.provider ?? 'Custom'}
                      </span>
                    </div>
                    {typeof agent.model !== 'string' && (agent.model.name || agent.model.model_name) && (
                      <div className="llm-provider-row">
                        <span className="llm-label">Model</span>
                        <span className="llm-value">{agent.model.name || agent.model.model_name}</span>
                      </div>
                    )}
                    {typeof agent.model !== 'string' && agent.model.temperature !== undefined && (
                      <div className="llm-provider-row">
                        <span className="llm-label">Temperature</span>
                        <span className="llm-value">{agent.model.temperature}</span>
                      </div>
                    )}
                    {typeof agent.model !== 'string' && agent.model.max_tokens && (
                      <div className="llm-provider-row">
                        <span className="llm-label">Max Tokens</span>
                        <span className="llm-value">{agent.model.max_tokens}</span>
                      </div>
                    )}
                  </div>
                ) : (
                  <p className="overview-empty">Default Model</p>
                )}
              </div>

              {/* Version */}
              {agent?.version && (
                <div className="overview-block">
                  <span className="overview-label">Version</span>
                  <p className="overview-value">v{agent.version}</p>
                </div>
              )}
            </div>
          )}

          {leftTab === 'tools' && (
            <div className="tools-tab-content">
              {toolsLoading && (
                <div className="tools-loading-state">
                  <Spinner animation="border" size="sm" style={{ color: 'var(--primary-accent)' }} />
                  <span className="tools-loading-text">Loading tools…</span>
                </div>
              )}

              {toolsError && (
                <div className="tools-error-badge">
                  <span>⚠ {toolsError}</span>
                </div>
              )}

              {!toolsLoading && !toolsError && toolsList.length === 0 && (
                <div className="tools-empty-state">
                  <p className="overview-empty">No tools configured for this agent</p>
                </div>
              )}

              {!toolsLoading && toolsList.length > 0 && (
                <div className="tools-cards-list">
                  {toolsList.map((tool, idx) => (
                    <div key={tool.tool_id || idx} className="tool-detail-card">
                      <div className="tool-card-header">
                        <span className="tool-card-name">{tool.name}</span>
                        <span className={`tool-type-badge type-${(tool.tool_type || 'custom').toLowerCase()}`}>
                          {tool.tool_type}
                        </span>
                      </div>

                      {tool.description && (
                        <p className="tool-card-desc">{tool.description}</p>
                      )}

                      {/* API Tool Details */}
                      {tool.tool_type === 'API' && (
                        <div className="tool-meta-block">
                          {tool.method && (
                            <div className="tool-meta-row">
                              <span className="tool-meta-label">Method</span>
                              <span className="tool-method-badge">{tool.method}</span>
                            </div>
                          )}
                          {tool.url && (
                            <div className="tool-meta-row">
                              <span className="tool-meta-label">Endpoint</span>
                              <span className="tool-url-text" title={tool.url}>{tool.url}</span>
                            </div>
                          )}
                          {tool.parameters && tool.parameters.length > 0 && (
                            <div className="tool-meta-row">
                              <span className="tool-meta-label">Parameters</span>
                              <span className="tool-params-count">{tool.parameters.length} parameter(s)</span>
                            </div>
                          )}
                        </div>
                      )}

                      {/* Preconfigured Tool Details */}
                      {tool.tool_type === 'PRECONFIGURED' && tool.provider && (
                        <div className="tool-meta-block">
                          <div className="tool-meta-row">
                            <span className="tool-meta-label">Provider</span>
                            <span className="tool-meta-value">{tool.provider}</span>
                          </div>
                        </div>
                      )}

                      {/* MCP Tool Details */}
                      {tool.tool_type === 'MCP' && tool.allowed_tools && tool.allowed_tools.length > 0 && (
                        <div className="tool-meta-block">
                          <span className="tool-meta-label">Allowed Tools</span>
                          <div className="tool-mcp-pills">
                            {tool.allowed_tools.map((at, i) => (
                              <span key={i} className="tool-mcp-pill">{at}</span>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Code Tool Details */}
                      {tool.tool_type === 'CODE' && tool.function_name && (
                        <div className="tool-meta-block">
                          <div className="tool-meta-row">
                            <span className="tool-meta-label">Function</span>
                            <span className="tool-meta-value code-font">{tool.function_name}</span>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </aside>

        {/* Right: Chat interface */}
        <section className="chat-interface">
          {/* Messages area */}
          <div className="chat-messages">
            {messages.length === 0 && !isSending && (
              <div className="chat-empty-state">
                <div className="chat-empty-icon"><QuestionAnswerIcon fontSize='large' /></div>
                <p className="chat-empty-text">
                  Start a conversation with <strong>{agent?.name ?? 'the agent'}</strong>
                </p>
              </div>
            )}

            {messages.map((msg) => {
              const isUser = msg.role === 'user';
              return (
                <div
                  key={msg.id}
                  className={`chat-message-row ${isUser ? 'user-row' : 'assistant-row'}`}
                >
                  {/* System name bubble at left */}
                  {!isUser && (
                    <div className="chat-avatar-bubble system-avatar-bubble" title={agent?.name || 'System'}>
                      <FlutterDashIcon className="avatar-icon" />
                    </div>
                  )}

                  <div className={`chat-bubble ${isUser ? 'user-bubble' : 'assistant-bubble'}`}>
                    {/* Collapsible Execution Trace section */}
                    {!isUser && msg.traces && msg.traces.length > 0 && (() => {
                      const isExpanded = !!expandedTraces[msg.id];
                      return (
                        <div className="trace-accordion">
                          <button
                            type="button"
                            className="trace-accordion-header"
                            onClick={() => toggleTrace(msg.id)}
                            title={isExpanded ? 'Collapse thinking steps' : 'Expand thinking steps'}
                          >
                            <div className="trace-header-left">
                              <PsychologyIcon className="trace-icon" />
                              <span className="trace-title">
                                {isStreaming && msg.id === streamingMessageId && !msg.content
                                  ? 'Agent Thinking & Executing…'
                                  : 'Thinking & Execution Trace'}
                              </span>
                              <span className="trace-count-pill">
                                {msg.traces.length} {msg.traces.length === 1 ? 'step' : 'steps'}
                              </span>
                            </div>
                            <div className="trace-header-right">
                              {isStreaming && msg.id === streamingMessageId && !msg.content && (
                                <Spinner animation="border" size="sm" className="trace-header-spinner" />
                              )}
                              {isExpanded ? (
                                <ExpandLessIcon fontSize="small" />
                              ) : (
                                <ExpandMoreIcon fontSize="small" />
                              )}
                            </div>
                          </button>

                          {isExpanded && (
                            <div className="trace-accordion-content">
                              {msg.traces.map((trace, idx) => renderTraceCard(trace, idx))}
                            </div>
                          )}
                        </div>
                      );
                    })()}

                    {/* Message content */}
                    {isUser ? (
                      <p className="bubble-text">{msg.content}</p>
                    ) : msg.content ? (
                      <div className="bubble-markdown-content">
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                          components={{
                            a: ({ node, ...props }) => (
                              <a {...props} target="_blank" rel="noopener noreferrer" />
                            ),
                          }}
                        >
                          {msg.content}
                        </ReactMarkdown>
                        {isStreaming && msg.id === streamingMessageId && (
                          <span className="streaming-cursor" />
                        )}
                      </div>
                    ) : (
                      isStreaming && msg.id === streamingMessageId && (
                        <div className="trace-pending-dots">
                          <span className="typing-dot" />
                          <span className="typing-dot" />
                          <span className="typing-dot" />
                        </div>
                      )
                    )}

                    <span className="bubble-time">{formatTime(msg.timestamp)}</span>
                  </div>

                  {/* User name block at right */}
                  {isUser && (
                    <div className="chat-avatar-bubble user-avatar-bubble" title="You">
                      <PersonIcon className="avatar-icon" />
                    </div>
                  )}
                </div>
              );
            })}

            {isSending && !isStreaming && (
              <div className="chat-message-row assistant-row">
                <div className="chat-avatar-bubble system-avatar-bubble" title={agent?.name || 'System'}>
                  <FlutterDashIcon className="avatar-icon" />
                </div>
                <div className="chat-bubble assistant-bubble typing-bubble">
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                </div>
              </div>
            )}

            {chatError && (
              <div className="chat-error-row">
                <span className="chat-error-text">⚠ {chatError}</span>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Input row */}
          <div className="chat-input-row">
            <textarea
              ref={inputRef}
              className="chat-input"
              placeholder="Type a message… (Enter to send, Shift+Enter for newline)"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={1}
              disabled={isSending}
            />
            <button
              className="chat-send-btn"
              onClick={handleSend}
              disabled={isSending || !input.trim()}
              title="Send message"
            >
              {isSending
                ? <Spinner animation="border" size="sm" />
                : <SendIcon style={{ fontSize: 20 }} />
              }
            </button>
          </div>
        </section>
      </div>
    </div>
  );
};
