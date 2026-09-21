import { useState, useRef, useEffect, useCallback } from 'react';
import {
  Send, Loader2, Plus, MessageSquare, Brain, Wrench, CheckCircle2,
  ChevronDown, ChevronRight, Bot, ArrowRight, Trash2, Edit3, Check, X,
  PanelLeftClose, PanelLeft, Search, Key, Database, Upload, FileText,
  Paperclip, Zap, Bookmark, Mic, MicOff, Cpu, ScrollText,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Agent, ThinkingStep, TaskStatusResponse } from '../services/api';
import { getAgents, pollTaskStatus, streamGlobalChat, streamMongoRAG } from '../services/api';
import { getUserConfigPayloadForRequest } from '../utils/agentConfigStorage';
import BPMNViewer from '../components/BPMNViewer';
import StackBlitzEmbed from '../components/StackBlitzEmbed';
import MermaidDiagram from '../components/MermaidDiagram';
import SuggestionChips from '../components/SuggestionChips';
import TestReportView, { isTestReport } from '../components/TestReportView';
import CompanyReportView, { isCompanyResearchReport, LatestNewsCardsSection, type NewsCardData } from '../components/CompanyReportView';
import CompanyAiSolutionsView, { isCompanyAiSolutionsReport } from '../components/CompanyAiSolutionsView';
import DocumentView, { isDocumentResponse } from '../components/DocumentView';
import { FileAttachmentInput, FileAttachmentBubble } from '../components/FileAttachmentCard';
import JiraDashboard, { type JiraChartData } from '../components/JiraDashboard';

interface RoutedAgentInfo {
  agent_id: string;
  agent_name: string;
  confidence: number;
  reasoning: string;
}

interface ChatMessage {
  id?: number;
  role: 'user' | 'assistant';
  content: string;
  thinking_steps?: ThinkingStep[];
  routed_to?: RoutedAgentInfo;
  bpmn_xml?: string;
  stackblitz_repo?: string;
  latest_news_cards?: NewsCardData[];
  chart_data?: JiraChartData;
  created_at: string;
}

interface ChatSession {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

function ThinkingStepsDisplay({ steps }: { steps: ThinkingStep[] }) {
  const [isExpanded, setIsExpanded] = useState(false);

  if (!steps || steps.length === 0) return null;

  const getStepIcon = (type: string) => {
    switch (type) {
      case 'thinking':
        return <Brain className="w-3 h-3 text-purple-400" />;
      case 'tool':
        return <Wrench className="w-3 h-3 text-indigo-400" />;
      case 'tool_call':
        return <Wrench className="w-3 h-3 text-blue-400" />;
      case 'tool_result':
        return <CheckCircle2 className="w-3 h-3 text-green-400" />;
      case 'llm_call':
        return <Cpu className="w-3 h-3 text-amber-400" />;
      case 'llm_response':
        return <ScrollText className="w-3 h-3 text-teal-400" />;
      default:
        return <Brain className="w-3 h-3 text-gray-600 dark:text-gray-400" />;
    }
  };

  const getStepLabel = (step: ThinkingStep) => {
    switch (step.type) {
      case 'thinking': return 'Thinking';
      case 'tool': return step.tool_name ? `Step · ${step.tool_name}` : 'Step';
      case 'tool_call': return `Using: ${step.tool_name}`;
      case 'tool_result': return `Result: ${step.tool_name}`;
      case 'llm_call': return 'LLM request';
      case 'llm_response': return 'LLM response';
      default: return 'Processing';
    }
  };

  return (
    <div className="mb-3">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center gap-1.5 text-xs text-gray-600 dark:text-gray-400 hover:text-gray-300 transition-colors group"
      >
        {isExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        <Brain className="w-3 h-3 text-purple-400" />
        <span className="group-hover:underline">Thinking ({steps.length} steps)</span>
      </button>

      {isExpanded && (
        <div className="mt-2 ml-4 pl-3 border-l-2 border-gray-200 dark:border-gray-700 space-y-1.5">
          {steps.map((step, index) => (
            <div key={index} className="flex items-start gap-1.5 text-xs">
              <div className="mt-0.5 flex-shrink-0">{getStepIcon(step.type)}</div>
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="font-medium text-gray-600 dark:text-gray-400">{getStepLabel(step)}</span>
                  {(step.model || step.provider) && (
                    <span className="rounded bg-gray-100 dark:bg-gray-800/80 px-1 py-0.5 font-mono text-[0.625rem] text-gray-500">
                      {[step.provider, step.model].filter(Boolean).join(' · ')}
                      {step.prompt_length != null && step.type === 'llm_call' ? ` · ${step.prompt_length}c` : ''}
                      {step.response_length != null && step.type === 'llm_response' ? ` · ${step.response_length}c` : ''}
                    </span>
                  )}
                </div>
                {step.tool_input && (step.type === 'tool_call' || step.type === 'llm_call') && (
                  <div className="text-gray-500 bg-gray-100 dark:bg-gray-800/50 px-2 py-0.5 rounded text-xs font-mono mt-0.5 break-all max-h-40 overflow-y-auto">
                    {step.tool_input}
                  </div>
                )}
                {step.type === 'llm_response' && step.truncated && (
                  <p className="mt-0.5 text-[0.625rem] text-amber-400/90">Preview truncated in trace; full text used for the reply.</p>
                )}
                <div className={`text-gray-500 break-words overflow-y-auto ${step.type === 'llm_response' ? 'max-h-64' : 'max-h-32'}`}>{step.content}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function RoutedAgentBadge({ info }: { info: RoutedAgentInfo }) {
  return (
    <div className="mb-2 inline-flex items-center gap-1.5 rounded-lg border border-primary-500/25 bg-primary-500/10 px-2 py-1 font-body text-xs">
      <ArrowRight className="h-3 w-3 text-primary-400" />
      <span className="font-medium text-primary-200">{info.agent_name}</span>
      <span className="text-primary-400/70">({Math.round(info.confidence * 100)}%)</span>
    </div>
  );
}


export default function GlobalChat({ embedded = false }: { embedded?: boolean } = {}) {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [currentThinkingStep, setCurrentThinkingStep] = useState('');
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [showTokenInput, setShowTokenInput] = useState(false);
  const [githubToken, setGithubToken] = useState('');
  const [pendingPushQuery, setPendingPushQuery] = useState('');
  const [regeneratingDiagram, setRegeneratingDiagram] = useState<'architecture' | 'dataflow' | null>(null);
  const [showMongoUriInput, setShowMongoUriInput] = useState(false);
  const [mongoUri, setMongoUri] = useState('');
  const [mongoSessionId, setMongoSessionId] = useState('');
  const [mongoConnected, setMongoConnected] = useState(false);
  const [mongoIngested, setMongoIngested] = useState(false);
  const [showMongoFileUpload, setShowMongoFileUpload] = useState(false);
  const [mongoUploadedFile, setMongoUploadedFile] = useState<{ name: string; content: string; type: string } | null>(null);
  const [uploadedFile, setUploadedFile] = useState<{ name: string; content: string; type: string; size?: number } | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<string>('auto');
  const [agentDropdownOpen, setAgentDropdownOpen] = useState(false);
  const [agentSearchQuery, setAgentSearchQuery] = useState('');
  const [isSaved, setIsSaved] = useState(false);
  const [savingChat, setSavingChat] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [speechSupported, setSpeechSupported] = useState(false);
  const [voiceMode, setVoiceMode] = useState(false);
  const [voiceTranscript, setVoiceTranscript] = useState('');
  const [speakingResponse, setSpeakingResponse] = useState(false);
  const recognitionRef = useRef<any>(null);
  const ttsAudioRef = useRef<HTMLAudioElement | null>(null);
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const voiceModeRef = useRef(false);
  const autoSendRef = useRef(false);
  const recognitionModeRef = useRef<'wake' | 'dictation' | 'off'>('off');
  const transitioningRef = useRef(false);
  const recognitionRunningRef = useRef(false);
  const wakeFailCountRef = useRef(0);
  const [wakeListening, setWakeListening] = useState(false);
  const micPermissionRef = useRef(false);
  const startVoiceModeRef = useRef<(() => void) | null>(null);
  const agentDropdownRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const mongoFileInputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) return;

    setSpeechSupported(true);
    const recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = 'en-IN';

    const safeStop = () => {
      try { recognition.stop(); } catch(e) {}
      recognitionRunningRef.current = false;
    };

    const safeStart = () => {
      if (recognitionRunningRef.current) return false;
      try {
        recognition.start();
        recognitionRunningRef.current = true;
        return true;
      } catch(e) {
        recognitionRunningRef.current = false;
        return false;
      }
    };

    recognition.onstart = () => {
      recognitionRunningRef.current = true;
      if (recognitionModeRef.current === 'wake') {
        wakeFailCountRef.current = Math.max(0, wakeFailCountRef.current - 1);
      }
    };

    recognition.onresult = (event: any) => {
      const mode = recognitionModeRef.current;

      if (mode === 'wake') {
        for (let i = 0; i < event.results.length; i++) {
          const transcript = event.results[i][0].transcript.toLowerCase().trim();
          const wakeWords = ['hi mira', 'hey mira', 'hi meera', 'hey meera', 'high mira', 'high meera', 'he mira', 'he meera', 'hi mirror', 'hey mirror', 'hi mera', 'hey mera', 'himira', 'heymira', 'haimira', 'hai mira', 'hai meera', 'mira', 'meera'];
          if (wakeWords.some(w => transcript.includes(w))) {
            transitioningRef.current = true;
            recognitionModeRef.current = 'off';
            setWakeListening(false);
            safeStop();
            setTimeout(() => {
              transitioningRef.current = false;
              startVoiceModeRef.current?.();
            }, 500);
            return;
          }
        }
        return;
      }

      if (mode === 'dictation') {
        let finalText = '';
        let interim = '';
        for (let i = 0; i < event.results.length; i++) {
          const t = event.results[i][0].transcript;
          if (event.results[i].isFinal) {
            finalText += t + ' ';
          } else {
            interim += t;
          }
        }
        const combined = (finalText + interim).trim();
        setVoiceTranscript(combined);
        setInput(combined);

        if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
        if (combined && voiceModeRef.current) {
          silenceTimerRef.current = setTimeout(() => {
            if (voiceModeRef.current) {
              autoSendRef.current = true;
              safeStop();
            }
          }, 2000);
        }
      }
    };

    recognition.onerror = (e: any) => {
      recognitionRunningRef.current = false;
      if (recognitionModeRef.current === 'wake') {
        if (e.error === 'aborted' || e.error === 'no-speech' || e.error === 'network') {
          wakeFailCountRef.current++;
          if (wakeFailCountRef.current >= 3) {
            recognitionModeRef.current = 'off';
            setWakeListening(false);
            return;
          }
        }
      }
      if (recognitionModeRef.current === 'dictation') {
        setIsListening(false);
      }
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
        recognitionModeRef.current = 'off';
        setWakeListening(false);
      }
    };

    recognition.onend = () => {
      recognitionRunningRef.current = false;
      const mode = recognitionModeRef.current;

      if (mode === 'dictation') {
        setIsListening(false);
        if (autoSendRef.current) {
          autoSendRef.current = false;
          setVoiceAutoSend(true);
        }
        return;
      }

      if (mode === 'wake' && !transitioningRef.current && !voiceModeRef.current && wakeFailCountRef.current < 3) {
        const delay = Math.min(1000 * Math.pow(2, wakeFailCountRef.current), 10000);
        setTimeout(() => {
          if (!voiceModeRef.current && !transitioningRef.current && recognitionModeRef.current === 'wake' && wakeFailCountRef.current < 3) {
            if (safeStart()) {
              setWakeListening(true);
            }
          }
        }, delay);
      } else if (wakeFailCountRef.current >= 3) {
        setWakeListening(false);
      }
    };

    recognitionRef.current = recognition;

    try {
      recognitionModeRef.current = 'wake';
      recognition.start();
      recognitionRunningRef.current = true;
      setWakeListening(true);
      micPermissionRef.current = true;
    } catch(e) {
      recognitionModeRef.current = 'off';
      recognitionRunningRef.current = false;
    }

    return () => {
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
      recognitionModeRef.current = 'off';
      safeStop();
    };
  }, []);

  const [voiceAutoSend, setVoiceAutoSend] = useState(false);

  const stopTtsAudio = () => {
    if (ttsAudioRef.current) {
      ttsAudioRef.current.pause();
      ttsAudioRef.current.currentTime = 0;
      ttsAudioRef.current = null;
    }
  };

  const resumeListeningAfterSpeak = () => {
    setSpeakingResponse(false);
    if (voiceModeRef.current && recognitionRef.current) {
      setTimeout(() => {
        if (voiceModeRef.current) {
          recognitionModeRef.current = 'dictation';
          recognitionRunningRef.current = false;
          try {
            recognitionRef.current.start();
            recognitionRunningRef.current = true;
            setIsListening(true);
            setVoiceTranscript('');
            setInput('');
          } catch(e) {}
        }
      }, 500);
    }
  };

  const speakText = async (text: string) => {
    stopTtsAudio();
    window.speechSynthesis?.cancel();

    const cleaned = text
      .replace(/```[\s\S]*?```/g, '')
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
      .replace(/[#*_~`>|]/g, '')
      .replace(/[-]{3,}/g, '')
      .replace(/\n{2,}/g, '. ')
      .replace(/\n/g, ' ')
      .replace(/\s{2,}/g, ' ')
      .trim();
    if (!cleaned) return;
    const maxLen = 1500;
    const toSpeak = cleaned.length > maxLen ? cleaned.substring(0, maxLen) + '. That is a summary of the response.' : cleaned;

    setSpeakingResponse(true);

    try {
      const resp = await fetch('/api/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: toSpeak }),
      });

      if (!resp.ok) throw new Error('TTS request failed');

      const blob = await resp.blob();
      const audioUrl = URL.createObjectURL(blob);
      const audio = new Audio(audioUrl);
      ttsAudioRef.current = audio;

      audio.onended = () => {
        URL.revokeObjectURL(audioUrl);
        ttsAudioRef.current = null;
        resumeListeningAfterSpeak();
      };
      audio.onerror = () => {
        URL.revokeObjectURL(audioUrl);
        ttsAudioRef.current = null;
        resumeListeningAfterSpeak();
      };

      if (!voiceModeRef.current) {
        URL.revokeObjectURL(audioUrl);
        setSpeakingResponse(false);
        return;
      }

      await audio.play();
    } catch (e) {
      console.error('ElevenLabs TTS error, falling back to browser speech:', e);
      fallbackBrowserSpeak(toSpeak);
    }
  };

  const fallbackBrowserSpeak = (text: string) => {
    stopTtsAudio();
    if (!('speechSynthesis' in window)) {
      resumeListeningAfterSpeak();
      return;
    }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'en-IN';
    utterance.rate = 0.95;
    utterance.pitch = 1.05;
    utterance.volume = 1;
    utterance.onend = () => resumeListeningAfterSpeak();
    utterance.onerror = () => resumeListeningAfterSpeak();
    window.speechSynthesis.speak(utterance);
  };

  const safeRecognitionStop = () => {
    try { recognitionRef.current?.stop(); } catch(e) {}
    recognitionRunningRef.current = false;
  };

  const safeRecognitionStart = () => {
    if (recognitionRunningRef.current) return false;
    try {
      recognitionRef.current?.start();
      recognitionRunningRef.current = true;
      return true;
    } catch(e) {
      recognitionRunningRef.current = false;
      return false;
    }
  };

  const startWakeListener = () => {
    if (!recognitionRef.current || voiceModeRef.current || transitioningRef.current) return;
    if (!micPermissionRef.current) return;
    wakeFailCountRef.current = 0;
    recognitionModeRef.current = 'wake';
    if (safeRecognitionStart()) {
      setWakeListening(true);
    }
  };

  const startVoiceMode = () => {
    if (!recognitionRef.current) return;
    transitioningRef.current = true;
    recognitionModeRef.current = 'off';
    setWakeListening(false);
    safeRecognitionStop();

    setTimeout(() => {
      transitioningRef.current = false;
      micPermissionRef.current = true;
      voiceModeRef.current = true;
      setVoiceMode(true);
      setVoiceTranscript('');
      setInput('');
      recognitionModeRef.current = 'dictation';
      if (safeRecognitionStart()) {
        setIsListening(true);
      }
    }, 500);
  };

  startVoiceModeRef.current = startVoiceMode;

  const stopVoiceMode = () => {
    voiceModeRef.current = false;
    setVoiceMode(false);
    setIsListening(false);
    setSpeakingResponse(false);
    setVoiceTranscript('');
    autoSendRef.current = false;
    recognitionModeRef.current = 'off';
    transitioningRef.current = true;
    if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
    safeRecognitionStop();
    stopTtsAudio();
    window.speechSynthesis?.cancel();
    setTimeout(() => {
      transitioningRef.current = false;
      startWakeListener();
    }, 800);
  };

  const toggleVoice = () => {
    if (voiceMode) {
      stopVoiceMode();
    } else {
      startVoiceMode();
    }
  };

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'm') {
        e.preventDefault();
        toggleVoice();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [voiceMode]);

  useEffect(() => {
    scrollToBottom();
  }, [messages, currentThinkingStep]);

  useEffect(() => {
    loadSessions();
    getAgents().then(data => setAgents(data.agents || [])).catch(() => {});
  }, []);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (agentDropdownRef.current && !agentDropdownRef.current.contains(e.target as Node)) {
        setAgentDropdownOpen(false);
        setAgentSearchQuery('');
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const loadSessions = async () => {
    try {
      const resp = await fetch('/api/chat/sessions');
      if (resp.ok) {
        const data = await resp.json();
        setSessions(data);
      }
    } catch (err) {
      console.error('Failed to load sessions', err);
    }
  };

  const loadMessages = useCallback(async (sessionId: string) => {
    try {
      const resp = await fetch(`/api/chat/sessions/${sessionId}/messages`);
      if (resp.ok) {
        const data = await resp.json();
        setMessages(data.map((m: any) => ({
          id: m.id,
          role: m.role,
          content: m.content,
          thinking_steps: m.thinking_steps,
          routed_to: m.routed_to,
          bpmn_xml: m.bpmn_xml,
          created_at: m.created_at,
        })));
      }
    } catch (err) {
      console.error('Failed to load messages', err);
    }
  }, []);

  const selectSession = useCallback(async (sessionId: string) => {
    setActiveSessionId(sessionId);
    setIsSaved(true);
    await loadMessages(sessionId);
    if (window.innerWidth < 768) setSidebarOpen(false);
  }, [loadMessages]);

  const createNewChat = async () => {
    setActiveSessionId(null);
    setMessages([]);
    setInput('');
    setIsSaved(false);
    resetMongoState();
    if (window.innerWidth < 768) setSidebarOpen(false);
    inputRef.current?.focus();
  };

  const saveCurrentChat = async () => {
    if (messages.length === 0 || savingChat) return;
    setSavingChat(true);
    try {
      const resp = await fetch('/api/chat/sessions/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: messages.map(m => ({
            role: m.role,
            content: m.content,
            thinking_steps: m.thinking_steps,
            routed_to: m.routed_to,
            bpmn_xml: m.bpmn_xml,
          })),
        }),
      });
      if (resp.ok) {
        const data = await resp.json();
        setActiveSessionId(data.session_id);
        setIsSaved(true);
        await loadSessions();
      }
    } catch (err) {
      console.error('Failed to save chat', err);
    } finally {
      setSavingChat(false);
    }
  };

  const deleteSession = async (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await fetch(`/api/chat/sessions/${sessionId}`, { method: 'DELETE' });
      setSessions(prev => prev.filter(s => s.id !== sessionId));
      if (activeSessionId === sessionId) {
        setActiveSessionId(null);
        setMessages([]);
      }
    } catch (err) {
      console.error('Failed to delete session', err);
    }
  };

  const startEditTitle = (session: ChatSession, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingSessionId(session.id);
    setEditTitle(session.title);
  };

  const saveTitle = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!editingSessionId || !editTitle.trim()) return;
    try {
      await fetch(`/api/chat/sessions/${editingSessionId}/title`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: editTitle.trim() }),
      });
      setSessions(prev => prev.map(s =>
        s.id === editingSessionId ? { ...s, title: editTitle.trim() } : s
      ));
    } catch (err) {
      console.error('Failed to update title', err);
    }
    setEditingSessionId(null);
  };

  const handleRegenerateDiagram = async (diagramType: 'architecture' | 'dataflow') => {
    if (isLoading || regeneratingDiagram) return;
    setRegeneratingDiagram(diagramType);
    const prompt = diagramType === 'architecture' ? 'Regenerate the architecture diagram' : 'Regenerate the data flow diagram';
    try {
      let fullResponse = '';
      await streamGlobalChat({ query: prompt, session_id: activeSessionId || undefined, skip_save: !isSaved }, {
        onResponseChunk: (chunk, meta) => {
          if (meta?.reset) fullResponse = '';
          fullResponse += chunk;
        },
        onDone: (data) => { fullResponse = data.response || fullResponse; },
      });
      if (fullResponse) {
        setMessages((prev) => {
          const updated = [...prev];
          const lastAssistantIdx = updated.map((m, i) => m.role === 'assistant' ? i : -1).filter(i => i >= 0).pop();
          if (lastAssistantIdx !== undefined && lastAssistantIdx >= 0) {
            const oldContent = updated[lastAssistantIdx].content;
            const archHeading = '### Architecture Diagram';
            const dataFlowHeading = '### Data Flow Architecture Diagram';
            if (diagramType === 'architecture') {
              const archStart = oldContent.indexOf(archHeading);
              const dataFlowStart = oldContent.indexOf(dataFlowHeading);
              if (archStart >= 0) {
                const endPos = dataFlowStart >= 0 ? dataFlowStart : oldContent.length;
                const newArchSection = fullResponse.includes(archHeading) ? fullResponse.substring(fullResponse.indexOf(archHeading)) : `${archHeading}\n\n${fullResponse}`;
                const archOnly = newArchSection.includes(dataFlowHeading) ? newArchSection.substring(0, newArchSection.indexOf(dataFlowHeading)) : newArchSection;
                updated[lastAssistantIdx] = { ...updated[lastAssistantIdx], content: oldContent.substring(0, archStart) + archOnly.trim() + '\n\n' + oldContent.substring(endPos) };
              }
            } else {
              const dataFlowStart = oldContent.indexOf(dataFlowHeading);
              if (dataFlowStart >= 0) {
                const newFlowSection = fullResponse.includes(dataFlowHeading) ? fullResponse.substring(fullResponse.indexOf(dataFlowHeading)) : `${dataFlowHeading}\n\n${fullResponse}`;
                updated[lastAssistantIdx] = { ...updated[lastAssistantIdx], content: oldContent.substring(0, dataFlowStart) + newFlowSection.trim() };
              }
            }
          }
          return updated;
        });
      }
    } catch (e) {
      console.error('Failed to regenerate diagram:', e);
    } finally {
      setRegeneratingDiagram(null);
    }
  };

  const handleSuggestionClick = (text: string) => {
    if (isLoading) return;
    handleSend(text);
  };

  const resetMongoState = () => {
    setShowMongoUriInput(false);
    setMongoUri('');
    setMongoConnected(false);
    setMongoIngested(false);
    setShowMongoFileUpload(false);
    setMongoUploadedFile(null);
    setMongoSessionId('');
  };

  /** Same LLM/env as the MongoDB Agent page — Global Chat used to omit this and isolated env stripped Ollama/PwC keys. */
  const withMongoRagUserConfig = useCallback(
    (body: Record<string, unknown>) => {
      const ma = agents.find((a) => a.id === 'mongodb_rag');
      const uc = ma ? getUserConfigPayloadForRequest(ma) : undefined;
      return uc && Object.keys(uc).length > 0 ? { ...body, user_config: uc } : body;
    },
    [agents],
  );

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const ext = file.name.split('.').pop()?.toLowerCase() || '';
    const supported = ['pdf', 'docx', 'doc', 'pptx', 'ppt', 'xlsx', 'xls', 'txt', 'md', 'csv', 'html', 'htm', 'json', 'xml'];
    if (!supported.includes(ext)) {
      alert(`Unsupported file type ".${ext}". Supported: PDF, Word, PowerPoint, Excel, Text, HTML, CSV, JSON, XML.`);
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      const base64 = (reader.result as string).split(',')[1];
      setUploadedFile({ name: file.name, content: base64, type: ext, size: file.size });
    };
    reader.readAsDataURL(file);
    if (e.target) e.target.value = '';
  };

  const handleMongoUriSubmit = async () => {
    if (!mongoUri.trim() || isLoading) return;
    setShowMongoUriInput(false);
    setIsLoading(true);
    setCurrentThinkingStep('Connecting to MongoDB Atlas...');

    const sid = mongoSessionId || `mongo-${Date.now()}`;
    if (!mongoSessionId) setMongoSessionId(sid);

    const assistantMsg: ChatMessage = {
      role: 'assistant', content: '',
      routed_to: { agent_id: 'mongodb_rag', agent_name: 'MongoDB Atlas KB Agent', confidence: 1, reasoning: 'Direct MongoDB connection' },
      created_at: new Date().toISOString(),
    };
    setMessages(prev => [...prev, assistantMsg]);

    try {
      await streamMongoRAG(withMongoRagUserConfig({ query: 'connect', session_id: sid, mongodb_uri: mongoUri.trim() }) as Record<string, unknown>, {
        onThinking: (step) => {
          setCurrentThinkingStep(step.content || 'Connecting...');
          setMessages(prev => { const u = [...prev]; const l = u.length - 1; if (u[l]?.role === 'assistant') u[l] = { ...u[l], thinking_steps: [...(u[l].thinking_steps || []), step] }; return u; });
        },
        onResponseChunk: (chunk, meta) => {
          setMessages(prev => {
            const u = [...prev]; const l = u.length - 1;
            if (u[l]?.role === 'assistant') {
              const base = meta?.reset ? '' : (u[l].content || '');
              u[l] = { ...u[l], content: base + chunk };
            }
            return u;
          });
        },
        onDone: (data) => {
          setMessages(prev => { const u = [...prev]; const l = u.length - 1; if (u[l]?.role === 'assistant' && !u[l].content) u[l] = { ...u[l], content: data.response || 'Connection attempt completed.' }; return u; });
          if (data.connected) { setMongoConnected(true); setShowMongoFileUpload(true); } else { setShowMongoUriInput(true); }
        },
        onError: (err) => {
          setMessages(prev => { const u = [...prev]; const l = u.length - 1; if (u[l]?.role === 'assistant') u[l] = { ...u[l], content: `Failed to connect: ${err.message}` }; return u; });
          setShowMongoUriInput(true);
        },
      });
    } catch (error: any) {
      setMessages(prev => { const u = [...prev]; const l = u.length - 1; if (u[l]?.role === 'assistant') u[l] = { ...u[l], content: `Failed to connect: ${error.message}` }; return u; });
      setShowMongoUriInput(true);
    } finally {
      setIsLoading(false);
      setCurrentThinkingStep('');
      setMongoUri('');
    }
  };

  const handleMongoFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const ext = file.name.split('.').pop()?.toLowerCase() || '';
    const supported = ['pdf', 'docx', 'xlsx', 'pptx', 'txt'];
    if (!supported.includes(ext)) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `Unsupported file type ".${ext}". Please upload one of: PDF, Word (.docx), Excel (.xlsx), PowerPoint (.pptx), or Text (.txt).`,
        routed_to: { agent_id: 'mongodb_rag', agent_name: 'MongoDB Atlas KB Agent', confidence: 1, reasoning: 'File validation' },
        created_at: new Date().toISOString(),
      }]);
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      const base64 = (reader.result as string).split(',')[1];
      setMongoUploadedFile({ name: file.name, content: base64, type: ext });
    };
    reader.readAsDataURL(file);
    if (e.target) e.target.value = '';
  };

  const handleMongoIngest = async () => {
    if (!mongoUploadedFile || isLoading) return;
    setIsLoading(true);
    setCurrentThinkingStep(`Ingesting "${mongoUploadedFile.name}"...`);

    setMessages(prev => [...prev, { role: 'user', content: `Upload document: ${mongoUploadedFile.name}`, created_at: new Date().toISOString() }]);
    const assistantMsg: ChatMessage = {
      role: 'assistant', content: '',
      routed_to: { agent_id: 'mongodb_rag', agent_name: 'MongoDB Atlas KB Agent', confidence: 1, reasoning: 'Document ingestion' },
      created_at: new Date().toISOString(),
    };
    setMessages(prev => [...prev, assistantMsg]);

    try {
      await streamMongoRAG(withMongoRagUserConfig({
        query: 'ingest', session_id: mongoSessionId,
        file_content: mongoUploadedFile.content, file_type: mongoUploadedFile.type, file_name: mongoUploadedFile.name,
      }) as Record<string, unknown>, {
        onThinking: (step) => {
          setCurrentThinkingStep(step.content || 'Ingesting...');
          setMessages(prev => { const u = [...prev]; const l = u.length - 1; if (u[l]?.role === 'assistant') u[l] = { ...u[l], thinking_steps: [...(u[l].thinking_steps || []), step] }; return u; });
        },
        onResponseChunk: (chunk, meta) => {
          setMessages(prev => {
            const u = [...prev]; const l = u.length - 1;
            if (u[l]?.role === 'assistant') {
              const base = meta?.reset ? '' : (u[l].content || '');
              u[l] = { ...u[l], content: base + chunk };
            }
            return u;
          });
        },
        onDone: (data) => {
          setMessages(prev => { const u = [...prev]; const l = u.length - 1; if (u[l]?.role === 'assistant' && !u[l].content) u[l] = { ...u[l], content: data.response || 'Ingestion completed.' }; return u; });
          if (data.ingested) setMongoIngested(true);
        },
        onError: (err) => {
          setMessages(prev => { const u = [...prev]; const l = u.length - 1; if (u[l]?.role === 'assistant') u[l] = { ...u[l], content: `Ingestion failed: ${err.message}` }; return u; });
        },
      });
    } catch (error: any) {
      setMessages(prev => { const u = [...prev]; const l = u.length - 1; if (u[l]?.role === 'assistant') u[l] = { ...u[l], content: `Ingestion failed: ${error.message}` }; return u; });
    } finally {
      setIsLoading(false);
      setCurrentThinkingStep('');
      setMongoUploadedFile(null);
    }
  };

  const handleMongoQuery = async (queryText: string) => {
    if (!queryText.trim() || isLoading) return;
    setIsLoading(true);
    setCurrentThinkingStep('Searching your knowledge base...');

    setMessages(prev => [...prev, { role: 'user', content: queryText, created_at: new Date().toISOString() }]);
    setInput('');

    const assistantMsg: ChatMessage = {
      role: 'assistant', content: '',
      routed_to: { agent_id: 'mongodb_rag', agent_name: 'MongoDB Atlas KB Agent', confidence: 1, reasoning: 'RAG query' },
      created_at: new Date().toISOString(),
    };
    setMessages(prev => [...prev, assistantMsg]);

    try {
      await streamMongoRAG(withMongoRagUserConfig({ query: queryText, session_id: mongoSessionId }) as Record<string, unknown>, {
        onThinking: (step) => {
          setCurrentThinkingStep(step.content || 'Searching...');
          setMessages(prev => { const u = [...prev]; const l = u.length - 1; if (u[l]?.role === 'assistant') u[l] = { ...u[l], thinking_steps: [...(u[l].thinking_steps || []), step] }; return u; });
        },
        onResponseChunk: (chunk, meta) => {
          setMessages(prev => {
            const u = [...prev]; const l = u.length - 1;
            if (u[l]?.role === 'assistant') {
              const base = meta?.reset ? '' : (u[l].content || '');
              u[l] = { ...u[l], content: base + chunk };
            }
            return u;
          });
        },
        onDone: (data) => {
          setMessages(prev => {
            const u = [...prev];
            const l = u.length - 1;
            if (u[l]?.role !== 'assistant') return u;
            const cur = (u[l].content || '').trim();
            const srv = data.response != null ? String(data.response).trim() : '';
            if (srv) {
              if (!cur || srv.length > cur.length) u[l] = { ...u[l], content: String(data.response) };
            } else if (!cur) {
              u[l] = { ...u[l], content: 'No response received.' };
            }
            return u;
          });
        },
        onError: (err) => {
          setMessages(prev => { const u = [...prev]; const l = u.length - 1; if (u[l]?.role === 'assistant') u[l] = { ...u[l], content: `Query failed: ${err.message}` }; return u; });
        },
      });
    } catch (error: any) {
      setMessages(prev => { const u = [...prev]; const l = u.length - 1; if (u[l]?.role === 'assistant') u[l] = { ...u[l], content: `Query failed: ${error.message}` }; return u; });
    } finally {
      setIsLoading(false);
      setCurrentThinkingStep('');
    }
  };

  const fetchRagContext = async (queryText: string): Promise<string> => {
    if (!mongoConnected || !mongoIngested || !mongoSessionId) return '';
    try {
      const response = await fetch('/api/mongodb-rag/context', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: queryText,
          session_id: mongoSessionId,
        }),
      });
      if (!response.ok) return '';
      const data = await response.json();
      return data.context || '';
    } catch {
      return '';
    }
  };

  const _sendGlobalChatStream = async (query: string, extraBody?: Record<string, any>) => {
    const assistantMsg: ChatMessage = { role: 'assistant', content: '', created_at: new Date().toISOString() };
    setMessages(prev => [...prev, assistantMsg]);

    let doneData: any = null;

    const updateLast = (fn: (msg: ChatMessage) => ChatMessage) => {
      setMessages(prev => { const u = [...prev]; const l = u.length - 1; if (u[l]?.role === 'assistant') u[l] = fn(u[l]); return u; });
    };

    await streamGlobalChat({
      query,
      session_id: activeSessionId || undefined,
      skip_save: !isSaved,
      ...(selectedAgent !== 'auto' && { target_agent: selectedAgent }),
      ...extraBody,
    }, {
      onStart: () => setCurrentThinkingStep('Processing your query...'),
      onThinking: (step) => {
        setCurrentThinkingStep(step.content || 'Thinking...');
        updateLast(m => ({ ...m, thinking_steps: [...(m.thinking_steps || []), step] }));
      },
      onRouting: (info) => {
        updateLast(m => ({ ...m, routed_to: info as any }));
        setCurrentThinkingStep(`Routed to ${info.agent_name}...`);
      },
      onProgress: (data) => {
        setCurrentThinkingStep(data.message || data.stage || 'Processing...');
        updateLast(m => ({ ...m, thinking_steps: [...(m.thinking_steps || []), { type: 'thinking' as const, content: data.message || data.stage }] }));
      },
      onResponseChunk: (chunk, meta) => {
        updateLast(m => ({
          ...m,
          content: (meta?.reset ? '' : m.content) + chunk,
        }));
      },
      onDone: (data) => {
        doneData = data;
        updateLast(m => ({
          ...m,
          bpmn_xml: data.bpmn_xml || m.bpmn_xml,
          stackblitz_repo: data.stackblitz_repo || m.stackblitz_repo,
          latest_news_cards: data.latest_news_cards || m.latest_news_cards,
          chart_data: data.chart_data || m.chart_data,
          routed_to: data.routed_to || m.routed_to,
          ...((data.response && (String(m.content || '').trim().length < String(data.response).trim().length))
            ? { content: data.response }
            : {}),
        }));
      },
      onError: (err) => {
        updateLast(m => ({ ...m, content: `Error: ${err.message}` }));
      },
    });

    if (doneData?.session_id) {
      if (!activeSessionId) setActiveSessionId(doneData.session_id);
      if (isSaved) await loadSessions();
    }
    if (doneData?.requires_token) { setPendingPushQuery(query); setShowTokenInput(true); }
    if (doneData?.requires_uri || doneData?.routed_to?.agent_id === 'mongodb_rag') { setShowMongoUriInput(true); }

    if (doneData?.task_id) {
      const taskId = doneData.task_id;
      setCurrentThinkingStep('Generating unit tests... This may take a few minutes.');
      const pollResult = await new Promise<TaskStatusResponse>((resolve, reject) => {
        let lastStepCount = 0;
        const interval = setInterval(async () => {
          try {
            const status = await pollTaskStatus(taskId);
            if (status.thinking_steps && status.thinking_steps.length > lastStepCount) {
              setCurrentThinkingStep(status.progress || 'Processing...');
              lastStepCount = status.thinking_steps.length;
              updateLast(m => ({ ...m, thinking_steps: status.thinking_steps }));
            }
            if (status.status === 'completed') { clearInterval(interval); resolve(status); }
          } catch (err) { clearInterval(interval); reject(err); }
        }, 3000);
        setTimeout(() => { clearInterval(interval); reject(new Error('Timed out.')); }, 600000);
      });
      updateLast(m => ({ ...m, content: pollResult.response || 'Test generation completed.', thinking_steps: pollResult.thinking_steps }));
    }

    return doneData;
  };

  const handleSend = async (directMessage?: string) => {
    const msgText = directMessage || input.trim();
    const currentFile = uploadedFile;
    if ((!msgText && !currentFile) || isLoading) return;

    if (isListening && recognitionRef.current) {
      recognitionRef.current.stop();
      setIsListening(false);
    }

    if (mongoConnected && !mongoIngested) { handleMongoQuery(msgText); return; }

    if (mongoConnected && mongoIngested) {
      const displayContent = currentFile ? `${msgText || 'Process file'} [File: ${currentFile.name}]` : msgText;
      setMessages(prev => [...prev, { role: 'user', content: displayContent, created_at: new Date().toISOString() }]);
      if (!directMessage) setInput('');
      setUploadedFile(null);
      setIsLoading(true);
      setCurrentThinkingStep('Fetching relevant context from knowledge base...');
      if (inputRef.current) inputRef.current.style.height = 'auto';

      try {
        const ragContext = await fetchRagContext(msgText);
        const enrichedQuery = ragContext
          ? `[Knowledge Base Context from MongoDB RAG:\n${ragContext}\n]\n\nUser Query: ${msgText || `Process file: ${currentFile?.name}`}`
          : (msgText || `Process file: ${currentFile?.name}`);
        setCurrentThinkingStep('Routing to the best agent...');
        await _sendGlobalChatStream(enrichedQuery, currentFile ? { file_content: currentFile.content, file_type: currentFile.type, file_name: currentFile.name } : undefined);
      } catch (error: any) {
        setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${error.message}`, created_at: new Date().toISOString() }]);
      } finally {
        setIsLoading(false);
        setCurrentThinkingStep('');
      }
      return;
    }

    const displayContent = currentFile ? `${msgText || 'Process file'} [File: ${currentFile.name}]` : msgText;
    setMessages(prev => [...prev, { role: 'user', content: displayContent, created_at: new Date().toISOString() }]);
    const currentInput = msgText || (currentFile ? `Extract and format the content from this document: ${currentFile.name}` : '');
    if (!directMessage) setInput('');
    setUploadedFile(null);
    setIsLoading(true);
    setCurrentThinkingStep('Analyzing your query...');
    if (inputRef.current) inputRef.current.style.height = 'auto';

    try {
      await _sendGlobalChatStream(currentInput, currentFile ? { file_content: currentFile.content, file_type: currentFile.type, file_name: currentFile.name } : undefined);
    } catch (error: any) {
      setMessages(prev => [...prev, { role: 'assistant', content: `Something went wrong: ${error.message}`, created_at: new Date().toISOString() }]);
    } finally {
      setIsLoading(false);
      setCurrentThinkingStep('');
    }
  };

  useEffect(() => {
    if (voiceAutoSend && input.trim()) {
      setVoiceAutoSend(false);
      handleSend();
    } else if (voiceAutoSend) {
      setVoiceAutoSend(false);
    }
  }, [voiceAutoSend]);

  const prevMessagesLenRef = useRef(0);
  useEffect(() => {
    if (voiceMode && messages.length > prevMessagesLenRef.current) {
      const last = messages[messages.length - 1];
      if (last?.role === 'assistant' && !isLoading) {
        speakText(last.content);
      }
    }
    prevMessagesLenRef.current = messages.length;
  }, [messages, isLoading, voiceMode]);

  const handleTokenSubmit = async () => {
    if (!githubToken.trim() || isLoading) return;
    setShowTokenInput(false);
    setIsLoading(true);
    setCurrentThinkingStep('Pushing changes to GitHub...');

    try {
      await _sendGlobalChatStream(pendingPushQuery || 'push the code to GitHub', { github_token: githubToken.trim() });
      if (isSaved) await loadSessions();
    } catch (error: any) {
      setMessages(prev => [...prev, { role: 'assistant', content: `Something went wrong: ${error.message}`, created_at: new Date().toISOString() }]);
    } finally {
      setIsLoading(false);
      setCurrentThinkingStep('');
      setGithubToken('');
      setPendingPushQuery('');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleTextareaInput = () => {
    if (inputRef.current) {
      inputRef.current.style.height = 'auto';
      inputRef.current.style.height = Math.min(inputRef.current.scrollHeight, 200) + 'px';
    }
  };

  const filteredSessions = sessions.filter(s =>
    s.title.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const groupedSessions = (() => {
    const today: ChatSession[] = [];
    const yesterday: ChatSession[] = [];
    const thisWeek: ChatSession[] = [];
    const older: ChatSession[] = [];
    const now = new Date();

    filteredSessions.forEach(s => {
      const d = new Date(s.updated_at);
      const diffDays = Math.floor((now.getTime() - d.getTime()) / 86400000);
      if (diffDays === 0) today.push(s);
      else if (diffDays === 1) yesterday.push(s);
      else if (diffDays < 7) thisWeek.push(s);
      else older.push(s);
    });

    return { today, yesterday, thisWeek, older };
  })();

  const examplePrompts = [
    { text: "Latest SEBI regulations on insider trading", icon: "📊" },
    { text: "Search the web for AI trends in 2025", icon: "🔍" },
    { text: "Create a JIRA ticket for a login bug fix", icon: "🎫" },
    { text: "Generate a BRD for a mobile banking app", icon: "📄" },
    { text: "Market research on Indian fintech sector", icon: "📈" },
    { text: "I want to set up RAG with my MongoDB Atlas", icon: "🍃" },
  ];

  const renderSessionGroup = (label: string, items: ChatSession[]) => {
    if (items.length === 0) return null;
    return (
        <div className="mb-2">
        <div className="px-3 py-1.5 font-body text-[10px] font-semibold uppercase tracking-wider text-zinc-600">{label}</div>
        {items.map(session => (
          <div
            key={session.id}
            onClick={() => selectSession(session.id)}
            className={`group mx-1 flex cursor-pointer items-center gap-2 rounded-xl px-3 py-2.5 font-body text-sm transition-all ${
              activeSessionId === session.id
                ? 'bg-white/[0.1] text-gray-900 dark:text-white ring-1 ring-primary-500/25'
                : 'text-zinc-400 hover:bg-white/[0.05] hover:text-gray-900 dark:hover:text-white'
            }`}
          >
            <MessageSquare className="h-4 w-4 shrink-0 text-zinc-500" />
            {editingSessionId === session.id ? (
              <div className="flex-1 flex items-center gap-1" onClick={e => e.stopPropagation()}>
                <input
                  value={editTitle}
                  onChange={e => setEditTitle(e.target.value)}
                  className="flex-1 rounded border border-white/[0.1] bg-zinc-800 px-1.5 py-0.5 font-body text-sm text-gray-900 dark:text-white outline-none"
                  autoFocus
                  onKeyDown={e => { if (e.key === 'Enter') saveTitle(e as any); if (e.key === 'Escape') setEditingSessionId(null); }}
                />
                <button onClick={saveTitle} className="p-0.5 hover:text-green-400"><Check className="w-3.5 h-3.5" /></button>
                <button onClick={(e) => { e.stopPropagation(); setEditingSessionId(null); }} className="p-0.5 hover:text-red-400"><X className="w-3.5 h-3.5" /></button>
              </div>
            ) : (
              <>
                <span className="flex-1 truncate">{session.title}</span>
                <div className="hidden group-hover:flex items-center gap-0.5">
                  <button onClick={(e) => startEditTitle(session, e)} className="p-1 hover:text-blue-400 rounded transition-colors"><Edit3 className="w-3 h-3" /></button>
                  <button onClick={(e) => deleteSession(session.id, e)} className="p-1 hover:text-red-400 rounded transition-colors"><Trash2 className="w-3 h-3" /></button>
                </div>
              </>
            )}
          </div>
        ))}
      </div>
    );
  };

  return (
    <div
      className={
        embedded
          ? 'flex min-h-0 w-full min-w-0 flex-1 flex-row overflow-hidden bg-transparent'
          : 'flex h-[calc(100vh-64px)] flex-row bg-zinc-950'
      }
    >
      {sidebarOpen && (
        <div className="flex w-64 shrink-0 flex-col border-r border-gray-200 dark:border-white/[0.06] bg-zinc-950/70 backdrop-blur-xl">
          <div className="p-3">
            <button
              type="button"
              onClick={createNewChat}
              className="flex w-full items-center gap-2 rounded-xl border border-gray-200 dark:border-white/[0.08] bg-gradient-to-r from-primary-500/20 to-violet-600/15 px-3 py-2.5 font-body text-sm font-semibold text-gray-900 dark:text-white shadow-sm transition-all hover:border-primary-500/30 hover:from-primary-500/30 hover:to-violet-600/25"
            >
              <Plus className="h-4 w-4" />
              New chat
            </button>
          </div>

          <div className="px-3 pb-2">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-500" />
              <input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search chats…"
                className="w-full rounded-lg border border-gray-200 dark:border-white/[0.08] bg-zinc-900/80 py-1.5 pl-8 pr-3 font-body text-xs text-zinc-200 placeholder-zinc-600 outline-none transition-colors focus:border-primary-500/35 focus:ring-1 focus:ring-primary-500/20"
              />
            </div>
          </div>

          <div className="scrollbar-thin flex-1 overflow-y-auto">
            {sessions.length === 0 ? (
              <div className="px-4 py-8 text-center font-body text-xs text-zinc-500">No conversations yet</div>
            ) : (
              <>
                {renderSessionGroup('Today', groupedSessions.today)}
                {renderSessionGroup('Yesterday', groupedSessions.yesterday)}
                {renderSessionGroup('This Week', groupedSessions.thisWeek)}
                {renderSessionGroup('Older', groupedSessions.older)}
              </>
            )}
          </div>
        </div>
      )}

      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="flex items-center justify-between border-b border-gray-200 dark:border-white/[0.06] bg-zinc-950/40 px-4 py-2.5 backdrop-blur-md">
          <div className="flex min-w-0 items-center gap-2">
            <button
              type="button"
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="rounded-lg p-1.5 text-zinc-400 transition-colors hover:bg-gray-100 dark:hover:bg-white/[0.06] hover:text-gray-900 dark:hover:text-white"
            >
              {sidebarOpen ? <PanelLeftClose className="h-5 w-5" /> : <PanelLeft className="h-5 w-5" />}
            </button>
            <div className="flex min-w-0 items-center gap-2">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-primary-500/30 to-violet-600/25 ring-1 ring-white/10">
                <Bot className="h-4 w-4 text-primary-200" />
              </div>
              <span className="truncate font-body text-sm font-semibold text-zinc-100">
                {activeSessionId
                  ? sessions.find(s => s.id === activeSessionId)?.title || 'Chat'
                  : 'New chat'}
              </span>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {messages.length > 0 && !isSaved && (
              <button
                type="button"
                onClick={saveCurrentChat}
                disabled={savingChat}
                className="flex h-8 items-center gap-1.5 rounded-lg border border-primary-500/35 bg-primary-500/15 px-3 font-body text-xs font-semibold text-primary-200 transition-all hover:bg-primary-500/25 disabled:opacity-50"
                title="Save this conversation to history"
              >
                {savingChat ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Bookmark className="h-3.5 w-3.5" />
                )}
                <span>Save</span>
              </button>
            )}
            {messages.length > 0 && isSaved && (
              <div className="flex h-8 items-center gap-1.5 rounded-lg border border-emerald-500/25 bg-emerald-500/10 px-3 font-body text-xs font-medium text-emerald-300">
                <CheckCircle2 className="h-3.5 w-3.5" />
                <span>Saved</span>
              </div>
            )}
          <div ref={agentDropdownRef} className="relative">
            <button
              type="button"
              onClick={() => setAgentDropdownOpen(!agentDropdownOpen)}
              className={`flex h-8 items-center gap-1.5 rounded-lg border px-3 font-body text-xs font-medium transition-all ${
                selectedAgent === 'auto'
                  ? 'border-gray-200 dark:border-white/[0.08] bg-white/[0.05] text-zinc-300 hover:border-white/[0.12]'
                  : 'border-primary-500/30 bg-primary-500/10 text-primary-200 hover:border-primary-400/40'
              }`}
              title="Select agent"
            >
              {selectedAgent === 'auto' ? (
                <Zap className="w-3.5 h-3.5" />
              ) : (() => {
                const a = agents.find(a => a.id === selectedAgent);
                return a && (a.logo.startsWith('/') || a.logo.startsWith('http'))
                  ? <img src={a.logo} alt={a.name} className="w-4 h-4 object-contain" />
                  : <Bot className="w-3.5 h-3.5" />;
              })()}
              <span className="max-w-[100px] truncate">
                {selectedAgent === 'auto' ? 'Auto' : (agents.find(a => a.id === selectedAgent)?.name || selectedAgent)}
              </span>
              <ChevronDown className={`w-3 h-3 transition-transform ${agentDropdownOpen ? 'rotate-180' : ''}`} />
            </button>
            {agentDropdownOpen && (
              <div className="absolute right-0 top-full z-50 mt-1 flex max-h-96 w-64 flex-col overflow-hidden rounded-xl border border-gray-200 dark:border-white/[0.08] bg-zinc-950/95 shadow-2xl shadow-black/50 ring-1 ring-white/[0.04] backdrop-blur-xl">
                <div className="shrink-0 border-b border-gray-200 dark:border-white/[0.06] p-2">
                  <div className="relative">
                    <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-500" />
                    <input
                      type="text"
                      value={agentSearchQuery}
                      onChange={(e) => setAgentSearchQuery(e.target.value)}
                      placeholder="Search agents…"
                      className="w-full rounded-lg border border-gray-200 dark:border-white/[0.08] bg-zinc-900/80 py-1.5 pl-8 pr-3 font-body text-xs text-gray-900 dark:text-white placeholder-zinc-600 outline-none focus:border-primary-500/35"
                      autoFocus
                    />
                  </div>
                </div>
                <div className="flex-1 overflow-y-auto">
                  {!agentSearchQuery && (
                    <>
                      <button
                        type="button"
                        onClick={() => {
                          setSelectedAgent('auto');
                          setAgentDropdownOpen(false);
                          setAgentSearchQuery('');
                        }}
                        className={`flex w-full items-center gap-3 px-4 py-3 text-left font-body text-sm transition-colors ${
                          selectedAgent === 'auto' ? 'bg-primary-500/15 text-primary-200' : 'text-zinc-300 hover:bg-gray-100 dark:hover:bg-white/[0.06]'
                        }`}
                      >
                        <Zap className="h-4 w-4 shrink-0" />
                        <div>
                          <div className="font-medium">Auto</div>
                          <div className="text-xs text-zinc-500">AI picks the best agent</div>
                        </div>
                      </button>
                      <div className="border-t border-gray-200 dark:border-white/[0.06]" />
                    </>
                  )}
                  {agents
                    .filter(a => !agentSearchQuery || a.name.toLowerCase().includes(agentSearchQuery.toLowerCase()) || a.type.toLowerCase().includes(agentSearchQuery.toLowerCase()))
                    .map(agent => (
                    <button
                      type="button"
                      key={agent.id}
                      onClick={() => {
                        setSelectedAgent(agent.id);
                        setAgentDropdownOpen(false);
                        setAgentSearchQuery('');
                      }}
                      className={`flex w-full items-center gap-3 px-4 py-2.5 text-left font-body text-sm transition-colors ${
                        selectedAgent === agent.id ? 'bg-primary-500/15 text-primary-200' : 'text-zinc-300 hover:bg-gray-100 dark:hover:bg-white/[0.06]'
                      }`}
                    >
                      {agent.logo.startsWith('/') || agent.logo.startsWith('http') ? (
                        <img src={agent.logo} alt={agent.name} className="w-5 h-5 object-contain flex-shrink-0" />
                      ) : (
                        <span className="text-lg flex-shrink-0">{agent.logo}</span>
                      )}
                      <div className="min-w-0">
                        <div className="font-medium truncate">{agent.name}</div>
                        <div className="truncate font-body text-xs text-zinc-500">{agent.type}</div>
                      </div>
                    </button>
                  ))}
                  {agentSearchQuery && agents.filter(a => a.name.toLowerCase().includes(agentSearchQuery.toLowerCase()) || a.type.toLowerCase().includes(agentSearchQuery.toLowerCase())).length === 0 && (
                    <div className="px-4 py-3 text-center font-body text-xs text-zinc-500">No agents found</div>
                  )}
                </div>
              </div>
            )}
          </div>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {messages.length === 0 ? (
            <div className="relative flex h-full flex-col items-center justify-center overflow-hidden px-4">
              <div className="pointer-events-none absolute inset-0 z-0">
                <img src="/images/chat-bg.png" alt="" className="h-full w-full object-cover opacity-[0.35]" />
                <div className="absolute inset-0 bg-gradient-to-t from-zinc-950 via-zinc-950/50 to-transparent" />
                <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(99,102,241,0.12),transparent_55%)]" />
              </div>
              <div className="relative z-10 w-full max-w-2xl text-center">
                <div className="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-primary-500 to-violet-600 shadow-lg shadow-primary-900/40 ring-1 ring-white/10">
                  <Bot className="h-9 w-9 text-gray-900 dark:text-white" />
                </div>
                <h2 className="mb-2 font-heading text-2xl font-bold tracking-tight text-gray-900 dark:text-white">How can we help?</h2>
                <p className="mb-8 font-body text-sm text-zinc-500">
                  The router picks the right agent. Choose a starter or type your own message below.
                </p>
                <div className="mx-auto grid max-w-xl grid-cols-1 gap-2.5 sm:grid-cols-2 sm:gap-3">
                  {examplePrompts.map((prompt, index) => (
                    <button
                      key={index}
                      type="button"
                      onClick={() => setInput(prompt.text)}
                      className="group relative flex items-start gap-3 overflow-hidden rounded-2xl border border-gray-200 dark:border-white/[0.08] bg-zinc-900/50 px-4 py-3.5 text-left backdrop-blur-sm transition-all duration-200 hover:-translate-y-0.5 hover:border-primary-500/35 hover:bg-zinc-900/80 hover:shadow-lg hover:shadow-primary-900/20"
                    >
                      <span className="relative mt-0.5 text-lg transition-transform duration-200 group-hover:scale-110">{prompt.icon}</span>
                      <span className="relative font-body text-sm font-medium leading-snug text-gray-700 dark:text-zinc-300 group-hover:text-gray-900 dark:group-hover:text-white">{prompt.text}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className="mx-auto max-w-3xl space-y-6 px-4 py-6">
              {messages.map((message, index) => (
                <div key={index} className="group">
                  {message.role === 'user' ? (
                    <div className="flex justify-end">
                      <div className="max-w-[80%]">
                        {(() => {
                          const fileMatch = message.content.match(/\[File:\s*(.+?)\]$/);
                          const textContent = fileMatch ? message.content.replace(/\s*\[File:\s*.+?\]$/, '') : message.content;
                          const fileName = fileMatch?.[1];
                          return (
                            <div className="flex flex-col items-end gap-1.5">
                              {fileName && (
                                <FileAttachmentBubble fileName={fileName} variant="dark" />
                              )}
                              {textContent.trim() && (
                                <div className="rounded-2xl rounded-br-md bg-gradient-to-br from-primary-600 to-violet-700 px-4 py-3 text-gray-900 dark:text-white shadow-md shadow-primary-950/30 ring-1 ring-white/10">
                                  <p className="whitespace-pre-wrap font-body text-sm leading-relaxed">{textContent.trim()}</p>
                                </div>
                              )}
                            </div>
                          );
                        })()}
                      </div>
                    </div>
                  ) : (
                    <div className="flex gap-3">
                      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-primary-500 to-violet-600 ring-1 ring-white/10">
                        <Bot className="h-4 w-4 text-gray-900 dark:text-white" />
                      </div>
                      <div className="flex-1 min-w-0">
                        {message.thinking_steps && message.thinking_steps.length > 0 && (
                          <ThinkingStepsDisplay steps={message.thinking_steps} />
                        )}
                        {message.routed_to && (
                          <RoutedAgentBadge info={message.routed_to} />
                        )}
                        {isTestReport(message.content) ? (
                          <TestReportView content={message.content} />
                        ) : isCompanyAiSolutionsReport(message.content) ? (
                          <CompanyAiSolutionsView content={message.content} />
                        ) : isCompanyResearchReport(message.content) ? (
                          <CompanyReportView content={message.content} newsCards={message.latest_news_cards} />
                        ) : isDocumentResponse(message.content) ? (
                          <DocumentView
                            content={message.content}
                            subtitle={message.routed_to?.agent_name || 'Formatted Document'}
                          />
                        ) : (
                        <div className="prose prose-sm prose-invert max-w-none text-zinc-200">
                          <ReactMarkdown
                            remarkPlugins={[remarkGfm]}
                            components={{
                              a: ({ href, children }) => (
                                <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary-400 underline hover:text-primary-300">{children}</a>
                              ),
                              code: ({ children, className }) => {
                                const isBlock = className?.includes('language-');
                                const isMermaid = className?.includes('language-mermaid');
                                if (isMermaid) {
                                  const code = String(children).replace(/\n$/, '');
                                  const isArchDiagram = code.includes('graph ') || code.includes('flowchart ');
                                  const isDataFlow = code.includes('sequenceDiagram');
                                  const diagramType: 'architecture' | 'dataflow' | null =
                                    isArchDiagram ? 'architecture' : isDataFlow ? 'dataflow' : null;
                                  return (
                                    <MermaidDiagram
                                      chart={code}
                                      onRegenerate={diagramType ? () => handleRegenerateDiagram(diagramType) : undefined}
                                      isRegenerating={regeneratingDiagram === diagramType}
                                    />
                                  );
                                }
                                if (isBlock) {
                                  if (message.bpmn_xml) {
                                    return (
                                      <details className="my-1">
                                        <summary className="cursor-pointer text-xs text-gray-600 dark:text-gray-400 hover:text-gray-300 select-none">View XML source</summary>
                                        <div className="bg-gray-100 dark:bg-gray-800 rounded-lg overflow-x-auto my-1 max-h-48 overflow-y-auto">
                                          <pre className="p-3 text-xs"><code>{children}</code></pre>
                                        </div>
                                      </details>
                                    );
                                  }
                                  return (
                                    <div className="bg-gray-100 dark:bg-gray-800 rounded-lg overflow-x-auto my-2">
                                      <pre className="p-3 text-xs"><code>{children}</code></pre>
                                    </div>
                                  );
                                }
                                return <code className="rounded bg-gray-100 dark:bg-zinc-800 px-1 py-0.5 font-mono text-xs text-primary-700 dark:text-primary-300">{children}</code>;
                              },
                              pre: ({ children }) => {
                                const child = children as any;
                                if (child?.props?.className?.includes('language-mermaid') || message.bpmn_xml) {
                                  return <>{children}</>;
                                }
                                return <pre>{children}</pre>;
                              },
                              p: ({ children }) => <p className="mb-3 last:mb-0 leading-relaxed">{children}</p>,
                              ul: ({ children }) => <ul className="list-disc pl-4 mb-3 space-y-1">{children}</ul>,
                              ol: ({ children }) => <ol className="list-decimal pl-4 mb-3 space-y-1">{children}</ol>,
                              li: ({ children }) => <li className="text-sm">{children}</li>,
                              h1: ({ children }) => <h1 className="text-lg font-bold text-gray-900 dark:text-white mt-4 mb-2">{children}</h1>,
                              h2: ({ children }) => <h2 className="text-base font-bold text-gray-900 dark:text-white mt-3 mb-2">{children}</h2>,
                              h3: ({ children }) => <h3 className="text-sm font-bold text-gray-900 dark:text-white mt-3 mb-1">{children}</h3>,
                              blockquote: ({ children }) => (
                                <blockquote className="my-2 border-l-2 border-primary-500/60 pl-3 italic text-zinc-400">{children}</blockquote>
                              ),
                              table: ({ children }) => (
                                <div className="overflow-x-auto my-3">
                                  <table className="min-w-full border-collapse border border-gray-200 dark:border-gray-700 text-sm">{children}</table>
                                </div>
                              ),
                              thead: ({ children }) => <thead className="bg-gray-100 dark:bg-gray-800">{children}</thead>,
                              th: ({ children }) => <th className="border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-left font-semibold text-gray-200 align-top break-words whitespace-normal">{children}</th>,
                              td: ({ children }) => <td className="border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-gray-700 dark:text-gray-300 align-top break-words whitespace-normal min-w-0">{children}</td>,
                            }}
                          >{message.content}</ReactMarkdown>
                          {!isLoading && index === messages.length - 1 && (
                            <SuggestionChips content={message.content} onSuggestionClick={handleSuggestionClick} disabled={isLoading} darkMode={true} />
                          )}
                        </div>
                        )}
                        {message.bpmn_xml && (
                          <div className="mt-3">
                            <BPMNViewer xml={message.bpmn_xml} />
                          </div>
                        )}
                        {message.stackblitz_repo && (
                          <StackBlitzEmbed repoSlug={message.stackblitz_repo} darkMode={true} />
                        )}
                        {message.chart_data && (
                          <JiraDashboard data={message.chart_data} />
                        )}
                        {message.routed_to?.agent_id === 'meeting_prep' && message.latest_news_cards && message.latest_news_cards.length > 0 && (
                          <div className="mt-3 w-full min-w-0">
                            <LatestNewsCardsSection newsCards={message.latest_news_cards} />
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              ))}

              {isLoading && (
                <div className="flex gap-3">
                  <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-primary-500 to-violet-600 ring-1 ring-white/10">
                    <Bot className="h-4 w-4 text-gray-900 dark:text-white" />
                  </div>
                  <div className="flex-1">
                    <div className="mb-2 flex items-center gap-2 font-body text-xs text-violet-400">
                      <Brain className="w-3 h-3 animate-pulse" />
                      <span>{currentThinkingStep}</span>
                    </div>
                    <div className="flex gap-1">
                      <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                      <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                      <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                    </div>
                  </div>
                </div>
              )}

              {showTokenInput && (
                <div className="flex gap-3">
                  <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-primary-500 to-violet-600 ring-1 ring-white/10">
                    <Key className="h-4 w-4 text-gray-900 dark:text-white" />
                  </div>
                  <div className="flex-1 max-w-lg">
                    <div className="bg-orange-900/20 border border-orange-800 rounded-xl px-4 py-3">
                      <p className="text-sm font-medium text-orange-300 mb-1">Enter your GitHub Personal Access Token</p>
                      <p className="text-xs text-orange-400/70 mb-3">Your token is used only for this push and is not stored.</p>
                      <div className="flex gap-2">
                        <input
                          type="password"
                          value={githubToken}
                          onChange={e => setGithubToken(e.target.value)}
                          onKeyDown={e => e.key === 'Enter' && handleTokenSubmit()}
                          placeholder="ghp_xxxxxxxxxxxx"
                          className="flex-1 px-3 py-2 text-sm bg-gray-100 dark:bg-gray-800 border border-orange-700 rounded-lg outline-none focus:ring-2 focus:ring-orange-500 text-gray-900 dark:text-white placeholder-gray-500"
                          autoFocus
                        />
                        <button
                          onClick={handleTokenSubmit}
                          disabled={!githubToken.trim()}
                          className="px-4 py-2 text-sm font-medium text-gray-900 dark:text-white bg-orange-600 hover:bg-orange-500 disabled:bg-gray-700 disabled:text-gray-500 rounded-lg transition-colors"
                        >
                          Push
                        </button>
                        <button
                          onClick={() => { setShowTokenInput(false); setGithubToken(''); setPendingPushQuery(''); }}
                          className="px-3 py-2 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-800 rounded-lg transition-colors"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {showMongoUriInput && (
                <div className="flex gap-3">
                  <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-green-600 to-green-800 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <Database className="w-4 h-4 text-gray-900 dark:text-white" />
                  </div>
                  <div className="flex-1 max-w-lg">
                    <div className="bg-green-900/20 border border-green-800 rounded-xl px-4 py-3">
                      <p className="text-sm font-medium text-green-300 mb-1">Enter your MongoDB Atlas Connection URI</p>
                      <p className="text-xs text-green-400/70 mb-3">Your URI is used only for this session and is not stored permanently.</p>
                      <div className="flex gap-2">
                        <input
                          type="password"
                          value={mongoUri}
                          onChange={e => setMongoUri(e.target.value)}
                          onKeyDown={e => e.key === 'Enter' && handleMongoUriSubmit()}
                          placeholder="mongodb+srv://user:pass@cluster.xxxxx.mongodb.net/"
                          className="flex-1 px-3 py-2 text-sm bg-gray-100 dark:bg-gray-800 border border-green-700 rounded-lg outline-none focus:ring-2 focus:ring-green-500 text-gray-900 dark:text-white placeholder-gray-500"
                          autoFocus
                        />
                        <button
                          onClick={handleMongoUriSubmit}
                          disabled={!mongoUri.trim()}
                          className="px-4 py-2 text-sm font-medium text-gray-900 dark:text-white bg-green-600 hover:bg-green-500 disabled:bg-gray-700 disabled:text-gray-500 rounded-lg transition-colors"
                        >
                          Connect
                        </button>
                        <button
                          onClick={() => { setShowMongoUriInput(false); setMongoUri(''); }}
                          className="px-3 py-2 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-800 rounded-lg transition-colors"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {showMongoFileUpload && mongoConnected && (
                <div className="flex gap-3">
                  <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-green-600 to-green-800 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <Database className="w-4 h-4 text-gray-900 dark:text-white" />
                  </div>
                  <div className="flex-1 max-w-lg">
                    <div className="bg-green-900/20 border border-green-800 rounded-xl px-4 py-3">
                      <div className="flex items-center gap-2 mb-2">
                        <CheckCircle2 className="w-4 h-4 text-green-400" />
                        <p className="text-sm font-medium text-green-300">Connected to MongoDB Atlas</p>
                      </div>
                      <p className="text-xs text-green-400/70 mb-3">
                        {mongoIngested
                          ? 'Documents ingested! You can upload more files or ask questions below.'
                          : 'Upload documents to build your knowledge base, then ask questions.'}
                      </p>
                      <input
                        ref={mongoFileInputRef}
                        type="file"
                        onChange={handleMongoFileSelect}
                        accept=".pdf,.docx,.xlsx,.pptx,.txt"
                        className="hidden"
                      />
                      <div className="flex items-center gap-2">
                        {!mongoUploadedFile ? (
                          <button
                            onClick={() => mongoFileInputRef.current?.click()}
                            disabled={isLoading}
                            className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-gray-900 dark:text-white bg-green-600 hover:bg-green-500 disabled:bg-gray-700 disabled:text-gray-500 rounded-lg transition-colors"
                          >
                            <Upload className="w-4 h-4" />
                            Upload Document
                          </button>
                        ) : (
                          <>
                            <div className="flex items-center gap-2 px-3 py-2 bg-gray-100 dark:bg-gray-800 rounded-lg border border-green-700 text-sm text-green-300">
                              <FileText className="w-4 h-4" />
                              <span className="truncate max-w-[200px]">{mongoUploadedFile.name}</span>
                              <button onClick={() => setMongoUploadedFile(null)} className="text-gray-600 dark:text-gray-400 hover:text-red-400 ml-1">
                                <X className="w-3 h-3" />
                              </button>
                            </div>
                            <button
                              onClick={handleMongoIngest}
                              disabled={isLoading}
                              className="px-4 py-2 text-sm font-medium text-gray-900 dark:text-white bg-green-600 hover:bg-green-500 disabled:bg-gray-700 disabled:text-gray-500 rounded-lg transition-colors"
                            >
                              Ingest
                            </button>
                          </>
                        )}
                        {mongoIngested && (
                          <button
                            onClick={() => { setShowMongoFileUpload(false); inputRef.current?.focus(); }}
                            className="px-3 py-2 text-sm text-green-700 dark:text-green-400 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors"
                          >
                            Start Asking Questions
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        <div className="border-t border-gray-200 dark:border-white/[0.06] bg-zinc-950/80 px-4 py-3 backdrop-blur-md">
          <div className="mx-auto max-w-3xl">
            {mongoConnected && (
              <div className="flex items-center gap-2 mb-2 px-1">
                <div className="flex items-center gap-1.5 px-2 py-1 bg-green-900/30 border border-green-800/50 rounded-md text-xs text-green-400">
                  <Database className="w-3 h-3" />
                  <span>MongoDB RAG Active</span>
                  {mongoIngested && <CheckCircle2 className="w-3 h-3 text-green-400" />}
                </div>
                <button
                  onClick={() => { resetMongoState(); }}
                  className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
                >
                  Disconnect
                </button>
              </div>
            )}
            <input
              ref={fileInputRef}
              type="file"
              onChange={handleFileSelect}
              accept=".pdf,.docx,.doc,.pptx,.ppt,.xlsx,.xls,.txt,.md,.csv,.html,.htm,.json,.xml"
              className="hidden"
            />
            {uploadedFile && (
              <div className="mb-2 max-w-xs">
                <FileAttachmentInput
                  file={uploadedFile}
                  onRemove={() => setUploadedFile(null)}
                  variant="dark"
                />
              </div>
            )}
            <div
              className={`flex items-end gap-1.5 rounded-2xl border bg-zinc-900/80 px-2 py-1.5 shadow-lg shadow-black/25 backdrop-blur-sm transition-all focus-within:border-primary-500/35 focus-within:bg-zinc-900 ${
                mongoConnected ? 'border-emerald-500/35' : 'border-white/[0.1]'
              }`}
            >
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={isLoading}
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-zinc-400 transition-all hover:bg-gray-100 dark:hover:bg-white/[0.06] hover:text-primary-400 disabled:text-zinc-600"
                title="Attach a file (PDF, Word, Excel, PowerPoint, etc.)"
              >
                <Paperclip className="w-4 h-4" />
              </button>
              <textarea
                ref={inputRef}
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                onInput={handleTextareaInput}
                placeholder={mongoConnected ? 'Ask about your documents...' : selectedAgent === 'auto' ? 'Message the AI agents...' : `Message ${agents.find(a => a.id === selectedAgent)?.name || 'agent'}...`}
                rows={1}
                className="min-h-[36px] max-h-[160px] flex-1 resize-none bg-transparent py-2 font-body text-sm text-gray-900 dark:text-zinc-100 outline-none placeholder-gray-400 dark:placeholder-zinc-600"
                disabled={isLoading}
              />
              <div className="flex items-center gap-0.5 flex-shrink-0">
                {speechSupported && (
                  <div className="relative">
                    <button
                      onClick={toggleVoice}
                      disabled={isLoading}
                      className={`w-9 h-9 flex items-center justify-center rounded-xl transition-all ${
                        isListening
                          ? 'bg-red-500/20 text-red-400 hover:bg-red-500/30 animate-pulse'
                          : 'text-zinc-400 hover:bg-gray-100 dark:hover:bg-white/[0.06] hover:text-primary-400'
                      } disabled:cursor-not-allowed disabled:text-zinc-600`}
                      title={isListening ? 'Stop listening' : wakeListening ? 'Say "Hi MIRA" or Ctrl+M • Click for voice' : 'Voice input (Ctrl+M)'}
                      type="button"
                    >
                      {isListening ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
                    </button>
                    {wakeListening && !voiceMode && !isListening && (
                      <span className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-green-500 rounded-full animate-pulse" />
                    )}
                  </div>
                )}
                <button
                  onClick={() => handleSend()}
                  disabled={(!input.trim() && !uploadedFile) || isLoading}
                  className={`flex h-9 w-9 items-center justify-center rounded-xl text-gray-900 dark:text-white transition-all disabled:cursor-not-allowed disabled:bg-transparent disabled:text-zinc-600 ${
                    mongoConnected ? 'bg-emerald-600 hover:bg-emerald-500' : 'bg-gradient-to-br from-primary-600 to-violet-600 hover:from-primary-500 hover:to-violet-500'
                  }`}
                >
                  {isLoading ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Send className="w-4 h-4" />
                  )}
                </button>
              </div>
            </div>
            <p className="mt-1.5 text-center font-body text-[11px] text-zinc-600">
              {wakeListening && !voiceMode ? (
                <span className="inline-flex items-center gap-1">
                  <span className="w-1.5 h-1.5 bg-green-500 rounded-full animate-pulse inline-block" />
                  Say <span className="text-green-500/80 font-medium">"Hi MIRA"</span> or press <span className="text-green-500/80 font-medium">Ctrl+M</span> for voice
                </span>
              ) : speechSupported && !voiceMode ? (
                <span className="inline-flex items-center gap-1">
                  Press <span className="font-medium text-primary-400">Ctrl+M</span> or click <span className="font-medium text-primary-400">mic</span> for voice chat
                </span>
              ) : (
                'AI agents may produce inaccurate information. Verify important details.'
              )}
            </p>
          </div>
        </div>
      </div>

      {voiceMode && (
        <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-white/95 dark:bg-gray-950/95 backdrop-blur-xl">
          <button
            onClick={stopVoiceMode}
            className="absolute top-6 right-6 p-2 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-800 rounded-xl transition-colors"
            title="Exit voice mode"
            type="button"
          >
            <X className="w-6 h-6" />
          </button>

          <div className="flex flex-col items-center gap-8 max-w-lg px-6 text-center">
            <div className={`relative w-32 h-32 rounded-full flex items-center justify-center transition-all duration-500 ${
              isListening
                ? 'bg-gradient-to-br from-orange-500 to-red-500 shadow-2xl shadow-orange-500/40'
                : speakingResponse
                  ? 'bg-gradient-to-br from-blue-500 to-purple-500 shadow-2xl shadow-blue-500/40'
                  : isLoading
                    ? 'bg-gradient-to-br from-orange-600 to-amber-500 shadow-2xl shadow-orange-500/30'
                    : 'bg-gray-100 dark:bg-gray-800 border-2 border-gray-200 dark:border-gray-700'
            }`}>
              {isListening && (
                <>
                  <div className="absolute inset-0 rounded-full bg-orange-500/30 animate-ping" />
                  <div className="absolute -inset-3 rounded-full border-2 border-orange-400/20 animate-pulse" />
                  <div className="absolute -inset-6 rounded-full border border-orange-400/10 animate-pulse" style={{ animationDelay: '0.5s' }} />
                </>
              )}
              {speakingResponse && (
                <>
                  <div className="absolute -inset-2 rounded-full border-2 border-blue-400/30 animate-pulse" />
                  <div className="absolute -inset-4 rounded-full border border-purple-400/20 animate-pulse" style={{ animationDelay: '0.3s' }} />
                </>
              )}
              {isLoading && (
                <div className="absolute -inset-2 rounded-full border-2 border-orange-400/30 animate-spin" style={{ borderTopColor: 'transparent' }} />
              )}
              {isListening ? (
                <Mic className="w-12 h-12 text-gray-900 dark:text-white relative z-10" />
              ) : speakingResponse ? (
                <Bot className="w-12 h-12 text-gray-900 dark:text-white relative z-10" />
              ) : isLoading ? (
                <Loader2 className="w-12 h-12 text-gray-900 dark:text-white relative z-10 animate-spin" />
              ) : (
                <Mic className="w-12 h-12 text-gray-600 dark:text-gray-400 relative z-10" />
              )}
            </div>

            <div className="space-y-2 min-h-[80px]">
              <p className={`text-lg font-semibold ${
                isListening ? 'text-orange-400' : speakingResponse ? 'text-blue-400' : isLoading ? 'text-orange-300' : 'text-gray-600 dark:text-gray-400'
              }`}>
                {isListening ? 'Listening...' : speakingResponse ? 'Speaking response...' : isLoading ? 'Processing...' : 'Ready'}
              </p>
              {voiceTranscript && (
                <p className="text-gray-900 dark:text-white text-base leading-relaxed max-h-[120px] overflow-y-auto">
                  {voiceTranscript}
                </p>
              )}
              {!voiceTranscript && !isLoading && !speakingResponse && !isListening && (
                <p className="text-gray-500 text-sm">Tap the mic or start speaking</p>
              )}
            </div>

            <div className="flex items-center gap-4 mt-4">
              {!isListening && !isLoading && !speakingResponse && (
                <button
                  onClick={() => {
                    try {
                      setVoiceTranscript('');
                      setInput('');
                      recognitionRef.current?.start();
                      setIsListening(true);
                    } catch(e) {}
                  }}
                  className="px-6 py-3 bg-orange-600 hover:bg-orange-500 text-gray-900 dark:text-white rounded-2xl font-medium transition-all flex items-center gap-2"
                  type="button"
                >
                  <Mic className="w-5 h-5" />
                  Start Listening
                </button>
              )}
              {speakingResponse && (
                <button
                  onClick={() => {
                    stopTtsAudio();
                    window.speechSynthesis?.cancel();
                    resumeListeningAfterSpeak();
                  }}
                  className="px-6 py-3 bg-gray-700 hover:bg-gray-600 text-gray-900 dark:text-white rounded-2xl font-medium transition-all flex items-center gap-2"
                  type="button"
                >
                  <MicOff className="w-5 h-5" />
                  Skip Response
                </button>
              )}
            </div>

            <p className="text-gray-600 text-xs mt-8">
              Speak naturally. Messages send automatically after a 2-second pause.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
