import React, { useState, useEffect } from 'react';
import { Modal, Button, Form, Badge, Row, Col } from 'react-bootstrap';
import type { AgentItem } from '../../types/agent';

interface AgentConfigModalProps {
  show: boolean;
  agent: AgentItem | null;
  onHide: () => void;
  onSave?: (updatedAgent: AgentItem) => void;
}

export const AgentConfigModal: React.FC<AgentConfigModalProps> = ({
  show,
  agent,
  onHide,
  onSave,
}) => {
  const [formData, setFormData] = useState<AgentItem>({
    name: '',
    description: '',
    system_prompt: '',
    version: '1.0.0',
    enabled: true,
    status: 'DRAFT',
    visibility: 'PRIVATE',
    capabilities: [],
    tools: [],
  });

  useEffect(() => {
    if (agent) {
      setFormData({
        ...agent,
        system_prompt: agent.system_prompt || '',
        version: agent.version || '1.0.0',
        enabled: agent.enabled !== undefined ? agent.enabled : true,
        status: agent.status || 'DRAFT',
        capabilities: agent.capabilities || [],
        tools: agent.tools || [],
      });
    }
  }, [agent]);

  if (!agent) return null;

  const getModelDisplayName = (): string => {
    if (!formData.model) return 'Not configured';
    if (typeof formData.model === 'string') return formData.model;
    return `${formData.model.provider || 'Provider'} (${formData.model.model_name || 'Default'})`;
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
    const { name, value, type } = e.target;
    const checked = (e.target as HTMLInputElement).checked;
    setFormData((prev) => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value,
    }));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (onSave) {
      onSave(formData);
    }
    onHide();
  };

  return (
    <Modal show={show} onHide={onHide} centered size="lg" contentClassName="auth-card border-0 p-2">
      <Modal.Header closeButton closeVariant="white" className="border-bottom border-secondary border-opacity-25 pb-3">
        <Modal.Title className="d-flex align-items-center gap-2 text-white fw-bold fs-4">
          <span>Agent Configuration</span>
          <Badge className="badge-custom ms-2 fs-6">
            v{formData.version}
          </Badge>
        </Modal.Title>
      </Modal.Header>


      <Form onSubmit={handleSubmit}>
        <Modal.Body className="py-4">
          <Row className="g-3 mb-3">
            <Col md={8}>
              <Form.Group controlId="agent-name">
                <Form.Label className="form-label-custom">Agent Name</Form.Label>
                <Form.Control
                  type="text"
                  name="name"
                  value={formData.name}
                  onChange={handleInputChange}
                  className="custom-input"
                  required
                />
              </Form.Group>
            </Col>
            <Col md={4}>
              <Form.Group controlId="agent-version">
                <Form.Label className="form-label-custom">Version</Form.Label>
                <Form.Control
                  type="text"
                  name="version"
                  value={formData.version}
                  onChange={handleInputChange}
                  className="custom-input"
                />
              </Form.Group>
            </Col>
          </Row>

          <Form.Group className="mb-3" controlId="agent-description">
            <Form.Label className="form-label-custom">Description</Form.Label>
            <Form.Control
              as="textarea"
              rows={2}
              name="description"
              value={formData.description}
              onChange={handleInputChange}
              className="custom-input"
            />
          </Form.Group>

          <Form.Group className="mb-3" controlId="agent-system-prompt">
            <Form.Label className="form-label-custom">System Prompt</Form.Label>
            <Form.Control
              as="textarea"
              rows={4}
              name="system_prompt"
              value={formData.system_prompt}
              onChange={handleInputChange}
              className="custom-input font-monospace small"
              placeholder="You are a helpful AI assistant..."
            />
          </Form.Group>

          <Row className="g-3 mb-3">
            <Col md={6}>
              <Form.Group controlId="agent-status">
                <Form.Label className="form-label-custom">Status</Form.Label>
                <Form.Select
                  name="status"
                  value={formData.status}
                  onChange={handleInputChange}
                  className="custom-input"
                >
                  <option value="DRAFT">DRAFT</option>
                  <option value="PUBLISHED">PUBLISHED</option>
                  <option value="ARCHIVED">ARCHIVED</option>
                </Form.Select>
              </Form.Group>
            </Col>
            <Col md={6}>
              <Form.Group controlId="agent-model">
                <Form.Label className="form-label-custom">Model Config</Form.Label>
                <Form.Control
                  type="text"
                  value={getModelDisplayName()}
                  disabled
                  className="custom-input text-muted"
                />
              </Form.Group>
            </Col>
          </Row>

          <div className="d-flex align-items-center justify-content-between p-3 rounded-3 border border-secondary border-opacity-25 mb-3" style={{ background: 'var(--input-bg-dark)' }}>
            <div>
              <h6 className="fw-semibold text-white mb-1">Agent Status (Enabled)</h6>
              <small className="text-secondary">Toggle whether this agent is active for execution</small>
            </div>
            <Form.Check
              type="switch"
              id="agent-enabled-switch"
              name="enabled"
              checked={formData.enabled}
              onChange={handleInputChange}
              className="fs-4 form-check-input-custom"
            />
          </div>

          {formData.capabilities && formData.capabilities.length > 0 && (
            <div className="mb-2">
              <Form.Label className="form-label-custom">Capabilities</Form.Label>
              <div className="d-flex flex-wrap gap-2">
                {formData.capabilities.map((cap, idx) => (
                  <Badge key={idx} className="badge-custom px-2 py-1">
                    {cap}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </Modal.Body>

        <Modal.Footer className="border-top border-secondary border-opacity-25 pt-3">
          <Button variant="outline-secondary" onClick={onHide} className="px-4 rounded-3">
            Cancel
          </Button>
          <Button type="submit" className="btn-cyan-primary px-4">
            Save Configuration
          </Button>
        </Modal.Footer>
      </Form>
    </Modal>
  );
};
