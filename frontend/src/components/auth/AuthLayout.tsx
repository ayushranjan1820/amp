import React from 'react';
import { Container, Row, Col } from 'react-bootstrap';
import './AuthLayout.css';

interface AuthLayoutProps {
  children: React.ReactNode;
  title: string;
  subtitle: string;
}

export const AuthLayout: React.FC<AuthLayoutProps> = ({ children, title, subtitle }) => {
  return (
    <div className="min-vh-100 d-flex flex-column justify-content-center py-5">
      <Container>
        <Row className="justify-content-center">
          <Col xs={12} sm={10} md={8} lg={5} xl={4}>
            {/* Brand Header */}
            <div className="text-center mb-4">
              <h2 className="fw-bold text-white mb-1">
                Agent<span className="text-cyan-accent">Mart</span>
              </h2>
              <p className="text-muted small">{subtitle}</p>
            </div>

            {/* Auth Card */}
            <div className="auth-card p-4 p-sm-5">
              <h4 className="fw-semibold text-white mb-4 text-center">{title}</h4>
              {children}
            </div>

            {/* Sub-footer */}
            <div className="text-center mt-4 text-muted small">
              &copy; {new Date().getFullYear()} AgentMart. All rights reserved.
            </div>
          </Col>
        </Row>
      </Container>
    </div>
  );
};
