import React from 'react';
import { Container, Row, Col } from 'react-bootstrap';

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
              <div className="brand-glow-icon">
                <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" fill="currentColor" viewBox="0 0 16 16">
                  <path d="M6 12c0 1.657 3.134 3 7 3s7-1.343 7-3-3.134-3-7-3-7 1.343-7 3"/>
                  <path d="M5 6.25a3.5 3.5 0 1 1 7 0 3.5 3.5 0 0 1-7 0m3.5-2.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5"/>
                  <path d="M0 8a8 8 0 1 1 16 0A8 8 0 0 1 0 8m8-7a7 7 0 0 0-5.468 11.37C3.242 11.226 4.805 10 8 10s4.757 1.225 5.468 2.37A7 7 0 0 0 8 1"/>
                </svg>
              </div>
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
