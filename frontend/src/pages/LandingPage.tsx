import React, { useEffect, useState } from 'react';
import { Container, Row, Col, Card, Badge, Button, Spinner, Alert } from 'react-bootstrap';
import { Navbar } from '../components/layout/Navbar';
import { useAuth } from '../context/AuthContext';
import { get, extractErrorMessage, type ApiResponse } from '../services/apiWrapper';
import { API_ENDPOINTS } from '../constants';
import type { AgentItem } from '../types/agent';
import { AgentConfigModal } from '../components/agents/AgentConfigModal';
import './LandingPage.css';

export const LandingPage: React.FC = () => {
  const { user } = useAuth();
  const [agents, setAgents] = useState<AgentItem[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Selected agent for configuration modal
  const [selectedAgent, setSelectedAgent] = useState<AgentItem | null>(null);
  const [showModal, setShowModal] = useState<boolean>(false);

  useEffect(() => {
    const fetchAgents = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const response = await get<ApiResponse<AgentItem[]> | AgentItem[]>(API_ENDPOINTS.AGENTS.FETCH);

        const fetchedAgents = Array.isArray(response)
          ? response
          : (response && 'data' in response && Array.isArray(response.data) ? response.data : []);

        setAgents(fetchedAgents);
      } catch (err) {
        // Fallback error handling if unauthenticated or network error occurs
        const msg = extractErrorMessage(err);
        setError(msg);
      } finally {
        setIsLoading(false);
      }
    };

    fetchAgents();
  }, []);

  const handleEditClick = (agent: AgentItem) => {
    setSelectedAgent(agent);
    setShowModal(true);
  };

  const handleSaveConfig = (updatedAgent: AgentItem) => {
    setAgents((prev) =>
      prev.map((a) => (a.id === updatedAgent.id || a.name === updatedAgent.name ? updatedAgent : a))
    );
  };

  const getModelLabel = (agent: AgentItem): string => {
    if (!agent.model) return 'Default LLM';
    if (typeof agent.model === 'string') return agent.model;
    return `${agent.model.provider || ''} ${agent.model.model_name || ''}`.trim() || 'Custom Model';
  };

  return (
    <div className="min-vh-100 d-flex flex-column bg-dark text-light">
      <Navbar />

      {/* Hero Section */}
      <main className="flex-grow-1 py-5">
        <Container>
          <Row className="justify-content-center text-center my-4 py-3">
            <Col lg={9} xl={8}>
              <h1 className="display-4 fw-bold text-white mb-3">
                Discover & Orchestrate <span className="text-cyan-accent">AI Agents</span>
              </h1>
              <p className="lead text-secondary mb-4 fs-5">
                {user ? (
                  <>Welcome back, <strong className="text-cyan-accent">{user.name}</strong>! Explore and configure your active AI agent catalog below.</>
                ) : (
                  <>AgentMart empowers developers and enterprises to deploy, scale, and monitor specialized AI agents seamlessly.</>
                )}
              </p>
            </Col>
          </Row>

          {/* Section Header */}
          <div className="d-flex align-items-center justify-content-between mb-4 border-bottom border-secondary border-opacity-25 pb-3">
            <div>
              <h3 className="fw-bold text-white mb-1">Available Agents</h3>
              <p className="text-secondary small mb-0">Manage agent configurations, capabilities, and system prompts</p>
            </div>
            <Badge bg="dark" className="text-cyan-accent border border-info border-opacity-25 fs-6 px-3 py-2">
              {agents.length} Agents Registered
            </Badge>
          </div>

          {/* Loading Indicator */}
          {isLoading && (
            <div className="text-center py-5 my-4">
              <Spinner animation="border" variant="info" className="mb-3" />
              <p className="text-secondary">Fetching agents from catalog...</p>
            </div>
          )}

          {/* Error Message */}
          {!isLoading && error && (
            <Alert variant="danger" className="alert-custom-error mb-4 text-center">
              Unable to load agents catalog: {error}
            </Alert>
          )}

          {/* Empty State */}
          {!isLoading && !error && agents.length === 0 && (
            <div className="text-center py-5 auth-card border-0 p-5 my-4">
              <h5 className="fw-bold text-white mb-2">No Agents Available</h5>
              <p className="text-secondary small mb-0">No agent configurations were returned by the catalog service.</p>
            </div>
          )}

          {/* Agent Card Grid */}
          {!isLoading && agents.length > 0 && (
            <Row className="g-4">
              {agents.map((agent, index) => {
                const isEnabled = agent.enabled !== undefined ? agent.enabled : true;
                const statusBadgeBg = agent.status === 'PUBLISHED' ? 'success' : 'warning';
                const modelName = getModelLabel(agent);

                return (
                  <Col md={6} lg={4} key={agent.id || agent._id || index}>
                    <Card className="auth-card h-100 p-4 border-0 d-flex flex-column">
                      {/* Top Header */}
                      <div className="d-flex align-items-start justify-content-between mb-3">
                        <div>
                          <h5 className="fw-bold text-white mb-0">{agent.name}</h5>
                          {agent.version && (
                            <span className="text-muted extra-small">v{agent.version}</span>
                          )}
                        </div>

                        <Badge bg={statusBadgeBg} className="bg-opacity-20 text-light border border-secondary border-opacity-25 px-2 py-1 small">
                          {agent.status || 'DRAFT'}
                        </Badge>
                      </div>

                      {/* Description */}
                      <p className="text-secondary small mb-3 flex-grow-1 agent-desc-clamp">
                        {agent.description || 'No description provided for this agent.'}
                      </p>

                      {/* Model & Specs info */}
                      <div className="mb-3 d-flex flex-wrap align-items-center gap-2">
                        <Badge bg="dark" className="text-cyan-accent border border-info border-opacity-25">
                          {modelName}
                        </Badge>
                        {isEnabled ? (
                          <Badge bg="dark" className="text-success border border-success border-opacity-25">
                            ● Enabled
                          </Badge>
                        ) : (
                          <Badge bg="dark" className="text-muted border border-secondary border-opacity-25">
                            ○ Disabled
                          </Badge>
                        )}
                      </div>

                      {/* Capabilities pills */}
                      {agent.capabilities && agent.capabilities.length > 0 && (
                        <div className="d-flex flex-wrap gap-1 mb-3">
                          {agent.capabilities.slice(0, 3).map((cap, i) => (
                            <span key={i} className="badge bg-secondary bg-opacity-20 text-secondary extra-small">
                              {cap}
                            </span>
                          ))}
                          {agent.capabilities.length > 3 && (
                            <span className="badge bg-secondary bg-opacity-20 text-secondary extra-small">
                              +{agent.capabilities.length - 3} more
                            </span>
                          )}
                        </div>
                      )}

                      {/* Card Action Footer */}
                      <div className="mt-auto d-flex justify-content-between align-items-center pt-3 border-top border-secondary border-opacity-25">
                        <span className="text-cyan-accent small fw-medium">
                          {isEnabled ? 'Ready' : 'Inactive'}
                        </span>
                        <Button
                          variant="outline-info"
                          size="sm"
                          className="btn-edit-agent d-flex align-items-center gap-2 rounded-3 px-3 py-1"
                          onClick={() => handleEditClick(agent)}
                        >
                          <span>Edit</span>
                        </Button>
                      </div>
                    </Card>
                  </Col>
                );
              })}
            </Row>
          )}
        </Container>
      </main>

      {/* Agent Configuration Modal */}
      <AgentConfigModal
        show={showModal}
        agent={selectedAgent}
        onHide={() => setShowModal(false)}
        onSave={handleSaveConfig}
      />

      {/* Footer */}
      <footer className="py-4 border-top border-secondary border-opacity-25 text-center text-muted small">
        <Container>
          &copy; {new Date().getFullYear()} AgentMart. All rights reserved.
        </Container>
      </footer>
    </div>
  );
};
