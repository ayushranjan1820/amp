import React from 'react';
import { Container, Row, Col, Card, Badge, Button } from 'react-bootstrap';
import { Navbar } from '../components/layout/Navbar';
import { useAuth } from '../context/AuthContext';

export const LandingPage: React.FC = () => {
  const { user } = useAuth();

  return (
    <div className="min-vh-100 d-flex flex-column bg-dark text-light">
      <Navbar />

      {/* Hero Section */}
      <main className="flex-grow-1 py-5">
        <Container>
          <Row className="justify-content-center text-center my-4 py-4">
            <Col lg={9} xl={8}>
              <Badge bg="info" className="bg-opacity-20 text-cyan-accent border border-info border-opacity-25 px-3 py-2 rounded-pill mb-3">
                🤖 Autonomous AI Agent Ecosystem
              </Badge>
              <h1 className="display-4 fw-bold text-white mb-3">
                Discover & Deploy Next-Gen <span className="text-cyan-accent">AI Agents</span>
              </h1>
              <p className="lead text-secondary mb-4 fs-5">
                {user ? (
                  <>Welcome back, <strong className="text-cyan-accent">{user.name}</strong>! Explore, manage, and orchestrate intelligent autonomous agents.</>
                ) : (
                  <>AgentMart empowers developers and enterprises to deploy, scale, and monitor specialized AI agents seamlessly.</>
                )}
              </p>
              <div className="d-flex justify-content-center gap-3">
                <Button className="btn-cyan-primary px-4 py-2">
                  Explore Marketplace
                </Button>
                <Button variant="outline-light" className="px-4 py-2 rounded-3">
                  Deploy Custom Agent
                </Button>
              </div>
            </Col>
          </Row>

          {/* Featured Agent Cards Grid */}
          <Row className="g-4 mt-4">
            <Col md={4}>
              <Card className="auth-card h-100 p-4 border-0">
                <div className="d-flex align-items-center justify-content-between mb-3">
                  <div className="brand-glow-icon-sm">
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" fill="currentColor" viewBox="0 0 16 16">
                      <path d="M14 1a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H2a1 1 0 0 1-1-1V2a1 1 0 0 1 1-1zM2 0a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V2a2 2 0 0 0-2-2z"/>
                      <path d="M6.854 4.646a.5.5 0 0 1 0 .708L4.207 8l2.647 2.646a.5.5 0 0 1-.708.708l-3-3a.5.5 0 0 1 0-.708l3-3a.5.5 0 0 1 .708 0zm2.292 0a.5.5 0 0 0 0 .708L11.793 8l-2.647 2.646a.5.5 0 0 0 .708.708l3-3a.5.5 0 0 0 0-.708l-3-3a.5.5 0 0 0-.708 0z"/>
                    </svg>
                  </div>
                  <Badge bg="dark" className="text-cyan-accent border border-info border-opacity-25">Code Assistant</Badge>
                </div>
                <h5 className="fw-bold text-white mb-2">DevAgent Pro</h5>
                <p className="text-secondary small mb-4">
                  Automates code reviews, refactoring, and automated test generation across your repository.
                </p>
                <div className="mt-auto d-flex justify-content-between align-items-center pt-3 border-top border-secondary border-opacity-25">
                  <span className="text-cyan-accent fw-bold">Active</span>
                  <a href="#view" className="link-cyan small" onClick={(e) => e.preventDefault()}>View Details &rarr;</a>
                </div>
              </Card>
            </Col>

            <Col md={4}>
              <Card className="auth-card h-100 p-4 border-0">
                <div className="d-flex align-items-center justify-content-between mb-3">
                  <div className="brand-glow-icon-sm">
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" fill="currentColor" viewBox="0 0 16 16">
                      <path d="M0 2a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2zm15 2h-4v3h4zm0 4h-4v3h4zm0 4h-4v3h4zM1 4v3h9V4zm0 4v3h9V8zm0 4v3h9v-3z"/>
                    </svg>
                  </div>
                  <Badge bg="dark" className="text-cyan-accent border border-info border-opacity-25">Data Analytics</Badge>
                </div>
                <h5 className="fw-bold text-white mb-2">DataInsight AI</h5>
                <p className="text-secondary small mb-4">
                  Performs automated SQL queries, data transformations, and generates visual executive summaries.
                </p>
                <div className="mt-auto d-flex justify-content-between align-items-center pt-3 border-top border-secondary border-opacity-25">
                  <span className="text-cyan-accent fw-bold">Active</span>
                  <a href="#view" className="link-cyan small" onClick={(e) => e.preventDefault()}>View Details &rarr;</a>
                </div>
              </Card>
            </Col>

            <Col md={4}>
              <Card className="auth-card h-100 p-4 border-0">
                <div className="d-flex align-items-center justify-content-between mb-3">
                  <div className="brand-glow-icon-sm">
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" fill="currentColor" viewBox="0 0 16 16">
                      <path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1M0 8a8 8 0 1 1 16 0A8 8 0 0 1 0 8"/>
                      <path d="M8 4a.5.5 0 0 1 .5.5v3h3a.5.5 0 0 1 0 1h-3.5a.5.5 0 0 1-.5-.5v-4A.5.5 0 0 1 8 4"/>
                    </svg>
                  </div>
                  <Badge bg="dark" className="text-cyan-accent border border-info border-opacity-25">Customer Success</Badge>
                </div>
                <h5 className="fw-bold text-white mb-2">SupportFlow Bot</h5>
                <p className="text-secondary small mb-4">
                  24/7 intelligent customer triage agent with contextual knowledge base integration.
                </p>
                <div className="mt-auto d-flex justify-content-between align-items-center pt-3 border-top border-secondary border-opacity-25">
                  <span className="text-cyan-accent fw-bold">Active</span>
                  <a href="#view" className="link-cyan small" onClick={(e) => e.preventDefault()}>View Details &rarr;</a>
                </div>
              </Card>
            </Col>
          </Row>
        </Container>
      </main>

      {/* Footer */}
      <footer className="py-4 border-top border-secondary border-opacity-25 text-center text-muted small">
        <Container>
          &copy; {new Date().getFullYear()} AgentMart. All rights reserved.
        </Container>
      </footer>
    </div>
  );
};
