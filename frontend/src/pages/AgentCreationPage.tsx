import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Container, Row, Col, Form, Button, Alert, Spinner, Badge } from 'react-bootstrap';
import TaskAltIcon from '@mui/icons-material/TaskAlt';
import PermIdentityIcon from '@mui/icons-material/PermIdentity';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import HandymanIcon from '@mui/icons-material/Handyman';
import NotesIcon from '@mui/icons-material/Notes';
import RocketLaunchIcon from '@mui/icons-material/RocketLaunch';
import { 
  Openai, Gemini, Cohere, AzureAzureOpenai, Mistral,
  Anthropic, Xai, Groq, Azureai, Deepseek, Openrouter, Ollama, HuggingFace
} from '@thesvg/react';
import { Navbar } from '../components/layout/Navbar';
import { InputField } from '../components/common/InputField';
import { ToolsStep } from '../components/agents/ToolsStep';
import { put, extractErrorMessage } from '../services/apiWrapper';
import { API_ENDPOINTS } from '../constants';
import './AgentCreationPage.css';

type StepKey = 'identity' | 'model' | 'tools' | 'prompt' | 'deploy';


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

  // Step 4: Prompt Form State
  const [systemPrompt, setSystemPrompt] = useState('');

  // ------------------------------------------------------------------
  // Helper Functions & Dynamic Handlers
  // ------------------------------------------------------------------
  const clearAlerts = () => {
    setErrorMessage(null);
    setSuccessMessage(null);
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
                <ToolsStep
                  agentId={agentId}
                  agentName={identity.name}
                  agentDescription={identity.description}
                  onNext={() => setActiveStep('prompt')}
                  onBack={() => setActiveStep('model')}
                  onSuccess={setSuccessMessage}
                  onError={setErrorMessage}
                  clearAlerts={clearAlerts}
                  markStepComplete={markStepComplete}
                />
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
