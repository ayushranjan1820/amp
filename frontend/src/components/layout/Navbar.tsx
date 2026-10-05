import React, { useState, useRef, useEffect } from 'react';
import { Container, Button } from 'react-bootstrap';
import { Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import './Navbar.css';

export const Navbar: React.FC = () => {
  const { user } = useAuth();
  const [showPopup, setShowPopup] = useState(false);
  const popupRef = useRef<HTMLDivElement>(null);

  // Close popup when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (popupRef.current && !popupRef.current.contains(event.target as Node)) {
        setShowPopup(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  const displayName = user?.name || 'Guest User';
  const displayEmail = user?.email || 'guest@example.com';
  const userInitials = displayName.slice(0, 2).toUpperCase();

  return (
    <nav className="navbar-custom py-3 sticky-top">
      <Container className="d-flex justify-content-between align-items-center">
        {/* Brand Logo */}
        <Link to="/" className="d-flex align-items-center text-decoration-none gap-2">
          <span className="fw-bold text-white fs-5 tracking-wide">
            Agent<span className="text-cyan-accent">Mart</span>
          </span>
        </Link>

        {/* Right Nav Actions */}
        <div className="d-flex align-items-center gap-3 ms-auto">
          {user && (
            <Link to="/agent" className="text-decoration-none">
              <Button className="btn-cyan-primary btn-sm px-3 d-flex align-items-center gap-1 fw-semibold">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="12" y1="5" x2="12" y2="19"></line>
                  <line x1="5" y1="12" x2="19" y2="12"></line>
                </svg>
                <span>Create Agent</span>
              </Button>
            </Link>
          )}

          {/* Top Right User Section */}
          <div className="position-relative" ref={popupRef}>
            {user ? (
              <button
                type="button"
                className="user-profile-btn border-0 bg-transparent p-0 d-flex align-items-center gap-2"
                onClick={() => setShowPopup(!showPopup)}
                aria-expanded={showPopup}
              >
                <div className="avatar-circle">
                  {userInitials}
                </div>
                <span className="fw-medium text-light d-none d-sm-inline">{displayName}</span>
              </button>
            ) : (
              <Link to="/login">
                <Button className="btn-cyan-primary btn-sm px-3">Sign In</Button>
              </Link>
            )}

          {/* User Details Popup Modal / Popover */}
          {showPopup && user && (
            <div className="user-popup-menu shadow-lg p-3 rounded-4">
              <div className="d-flex align-items-center gap-3 mb-3 pb-3 border-bottom border-secondary-subtle">
                <div className="avatar-circle-lg flex-shrink-0">
                  {userInitials}
                </div>
                <div className="overflow-hidden">
                  <h6 className="fw-bold text-white mb-0 text-truncate">{displayName}</h6>
                  <small className="text-cyan-accent text-nowrap d-block">{displayEmail}</small>
                </div>
              </div>

              <div>
                <button
                  type="button"
                  className="btn btn-outline-danger w-100 btn-sm rounded-3"
                  onClick={() => setShowPopup(false)}
                >
                  Logout
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
      </Container>
    </nav>
  );
};
