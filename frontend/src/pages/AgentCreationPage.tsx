import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Container, Row, Col, Form, Button, Alert, Spinner, Badge, OverlayTrigger, Tooltip } from 'react-bootstrap';
import TaskAltIcon from '@mui/icons-material/TaskAlt';
import DeleteIcon from '@mui/icons-material/Delete';
import { Navbar } from '../components/layout/Navbar';
import { InputField } from '../components/common/InputField';
import { put, post, extractErrorMessage } from '../services/apiWrapper';
import { API_ENDPOINTS } from '../constants';
import './AgentCreationPage.css';

type StepKey = 'identity' | 'model' | 'tools' | 'prompt' | 'publish';

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
  const [toolToggle, setToolToggle] = useState<'PRECONFIGURED' | 'API' | 'MCP'>('API');
  
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

  // MCP Tool State - Empty default text with sample placeholder
  const [mcpConfigText, setMcpConfigText] = useState<string>('');
  const [isDiscoveringMcp, setIsDiscoveringMcp] = useState<boolean>(false);
  const [discoveredMcpTools, setDiscoveredMcpTools] = useState<DiscoveredMcpTool[]>([]);
  const [selectedMcpTools, setSelectedMcpTools] = useState<Record<string, boolean>>({});

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

  // Step 3: Tools Next Button
  const handleToolsSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!agentId) {
      setErrorMessage('Please complete Step 1 (Identity) first.');
      return;
    }

    setIsLoading(true);
    clearAlerts();

    try {
      if (toolToggle === 'API' && apiTool.url.trim()) {
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

        const toolConfigPayload = [
          {
            name: apiTool.name.trim() || `${identity.name} API Tool`,
            description: apiTool.description.trim() || identity.description,
            tool_type: 'API',
            url: apiTool.url.trim(),
            method: apiTool.method,
            headers: headerMap,
            parameters: paramConfigs,
            enabled: true,
            version: '1.0.0',
            timeout_seconds: 30,
          },
        ];

        await post(API_ENDPOINTS.AGENTS.ADD_TOOLS(agentId), toolConfigPayload);
      } else if (toolToggle === 'MCP' && mcpConfigText.trim()) {
        let parsedConfig: Record<string, any>;
        try {
          parsedConfig = JSON.parse(mcpConfigText);
        } catch {
          setErrorMessage('Invalid MCP JSON configuration format.');
          setIsLoading(false);
          return;
        }

        const selectedToolNames = discoveredMcpTools
          .filter((t) => selectedMcpTools[t.tool_name])
          .map((t) => t.tool_name);

        const toolConfigPayload = [
          {
            name: `${identity.name} MCP Tool`,
            description: identity.description,
            tool_type: 'MCP',
            mcp_config: parsedConfig,
            allowed_tools: selectedToolNames,
            enabled: true,
            version: '1.0.0',
          },
        ];

        await post(API_ENDPOINTS.AGENTS.ADD_TOOLS(agentId), toolConfigPayload);
      }

      setSuccessMessage('Tools configured successfully!');
      markStepComplete('tools');
      setActiveStep('prompt');
    } catch (err) {
      setErrorMessage(extractErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
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
      setActiveStep('publish');
    } catch (err) {
      setErrorMessage(extractErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  };

  // Step 5: Dummy Publish Button
  const handlePublishClick = async () => {
    if (!agentId) {
      setErrorMessage('No agent to publish. Please complete the previous steps first.');
      return;
    }

    setIsLoading(true);
    clearAlerts();

    try {
      await put(API_ENDPOINTS.AGENTS.CREATE_OR_UPDATE, {
        _id: agentId,
        status: 'DEPLOYED',
      });
      setSuccessMessage('Agent published and deployed successfully!');
      markStepComplete('publish');
      // Navigate to deployed agents page after a short delay for the user to see the success message
      setTimeout(() => navigate('/deployed'), 800);
    } catch (err) {
      setErrorMessage(extractErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  };

  // Steps Registry
  const steps: { key: StepKey; label: string; number: number }[] = [
    { key: 'identity', label: 'Identity', number: 1 },
    { key: 'model', label: 'Model', number: 2 },
    { key: 'tools', label: 'Tools', number: 3 },
    { key: 'prompt', label: 'Prompt', number: 4 },
    { key: 'publish', label: 'Publish', number: 5 },
  ];

  const mcpPlaceholderText = `{\n  "mcpServers": {\n    "filesystem": {\n      "command": "npx",\n      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"]\n    }\n  }\n}`;

  return (
    <div className="bg-deep-dark">
      <Navbar />

      <Container className="agent-creation-container">
        <div className="agent-creation-card h-100">
          <Row className="g-0 h-100">
            {/* Left Vertical Menu */}
            <Col md={3} className="sidebar-menu">
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
                    <div className="step-number-badge">{step.number}</div>
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
            <Col md={9} className="agent-step-content">
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
                      <Button type="submit" className="btn-cyan-primary px-4 rounded-pill" disabled={isLoading}>
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
                    <Row className="g-3 mb-3">
                      <Col md={6}>
                        <Form.Group controlId="model-provider">
                          <Form.Label className="form-label-custom">Model Provider</Form.Label>
                          <Form.Select
                            className="custom-input"
                            value={model.provider}
                            onChange={(e) => setModel({ ...model, provider: e.target.value })}
                          >
                            <option value="openai">OpenAI</option>
                            <option value="google_genai">Google Gemini</option>
                            <option value="anthropic">Anthropic</option>
                            <option value="groq">Groq</option>
                            <option value="xai">xAI</option>
                            <option value="deepseek">DeepSeek</option>
                            <option value="ollama">Ollama</option>
                            <option value="mistralai">Mistral AI</option>
                          </Form.Select>
                        </Form.Group>
                      </Col>

                      <Col md={6}>
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
                      <Button variant="outline-secondary" onClick={() => setActiveStep('identity')} className="px-4 rounded-pill">
                        Back
                      </Button>
                      <Button type="submit" className="btn-cyan-primary px-4 rounded-pill" disabled={isLoading}>
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

                  {/* Toggle Pill Selection */}
                  <div className="toggle-group-pills mb-4">
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
                  </div>

                  <Form onSubmit={handleToolsSubmit}>
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
                              + Add Header
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
                              + Add Parameter
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
                            className="btn-cyan-primary btn-sm px-4 rounded-pill me-2"
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
                                    <Form.Check
                                      type="checkbox"
                                      id={`mcp-tool-${t.tool_name}`}
                                      checked={isSelected}
                                      onChange={() => handleToggleSingleMcpTool(t.tool_name)}
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
                      <div className="p-4 rounded-3 border border-secondary border-opacity-25 text-center text-muted my-4">
                        <p className="mb-0">Selected tool mode: <strong className="text-white">Preconfigured Tools</strong>. Standard platform tools will be included.</p>
                      </div>
                    )}

                    <div className="d-flex justify-content-between mt-4">
                      <Button variant="outline-secondary" onClick={() => setActiveStep('model')} className="px-4 rounded-pill">
                        Back
                      </Button>
                      <Button type="submit" className="btn-cyan-primary px-4 rounded-pill" disabled={isLoading}>
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
                      <Button variant="outline-secondary" onClick={() => setActiveStep('tools')} className="px-4 rounded-pill">
                        Back
                      </Button>
                      <Button type="submit" className="btn-cyan-primary px-4 rounded-pill" disabled={isLoading}>
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

              {/* STEP 5: PUBLISH */}
              {activeStep === 'publish' && (
                <div>
                  <h3 className="step-title">Review & Publish</h3>
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
                    <Button variant="outline-secondary" onClick={() => setActiveStep('prompt')} className="px-4 rounded-pill">
                      Back
                    </Button>
                    <Button type="button" className="btn-cyan-primary px-5 rounded-pill fw-bold" onClick={handlePublishClick} disabled={isLoading}>
                      {isLoading ? (
                        <>
                          <Spinner animation="border" size="sm" className="me-2" />
                          Publishing...
                        </>
                      ) : (
                        'Publish Agent'
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
