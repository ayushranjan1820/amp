import React, { useState, useRef, useEffect } from 'react';
import { Container, Button } from 'react-bootstrap';
import { Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';

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
          <div className="brand-glow-icon-sm">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" fill="currentColor" viewBox="0 0 16 16">
              <path d="M6 12c0 1.657 3.134 3 7 3s7-1.343 7-3-3.134-3-7-3-7 1.343-7 3"/>
              <path d="M5 6.25a3.5 3.5 0 1 1 7 0 3.5 3.5 0 0 1-7 0m3.5-2.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5"/>
              <path d="M0 8a8 8 0 1 1 16 0A8 8 0 0 1 0 8m8-7a7 7 0 0 0-5.468 11.37C3.242 11.226 4.805 10 8 10s4.757 1.225 5.468 2.37A7 7 0 0 0 8 1"/>
            </svg>
          </div>
          <span className="fw-bold text-white fs-5 tracking-wide">
            Agent<span className="text-cyan-accent">Mart</span>
          </span>
        </Link>

        {/* Center Nav Links */}
        <div className="d-none d-md-flex align-items-center gap-4">
          <Link to="/" className="nav-link-custom active">Marketplace</Link>
          <a href="#agents" className="nav-link-custom" onClick={(e) => e.preventDefault()}>My Agents</a>
          <a href="#docs" className="nav-link-custom" onClick={(e) => e.preventDefault()}>Documentation</a>
        </div>

        {/* Top Right User Section (Right Aligned) */}
        <div className="position-relative ms-auto" ref={popupRef}>
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
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="currentColor" className={`text-muted transition-transform ${showPopup ? 'rotate-180' : ''}`} viewBox="0 0 16 16">
                <path fillRule="evenodd" d="M1.646 4.646a.5.5 0 0 1 .708 0L8 10.293l5.646-5.647a.5.5 0 0 1 .708.708l-6 6a.5.5 0 0 1-.708 0l-6-6a.5.5 0 0 1 0-.708"/>
              </svg>
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


              <div className="d-flex flex-column gap-2 mb-2">
                <div className="d-flex align-items-center gap-2 py-1 text-secondary small">
                  <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="currentColor" viewBox="0 0 16 16">
                    <path d="M8 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6m2-3a2 2 0 1 1-4 0 2 2 0 0 1 4 0m4 8c0 1-1 1-1 1H3s-1 0-1-1 1-4 6-4 6 3 6 4m-1-.004c-.001-.246-.154-.986-.832-1.664C11.516 10.68 10.289 10 8 10s-3.516.68-4.168 1.332c-.678.678-.83 1.418-.832 1.664z"/>
                  </svg>
                  <span>User Account</span>
                </div>
              </div>

              <div className="pt-2 border-top border-secondary-subtle">
                <button
                  type="button"
                  className="btn btn-outline-danger w-100 btn-sm d-flex align-items-center justify-content-center gap-2 rounded-3"
                  onClick={() => {
                    // Per requirement #4: No need to implement logout functionality
                    setShowPopup(false);
                  }}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="currentColor" viewBox="0 0 16 16">
                    <path fillRule="evenodd" d="M10 12.5a.5.5 0 0 1-.5.5h-8a.5.5 0 0 1-.5-.5v-9a.5.5 0 0 1 .5-.5h8a.5.5 0 0 1 .5.5v2a.5.5 0 0 0 1 0v-2A1.5 1.5 0 0 0 9.5 1h-8A1.5 1.5 0 0 0 0 2.5v9A1.5 1.5 0 0 0 1.5 13h8a1.5 1.5 0 0 0 1.5-1.5v-2a.5.5 0 0 0-1 0z"/>
                    <path fillRule="evenodd" d="M15.854 8.354a.5.5 0 0 0 0-.708l-3-3a.5.5 0 0 0-.708.708L14.293 7.5H5.5a.5.5 0 0 0 0 1h8.793l-2.147 2.146a.5.5 0 0 0 .708.708z"/>
                  </svg>
                  <span>Logout</span>
                </button>
              </div>
            </div>
          )}
        </div>
      </Container>
    </nav>
  );
};
