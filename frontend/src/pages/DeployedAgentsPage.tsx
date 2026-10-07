import React, { useEffect, useState } from 'react';
import { Container, Spinner, Badge } from 'react-bootstrap';
import { useNavigate } from 'react-router-dom';
import { Navbar } from '../components/layout/Navbar';
import { get, extractErrorMessage } from '../services/apiWrapper';
import { API_ENDPOINTS } from '../constants';
import type { AgentItem } from '../types/agent';
import './DeployedAgentsPage.css';

export const DeployedAgentsPage: React.FC = () => {
  const navigate = useNavigate();
  const [agents, setAgents] = useState<AgentItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    const fetchDeployedAgents = async () => {
      setIsLoading(true);
      setErrorMessage(null);
      try {
        const res: any = await get(`${API_ENDPOINTS.AGENTS.FETCH}?agent_status=DEPLOYED`);
        const list: AgentItem[] = Array.isArray(res)
          ? res
          : res?.data || [];
        setAgents(list);
      } catch (err) {
        setErrorMessage(extractErrorMessage(err));
      } finally {
        setIsLoading(false);
      }
    };

    fetchDeployedAgents();
  }, []);

  const getProviderLabel = (agent: AgentItem): string => {
    if (!agent.model) return 'Unknown';
    if (typeof agent.model === 'string') return agent.model;
    return `${agent.model.provider ?? ''} / ${agent.model.model_name ?? ''}`.trim().replace(/^\/|\/$/g, '');
  };

  return (
    <div className="bg-deep-dark deployed-page-wrapper">
      <Navbar />

      <Container className="deployed-agents-container">
        <div className="deployed-page-header">
          <h2 className="deployed-page-title">Deployed Agents</h2>
          <p className="deployed-page-subtitle">
            These agents are live and ready to handle requests.
          </p>
        </div>

        {isLoading && (
          <div className="d-flex justify-content-center align-items-center py-5">
            <Spinner animation="border" style={{ color: 'var(--primary-accent)' }} />
          </div>
        )}

        {!isLoading && errorMessage && (
          <div className="text-danger text-center py-5 small">{errorMessage}</div>
        )}

        {!isLoading && !errorMessage && agents.length === 0 && (
          <div className="deployed-empty-state">
            <div className="deployed-empty-icon">🤖</div>
            <h5 className="text-white mb-2">No deployed agents yet</h5>
            <p className="text-muted small">
              Create and publish an agent to see it appear here.
            </p>
          </div>
        )}

        {!isLoading && agents.length > 0 && (
          <div className="deployed-grid">
            {agents.map((agent, idx) => {
              const agentId = agent._id || agent.agent_id || agent.id || '';
              return (
                <div key={agentId || idx} className="deployed-agent-card">
                  {/* Status pill */}
                  <div className="deployed-card-top">
                    <span className="deployed-status-pill">
                      <span className="deployed-status-dot" />
                      LIVE
                    </span>
                    <Badge bg="secondary" className="visibility-badge">
                      {agent.visibility ?? 'PRIVATE'}
                    </Badge>
                  </div>

                  <h5 className="deployed-card-name">{agent.name}</h5>
                  <p className="deployed-card-description">{agent.description}</p>

                  <div className="deployed-card-meta">
                    <div className="meta-item">
                      <span className="meta-label">Model</span>
                      <span className="meta-value">{getProviderLabel(agent)}</span>
                    </div>
                    {agent.version && (
                      <div className="meta-item">
                        <span className="meta-label">Version</span>
                        <span className="meta-value">v{agent.version}</span>
                      </div>
                    )}
                  </div>

                  {/* Use button — full width, navigates to chat page */}
                  <button
                    className="agent-use-btn"
                    onClick={() => navigate(`/chat/${agentId}`, { state: { agent } })}
                  >
                    Use
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </Container>
    </div>
  );
};
