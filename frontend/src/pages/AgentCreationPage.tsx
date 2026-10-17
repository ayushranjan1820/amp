import React, { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Container, Row, Col, Form, Button, Alert, Spinner, Badge, OverlayTrigger, Tooltip } from 'react-bootstrap';
import TaskAltIcon from '@mui/icons-material/TaskAlt';
import DeleteIcon from '@mui/icons-material/Delete';
import PermIdentityIcon from '@mui/icons-material/PermIdentity';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import HandymanIcon from '@mui/icons-material/Handyman';
import NotesIcon from '@mui/icons-material/Notes';
import RocketLaunchIcon from '@mui/icons-material/RocketLaunch';
import CloudUploadIcon from '@mui/icons-material/CloudUpload';
import InsertDriveFileIcon from '@mui/icons-material/InsertDriveFile';
import TuneIcon from '@mui/icons-material/Tune';
import StorageIcon from '@mui/icons-material/Storage';
import MemoryIcon from '@mui/icons-material/Memory';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import AddCircleIcon from '@mui/icons-material/AddCircle';import { 
  Pinecone, Qdrant, Chroma, Milvus, 
  Aws, AzureBadge, Googlecloud,
  Openai, Gemini, Cohere, AzureAzureOpenai, Mistral,
  Anthropic, Xai, Groq, Azureai, Deepseek, Openrouter, Ollama, HuggingFace,
  Tavily, Duckduckgo
} from '@thesvg/react';
import { Navbar } from '../components/layout/Navbar';
import { InputField } from '../components/common/InputField';
import { put, post, extractErrorMessage } from '../services/apiWrapper';
import { API_ENDPOINTS } from '../constants';
import './AgentCreationPage.css';

type StepKey = 'identity' | 'model' | 'tools' | 'prompt' | 'deploy';

interface HeaderRow {
  id: string;
  key: string;
  value: string;
}

interface ParamRow {
  id: string;
  name: string;
  description: string;
  location: 'query' | 'path' | 'body';
  data_type: 'string' | 'integer' | 'decimal' | 'boolean';
  required: boolean;
}

interface DiscoveredMcpTool {
  tool_name: string;
  tool_description: string;
}

const VECTOR_DB_PROVIDERS = [
  {
    id: 'pinecone' as const,
    label: 'Pinecone',
    renderIcon: () => <Pinecone variant="mono" className="h-6 w-6" />,
  },
  {
    id: 'qdrant' as const,
    label: 'Qdrant',
    renderIcon: () => <Qdrant className="h-6 w-6" />,
  },
  {
    id: 'chroma' as const,
    label: 'Chroma',
    renderIcon: () => <Chroma className="h-6 w-6" />,
  },
  {
    id: 'milvus' as const,
    label: 'Milvus',
    renderIcon: () => <Milvus className="h-6 w-6" />,
  },
];

const CLOUD_PROVIDERS = [
  {
    id: 'aws' as const,
    label: 'AWS',
    renderIcon: () => <Aws className="h-6 w-6" />,
  },
  {
    id: 'azure' as const,
    label: 'Azure',
    renderIcon: () => <AzureBadge className="h-6 w-6" />,
  },
  {
    id: 'gcp' as const,
    label: 'GCP',
    renderIcon: () => <Googlecloud className="h-6 w-6" />,
  },
];

export type EmbeddingProviderType = 'openai' | 'google' | 'cohere' | 'azure_openai' | 'mistral';

const EMBEDDING_MODEL_PROVIDERS = [
  {
    id: 'openai' as const,
    label: 'OpenAI',
    renderIcon: () => <Openai variant="light" className="h-6 w-6" />,
    defaultModel: 'text-embedding-3-small',
    defaultDimension: 1536,
  },
  {
    id: 'google' as const,
    label: 'Google',
    renderIcon: () => <Gemini className="h-6 w-6" />,
    defaultModel: 'models/text-embedding-004',
    defaultDimension: 768,
  },
  {
    id: 'cohere' as const,
    label: 'Cohere',
    renderIcon: () => <Cohere className="h-6 w-6" />,
    defaultModel: 'embed-english-v3.0',
    defaultDimension: 1024,
  },
  {
    id: 'azure_openai' as const,
    label: 'Azure OpenAI',
    renderIcon: () => <AzureAzureOpenai className="h-6 w-6" />,
    defaultModel: 'text-embedding-3-small',
    defaultDimension: 1536,
  },
  {
    id: 'mistral' as const,
    label: 'Mistral',
    renderIcon: () => <Mistral className="h-6 w-6" />,
    defaultModel: 'mistral-embed',
    defaultDimension: 1024,
  },
];

const MODEL_PROVIDERS = [
  {
    id: 'openai' as const,
    label: 'OpenAI',
    renderIcon: () => <Openai variant="light" className="h-6 w-6" />,
    defaultModel: 'gpt-4o',
  },
  {
    id: 'google_genai' as const,
    label: 'Google',
    renderIcon: () => <Gemini className="h-6 w-6" />,
    defaultModel: 'gemini-1.5-pro',
  },
  {
    id: 'anthropic' as const,
    label: 'Anthropic',
    renderIcon: () => <Anthropic className="h-6 w-6" />,
    defaultModel: 'claude-3-5-sonnet',
  },
  {
    id: 'xai' as const,
    label: 'xAI',
    renderIcon: () => <Xai className="h-6 w-6" />,
    defaultModel: 'grok-2',
  },
  {
    id: 'groq' as const,
    label: 'Groq',
    renderIcon: () => <Groq className="h-6 w-6" />,
    defaultModel: 'llama-3.3-70b-versatile',
  },
  {
    id: 'azure_openai' as const,
    label: 'Azure OpenAI',
    renderIcon: () => <AzureAzureOpenai className="h-6 w-6" />,
    defaultModel: 'gpt-4o',
  },
  {
    id: 'azure_ai' as const,
    label: 'Azure AI',
    renderIcon: () => <Azureai className="h-6 w-6" />,
    defaultModel: 'gpt-4o',
  },
  {
    id: 'cohere' as const,
    label: 'Cohere',
    renderIcon: () => <Cohere className="h-6 w-6" />,
    defaultModel: 'command-r-plus',
  },
  {
    id: 'deepseek' as const,
    label: 'DeepSeek',
    renderIcon: () => <Deepseek className="h-6 w-6" />,
    defaultModel: 'deepseek-chat',
  },
  {
    id: 'openrouter' as const,
    label: 'OpenRouter',
    renderIcon: () => <Openrouter className="h-6 w-6" />,
    defaultModel: 'openai/gpt-4o',
  },
  {
    id: 'ollama' as const,
    label: 'Ollama',
    renderIcon: () => <Ollama variant="dark" className="h-6 w-6" />,
    defaultModel: 'llama3',
  },
  {
    id: 'mistralai' as const,
    label: 'Mistral',
    renderIcon: () => <Mistral className="h-6 w-6" />,
    defaultModel: 'mistral-large-latest',
  },
  {
    id: 'huggingface' as const,
    label: 'Hugging Face',
    renderIcon: () => <HuggingFace className="h-6 w-6" />,
    defaultModel: 'meta-llama/Llama-3.3-70B-Instruct',
  },
];

const PRECONFIGURED_TOOLS = [
  {
    id: 'tavily_search' as const,
    label: 'Tavily Search',
    renderIcon: () => <Tavily className="h-6 w-6" />,
  },
  {
    id: 'duckduckgo_search' as const,
    label: 'DuckDuckGo Search',
    renderIcon: () => <Duckduckgo className="h-6 w-6" />,
  },
];

export const AgentCreationPage: React.FC = () => {
  const navigate = useNavigate();
  // Navigation & Agent State
  const [activeStep, setActiveStep] = useState<StepKey>('identity');
  const [agentId, setAgentId] = useState<string | null>(null);
  // Tracks which steps have been successfully saved — gates sidebar navigation
  const [completedSteps, setCompletedSteps] = useState<Set<StepKey>>(new Set());

  const markStepComplete = (step: StepKey) =>
    setCompletedSteps((prev) => new Set(prev).add(step));

  // Status & Feedback
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Step 1: Identity Form State
  const [identity, setIdentity] = useState({
    name: '',
    description: '',
    visibility: 'PRIVATE',
    status: 'DRAFT'
  });

  // Step 2: Model Form State
  const [model, setModel] = useState({
    provider: 'openai',
    name: 'gpt-4o',
    temperature: 0.7,
    max_tokens: 2048,
    api_key: '',
  });

  // Step 3: Tools Form State
  const [toolToggle, setToolToggle] = useState<'PRECONFIGURED' | 'API' | 'MCP' | 'RAG'>('API');
  
  // API Tool State
  const [apiTool, setApiTool] = useState({
    name: '',
    description: '',
    method: 'GET',
    url: '',
  });

  const [showHeadersSection, setShowHeadersSection] = useState(false);
  const [headers, setHeaders] = useState<HeaderRow[]>([]);

  const [showParametersSection, setShowParametersSection] = useState(false);
  const [parameters, setParameters] = useState<ParamRow[]>([]);

  // MCP Tool State - Name, description, and config
  const [mcpTool, setMcpTool] = useState({
    name: '',
    description: '',
  });
  const [mcpConfigText, setMcpConfigText] = useState<string>('');
  const [isDiscoveringMcp, setIsDiscoveringMcp] = useState<boolean>(false);
  const [discoveredMcpTools, setDiscoveredMcpTools] = useState<DiscoveredMcpTool[]>([]);
  const [selectedMcpTools, setSelectedMcpTools] = useState<Record<string, boolean>>({});

  // RAG Tool State
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [ragTool, setRagTool] = useState({
    name: '',
    description: '',
    selectedFile: null as File | null,
    // Embedding Model Config
    embeddingProvider: 'openai' as EmbeddingProviderType,
    embeddingModel: 'text-embedding-3-small',
    embeddingApiKey: '',
    // Vector DB Config
    vectorDbProvider: 'pinecone' as 'pinecone' | 'qdrant' | 'chroma' | 'milvus',
    vectorDbUrl: '',
    vectorDbApiKey: '',
    collectionName: '',
    namespace: '',
    vectorDbTenant: '',
    vectorDimension: 1536,
    topK: 15,
    cloudProvider: 'aws' as 'aws' | 'azure' | 'gcp' | '',
    region: 'us-east-1',
    // Advanced Config
    retrievalStrategy: 'similarity' as 'similarity' | 'mmr' | 'hybrid',
    chunkingStrategy: 'recursive' as 'recursive' | 'token' | 'hierarchial' | 'semantic',
    chunkSize: 1000,
    chunkOverlap: 200,
    distanceStrategy: 'dotproduct' as 'dotproduct' | 'cosine' | 'euclidean' | 'manhattan',
    vectorType: 'dense' as 'dense' | 'sparse',
    rerankEnabled: false,
    rerankProvider: 'cohere' as 'cohere' | 'gemini' | 'openai',
    rerankModel: 'rerank-english-v3.0',
    rerankTopK: 5,
  });
  const [showRagAdvanced, setShowRagAdvanced] = useState(false);

  // Preconfigured Tool State
  const [preconfiguredProvider, setPreconfiguredProvider] = useState<'tavily_search' | 'duckduckgo_search'>('tavily_search');
  const [preconfiguredTool, setPreconfiguredTool] = useState({
    name: 'Tavily Search',
    description: 'Search the internet using Tavily.',
    apiKey: '',
    maxResults: 5,
  });

  const handlePreconfiguredProviderChange = (provider: 'tavily_search' | 'duckduckgo_search') => {
    setPreconfiguredProvider(provider);
    if (provider === 'tavily_search') {
      setPreconfiguredTool((prev) => ({
        ...prev,
        name: prev.name === 'DuckDuckGo Search' ? 'Tavily Search' : prev.name || 'Tavily Search',
        description: prev.description === 'Search the internet using DuckDuckGo.' ? 'Search the internet using Tavily.' : prev.description || 'Search the internet using Tavily.',
        maxResults: prev.maxResults || 5,
      }));
    } else {
      setPreconfiguredTool((prev) => ({
        ...prev,
        name: prev.name === 'Tavily Search' ? 'DuckDuckGo Search' : prev.name || 'DuckDuckGo Search',
        description: prev.description === 'Search the internet using Tavily.' ? 'Search the internet using DuckDuckGo.' : prev.description || 'Search the internet using DuckDuckGo.',
        maxResults: prev.maxResults || 4,
      }));
    }
  };

  const [isSavingTool, setIsSavingTool] = useState<boolean>(false);

  // Step 4: Prompt Form State
  const [systemPrompt, setSystemPrompt] = useState('');

  // ------------------------------------------------------------------
  // Helper Functions & Dynamic Handlers
  // ------------------------------------------------------------------
  const clearAlerts = () => {
    setErrorMessage(null);
    setSuccessMessage(null);
  };

  const handleAddHeader = () => {
    setShowHeadersSection(true);
    setHeaders((prev) => [...prev, { id: Date.now().toString(), key: '', value: '' }]);
  };

  const handleRemoveHeader = (id: string) => {
    setHeaders((prev) => prev.filter((h) => h.id !== id));
  };

  const handleHeaderChange = (id: string, field: 'key' | 'value', val: string) => {
    setHeaders((prev) =>
      prev.map((h) => (h.id === id ? { ...h, [field]: val } : h))
    );
  };

  const handleAddParameter = () => {
    setShowParametersSection(true);
    setParameters((prev) => [
      ...prev,
      {
        id: Date.now().toString(),
        name: '',
        description: '',
        location: 'query',
        data_type: 'string',
        required: false,
      },
    ]);
  };

  const handleRemoveParameter = (id: string) => {
    setParameters((prev) => prev.filter((p) => p.id !== id));
  };

  const handleParamChange = (id: string, field: keyof ParamRow, val: any) => {
    setParameters((prev) =>
      prev.map((p) => (p.id === id ? { ...p, [field]: val } : p))
    );
  };

  // MCP Discovery & Selection Handlers
  const handleDiscoverMcpTools = async () => {
    if (!mcpConfigText.trim()) {
      setErrorMessage('Please enter an MCP JSON configuration.');
      return;
    }

    let parsedConfig: Record<string, any>;
    try {
      parsedConfig = JSON.parse(mcpConfigText);
    } catch {
      setErrorMessage('Invalid MCP JSON configuration. Please ensure it is valid JSON.');
      return;
    }

    setIsDiscoveringMcp(true);
    clearAlerts();

    try {
      const res: any = await post(API_ENDPOINTS.AGENTS.TOOLS_FROM_MCP, parsedConfig);
      const toolsList: DiscoveredMcpTool[] = Array.isArray(res) ? res : res?.data || [];

      setDiscoveredMcpTools(toolsList);

      // Select all by default
      const initialSelection: Record<string, boolean> = {};
      toolsList.forEach((t) => {
        initialSelection[t.tool_name] = true;
      });
      setSelectedMcpTools(initialSelection);

      if (toolsList.length === 0) {
        setSuccessMessage('No tools were found in the provided MCP configuration.');
      } else {
        setSuccessMessage(`Successfully discovered ${toolsList.length} MCP tool(s).`);
      }
    } catch (err) {
      setErrorMessage(extractErrorMessage(err));
    } finally {
      setIsDiscoveringMcp(false);
    }
  };

  const isAllMcpSelected =
    discoveredMcpTools.length > 0 &&
    discoveredMcpTools.every((t) => selectedMcpTools[t.tool_name]);

  const handleToggleSelectAllMcp = (e: React.ChangeEvent<HTMLInputElement>) => {
    const checked = e.target.checked;
    const updatedSelection: Record<string, boolean> = {};
    discoveredMcpTools.forEach((t) => {
      updatedSelection[t.tool_name] = checked;
    });
    setSelectedMcpTools(updatedSelection);
  };

  const handleToggleSingleMcpTool = (toolName: string) => {
    setSelectedMcpTools((prev) => ({
      ...prev,
      [toolName]: !prev[toolName],
    }));
  };

  // RAG Handlers
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setRagTool((prev) => ({ ...prev, selectedFile: e.target.files![0] }));
    }
  };

  const handleRemoveFile = (e: React.MouseEvent) => {
    e.stopPropagation();
    setRagTool((prev) => ({ ...prev, selectedFile: null }));
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleEmbeddingProviderChange = (provider: EmbeddingProviderType) => {
    const provConfig = EMBEDDING_MODEL_PROVIDERS.find((p) => p.id === provider);
    const defaultModel = provConfig ? provConfig.defaultModel : 'text-embedding-3-small';
    const defaultDimension = provConfig ? provConfig.defaultDimension : 1536;

    setRagTool((prev) => ({
      ...prev,
      embeddingProvider: provider,
      embeddingModel: defaultModel,
      vectorDimension: defaultDimension,
    }));
  };

  // ------------------------------------------------------------------
  // Step Submission Handlers
  // ------------------------------------------------------------------

  // Step 1: Identity Next Button
  const handleIdentitySubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!identity.name.trim() || !identity.description.trim()) {
      setErrorMessage('Agent name and description are required.');
      return;
    }

    setIsLoading(true);
    clearAlerts();

    try {
      const payload: Record<string, any> = {
        name: identity.name,
        description: identity.description,
        visibility: identity.visibility,
        status: identity.status,
        enabled: false,
        capabilities: [],
        version: '1.0.0',
      };

      if (agentId) {
        payload._id = agentId;
      }

      const res: any = await put(API_ENDPOINTS.AGENTS.CREATE_OR_UPDATE, payload);
      const resData = res?.data || res;
      const returnedId = resData?.agent_id || resData?._id || agentId;

      if (returnedId) {
        setAgentId(returnedId);
      }

      setSuccessMessage('Agent identity saved successfully!');
      markStepComplete('identity');
      setActiveStep('model');
    } catch (err) {
      setErrorMessage(extractErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  };

  // Step 2: Model Next Button
  const handleModelSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!agentId) {
      setErrorMessage('Please complete Step 1 (Identity) first.');
      return;
    }

    setIsLoading(true);
    clearAlerts();

    try {
      const payload = {
        _id: agentId,
        model: {
          provider: model.provider,
          name: model.name,
          max_tokens: model.max_tokens ? Number(model.max_tokens) : null,
          temperature: Number(model.temperature),
          api_key: model.api_key,
        },
      };

      await put(API_ENDPOINTS.AGENTS.CREATE_OR_UPDATE, payload);

      setSuccessMessage('Model configuration saved successfully!');
      markStepComplete('model');
      setActiveStep('tools');
    } catch (err) {
      setErrorMessage(extractErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  };

  // Step 3: Tools Save Button Handler
  const handleSaveTool = async () => {
    if (!agentId) {
      setErrorMessage('Please complete Step 1 (Identity) first before saving tools.');
      return;
    }

    setIsSavingTool(true);
    clearAlerts();

    try {
      if (toolToggle === 'API') {
        if (!apiTool.url.trim()) {
          setErrorMessage('Please provide a target endpoint URL for the API tool.');
          setIsSavingTool(false);
          return;
        }

        const headerMap: Record<string, string> = {};
        headers.forEach((h) => {
          if (h.key.trim()) {
            headerMap[h.key.trim()] = h.value;
          }
        });

        const paramConfigs = parameters
          .filter((p) => p.name.trim())
          .map((p) => ({
            name: p.name.trim(),
            description: p.description,
            location: p.location,
            data_type: p.data_type,
            required: p.required,
          }));

        const apiToolConfig = {
          name: apiTool.name.trim() || `${identity.name || 'Agent'} API Tool`,
          description: apiTool.description.trim() || identity.description || '',
          tool_type: 'API',
          enabled: true,
          version: '1.0.0',
          url: apiTool.url.trim(),
          method: apiTool.method,
          headers: headerMap,
          parameters: paramConfigs,
          timeout_seconds: 30,
        };

        await post(API_ENDPOINTS.AGENTS.ADD_TOOLS(agentId), { tool: [apiToolConfig] });
        setSuccessMessage('API tool saved successfully!');
        markStepComplete('tools');
      } else if (toolToggle === 'MCP') {
        if (!mcpTool.name.trim()) {
          setErrorMessage('Please enter an MCP Tool Name.');
          setIsSavingTool(false);
          return;
        }
        if (!mcpTool.description.trim()) {
          setErrorMessage('Please enter an MCP Tool Description.');
          setIsSavingTool(false);
          return;
        }

        let parsedConfig: Record<string, any> = {};
        if (mcpConfigText.trim()) {
          try {
            parsedConfig = JSON.parse(mcpConfigText);
          } catch {
            setErrorMessage('Invalid MCP JSON configuration format. Please ensure it is valid JSON.');
            setIsSavingTool(false);
            return;
          }
        }

        const selectedToolNames = discoveredMcpTools
          .filter((t) => selectedMcpTools[t.tool_name])
          .map((t) => t.tool_name);

        const mcpToolConfig = {
          name: mcpTool.name.trim(),
          description: mcpTool.description.trim(),
          tool_type: 'MCP',
          enabled: true,
          version: '1.0.0',
          mcp_config: parsedConfig,
          allowed_tools: selectedToolNames,
        };

        await post(API_ENDPOINTS.AGENTS.ADD_TOOLS(agentId), { tool: [mcpToolConfig] });
        setSuccessMessage('MCP tool saved successfully!');
        markStepComplete('tools');
      } else if (toolToggle === 'PRECONFIGURED') {
        if (!preconfiguredTool.name.trim()) {
          setErrorMessage('Please enter a tool name.');
          setIsSavingTool(false);
          return;
        }

        const configMap: Record<string, any> = {};

        if (preconfiguredProvider === 'tavily_search') {
          if (!preconfiguredTool.apiKey.trim()) {
            setErrorMessage('Please provide a Tavily API Key.');
            setIsSavingTool(false);
            return;
          }
          configMap.api_key = preconfiguredTool.apiKey.trim();
          if (preconfiguredTool.maxResults) {
            configMap.max_results = Number(preconfiguredTool.maxResults);
          }
        } else if (preconfiguredProvider === 'duckduckgo_search') {
          if (preconfiguredTool.maxResults) {
            configMap.max_results = Number(preconfiguredTool.maxResults);
          }
        }

        const preconfiguredToolConfig = {
          name: preconfiguredTool.name.trim(),
          description: preconfiguredTool.description.trim() || (preconfiguredProvider === 'tavily_search' ? 'Search the internet using Tavily.' : 'Search the internet using DuckDuckGo.'),
          tool_type: 'PRECONFIGURED',
          enabled: true,
          version: '1.0.0',
          provider: preconfiguredProvider,
          config: configMap,
        };

        await post(API_ENDPOINTS.AGENTS.ADD_TOOLS(agentId), { tool: [preconfiguredToolConfig] });
        setSuccessMessage(`${preconfiguredProvider === 'tavily_search' ? 'Tavily Search' : 'DuckDuckGo Search'} tool saved successfully!`);
        markStepComplete('tools');
      } else if (toolToggle === 'RAG') {
        if (!ragTool.name.trim()) {
          setErrorMessage('Please enter an Agent Tool Name for RAG.');
          setIsSavingTool(false);
          return;
        }
        if (!ragTool.description.trim()) {
          setErrorMessage('Please enter a description for the RAG Tool.');
          setIsSavingTool(false);
          return;
        }
        if (!ragTool.selectedFile) {
          setErrorMessage('Please upload a document file to ingest for the RAG Tool.');
          setIsSavingTool(false);
          return;
        }
        if (!ragTool.embeddingApiKey.trim()) {
          setErrorMessage('Please provide an API key for the Embedding model.');
          setIsSavingTool(false);
          return;
        }
        if (!ragTool.collectionName.trim()) {
          setErrorMessage('Please provide a Collection / Index name for the Vector Database.');
          setIsSavingTool(false);
          return;
        }
        if (!ragTool.vectorDbApiKey.trim()) {
          setErrorMessage('Please provide an API key for the Vector Database.');
          setIsSavingTool(false);
          return;
        }

        // Step 1: Upload document to /api/v1/agents/upload
        const formData = new FormData();
        formData.append('file', ragTool.selectedFile);

        const uploadRes: any = await post(
          API_ENDPOINTS.AGENTS.UPLOAD_DOCUMENT,
          formData,
          {
            headers: {
              'Content-Type': 'multipart/form-data',
            },
          }
        );

        const uploadData = uploadRes?.data || uploadRes;
        const uploadedFilePath = uploadData?.file_path;

        if (!uploadedFilePath) {
          throw new Error('Document uploaded successfully, but server did not return a valid file path.');
        }

        // Step 2: Build RAG tool config payload and call add_tools_to_an_agent
        const isQdrant = ragTool.vectorDbProvider === 'qdrant';
        const isChroma = ragTool.vectorDbProvider === 'chroma';
        const ragToolConfig = {
          name: ragTool.name.trim(),
          description: ragTool.description.trim(),
          tool_type: 'RAG',
          enabled: true,
          version: '1.0.0',
          document_path: uploadedFilePath,
          embedding_model_config: {
            provider: ragTool.embeddingProvider,
            model: ragTool.embeddingModel.trim(),
            api_key: ragTool.embeddingApiKey.trim(),
          },
          vector_db_config: {
            vector_db_provider: ragTool.vectorDbProvider,
            vector_db_url: ragTool.vectorDbUrl.trim() || null,
            vector_db_api_key: ragTool.vectorDbApiKey.trim(),
            collection_name: ragTool.collectionName.trim(),
            namespace: (isQdrant || isChroma) ? null : (ragTool.namespace.trim() || null),
            vector_db_tenant: isChroma ? (ragTool.vectorDbTenant.trim() || null) : null,
            vector_dimension: ragTool.vectorDimension ? Number(ragTool.vectorDimension) : null,
            top_k: Number(ragTool.topK) || 15,
            cloud_provider: (isQdrant || isChroma) ? null : (ragTool.cloudProvider ? ragTool.cloudProvider : null),
            region: (isQdrant || isChroma) ? null : (ragTool.region.trim() || null),
          },
          rag_advanced_config: {
            retrieval_strategy: ragTool.retrievalStrategy,
            chunking_strategy: ragTool.chunkingStrategy,
            chunk_size: Number(ragTool.chunkSize) || 1000,
            chunk_overlap: Number(ragTool.chunkOverlap) || 200,
            distance_strategy: ragTool.distanceStrategy,
            vector_type: ragTool.vectorType,
            rerank_enabled: ragTool.rerankEnabled,
            rerank_provider: ragTool.rerankEnabled ? ragTool.rerankProvider : null,
            rerank_model: ragTool.rerankEnabled && ragTool.rerankModel.trim() ? ragTool.rerankModel.trim() : null,
            rerank_top_k: ragTool.rerankEnabled ? Number(ragTool.rerankTopK) || 5 : 5,
          },
        };

        await post(API_ENDPOINTS.AGENTS.ADD_TOOLS(agentId), { tool: [ragToolConfig] });
        setSuccessMessage('RAG tool document uploaded and saved successfully!');
        markStepComplete('tools');
      }
    } catch (err) {
      setErrorMessage(extractErrorMessage(err));
    } finally {
      setIsSavingTool(false);
    }
  };

  // Step 3: Tools Next Button Handler (navigates without calling API)
  const handleToolsNext = () => {
    clearAlerts();
    markStepComplete('tools');
    setActiveStep('prompt');
  };

  // Step 4: Prompt Next Button
  const handlePromptSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!agentId) {
      setErrorMessage('Please complete Step 1 (Identity) first.');
      return;
    }

    setIsLoading(true);
    clearAlerts();

    try {
      const payload = {
        _id: agentId,
        system_prompt: systemPrompt,
      };

      await put(API_ENDPOINTS.AGENTS.CREATE_OR_UPDATE, payload);

      setSuccessMessage('System prompt updated!');
      markStepComplete('prompt');
      setActiveStep('deploy');
    } catch (err) {
      setErrorMessage(extractErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  };

  // Step 5: Deploy Button
  const handleDeployClick = async () => {
    if (!agentId) {
      setErrorMessage('No agent to deploy. Please complete the previous steps first.');
      return;
    }

    setIsLoading(true);
    clearAlerts();

    try {
      await put(API_ENDPOINTS.AGENTS.CREATE_OR_UPDATE, {
        _id: agentId,
        enabled: true,
        status: 'DEPLOYED',
      });
      setSuccessMessage('Agent deployed successfully!');
      markStepComplete('deploy');
      // Navigate to deployed agents page after a short delay for the user to see the success message
      setTimeout(() => navigate('/deployed'), 800);
    } catch (err) {
      setErrorMessage(extractErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  };

  // Steps Registry
  const steps: { key: StepKey; label: string; icon: React.ReactNode }[] = [
    { key: 'identity', label: 'Identity', icon: <PermIdentityIcon style={{ fontSize: 17 }} /> },
    { key: 'model', label: 'Model', icon: <AutoAwesomeIcon style={{ fontSize: 17 }} /> },
    { key: 'tools', label: 'Tools', icon: <HandymanIcon style={{ fontSize: 17 }} /> },
    { key: 'prompt', label: 'Prompt', icon: <NotesIcon style={{ fontSize: 17 }} /> },
    { key: 'deploy', label: 'Deploy', icon: <RocketLaunchIcon style={{ fontSize: 17 }} /> },
  ];

  const mcpPlaceholderText = `{\n  "mcpServers": {\n    "filesystem": {\n      "command": "npx",\n      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"]\n    }\n  }\n}`;

  return (
    <div className="bg-deep-dark">
      <Navbar />

      <Container className="agent-creation-container">
        <div className="agent-creation-card h-100">
          <Row className="g-0 h-100">
            {/* Left Vertical Menu */}
            <Col md={2} className="sidebar-menu">
              <h6 className="text-uppercase text-muted fw-bold px-3 mb-3 small tracking-wider">
                Agent Workflow
              </h6>
              {steps.map((step) => {
                const isActive = activeStep === step.key;
                const isCompleted = completedSteps.has(step.key);

                // A step is navigable if it's identity, already completed, or
                // is the immediate next step after the last completed one.
                const stepIndex = steps.findIndex((s) => s.key === step.key);
                const maxUnlockedIndex = steps.reduce((max, s, i) =>
                  completedSteps.has(s.key) ? i + 1 : max, 0
                );
                const isClickable = stepIndex <= maxUnlockedIndex;

                return (
                  <div
                    key={step.key}
                    className={`sidebar-step-item ${
                      isActive ? 'active' : ''
                    } ${
                      isCompleted ? 'completed' : ''
                    } ${
                      !isClickable ? 'locked' : ''
                    }`}
                    onClick={() => {
                      if (isClickable) {
                        setActiveStep(step.key);
                        clearAlerts();
                      }
                    }}
                  >
                    <div className="step-number-badge">{step.icon}</div>
                    <span>{step.label}</span>
                    {isCompleted && (
                      <TaskAltIcon
                        style={{ fontSize: 18, color: '#22c55e', marginLeft: 'auto' }}
                      />
                    )}
                  </div>
                );
              })}
            </Col>

            {/* Right Panel Content */}
            <Col md={10} className="agent-step-content">
              {errorMessage && (
                <Alert variant="danger" className="alert-custom-error mb-4" onClose={() => setErrorMessage(null)} dismissible>
                  {errorMessage}
                </Alert>
              )}

              {successMessage && (
                <div className="text-success fw-semibold small mb-4 d-flex align-items-center gap-2">
                  <span>✓ {successMessage}</span>
                </div>
              )}

              {/* STEP 1: IDENTITY */}
              {activeStep === 'identity' && (
                <div>
                  <h3 className="step-title">AI Identity</h3>
                  <p className="step-description">Define the foundational name, description, and visibility for your AI agent.</p>

                  <Form onSubmit={handleIdentitySubmit}>
                    <InputField
                      id="agent-name"
                      label="Agent Name"
                      type="text"
                      name="name"
                      value={identity.name}
                      placeholder="e.g. Code Review Assistant"
                      onChange={(e) => setIdentity({ ...identity, name: e.target.value })}
                      required
                    />

                    <Form.Group className="mb-3" controlId="agent-description">
                      <Form.Label className="form-label-custom">Description</Form.Label>
                      <Form.Control
                        as="textarea"
                        rows={3}
                        className="custom-input"
                        placeholder="Describe what this agent does..."
                        value={identity.description}
                        onChange={(e) => setIdentity({ ...identity, description: e.target.value })}
                        required
                      />
                    </Form.Group>

                    <Form.Group className="mb-4" controlId="agent-visibility">
                      <Form.Label className="form-label-custom">Visibility</Form.Label>
                      <Form.Select
                        className="custom-input"
                        value={identity.visibility}
                        onChange={(e) => setIdentity({ ...identity, visibility: e.target.value })}
                      >
                        <option value="PRIVATE">PRIVATE -- Only you can see</option>
                        <option value="PUBLIC">PUBLIC -- Everyone can see</option>
                      </Form.Select>
                    </Form.Group>

                    <div className="d-flex justify-content-end">
                      <Button type="submit" className="btn-cyan-primary agent-action-btn px-4" disabled={isLoading}>
                        {isLoading ? (
                          <>
                            <Spinner animation="border" size="sm" className="me-2" />
                            Saving...
                          </>
                        ) : (
                          'Next'
                        )}
                      </Button>
                    </div>
                  </Form>
                </div>
              )}

              {/* STEP 2: MODEL */}
              {activeStep === 'model' && (
                <div>
                  <h3 className="step-title">Model Configuration</h3>
                  <p className="step-description">Select an AI provider, model architecture, sampling temperature, and token limits.</p>

                  <Form onSubmit={handleModelSubmit}>
                    {/* Model Provider Horizontal List */}
                    <div className="mb-4">
                      <Form.Label className="form-label-custom mb-2 d-block">
                        Model Provider
                      </Form.Label>
                      <div className="model-provider-grid">
                        {MODEL_PROVIDERS.map((provider) => {
                          const isSelected = model.provider === provider.id;
                          return (
                            <div
                              key={provider.id}
                              id={`model-provider-${provider.id}`}
                              className={`vector-provider-card ${isSelected ? 'selected' : ''}`}
                              onClick={() => {
                                setModel((prev) => ({
                                  ...prev,
                                  provider: provider.id,
                                  name: prev.name === '' || MODEL_PROVIDERS.some((p) => p.defaultModel === prev.name)
                                    ? provider.defaultModel
                                    : prev.name,
                                }));
                              }}
                              role="button"
                              tabIndex={0}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter' || e.key === ' ') {
                                  setModel((prev) => ({
                                    ...prev,
                                    provider: provider.id,
                                    name: prev.name === '' || MODEL_PROVIDERS.some((p) => p.defaultModel === prev.name)
                                      ? provider.defaultModel
                                      : prev.name,
                                  }));
                                }
                              }}
                            >
                              <div className="vector-provider-icon-wrapper">
                                {provider.renderIcon()}
                              </div>
                              <span className="vector-provider-name">{provider.label}</span>
                              {isSelected && (
                                <span className="vector-provider-check ms-auto">
                                  <TaskAltIcon style={{ fontSize: 16 }} />
                                </span>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>

                    <Row className="g-3 mb-4">
                      <Col md={12}>
                        <Form.Group controlId="model-name">
                          <Form.Label className="form-label-custom">Model Name</Form.Label>
                          <Form.Control
                            type="text"
                            className="custom-input"
                            value={model.name}
                            placeholder="e.g. gpt-4o, gemini-1.5-pro, claude-3-5-sonnet"
                            onChange={(e) => setModel({ ...model, name: e.target.value })}
                            required
                          />
                        </Form.Group>
                      </Col>
                    </Row>

                    <Form.Group className="mb-4" controlId="model-temperature">
                      <div className="d-flex justify-content-between align-items-center mb-1">
                        <Form.Label className="form-label-custom mb-0">
                          Temperature: <span className="text-cyan-accent fw-bold ms-1">{model.temperature}</span>
                        </Form.Label>
                      </div>
                      <Form.Range
                        min={0.0}
                        max={2.0}
                        step={0.1}
                        value={model.temperature}
                        onChange={(e) => setModel({ ...model, temperature: parseFloat(e.target.value) })}
                        style={{ '--slider-fill': `${(model.temperature / 2.0) * 100}%` } as React.CSSProperties}
                        className="custom-range-slider w-100"
                      />
                      <div className="d-flex justify-content-between mt-1">
                        <span className="small text-muted">Definitive</span>
                        <span className="small text-muted">Creative</span>
                      </div>
                    </Form.Group>

                    <Row className="g-3 mb-4">
                      <Col md={6}>
                        <InputField
                          id="max-tokens"
                          label="Max Tokens"
                          type="number"
                          name="max_tokens"
                          value={model.max_tokens.toString()}
                          placeholder="2048"
                          onChange={(e) => setModel({ ...model, max_tokens: parseInt(e.target.value) || 0 })}
                        />
                      </Col>
                      <Col md={6}>
                        <InputField
                          id="api-key"
                          label="API Key"
                          type="password"
                          name="api_key"
                          value={model.api_key}
                          placeholder="sk-..."
                          onChange={(e) => setModel({ ...model, api_key: e.target.value })}
                          showPasswordToggle
                        />
                      </Col>
                    </Row>

                    <div className="d-flex justify-content-between">
                      <Button variant="outline-secondary" onClick={() => setActiveStep('identity')} className="px-4 agent-action-btn">
                        Back
                      </Button>
                      <Button type="submit" className="btn-cyan-primary agent-action-btn px-4" disabled={isLoading}>
                        {isLoading ? (
                          <>
                            <Spinner animation="border" size="sm" className="me-2" />
                            Saving...
                          </>
                        ) : (
                          'Next'
                        )}
                      </Button>
                    </div>
                  </Form>
                </div>
              )}

              {/* STEP 3: TOOLS */}
              {activeStep === 'tools' && (
                <div>
                  <h3 className="step-title">Tool Configuration</h3>
                  <p className="step-description">Connect external APIs, preconfigured utilities, or MCP protocol endpoints to your agent.</p>

                  {/* Toggle Pill Selection & Top-Right Save Button */}
                  <div className="d-flex align-items-center justify-content-between mb-4 flex-wrap gap-2">
                    <div className="toggle-group-pills">
                      <button
                        type="button"
                        className={`toggle-pill-btn ${toolToggle === 'PRECONFIGURED' ? 'active' : ''}`}
                        onClick={() => setToolToggle('PRECONFIGURED')}
                      >
                        Preconfigured
                      </button>
                      <button
                        type="button"
                        className={`toggle-pill-btn ${toolToggle === 'API' ? 'active' : ''}`}
                        onClick={() => setToolToggle('API')}
                      >
                        API
                      </button>
                      <button
                        type="button"
                        className={`toggle-pill-btn ${toolToggle === 'MCP' ? 'active' : ''}`}
                        onClick={() => setToolToggle('MCP')}
                      >
                        MCP
                      </button>
                      <button
                        type="button"
                        className={`toggle-pill-btn ${toolToggle === 'RAG' ? 'active' : ''}`}
                        onClick={() => setToolToggle('RAG')}
                      >
                        RAG
                      </button>
                    </div>
                  </div>

                  <Form onSubmit={(e) => { e.preventDefault(); handleToolsNext(); }}>
                    {/* API TOOL TOGGLE */}
                    {toolToggle === 'API' && (
                      <div>
                        {/* 1. Tool Name - Full Width */}
                        <div className="mb-3">
                          <InputField
                            id="tool-name"
                            label="Tool Name"
                            type="text"
                            name="tool_name"
                            value={apiTool.name}
                            placeholder="e.g. Weather API Tool"
                            onChange={(e) => setApiTool({ ...apiTool, name: e.target.value })}
                          />
                        </div>

                        {/* 2. Tool Description - Right After Tool Name */}
                        <Form.Group className="mb-3" controlId="tool-description">
                          <Form.Label className="form-label-custom">Tool Description</Form.Label>
                          <Form.Control
                            as="textarea"
                            rows={2}
                            className="custom-input"
                            placeholder="Describes what this API tool does..."
                            value={apiTool.description}
                            onChange={(e) => setApiTool({ ...apiTool, description: e.target.value })}
                          />
                        </Form.Group>

                        {/* 3. Method & Target Endpoint URL Inline */}
                        <Row className="g-3 mb-4">
                          <Col md={2}>
                            <Form.Group controlId="tool-method">
                              <Form.Label className="form-label-custom">Method</Form.Label>
                              <Form.Select
                                className="custom-input"
                                value={apiTool.method}
                                onChange={(e) => setApiTool({ ...apiTool, method: e.target.value })}
                              >
                                <option value="GET">GET</option>
                                <option value="POST">POST</option>
                                <option value="PUT">PUT</option>
                                <option value="DELETE">DELETE</option>
                                <option value="PATCH">PATCH</option>
                              </Form.Select>
                            </Form.Group>
                          </Col>

                          <Col md={10}>
                            <InputField
                              id="tool-url"
                              label="Target Endpoint URL"
                              type="url"
                              name="url"
                              value={apiTool.url}
                              placeholder="https://api.example.com/v1/resource"
                              onChange={(e) => setApiTool({ ...apiTool, url: e.target.value })}
                            />
                          </Col>
                        </Row>

                        {/* 4. HTTP HEADERS SECTION - Minimal & Modern */}
                        <div className="mb-4">
                          <div className="d-flex align-items-center justify-content-between mb-2">
                            <span className="form-label-custom mb-0 fw-semibold">HTTP Headers</span>
                            <span className="add-option-btn" onClick={handleAddHeader}>
                              <AddCircleIcon style={{ fontSize: 20, cursor: 'pointer' }}/>Add Header
                            </span>
                          </div>

                          {showHeadersSection && headers.length === 0 && (
                            <p className="small text-muted mb-2">No headers added yet. Click "+ Add Header" to include key-value pairs.</p>
                          )}

                          {headers.map((h) => (
                            <Row key={h.id} className="header-input-row align-items-center g-2">
                              <Col md={3}>
                                <Form.Control
                                  type="text"
                                  placeholder="Header Key (e.g. Authorization)"
                                  className="custom-input py-1.5 px-3 fs-6"
                                  value={h.key}
                                  onChange={(e) => handleHeaderChange(h.id, 'key', e.target.value)}
                                />
                              </Col>
                              <Col md={8}>
                                <Form.Control
                                  type="text"
                                  placeholder="Value (e.g. Bearer xyz)"
                                  className="custom-input py-1.5 px-3 fs-6"
                                  value={h.value}
                                  onChange={(e) => handleHeaderChange(h.id, 'value', e.target.value)}
                                />
                              </Col>
                              <Col md={1} className="text-center">
                                <Button
                                  variant="link"
                                  size="sm"
                                  onClick={() => handleRemoveHeader(h.id)}
                                  className="text-danger p-0 text-decoration-none d-flex align-items-center justify-content-center"
                                  title="Remove Header"
                                >
                                  <DeleteIcon style={{ fontSize: 18 }} />
                                </Button>
                              </Col>
                            </Row>
                          ))}
                        </div>

                        {/* 5. API PARAMETERS SECTION - Structured & Self-Explanatory */}
                        <div className="mb-4">
                          <div className="d-flex align-items-center justify-content-between mb-2">
                            <span className="form-label-custom mb-0 fw-semibold">API Parameters</span>
                            <span className="add-option-btn" onClick={handleAddParameter}>
                              <AddCircleIcon style={{ fontSize: 20, cursor: 'pointer' }}/>Add Parameter
                            </span>
                          </div>

                          {showParametersSection && parameters.length === 0 && (
                            <p className="small text-muted mb-2">No parameters added yet. Click "+ Add Parameter" to specify inputs.</p>
                          )}

                          {parameters.map((p, idx) => (
                            <div key={p.id} className="parameter-card">
                              <div className="parameter-card-header">
                                <span className="fw-semibold text-cyan-accent small">Parameter #{idx + 1}</span>
                                <Button
                                  variant="link"
                                  size="sm"
                                  onClick={() => handleRemoveParameter(p.id)}
                                  className="text-danger p-0 text-decoration-none d-flex align-items-center gap-1"
                                  title="Remove Parameter"
                                >
                                  <DeleteIcon style={{ fontSize: 16 }} />
                                </Button>
                              </div>

                              <Row className="g-3 mb-3">
                                <Col md={4}>
                                  <Form.Group controlId={`param-name-${p.id}`}>
                                    <Form.Label className="form-label-custom small mb-1">Parameter Name</Form.Label>
                                    <Form.Control
                                      type="text"
                                      placeholder="e.g. city, user_id"
                                      className="custom-input py-1.5 px-3 fs-6"
                                      value={p.name}
                                      onChange={(e) => handleParamChange(p.id, 'name', e.target.value)}
                                    />
                                  </Form.Group>
                                </Col>

                                <Col md={3}>
                                  <Form.Group controlId={`param-loc-${p.id}`}>
                                    <Form.Label className="form-label-custom small mb-1">Where is it passed?</Form.Label>
                                    <Form.Select
                                      className="custom-input py-1.5 px-3 fs-6"
                                      value={p.location}
                                      onChange={(e) => handleParamChange(p.id, 'location', e.target.value)}
                                    >
                                      <option value="query">Query</option>
                                      <option value="path">Path</option>
                                      <option value="body">Body</option>
                                    </Form.Select>
                                  </Form.Group>
                                </Col>

                                <Col md={3}>
                                  <Form.Group controlId={`param-type-${p.id}`}>
                                    <Form.Label className="form-label-custom small mb-1">Data Type</Form.Label>
                                    <Form.Select
                                      className="custom-input py-1.5 px-3 fs-6"
                                      value={p.data_type}
                                      onChange={(e) => handleParamChange(p.id, 'data_type', e.target.value)}
                                    >
                                      <option value="string">String</option>
                                      <option value="integer">Integer</option>
                                      <option value="decimal">Decimal</option>
                                      <option value="boolean">Boolean</option>
                                    </Form.Select>
                                  </Form.Group>
                                </Col>

                                <Col md={2} className="d-flex flex-column justify-content-end">
                                  <Form.Group controlId={`param-req-${p.id}`} className="mb-2">
                                    <Form.Check
                                      type="checkbox"
                                      id={`req-check-${p.id}`}
                                      label="Required"
                                      checked={p.required}
                                      onChange={(e) => handleParamChange(p.id, 'required', e.target.checked)}
                                      className="text-light small mt-1"
                                    />
                                  </Form.Group>
                                </Col>
                              </Row>

                              <Form.Group controlId={`param-desc-${p.id}`}>
                                <Form.Label className="form-label-custom small mb-1">Description (How to use)</Form.Label>
                                <Form.Control
                                  type="text"
                                  placeholder="Explain what this parameter does for the API..."
                                  className="custom-input py-1.5 px-3 fs-6"
                                  value={p.description}
                                  onChange={(e) => handleParamChange(p.id, 'description', e.target.value)}
                                />
                              </Form.Group>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* MCP TOOL TOGGLE */}
                    {toolToggle === 'MCP' && (
                      <div>
                        {/* 1. MCP Tool Name */}
                        <div className="mb-3">
                          <InputField
                            id="mcp-tool-name"
                            label="MCP Tool Name"
                            type="text"
                            name="mcp_tool_name"
                            value={mcpTool.name}
                            placeholder="e.g. GitHub MCP Server Tool"
                            onChange={(e) => setMcpTool({ ...mcpTool, name: e.target.value })}
                          />
                        </div>

                        {/* 2. MCP Tool Description */}
                        <Form.Group className="mb-3" controlId="mcp-tool-description">
                          <Form.Label className="form-label-custom">MCP Tool Description</Form.Label>
                          <Form.Control
                            as="textarea"
                            rows={2}
                            className="custom-input"
                            placeholder="Describes what this MCP tool does..."
                            value={mcpTool.description}
                            onChange={(e) => setMcpTool({ ...mcpTool, description: e.target.value })}
                          />
                        </Form.Group>

                        {/* 3. MCP Server JSON Configuration */}
                        <Form.Group className="mb-3" controlId="mcp-config-json">
                          <Form.Label className="form-label-custom">MCP Server JSON Configuration</Form.Label>
                          <Form.Control
                            as="textarea"
                            rows={10}
                            style={{ minHeight: '220px' }}
                            className="custom-input font-monospace small"
                            placeholder={mcpPlaceholderText}
                            value={mcpConfigText}
                            onChange={(e) => setMcpConfigText(e.target.value)}
                          />
                        </Form.Group>

                        <div className="mb-4">
                          <Button
                            type="button"
                            className="btn-cyan-primary btn-sm px-4 agent-action-btn me-2"
                            onClick={handleDiscoverMcpTools}
                            disabled={isDiscoveringMcp}
                          >
                            {isDiscoveringMcp ? (
                              <>
                                <Spinner animation="border" size="sm" className="me-2" />
                                Discovering...
                              </>
                            ) : (
                              'Discover Tools'
                            )}
                          </Button>
                        </div>

                        {/* DISCOVERED MCP TOOLS LIST - Dynamic Width Pills (Green when selected, 8px corners) */}
                        {discoveredMcpTools.length > 0 && (
                          <div className="p-3 rounded-3 border border-secondary border-opacity-25 bg-dark bg-opacity-40 mb-4">
                            <div className="d-flex align-items-center justify-content-between mb-3 pb-2 border-bottom border-secondary border-opacity-25">
                              <Form.Check
                                type="checkbox"
                                id="select-all-mcp-tools"
                                label={<strong className="text-white ms-1">Select All ({discoveredMcpTools.length} Tools)</strong>}
                                checked={isAllMcpSelected}
                                onChange={handleToggleSelectAllMcp}
                                className="text-white"
                              />
                            </div>

                            <div className="d-flex flex-wrap gap-2">
                              {discoveredMcpTools.map((t) => {
                                const isSelected = !!selectedMcpTools[t.tool_name];
                                return (
                                   <div
                                    key={t.tool_name}
                                    className={`mcp-tool-pill d-inline-flex align-items-center gap-2 px-3 py-1.5 border ${
                                      isSelected ? 'selected' : 'unselected'
                                    }`}
                                    onClick={() => handleToggleSingleMcpTool(t.tool_name)}
                                    style={{ cursor: 'pointer' }}
                                  >
                                    <input
                                      type="checkbox"
                                      className="form-check-input m-0"
                                      id={`mcp-tool-${t.tool_name}`}
                                      checked={isSelected}
                                      onChange={(e) => {
                                        e.stopPropagation();
                                        handleToggleSingleMcpTool(t.tool_name);
                                      }}
                                      onClick={(e) => e.stopPropagation()}
                                      style={{ cursor: 'pointer' }}
                                    />
                                    <OverlayTrigger
                                      placement="top"
                                      overlay={
                                        <Tooltip id={`tooltip-${t.tool_name}`}>
                                          {t.tool_description || 'No description provided.'}
                                        </Tooltip>
                                      }
                                    >
                                      <span className="fw-medium small text-nowrap">{t.tool_name}</span>
                                    </OverlayTrigger>
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    {/* PRECONFIGURED TOOL TOGGLE */}
                    {toolToggle === 'PRECONFIGURED' && (
                      <div>
                        {/* 1. Preconfigured Tool Selector (Horizontal List) */}
                        <div className="mb-4">
                          <Form.Label className="form-label-custom small mb-2 d-block">
                            Select Preconfigured Tool
                          </Form.Label>
                          <div className="preconfigured-provider-grid">
                            {PRECONFIGURED_TOOLS.map((provider) => {
                              const isSelected = preconfiguredProvider === provider.id;
                              return (
                                <div
                                  key={provider.id}
                                  id={`preconfigured-provider-${provider.id}`}
                                  className={`vector-provider-card ${isSelected ? 'selected' : ''}`}
                                  onClick={() => handlePreconfiguredProviderChange(provider.id)}
                                  role="button"
                                  tabIndex={0}
                                  onKeyDown={(e) => {
                                    if (e.key === 'Enter' || e.key === ' ') {
                                      handlePreconfiguredProviderChange(provider.id);
                                    }
                                  }}
                                >
                                  <div className="vector-provider-icon-wrapper">
                                    {provider.renderIcon()}
                                  </div>
                                  <span className="vector-provider-name">{provider.label}</span>
                                  {isSelected && (
                                    <span className="vector-provider-check ms-auto">
                                      <TaskAltIcon style={{ fontSize: 16 }} />
                                    </span>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        </div>

                        {/* 2. Tool Identity */}
                        <div className="mb-3">
                          <InputField
                            id="preconfigured-tool-name"
                            label="Tool Name"
                            type="text"
                            name="preconfigured_tool_name"
                            value={preconfiguredTool.name}
                            placeholder="e.g. Web Search"
                            onChange={(e) => setPreconfiguredTool({ ...preconfiguredTool, name: e.target.value })}
                          />
                        </div>

                        <Form.Group className="mb-4" controlId="preconfigured-tool-description">
                          <Form.Label className="form-label-custom">Tool Description</Form.Label>
                          <Form.Control
                            as="textarea"
                            rows={2}
                            className="custom-input"
                            placeholder="Describes what this tool does..."
                            value={preconfiguredTool.description}
                            onChange={(e) => setPreconfiguredTool({ ...preconfiguredTool, description: e.target.value })}
                          />
                        </Form.Group>

                        {/* 3. Provider Specific Configuration */}
                        <div className="parameter-card mb-4">
                          <div className="parameter-card-header">
                            <span className="rag-section-header mb-0">
                              <TuneIcon style={{ fontSize: 20 }} /> {preconfiguredProvider === 'tavily_search' ? 'Tavily Search Configuration' : 'DuckDuckGo Search Configuration'}
                            </span>
                          </div>

                          <Row className="g-3">
                            {preconfiguredProvider === 'tavily_search' && (
                              <Col md={8}>
                                <InputField
                                  id="tavily-api-key"
                                  label="Tavily API Key"
                                  type="password"
                                  name="tavily_api_key"
                                  value={preconfiguredTool.apiKey}
                                  placeholder="tvly-..."
                                  onChange={(e) => setPreconfiguredTool({ ...preconfiguredTool, apiKey: e.target.value })}
                                  showPasswordToggle
                                  required
                                />
                              </Col>
                            )}

                            <Col md={preconfiguredProvider === 'tavily_search' ? 4 : 6}>
                              <InputField
                                id="preconfigured-max-results"
                                label="Max Results (Optional)"
                                type="number"
                                name="max_results"
                                value={preconfiguredTool.maxResults ? preconfiguredTool.maxResults.toString() : ''}
                                placeholder={preconfiguredProvider === 'tavily_search' ? '5' : '4'}
                                onChange={(e) => setPreconfiguredTool({ ...preconfiguredTool, maxResults: parseInt(e.target.value) || 0 })}
                              />
                            </Col>
                          </Row>
                        </div>
                      </div>
                    )}

                    {/* RAG TOOL TOGGLE */}
                    {toolToggle === 'RAG' && (
                      <div>
                        {/* 1. Tool Identity */}
                        <div className="mb-3">
                          <InputField
                            id="rag-tool-name"
                            label="RAG Tool Name"
                            type="text"
                            name="rag_tool_name"
                            value={ragTool.name}
                            placeholder="e.g. Corporate Knowledge Base"
                            onChange={(e) => setRagTool({ ...ragTool, name: e.target.value })}
                          />
                        </div>

                        <Form.Group className="mb-4" controlId="rag-tool-description">
                          <Form.Label className="form-label-custom">Tool Description</Form.Label>
                          <Form.Control
                            as="textarea"
                            rows={2}
                            className="custom-input"
                            placeholder="Describes what documents this RAG tool searches and retrieves..."
                            value={ragTool.description}
                            onChange={(e) => setRagTool({ ...ragTool, description: e.target.value })}
                          />
                        </Form.Group>

                        {/* 2. Document Knowledge Source */}
                        <div className="parameter-card mb-4">
                          <div className="parameter-card-header">
                            <span className="rag-section-header mb-0">
                              <CloudUploadIcon style={{ fontSize: 20 }} /> Document Knowledge Source
                            </span>
                          </div>

                          <input
                            type="file"
                            ref={fileInputRef}
                            onChange={handleFileChange}
                            accept=".pdf,.docx,.txt,.md,.html,.pptx"
                            style={{ display: 'none' }}
                          />

                          {!ragTool.selectedFile ? (
                            <div
                              className="rag-upload-dropzone"
                              onClick={() => fileInputRef.current?.click()}
                            >
                              <CloudUploadIcon className="text-cyan-accent mb-2" style={{ fontSize: 40 }} />
                              <h6 className="text-white mb-1">Click to upload document file</h6>
                              <p className="small text-muted mb-0">
                                Supported formats: PDF, DOCX, TXT, MD, HTML, PPTX. File will be ingested into your vector database.
                              </p>
                            </div>
                          ) : (
                            <div className="rag-upload-file-badge">
                              <div className="d-flex align-items-center gap-3">
                                <InsertDriveFileIcon className="text-cyan-accent" style={{ fontSize: 32 }} />
                                <div>
                                  <div className="fw-semibold text-white small">{ragTool.selectedFile.name}</div>
                                  <div className="text-muted" style={{ fontSize: '0.78rem' }}>
                                    {(ragTool.selectedFile.size / 1024 / 1024).toFixed(2)} MB • Ready for ingestion
                                  </div>
                                </div>
                              </div>
                              <div className="d-flex align-items-center gap-2">
                                <Button
                                  variant="outline-info"
                                  size="sm"
                                  className="rounded-pill px-3 py-1"
                                  style={{ fontSize: '0.8rem' }}
                                  onClick={() => fileInputRef.current?.click()}
                                >
                                  Change
                                </Button>
                                <Button
                                  variant="link"
                                  size="sm"
                                  className="text-danger p-0"
                                  onClick={handleRemoveFile}
                                  title="Remove File"
                                >
                                  <DeleteIcon style={{ fontSize: 20 }} />
                                </Button>
                              </div>
                            </div>
                          )}
                        </div>

                        {/* 3. Embedding Model Configuration */}
                        <div className="parameter-card mb-4">
                          <div className="parameter-card-header">
                            <span className="rag-section-header mb-0">
                              <MemoryIcon style={{ fontSize: 20 }} /> Embedding Model Configuration
                            </span>
                          </div>

                          {/* Embedding Provider Horizontal List */}
                          <div className="mb-3">
                            <Form.Label className="form-label-custom small mb-2 d-block">
                              Embedding Provider
                            </Form.Label>
                            <div className="embedding-provider-grid">
                              {EMBEDDING_MODEL_PROVIDERS.map((provider) => {
                                const isSelected = ragTool.embeddingProvider === provider.id;
                                return (
                                  <div
                                    key={provider.id}
                                    id={`embedding-provider-${provider.id}`}
                                    className={`vector-provider-card ${isSelected ? 'selected' : ''}`}
                                    onClick={() => handleEmbeddingProviderChange(provider.id)}
                                    role="button"
                                    tabIndex={0}
                                    onKeyDown={(e) => {
                                      if (e.key === 'Enter' || e.key === ' ') {
                                        handleEmbeddingProviderChange(provider.id);
                                      }
                                    }}
                                  >
                                    <div className="vector-provider-icon-wrapper">
                                      {provider.renderIcon()}
                                    </div>
                                    <span className="vector-provider-name">{provider.label}</span>
                                    {isSelected && (
                                      <span className="vector-provider-check ms-auto">
                                        <TaskAltIcon style={{ fontSize: 16 }} />
                                      </span>
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          </div>

                          <Row className="g-3">
                            <Col md={6}>
                              <InputField
                                id="embedding-model"
                                label="Embedding Model"
                                type="text"
                                name="embedding_model"
                                value={ragTool.embeddingModel}
                                placeholder="e.g. text-embedding-3-small"
                                onChange={(e) => setRagTool({ ...ragTool, embeddingModel: e.target.value })}
                              />
                            </Col>

                            <Col md={6}>
                              <InputField
                                id="embedding-api-key"
                                label="Embedding API Key"
                                type="password"
                                name="embedding_api_key"
                                value={ragTool.embeddingApiKey}
                                placeholder="sk-..."
                                onChange={(e) => setRagTool({ ...ragTool, embeddingApiKey: e.target.value })}
                              />
                            </Col>
                          </Row>
                        </div>

                        {/* 4. Vector Database Configuration */}
                        <div className="parameter-card mb-4">
                          <div className="parameter-card-header">
                            <span className="rag-section-header mb-0">
                              <StorageIcon style={{ fontSize: 20 }} /> Vector Database Configuration
                            </span>
                          </div>

                          {/* Vector DB Provider Select Cards */}
                          <div className="mb-4">
                            <Form.Label className="form-label-custom small mb-2 d-block">
                              Vector DB Provider <span className="text-secondary" style={{ fontSize: '0.8rem' }}>(Select from supported providers)</span>
                            </Form.Label>
                            <div className="vector-provider-grid">
                              {VECTOR_DB_PROVIDERS.map((provider) => {
                                const isSelected = ragTool.vectorDbProvider === provider.id;
                                return (
                                  <div
                                    key={provider.id}
                                    id={`vector-provider-${provider.id}`}
                                    className={`vector-provider-card ${isSelected ? 'selected' : ''}`}
                                    onClick={() => setRagTool({ ...ragTool, vectorDbProvider: provider.id })}
                                    role="button"
                                    tabIndex={0}
                                    onKeyDown={(e) => {
                                      if (e.key === 'Enter' || e.key === ' ') {
                                        setRagTool({ ...ragTool, vectorDbProvider: provider.id });
                                      }
                                    }}
                                  >
                                    <div className="vector-provider-icon-wrapper">
                                      {provider.renderIcon()}
                                    </div>
                                    <span className="vector-provider-name">{provider.label}</span>
                                    {isSelected && (
                                      <span className="vector-provider-check ms-auto">
                                        <TaskAltIcon style={{ fontSize: 16 }} />
                                      </span>
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          </div>

                          <Row className="g-3 mb-3">
                            <Col md={6}>
                              <InputField
                                id="vector-collection-name"
                                label="Collection / Index Name"
                                type="text"
                                name="collection_name"
                                value={ragTool.collectionName}
                                placeholder="e.g. agent-mart-kb"
                                onChange={(e) => setRagTool({ ...ragTool, collectionName: e.target.value })}
                              />
                            </Col>

                            <Col md={6}>
                              <InputField
                                id="vector-db-api-key"
                                label="Vector DB API Key"
                                type="password"
                                name="vector_db_api_key"
                                value={ragTool.vectorDbApiKey}
                                placeholder="Enter API Key"
                                onChange={(e) => setRagTool({ ...ragTool, vectorDbApiKey: e.target.value })}
                              />
                            </Col>
                          </Row>

                          <Row className="g-3 mb-3">
                            <Col md={ragTool.vectorDbProvider === 'chroma' ? 6 : 4}>
                              <InputField
                                id="vector-dimension"
                                label="Vector Dimension"
                                type="number"
                                name="vector_dimension"
                                value={ragTool.vectorDimension ? ragTool.vectorDimension.toString() : ''}
                                placeholder="1536"
                                onChange={(e) => setRagTool({ ...ragTool, vectorDimension: Number(e.target.value) || 0 })}
                              />
                            </Col>

                            <Col md={ragTool.vectorDbProvider === 'chroma' ? 6 : 4}>
                              <InputField
                                id="vector-top-k"
                                label="Top K Results"
                                type="number"
                                name="top_k"
                                value={ragTool.topK ? ragTool.topK.toString() : ''}
                                placeholder="15"
                                onChange={(e) => setRagTool({ ...ragTool, topK: Number(e.target.value) || 15 })}
                              />
                            </Col>

                            {ragTool.vectorDbProvider !== 'chroma' && (
                              <Col md={4}>
                                <InputField
                                  id="vector-namespace"
                                  label={`Namespace (Optional)${ragTool.vectorDbProvider === 'qdrant' ? ' (Not required for Qdrant)' : ''}`}
                                  type="text"
                                  name="namespace"
                                  value={ragTool.vectorDbProvider === 'qdrant' ? '' : ragTool.namespace}
                                  placeholder={ragTool.vectorDbProvider === 'qdrant' ? 'Not applicable for Qdrant' : 'e.g. default'}
                                  onChange={(e) => setRagTool({ ...ragTool, namespace: e.target.value })}
                                  disabled={ragTool.vectorDbProvider === 'qdrant'}
                                />
                              </Col>
                            )}
                          </Row>

                          {ragTool.vectorDbProvider === 'chroma' ? (
                            <Row className="g-3">
                              <Col md={6}>
                                <InputField
                                  id="vector-db-tenant"
                                  label="Vector DB Tenant (Optional)"
                                  type="text"
                                  name="vector_db_tenant"
                                  value={ragTool.vectorDbTenant}
                                  placeholder="e.g. default_tenant"
                                  onChange={(e) => setRagTool({ ...ragTool, vectorDbTenant: e.target.value })}
                                />
                              </Col>

                              <Col md={6}>
                                <InputField
                                  id="vector-db-url"
                                  label="Database Name / URL (Optional)"
                                  type="text"
                                  name="vector_db_url"
                                  value={ragTool.vectorDbUrl}
                                  placeholder="e.g. default_database"
                                  onChange={(e) => setRagTool({ ...ragTool, vectorDbUrl: e.target.value })}
                                />
                              </Col>
                            </Row>
                          ) : (
                            <Row className="g-3">
                              <Col md={5}>
                                <Form.Group controlId="vector-cloud-provider">
                                  <Form.Label className="form-label-custom small mb-1 d-block">
                                    Cloud Provider {ragTool.vectorDbProvider === 'pinecone' && <span className="text-secondary">(Pinecone)</span>}
                                    {ragTool.vectorDbProvider === 'qdrant' && <span className="text-muted ms-1">(Not required for Qdrant)</span>}
                                  </Form.Label>
                                  <div className={`cloud-provider-group ${ragTool.vectorDbProvider === 'qdrant' ? 'disabled' : ''}`}>
                                    {CLOUD_PROVIDERS.map((cp) => {
                                      const isSelected = ragTool.vectorDbProvider !== 'qdrant' && ragTool.cloudProvider === cp.id;
                                      return (
                                        <div
                                          key={cp.id}
                                          id={`cloud-provider-${cp.id}`}
                                          className={`cloud-provider-btn ${isSelected ? 'selected' : ''} ${ragTool.vectorDbProvider === 'qdrant' ? 'disabled' : ''}`}
                                          onClick={() => {
                                            if (ragTool.vectorDbProvider !== 'qdrant') {
                                              setRagTool({ ...ragTool, cloudProvider: cp.id });
                                            }
                                          }}
                                          role="button"
                                          tabIndex={ragTool.vectorDbProvider === 'qdrant' ? -1 : 0}
                                          aria-disabled={ragTool.vectorDbProvider === 'qdrant'}
                                          onKeyDown={(e) => {
                                            if (ragTool.vectorDbProvider !== 'qdrant' && (e.key === 'Enter' || e.key === ' ')) {
                                              setRagTool({ ...ragTool, cloudProvider: cp.id });
                                            }
                                          }}
                                        >
                                          <div className="cloud-provider-icon">
                                            {cp.renderIcon()}
                                          </div>
                                          <span className="cloud-provider-label">{cp.label}</span>
                                        </div>
                                      );
                                    })}
                                  </div>
                                </Form.Group>
                              </Col>

                              <Col md={3}>
                                <InputField
                                  id="vector-region"
                                  label={`Region${ragTool.vectorDbProvider === 'qdrant' ? ' (Not required for Qdrant)' : ''}`}
                                  type="text"
                                  name="region"
                                  value={ragTool.vectorDbProvider === 'qdrant' ? '' : ragTool.region}
                                  placeholder={ragTool.vectorDbProvider === 'qdrant' ? 'Not applicable for Qdrant' : 'e.g. us-east-1'}
                                  onChange={(e) => setRagTool({ ...ragTool, region: e.target.value })}
                                  disabled={ragTool.vectorDbProvider === 'qdrant'}
                                />
                              </Col>

                              <Col md={4}>
                                <InputField
                                  id="vector-db-url"
                                  label="Vector DB URL (Optional)"
                                  type="text"
                                  name="vector_db_url"
                                  value={ragTool.vectorDbUrl}
                                  placeholder="e.g. https://xxx.pinecone.io"
                                  onChange={(e) => setRagTool({ ...ragTool, vectorDbUrl: e.target.value })}
                                />
                              </Col>
                            </Row>
                          )}
                        </div>

                        {/* 5. Advanced RAG Configuration Section */}
                        <div className="mb-4">
                          <div className="d-flex align-items-center justify-content-between mb-2">
                            <span className="rag-section-header mb-0">
                              <TuneIcon style={{ fontSize: 20 }} /> Advanced RAG Settings
                            </span>
                            <button
                              type="button"
                              className="btn btn-link p-0 text-decoration-none d-inline-flex align-items-center"
                              style={{ color: 'var(--primary-accent)' }}
                              onClick={() => setShowRagAdvanced(!showRagAdvanced)}
                              title={showRagAdvanced ? 'Hide Advanced Settings' : 'Show Advanced Settings'}
                              aria-label={showRagAdvanced ? 'Hide Advanced Settings' : 'Show Advanced Settings'}
                            >
                              {showRagAdvanced ? (
                                <ExpandMoreIcon style={{ fontSize: 24, cursor: 'pointer' }} />
                              ) : (
                                <ExpandLessIcon style={{ fontSize: 24, cursor: 'pointer' }} />
                              )}
                            </button>
                          </div>

                          {showRagAdvanced && (
                            <div className="parameter-card">
                              <Row className="g-3 mb-3">
                                <Col md={3}>
                                  <Form.Group controlId="rag-chunking-strategy">
                                    <Form.Label className="form-label-custom small mb-1">Chunking Strategy</Form.Label>
                                    <Form.Select
                                      className="custom-input"
                                      value={ragTool.chunkingStrategy}
                                      onChange={(e) => setRagTool({ ...ragTool, chunkingStrategy: e.target.value as any })}
                                    >
                                      <option value="recursive">Recursive Character</option>
                                      <option value="token">Token Based</option>
                                      <option value="hierarchial">Hierarchical</option>
                                      <option value="semantic">Semantic</option>
                                    </Form.Select>
                                  </Form.Group>
                                </Col>

                                <Col md={3}>
                                  <InputField
                                    id="rag-chunk-size"
                                    label="Chunk Size"
                                    type="number"
                                    name="chunk_size"
                                    value={ragTool.chunkSize ? ragTool.chunkSize.toString() : ''}
                                    placeholder="1000"
                                    onChange={(e) => setRagTool({ ...ragTool, chunkSize: Number(e.target.value) || 1000 })}
                                  />
                                </Col>

                                <Col md={3}>
                                  <InputField
                                    id="rag-chunk-overlap"
                                    label="Chunk Overlap"
                                    type="number"
                                    name="chunk_overlap"
                                    value={ragTool.chunkOverlap !== undefined ? ragTool.chunkOverlap.toString() : ''}
                                    placeholder="200"
                                    onChange={(e) => setRagTool({ ...ragTool, chunkOverlap: Number(e.target.value) || 200 })}
                                  />
                                </Col>

                                <Col md={3}>
                                  <Form.Group controlId="rag-retrieval-strategy">
                                    <Form.Label className="form-label-custom small mb-1">Retrieval Strategy</Form.Label>
                                    <Form.Select
                                      className="custom-input"
                                      value={ragTool.retrievalStrategy}
                                      onChange={(e) => setRagTool({ ...ragTool, retrievalStrategy: e.target.value as any })}
                                    >
                                      <option value="similarity">Similarity</option>
                                      <option value="mmr">MMR</option>
                                      <option value="hybrid">Hybrid</option>
                                    </Form.Select>
                                  </Form.Group>
                                </Col>
                              </Row>

                              <Row className="g-3 mb-3">
                                <Col md={3}>
                                  <Form.Group controlId="rag-distance-strategy">
                                    <Form.Label className="form-label-custom small mb-1">Distance Metric</Form.Label>
                                    <Form.Select
                                      className="custom-input"
                                      value={ragTool.distanceStrategy}
                                      onChange={(e) => setRagTool({ ...ragTool, distanceStrategy: e.target.value as any })}
                                    >
                                      <option value="dotproduct">Dot Product</option>
                                      <option value="cosine">Cosine</option>
                                      <option value="euclidean">Euclidean</option>
                                      <option value="manhattan">Manhattan</option>
                                    </Form.Select>
                                  </Form.Group>
                                </Col>

                                <Col md={3}>
                                  <Form.Group controlId="rag-vector-type">
                                    <Form.Label className="form-label-custom small mb-1">Vector Type</Form.Label>
                                    <Form.Select
                                      className="custom-input"
                                      value={ragTool.vectorType}
                                      onChange={(e) => setRagTool({ ...ragTool, vectorType: e.target.value as any })}
                                    >
                                      <option value="dense">Dense</option>
                                      <option value="sparse">Sparse</option>
                                    </Form.Select>
                                  </Form.Group>
                                </Col>

                                <Col md={6} className="d-flex align-items-center mt-4">
                                  <Form.Check
                                    type="switch"
                                    id="rag-rerank-switch"
                                    label={<span className="text-light small fw-medium">Enable Document Reranking</span>}
                                    checked={ragTool.rerankEnabled}
                                    onChange={(e) => setRagTool({ ...ragTool, rerankEnabled: e.target.checked })}
                                  />
                                </Col>
                              </Row>

                              {ragTool.rerankEnabled && (
                                <Row className="g-3 pt-2 border-top border-secondary border-opacity-25">
                                  <Col md={4}>
                                    <Form.Group controlId="rag-rerank-provider">
                                      <Form.Label className="form-label-custom small mb-1">Rerank Provider</Form.Label>
                                      <Form.Select
                                        className="custom-input"
                                        value={ragTool.rerankProvider}
                                        onChange={(e) => setRagTool({ ...ragTool, rerankProvider: e.target.value as any })}
                                      >
                                        <option value="cohere">Cohere</option>
                                        <option value="gemini">Gemini</option>
                                        <option value="openai">OpenAI</option>
                                      </Form.Select>
                                    </Form.Group>
                                  </Col>

                                  <Col md={5}>
                                    <InputField
                                      id="rag-rerank-model"
                                      label="Rerank Model Name"
                                      type="text"
                                      name="rerank_model"
                                      value={ragTool.rerankModel}
                                      placeholder="e.g. rerank-english-v3.0"
                                      onChange={(e) => setRagTool({ ...ragTool, rerankModel: e.target.value })}
                                    />
                                  </Col>

                                  <Col md={3}>
                                    <InputField
                                      id="rag-rerank-top-k"
                                      label="Rerank Top K"
                                      type="number"
                                      name="rerank_top_k"
                                      value={ragTool.rerankTopK ? ragTool.rerankTopK.toString() : ''}
                                      placeholder="5"
                                      onChange={(e) => setRagTool({ ...ragTool, rerankTopK: Number(e.target.value) || 5 })}
                                    />
                                  </Col>
                                </Row>
                              )}
                            </div>
                          )}
                        </div>
                      </div>
                    )}

                    <div className="d-flex justify-content-between align-items-center mt-4">
                      <Button variant="outline-secondary" onClick={() => setActiveStep('model')} className="px-4 agent-action-btn">
                        Back
                      </Button>
                      <div className="d-flex align-items-center gap-3">
                        <Button
                          type="button"
                          className="btn-cyan-primary agent-action-btn px-4 d-flex align-items-center gap-2"
                          onClick={handleSaveTool}
                          disabled={isSavingTool}
                        >
                          {isSavingTool ? (
                            <>
                              <Spinner animation="border" size="sm" />
                              <span>Saving...</span>
                            </>
                          ) : (
                            <>
                              
                              <span>Save</span>
                            </>
                          )}
                        </Button>
                        <Button
                          type="button"
                          className="btn-cyan-primary agent-action-btn px-4"
                          onClick={handleToolsNext}
                        >
                          Next
                        </Button>
                      </div>
                    </div>
                  </Form>
                </div>
              )}

              {/* STEP 4: PROMPT */}
              {activeStep === 'prompt' && (
                <div>
                  <h3 className="step-title">System Prompt</h3>
                  <p className="step-description">Provide instructions, domain knowledge, and behavioral guidelines for the agent.</p>

                  <Form onSubmit={handlePromptSubmit}>
                    <Form.Group className="mb-4" controlId="system-prompt font-monospace">
                      <Form.Label className="form-label-custom">System Prompt Text</Form.Label>
                      <Form.Control
                        as="textarea"
                        rows={8}
                        className="custom-input font-monospace fs-6"
                        placeholder="You are an expert AI assistant that follows strict guidelines..."
                        value={systemPrompt}
                        onChange={(e) => setSystemPrompt(e.target.value)}
                        required
                      />
                    </Form.Group>

                    <div className="d-flex justify-content-between">
                      <Button variant="outline-secondary" onClick={() => setActiveStep('tools')} className="px-4 agent-action-btn">
                        Back
                      </Button>
                      <Button type="submit" className="btn-cyan-primary agent-action-btn px-4" disabled={isLoading}>
                        {isLoading ? (
                          <>
                            <Spinner animation="border" size="sm" className="me-2" />
                            Saving...
                          </>
                        ) : (
                          'Next'
                        )}
                      </Button>
                    </div>
                  </Form>
                </div>
              )}

              {/* STEP 5: DEPLOY */}
              {activeStep === 'deploy' && (
                <div>
                  <h3 className="step-title">Review & Deploy</h3>
                  <p className="step-description">Your agent configuration is ready to be finalized and activated.</p>

                  <div className="p-4 rounded-4 bg-dark bg-opacity-50 border border-secondary border-opacity-25 mb-4">
                    <Row className="g-3">
                      <Col md={6}>
                        <small className="text-secondary d-block mb-1">Agent Name</small>
                        <h6 className="text-white fw-bold">{identity.name || 'Untitled Agent'}</h6>
                      </Col>
                      <Col md={6}>
                        <small className="text-secondary d-block mb-1">Visibility</small>
                        <Badge bg={identity.visibility === 'PUBLIC' ? 'success' : 'secondary'} className="px-2 py-1">
                          {identity.visibility}
                        </Badge>
                      </Col>
                      <Col md={6}>
                        <small className="text-secondary d-block mb-1">Model Provider & Name</small>
                        <span className="text-light fw-medium">{model.provider} ({model.name})</span>
                      </Col>
                      <Col md={6}>
                        <small className="text-secondary d-block mb-1">Temperature / Tokens</small>
                        <span className="text-light fw-medium">{model.temperature} / {model.max_tokens}</span>
                      </Col>
                      <Col md={12}>
                        <small className="text-secondary d-block mb-1">System Prompt Preview</small>
                        <div className="p-2 rounded bg-black bg-opacity-40 text-secondary font-monospace small">
                          {systemPrompt ? `${systemPrompt.slice(0, 150)}...` : 'No prompt configured.'}
                        </div>
                      </Col>
                    </Row>
                  </div>

                  <div className="d-flex justify-content-between">
                    <Button variant="outline-secondary" onClick={() => setActiveStep('prompt')} className="px-4 agent-action-btn">
                      Back
                    </Button>
                    <Button type="button" className="btn-cyan-primary agent-action-btn px-5 fw-bold" onClick={handleDeployClick} disabled={isLoading}>
                      {isLoading ? (
                        <>
                          <Spinner animation="border" size="sm" className="me-2" />
                          Deploying...
                        </>
                      ) : (
                        'Deploy Agent'
                      )}
                    </Button>
                  </div>
                </div>
              )}
            </Col>
          </Row>
        </div>
      </Container>
    </div>
  );
};
