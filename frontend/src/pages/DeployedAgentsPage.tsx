import React, { useEffect, useState } from 'react';
import { Container, Spinner } from 'react-bootstrap';
import { useNavigate } from 'react-router-dom';
import EditIcon from '@mui/icons-material/Edit';
import HandymanIcon from '@mui/icons-material/Handyman';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import ArrowForwardIcon from '@mui/icons-material/ArrowForward';
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
        const res: any = await get(API_ENDPOINTS.AGENTS.FETCH);
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

  const handleEditAgent = (agent: AgentItem) => {
    const agentId = agent._id || agent.agent_id || agent.id || '';
    navigate(`/agent/${agentId}`, { state: { agent } });
  };

  const getModelName = (agent: AgentItem): string => {
    if (!agent.model) return 'Default';
    if (typeof agent.model === 'string') return agent.model;
    return agent.model.name || agent.model.model_name || agent.model.provider || 'Default';
  };

  const getToolsCount = (agent: AgentItem): number => {
    if (Array.isArray(agent.tools)) return agent.tools.length;
    return 0;
  };

  return (
    <div className="bg-deep-dark deployed-page-wrapper">
      <Navbar />

      <Container fluid className="deployed-agents-container">
        <div className="deployed-page-header">
          <h2 className="deployed-page-title">My Agents</h2>
          <p className="deployed-page-subtitle">
            Manage, configure, and interact with your AI agents.
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
            <h5 className="text-white mb-2">No agents yet</h5>
            <p className="text-muted small">
              Create an agent to see it appear here.
            </p>
          </div>
        )}

        {!isLoading && agents.length > 0 && (
          <div className="deployed-grid">
            {agents.map((agent, idx) => {
              const agentId = agent._id || agent.agent_id || agent.id || '';
              const isDeployed = agent.status?.toUpperCase() === 'DEPLOYED';
              const toolsCount = getToolsCount(agent);
              const modelName = getModelName(agent);

              return (
                <div key={agentId || idx} className="deployed-agent-card">
                  {/* Top Bar: Status + Visibility Badges (Left) & Shifted Edit Action (Right) */}
                  <div className="deployed-card-top">
                    <div className="deployed-card-badges">
                      {isDeployed ? (
                        <span className="deployed-status-pill">
                          <span className="deployed-status-dot" />
                          LIVE
                        </span>
                      ) : (
                        <span className="deployed-status-pill draft">
                          {agent.status || 'DRAFT'}
                        </span>
                      )}
                      <span className="visibility-badge">
                        {agent.visibility ?? 'PRIVATE'}
                      </span>
                    </div>

                    <button
                      type="button"
                      className="agent-card-edit-action"
                      onClick={() => handleEditAgent(agent)}
                      title="Edit Agent Configuration"
                    >
                      <EditIcon style={{ fontSize: 14 }} />
                      <span>Edit</span>
                    </button>
                  </div>

                  {/* Identity: Bot Glyph + Name + Version Tag */}
                  <div className="agent-card-identity">
                    <div className="agent-avatar-glyph">🤖</div>
                    <div className="agent-title-group">
                      <h5 className="deployed-card-name" title={agent.name}>
                        {agent.name}
                      </h5>
                      {agent.version && (
                        <span className="agent-version-tag">v{agent.version}</span>
                      )}
                    </div>
                  </div>

                  {/* Description: Clamped to exactly 3 lines with '...' */}
                  <p className="deployed-card-description" title={agent.description}>
                    {agent.description || 'No description provided for this agent.'}
                  </p>

                  {/* Meta Stats Panel: Model Name + Tools Count */}
                  <div className="deployed-card-meta">
                    <div className="meta-item">
                      <span className="meta-label">Model</span>
                      <span className="meta-value" title={modelName}>
                        <AutoAwesomeIcon style={{ fontSize: 14 }} />
                        <span className="meta-text">{modelName}</span>
                      </span>
                    </div>
                    <div className="meta-divider" />
                    <div className="meta-item">
                      <span className="meta-label">Tools</span>
                      <span className="meta-value">
                        <HandymanIcon style={{ fontSize: 14 }} />
                        <span className="meta-text">
                          {toolsCount} {toolsCount === 1 ? 'tool' : 'tools'}
                        </span>
                      </span>
                    </div>
                  </div>

                  {/* Bottom Action Area: Uniform height, dedicated to Use button */}
                  <div className="agent-card-bottom">
                    {isDeployed ? (
                      <button
                        type="button"
                        className="agent-use-btn"
                        onClick={() => navigate(`/chat/${agentId}`, { state: { agent } })}
                      >
                        <span>Use Agent</span>
                        <ArrowForwardIcon style={{ fontSize: 16 }} className="use-btn-arrow" />
                      </button>
                    ) : (
                      <div className="agent-draft-footer">
                        <span className="draft-hint-text">Draft &bull; Edit to deploy</span>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Container>
    </div>
  );
};
