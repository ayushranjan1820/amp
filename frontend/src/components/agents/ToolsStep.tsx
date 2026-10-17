import React, { useState, useRef } from 'react';
import { Row, Col, Form, Button, Spinner, OverlayTrigger, Tooltip } from 'react-bootstrap';
import TaskAltIcon from '@mui/icons-material/TaskAlt';
import DeleteIcon from '@mui/icons-material/Delete';
import CloudUploadIcon from '@mui/icons-material/CloudUpload';
import InsertDriveFileIcon from '@mui/icons-material/InsertDriveFile';
import TuneIcon from '@mui/icons-material/Tune';
import StorageIcon from '@mui/icons-material/Storage';
import MemoryIcon from '@mui/icons-material/Memory';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import AddCircleIcon from '@mui/icons-material/AddCircle';
import { InputField } from '../common/InputField';
import { post, extractErrorMessage } from '../../services/apiWrapper';
import { API_ENDPOINTS } from '../../constants';
import type {
  HeaderRow,
  ParamRow,
  DiscoveredMcpTool,
  EmbeddingProviderType,
} from './toolsStepConstants';
import {
  VECTOR_DB_PROVIDERS,
  CLOUD_PROVIDERS,
  EMBEDDING_MODEL_PROVIDERS,
  PRECONFIGURED_TOOLS,
  mcpPlaceholderText,
  INITIAL_API_TOOL_STATE,
  INITIAL_MCP_TOOL_STATE,
  INITIAL_PRECONFIGURED_TOOL_STATE,
  INITIAL_RAG_TOOL_STATE,
} from './toolsStepConstants';
import './ToolsStep.css';

export type {
  HeaderRow,
  ParamRow,
  DiscoveredMcpTool,
  EmbeddingProviderType,
  VectorDbProviderType,
} from './toolsStepConstants';

export interface ToolsStepProps {
  agentId: string | null;
  agentName?: string;
  agentDescription?: string;
  onNext: () => void;
  onBack: () => void;
  onSuccess: (message: string) => void;
  onError: (message: string) => void;
  clearAlerts: () => void;
  markStepComplete: (step: 'tools') => void;
}

export const ToolsStep: React.FC<ToolsStepProps> = ({
  agentId,
  agentName = '',
  agentDescription = '',
  onNext,
  onBack,
  onSuccess,
  onError,
  clearAlerts,
  markStepComplete,
}) => {
  const [toolToggle, setToolToggle] = useState<'PRECONFIGURED' | 'API' | 'MCP' | 'RAG'>('API');

  // API Tool State
  const [apiTool, setApiTool] = useState(INITIAL_API_TOOL_STATE);

  const [showHeadersSection, setShowHeadersSection] = useState(false);
  const [headers, setHeaders] = useState<HeaderRow[]>([]);

  const [showParametersSection, setShowParametersSection] = useState(false);
  const [parameters, setParameters] = useState<ParamRow[]>([]);

  // MCP Tool State
  const [mcpTool, setMcpTool] = useState(INITIAL_MCP_TOOL_STATE);
  const [mcpConfigText, setMcpConfigText] = useState<string>('');
  const [isDiscoveringMcp, setIsDiscoveringMcp] = useState<boolean>(false);
  const [discoveredMcpTools, setDiscoveredMcpTools] = useState<DiscoveredMcpTool[]>([]);
  const [selectedMcpTools, setSelectedMcpTools] = useState<Record<string, boolean>>({});

  // RAG Tool State
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [ragTool, setRagTool] = useState(INITIAL_RAG_TOOL_STATE);
  const [showRagAdvanced, setShowRagAdvanced] = useState(false);

  // Preconfigured Tool State
  const [preconfiguredProvider, setPreconfiguredProvider] = useState<'tavily_search' | 'duckduckgo_search'>('tavily_search');
  const [preconfiguredTool, setPreconfiguredTool] = useState(INITIAL_PRECONFIGURED_TOOL_STATE);

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

  // Dynamic Header Handlers
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

  // Dynamic Parameter Handlers
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
      onError('Please enter an MCP JSON configuration.');
      return;
    }

    let parsedConfig: Record<string, any>;
    try {
      parsedConfig = JSON.parse(mcpConfigText);
    } catch {
      onError('Invalid MCP JSON configuration. Please ensure it is valid JSON.');
      return;
    }

    setIsDiscoveringMcp(true);
    clearAlerts();

    try {
      const res: any = await post(API_ENDPOINTS.AGENTS.TOOLS_FROM_MCP, parsedConfig);
      const toolsList: DiscoveredMcpTool[] = Array.isArray(res) ? res : res?.data || [];

      setDiscoveredMcpTools(toolsList);

      const initialSelection: Record<string, boolean> = {};
      toolsList.forEach((t) => {
        initialSelection[t.tool_name] = true;
      });
      setSelectedMcpTools(initialSelection);

      if (toolsList.length === 0) {
        onSuccess('No tools were found in the provided MCP configuration.');
      } else {
        onSuccess(`Successfully discovered ${toolsList.length} MCP tool(s).`);
      }
    } catch (err) {
      onError(extractErrorMessage(err));
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

  // Step 3: Tools Save Button Handler
  const handleSaveTool = async () => {
    if (!agentId) {
      onError('Please complete Step 1 (Identity) first before saving tools.');
      return;
    }

    setIsSavingTool(true);
    clearAlerts();

    try {
      if (toolToggle === 'API') {
        if (!apiTool.url.trim()) {
          onError('Please provide a target endpoint URL for the API tool.');
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
          name: apiTool.name.trim() || `${agentName || 'Agent'} API Tool`,
          description: apiTool.description.trim() || agentDescription || '',
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
        onSuccess('API tool saved successfully!');
        markStepComplete('tools');
      } else if (toolToggle === 'MCP') {
        if (!mcpTool.name.trim()) {
          onError('Please enter an MCP Tool Name.');
          setIsSavingTool(false);
          return;
        }
        if (!mcpTool.description.trim()) {
          onError('Please enter an MCP Tool Description.');
          setIsSavingTool(false);
          return;
        }

        let parsedConfig: Record<string, any> = {};
        if (mcpConfigText.trim()) {
          try {
            parsedConfig = JSON.parse(mcpConfigText);
          } catch {
            onError('Invalid MCP JSON configuration format. Please ensure it is valid JSON.');
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
        onSuccess('MCP tool saved successfully!');
        markStepComplete('tools');
      } else if (toolToggle === 'PRECONFIGURED') {
        if (!preconfiguredTool.name.trim()) {
          onError('Please enter a tool name.');
          setIsSavingTool(false);
          return;
        }

        const configMap: Record<string, any> = {};

        if (preconfiguredProvider === 'tavily_search') {
          if (!preconfiguredTool.apiKey.trim()) {
            onError('Please provide a Tavily API Key.');
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
        onSuccess(`${preconfiguredProvider === 'tavily_search' ? 'Tavily Search' : 'DuckDuckGo Search'} tool saved successfully!`);
        markStepComplete('tools');
      } else if (toolToggle === 'RAG') {
        if (!ragTool.name.trim()) {
          onError('Please enter an Agent Tool Name for RAG.');
          setIsSavingTool(false);
          return;
        }
        if (!ragTool.description.trim()) {
          onError('Please enter a description for the RAG Tool.');
          setIsSavingTool(false);
          return;
        }
        if (!ragTool.selectedFile) {
          onError('Please upload a document file to ingest for the RAG Tool.');
          setIsSavingTool(false);
          return;
        }
        if (!ragTool.embeddingApiKey.trim()) {
          onError('Please provide an API key for the Embedding model.');
          setIsSavingTool(false);
          return;
        }
        if (!ragTool.collectionName.trim()) {
          onError(ragTool.vectorDbProvider === 'pinecone'
            ? 'Please provide an Index Name for Pinecone.'
            : 'Please provide a Collection Name for the Vector Database.');
          setIsSavingTool(false);
          return;
        }
        if (!ragTool.vectorDbApiKey.trim()) {
          onError('Please provide an API key for the Vector Database.');
          setIsSavingTool(false);
          return;
        }
        if ((ragTool.vectorDbProvider === 'qdrant' || ragTool.vectorDbProvider === 'weaviate') && !ragTool.vectorDbUrl.trim()) {
          onError(`Please provide a Vector DB URL for ${ragTool.vectorDbProvider === 'weaviate' ? 'Weaviate' : 'Qdrant'}.`);
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
        const isPinecone = ragTool.vectorDbProvider === 'pinecone';
        const isQdrant = ragTool.vectorDbProvider === 'qdrant';
        const isChroma = ragTool.vectorDbProvider === 'chroma';
        const isWeaviate = ragTool.vectorDbProvider === 'weaviate';

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
            vector_db_url: (isQdrant || isChroma || isWeaviate) ? (ragTool.vectorDbUrl.trim() || null) : null,
            vector_db_api_key: ragTool.vectorDbApiKey.trim(),
            collection_name: ragTool.collectionName.trim(),
            namespace: isPinecone ? (ragTool.namespace.trim() || null) : null,
            vector_db_tenant: isChroma ? (ragTool.vectorDbTenant.trim() || null) : null,
            vector_dimension: (isPinecone || isQdrant) ? (ragTool.vectorDimension ? Number(ragTool.vectorDimension) : null) : null,
            top_k: Number(ragTool.topK) || 15,
            cloud_provider: isPinecone ? (ragTool.cloudProvider || null) : null,
            region: isPinecone ? (ragTool.region.trim() || null) : null,
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
        onSuccess('RAG tool document uploaded and saved successfully!');
        markStepComplete('tools');
      }
    } catch (err) {
      onError(extractErrorMessage(err));
    } finally {
      setIsSavingTool(false);
    }
  };

  const handleToolsNext = () => {
    clearAlerts();
    markStepComplete('tools');
    onNext();
  };

  return (
    <div>
      <h3 className="step-title">Tool Configuration</h3>
      <p className="step-description">Connect external APIs, preconfigured utilities, or MCP protocol endpoints to your agent.</p>

      {/* Toggle Pill Selection */}
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
                placeholder="Describes what this tool does and when the agent should invoke it..."
                value={apiTool.description}
                onChange={(e) => setApiTool({ ...apiTool, description: e.target.value })}
              />
            </Form.Group>

            {/* 3. HTTP Method & Target URL side-by-side */}
            <Row className="g-3 mb-4">
              <Col md={3}>
                <Form.Group controlId="tool-method">
                  <Form.Label className="form-label-custom">HTTP Method</Form.Label>
                  <Form.Select
                    className="custom-input"
                    value={apiTool.method}
                    onChange={(e) => setApiTool({ ...apiTool, method: e.target.value as any })}
                  >
                    <option value="GET">GET</option>
                    <option value="POST">POST</option>
                    <option value="PUT">PUT</option>
                    <option value="DELETE">DELETE</option>
                  </Form.Select>
                </Form.Group>
              </Col>
              <Col md={9}>
                <InputField
                  id="tool-url"
                  label="Target Endpoint URL"
                  type="url"
                  name="tool_url"
                  value={apiTool.url}
                  placeholder="https://api.weatherapi.com/v1/current.json"
                  onChange={(e) => setApiTool({ ...apiTool, url: e.target.value })}
                  required
                />
              </Col>
            </Row>

            {/* 4. Dynamic HTTP Headers Section */}
            <div className="mb-4">
              <div className="d-flex align-items-center justify-content-between mb-2">
                <span className="form-label-custom mb-0 fw-semibold">HTTP Headers</span>
                <span className="add-option-btn" onClick={handleAddHeader}>
                  <AddCircleIcon style={{ fontSize: 20, cursor: 'pointer' }} />Add Header
                </span>
              </div>

              {showHeadersSection && headers.length > 0 ? (
                <div className="p-3 rounded-4 bg-dark bg-opacity-25 border border-secondary border-opacity-25 mb-3">
                  {headers.map((h) => (
                    <Row key={h.id} className="g-2 header-input-row align-items-center">
                      <Col md={5}>
                        <Form.Control
                          type="text"
                          placeholder="Header Key (e.g. Authorization)"
                          className="custom-input"
                          value={h.key}
                          onChange={(e) => handleHeaderChange(h.id, 'key', e.target.value)}
                        />
                      </Col>
                      <Col md={6}>
                        <Form.Control
                          type="text"
                          placeholder="Header Value (e.g. Bearer token)"
                          className="custom-input"
                          value={h.value}
                          onChange={(e) => handleHeaderChange(h.id, 'value', e.target.value)}
                        />
                      </Col>
                      <Col md={1} className="d-flex justify-content-end">
                        <Button
                          variant="link"
                          className="text-danger p-0 d-flex align-items-center justify-content-center"
                          onClick={() => handleRemoveHeader(h.id)}
                          title="Remove Header"
                        >
                          <DeleteIcon style={{ fontSize: 20 }} />
                        </Button>
                      </Col>
                    </Row>
                  ))}
                </div>
              ) : null}
            </div>

            {/* 5. Dynamic API Parameters Section */}
            <div className="mb-4">
              <div className="d-flex align-items-center justify-content-between mb-2">
                <span className="form-label-custom mb-0 fw-semibold">API Parameters</span>
                <span className="add-option-btn" onClick={handleAddParameter}>
                  <AddCircleIcon style={{ fontSize: 20, cursor: 'pointer' }} />Add Parameter
                </span>
              </div>

              {showParametersSection && parameters.length > 0 ? (
                <div>
                  {parameters.map((p, idx) => (
                    <div key={p.id} className="parameter-card">
                      <div className="parameter-card-header">
                        <span className="text-white-50 small fw-bold">Parameter #{idx + 1}</span>
                        <Button
                          variant="link"
                          className="text-danger p-0 d-inline-flex align-items-center"
                          onClick={() => handleRemoveParameter(p.id)}
                          title="Remove Parameter"
                        >
                          <DeleteIcon style={{ fontSize: 18 }} />
                        </Button>
                      </div>

                      <Row className="g-3">
                        <Col md={6}>
                          <InputField
                            id={`param-name-${p.id}`}
                            label="Parameter Name"
                            type="text"
                            name={`param_name_${p.id}`}
                            value={p.name}
                            placeholder="e.g. city"
                            onChange={(e) => handleParamChange(p.id, 'name', e.target.value)}
                          />
                        </Col>
                        <Col md={6}>
                          <InputField
                            id={`param-desc-${p.id}`}
                            label="Description"
                            type="text"
                            name={`param_desc_${p.id}`}
                            value={p.description}
                            placeholder="City name for query"
                            onChange={(e) => handleParamChange(p.id, 'description', e.target.value)}
                          />
                        </Col>
                        <Col md={4}>
                          <Form.Group controlId={`param-location-${p.id}`}>
                            <Form.Label className="form-label-custom small">Location</Form.Label>
                            <Form.Select
                              className="custom-input"
                              value={p.location}
                              onChange={(e) => handleParamChange(p.id, 'location', e.target.value)}
                            >
                              <option value="query">Query Parameter</option>
                              <option value="path">Path Parameter</option>
                              <option value="body">Request Body</option>
                            </Form.Select>
                          </Form.Group>
                        </Col>
                        <Col md={4}>
                          <Form.Group controlId={`param-datatype-${p.id}`}>
                            <Form.Label className="form-label-custom small">Data Type</Form.Label>
                            <Form.Select
                              className="custom-input"
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
                        <Col md={4} className="d-flex align-items-center mt-4">
                          <Form.Check
                            type="checkbox"
                            id={`param-required-${p.id}`}
                            label={<span className="text-light small">Required Parameter</span>}
                            checked={p.required}
                            onChange={(e) => handleParamChange(p.id, 'required', e.target.checked)}
                          />
                        </Col>
                      </Row>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        )}

        {/* MCP TOOL TOGGLE */}
        {toolToggle === 'MCP' && (
          <div>
            <div className="mb-3">
              <InputField
                id="mcp-tool-name"
                label="MCP Tool Name"
                type="text"
                name="mcp_tool_name"
                value={mcpTool.name}
                placeholder="e.g. Filesystem MCP Server"
                onChange={(e) => setMcpTool({ ...mcpTool, name: e.target.value })}
              />
            </div>

            <Form.Group className="mb-4" controlId="mcp-tool-description">
              <Form.Label className="form-label-custom">MCP Tool Description</Form.Label>
              <Form.Control
                as="textarea"
                rows={2}
                className="custom-input"
                placeholder="Describes the scope of this MCP server integration..."
                value={mcpTool.description}
                onChange={(e) => setMcpTool({ ...mcpTool, description: e.target.value })}
              />
            </Form.Group>

            <Form.Group className="mb-3" controlId="mcp-config-json">
              <div className="d-flex align-items-center justify-content-between mb-1">
                <Form.Label className="form-label-custom mb-0">MCP Configuration (JSON)</Form.Label>
                <span className="text-secondary small font-monospace">Standard MCP Schema</span>
              </div>
              <Form.Control
                as="textarea"
                rows={8}
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

            {discoveredMcpTools.length > 0 && (
              <div className="parameter-card mb-4">
                <div className="parameter-card-header mb-3">
                  <div className="d-flex align-items-center gap-2">
                    <TaskAltIcon className="text-success" style={{ fontSize: 20 }} />
                    <span className="fw-semibold text-white small">
                      Discovered Tools ({Object.values(selectedMcpTools).filter(Boolean).length}/{discoveredMcpTools.length} enabled)
                    </span>
                  </div>
                  <Form.Check
                    type="checkbox"
                    id="select-all-mcp-tools"
                    label={<span className="text-white-50 small">Select All</span>}
                    checked={isAllMcpSelected}
                    onChange={handleToggleSelectAllMcp}
                  />
                </div>

                <div className="d-flex flex-wrap gap-2 pt-1">
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
            {/* 1. Preconfigured Tool Selector */}
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
                placeholder="Describe documents ingested and queries this tool will assist with..."
                value={ragTool.description}
                onChange={(e) => setRagTool({ ...ragTool, description: e.target.value })}
              />
            </Form.Group>

            {/* 2. File Upload Dropzone Area */}
            <div className="mb-4">
              <Form.Label className="form-label-custom small mb-1">Knowledge Document</Form.Label>
              <input
                type="file"
                ref={fileInputRef}
                className="d-none"
                accept=".pdf,.txt,.docx,.md,.csv"
                onChange={handleFileChange}
              />

              {!ragTool.selectedFile ? (
                <div
                  className="rag-upload-dropzone"
                  onClick={() => fileInputRef.current?.click()}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      fileInputRef.current?.click();
                    }
                  }}
                >
                  <CloudUploadIcon className="text-cyan-accent mb-2" style={{ fontSize: 36 }} />
                  <h6 className="text-light mb-1">Click or drag a file to upload</h6>
                  <p className="text-secondary small mb-0">Supported formats: PDF, TXT, DOCX, MD, CSV (Max 25MB)</p>
                </div>
              ) : (
                <div className="rag-upload-file-badge">
                  <div className="d-flex align-items-center gap-3">
                    <InsertDriveFileIcon className="text-cyan-accent" style={{ fontSize: 28 }} />
                    <div>
                      <div className="text-light fw-medium">{ragTool.selectedFile.name}</div>
                      <div className="text-secondary small">{(ragTool.selectedFile.size / 1024).toFixed(1)} KB</div>
                    </div>
                  </div>
                  <Button
                    variant="link"
                    className="text-danger p-0"
                    onClick={handleRemoveFile}
                    title="Remove File"
                  >
                    <DeleteIcon style={{ fontSize: 20 }} />
                  </Button>
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

              {/* Embedding Model Provider Cards */}
              <div className="mb-3">
                <Form.Label className="form-label-custom small mb-2 d-block">Embedding Provider</Form.Label>
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

              {/* Conditional Vector DB Fields based on selected provider */}
              {ragTool.vectorDbProvider === 'pinecone' && (
                <>
                  {/* Row 1: Index Name & API Key */}
                  <Row className="g-3 mb-3">
                    <Col md={6}>
                      <InputField
                        id="vector-pinecone-index-name"
                        label="Index Name"
                        type="text"
                        name="collection_name"
                        value={ragTool.collectionName}
                        placeholder="e.g. my-pinecone-index"
                        onChange={(e) => setRagTool({ ...ragTool, collectionName: e.target.value })}
                      />
                    </Col>
                    <Col md={6}>
                      <InputField
                        id="vector-pinecone-api-key"
                        label="API Key"
                        type="password"
                        name="vector_db_api_key"
                        value={ragTool.vectorDbApiKey}
                        placeholder="Enter Pinecone API Key"
                        onChange={(e) => setRagTool({ ...ragTool, vectorDbApiKey: e.target.value })}
                      />
                    </Col>
                  </Row>

                  {/* Row 2: Vector Dimension, Top K & Namespace (Optional) */}
                  <Row className="g-3 mb-3">
                    <Col md={4}>
                      <InputField
                        id="vector-pinecone-dimension"
                        label="Vector Dimension"
                        type="number"
                        name="vector_dimension"
                        value={ragTool.vectorDimension ? ragTool.vectorDimension.toString() : ''}
                        placeholder="1536"
                        onChange={(e) => setRagTool({ ...ragTool, vectorDimension: Number(e.target.value) || 0 })}
                      />
                    </Col>
                    <Col md={4}>
                      <InputField
                        id="vector-pinecone-top-k"
                        label="Top K Results"
                        type="number"
                        name="top_k"
                        value={ragTool.topK ? ragTool.topK.toString() : ''}
                        placeholder="15"
                        onChange={(e) => setRagTool({ ...ragTool, topK: Number(e.target.value) || 15 })}
                      />
                    </Col>
                    <Col md={4}>
                      <InputField
                        id="vector-pinecone-namespace"
                        label="Namespace (Optional)"
                        type="text"
                        name="namespace"
                        value={ragTool.namespace}
                        placeholder="e.g. default"
                        onChange={(e) => setRagTool({ ...ragTool, namespace: e.target.value })}
                      />
                    </Col>
                  </Row>

                  {/* Row 3: Cloud Provider & Region */}
                  <Row className="g-3">
                    <Col md={7}>
                      <Form.Group controlId="vector-pinecone-cloud-provider">
                        <Form.Label className="form-label-custom small mb-1 d-block">
                          Cloud Provider
                        </Form.Label>
                        <div className="cloud-provider-group">
                          {CLOUD_PROVIDERS.map((cp) => {
                            const isSelected = ragTool.cloudProvider === cp.id;
                            return (
                              <div
                                key={cp.id}
                                id={`cloud-provider-${cp.id}`}
                                className={`cloud-provider-btn ${isSelected ? 'selected' : ''}`}
                                onClick={() => setRagTool({ ...ragTool, cloudProvider: cp.id })}
                                role="button"
                                tabIndex={0}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter' || e.key === ' ') {
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
                    <Col md={5}>
                      <InputField
                        id="vector-pinecone-region"
                        label="Region"
                        type="text"
                        name="region"
                        value={ragTool.region}
                        placeholder="e.g. us-east-1"
                        onChange={(e) => setRagTool({ ...ragTool, region: e.target.value })}
                      />
                    </Col>
                  </Row>
                </>
              )}

              {ragTool.vectorDbProvider === 'qdrant' && (
                <>
                  {/* Row 1: Collection Name & API Key */}
                  <Row className="g-3 mb-3">
                    <Col md={6}>
                      <InputField
                        id="vector-qdrant-collection-name"
                        label="Collection Name"
                        type="text"
                        name="collection_name"
                        value={ragTool.collectionName}
                        placeholder="e.g. my-qdrant-collection"
                        onChange={(e) => setRagTool({ ...ragTool, collectionName: e.target.value })}
                      />
                    </Col>
                    <Col md={6}>
                      <InputField
                        id="vector-qdrant-api-key"
                        label="API Key"
                        type="password"
                        name="vector_db_api_key"
                        value={ragTool.vectorDbApiKey}
                        placeholder="Enter Qdrant API Key"
                        onChange={(e) => setRagTool({ ...ragTool, vectorDbApiKey: e.target.value })}
                      />
                    </Col>
                  </Row>

                  {/* Row 2: Vector DB URL, Vector Dimension, Top K Results */}
                  <Row className="g-3">
                    <Col md={6}>
                      <InputField
                        id="vector-qdrant-url"
                        label="Vector DB URL"
                        type="text"
                        name="vector_db_url"
                        value={ragTool.vectorDbUrl}
                        placeholder="e.g. https://xyz.cloud.qdrant.io:6333"
                        onChange={(e) => setRagTool({ ...ragTool, vectorDbUrl: e.target.value })}
                      />
                    </Col>
                    <Col md={3}>
                      <InputField
                        id="vector-qdrant-dimension"
                        label="Vector Dimension"
                        type="number"
                        name="vector_dimension"
                        value={ragTool.vectorDimension ? ragTool.vectorDimension.toString() : ''}
                        placeholder="1536"
                        onChange={(e) => setRagTool({ ...ragTool, vectorDimension: Number(e.target.value) || 0 })}
                      />
                    </Col>
                    <Col md={3}>
                      <InputField
                        id="vector-qdrant-top-k"
                        label="Top K Results"
                        type="number"
                        name="top_k"
                        value={ragTool.topK ? ragTool.topK.toString() : ''}
                        placeholder="15"
                        onChange={(e) => setRagTool({ ...ragTool, topK: Number(e.target.value) || 15 })}
                      />
                    </Col>
                  </Row>
                </>
              )}

              {ragTool.vectorDbProvider === 'chroma' && (
                <>
                  {/* Row 1: Collection Name & API Key */}
                  <Row className="g-3 mb-3">
                    <Col md={6}>
                      <InputField
                        id="vector-chroma-collection-name"
                        label="Collection Name"
                        type="text"
                        name="collection_name"
                        value={ragTool.collectionName}
                        placeholder="e.g. my-chroma-collection"
                        onChange={(e) => setRagTool({ ...ragTool, collectionName: e.target.value })}
                      />
                    </Col>
                    <Col md={6}>
                      <InputField
                        id="vector-chroma-api-key"
                        label="API Key"
                        type="password"
                        name="vector_db_api_key"
                        value={ragTool.vectorDbApiKey}
                        placeholder="Enter Chroma API Key"
                        onChange={(e) => setRagTool({ ...ragTool, vectorDbApiKey: e.target.value })}
                      />
                    </Col>
                  </Row>

                  {/* Row 2: Database Name (linked to vector_db_url), Tenant, Top K Results */}
                  <Row className="g-3">
                    <Col md={4}>
                      <InputField
                        id="vector-chroma-database-name"
                        label="Database Name"
                        type="text"
                        name="vector_db_url"
                        value={ragTool.vectorDbUrl}
                        placeholder="e.g. default_database"
                        onChange={(e) => setRagTool({ ...ragTool, vectorDbUrl: e.target.value })}
                      />
                    </Col>
                    <Col md={4}>
                      <InputField
                        id="vector-chroma-tenant"
                        label="Tenant"
                        type="text"
                        name="vector_db_tenant"
                        value={ragTool.vectorDbTenant}
                        placeholder="e.g. default_tenant"
                        onChange={(e) => setRagTool({ ...ragTool, vectorDbTenant: e.target.value })}
                      />
                    </Col>
                    <Col md={4}>
                      <InputField
                        id="vector-chroma-top-k"
                        label="Top K Results"
                        type="number"
                        name="top_k"
                        value={ragTool.topK ? ragTool.topK.toString() : ''}
                        placeholder="15"
                        onChange={(e) => setRagTool({ ...ragTool, topK: Number(e.target.value) || 15 })}
                      />
                    </Col>
                  </Row>
                </>
              )}

              {ragTool.vectorDbProvider === 'weaviate' && (
                <>
                  {/* Row 1: Collection Name & API Key */}
                  <Row className="g-3 mb-3">
                    <Col md={6}>
                      <InputField
                        id="vector-weaviate-collection-name"
                        label="Collection Name"
                        type="text"
                        name="collection_name"
                        value={ragTool.collectionName}
                        placeholder="e.g. my-weaviate-collection"
                        onChange={(e) => setRagTool({ ...ragTool, collectionName: e.target.value })}
                      />
                    </Col>
                    <Col md={6}>
                      <InputField
                        id="vector-weaviate-api-key"
                        label="API Key"
                        type="password"
                        name="vector_db_api_key"
                        value={ragTool.vectorDbApiKey}
                        placeholder="Enter Weaviate API Key"
                        onChange={(e) => setRagTool({ ...ragTool, vectorDbApiKey: e.target.value })}
                      />
                    </Col>
                  </Row>

                  {/* Row 2: Vector DB URL & Top K Results */}
                  <Row className="g-3">
                    <Col md={8}>
                      <InputField
                        id="vector-weaviate-url"
                        label="Vector DB URL"
                        type="text"
                        name="vector_db_url"
                        value={ragTool.vectorDbUrl}
                        placeholder="e.g. https://xxx.weaviate.cloud"
                        onChange={(e) => setRagTool({ ...ragTool, vectorDbUrl: e.target.value })}
                      />
                    </Col>
                    <Col md={4}>
                      <InputField
                        id="vector-weaviate-top-k"
                        label="Top K Results"
                        type="number"
                        name="top_k"
                        value={ragTool.topK ? ragTool.topK.toString() : ''}
                        placeholder="15"
                        onChange={(e) => setRagTool({ ...ragTool, topK: Number(e.target.value) || 15 })}
                      />
                    </Col>
                  </Row>
                </>
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
                        value={ragTool.chunkOverlap ? ragTool.chunkOverlap.toString() : ''}
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
                        <Form.Label className="form-label-custom small mb-1">Distance Strategy</Form.Label>
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
          <Button variant="outline-secondary" onClick={onBack} className="px-4 agent-action-btn">
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
                <span>Save</span>
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
  );
};
