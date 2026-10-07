import React, { useState, useRef, useEffect } from 'react';
import { Container } from 'react-bootstrap';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import './Navbar.css';

export const Navbar: React.FC = () => {
  const { user, logoutUser } = useAuth();
  const [showPopup, setShowPopup] = useState(false);
  const popupRef = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const navigate = useNavigate();

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

  // Determine which tab is active for the capsule toggle
  const isDeployed = location.pathname === '/deployed';
  const isCreateAgent = location.pathname === '/agent';

  const handleLogout = () => {
    setShowPopup(false);
    if (logoutUser) logoutUser();
    navigate('/login');
  };

  return (
    <nav className="navbar-custom py-3 sticky-top">
      <Container className="d-flex justify-content-between align-items-center">
        {/* Brand Logo */}
        <Link to="/" className="d-flex align-items-center text-decoration-none gap-2">
          <span className="fw-bold text-white fs-5 tracking-wide">
            Agent<span className="text-cyan-accent">Mart</span>
          </span>
        </Link>

        {/* Centre: Capsule toggle (only when logged in) */}
        {user && (
          <div className="nav-capsule-toggle">
            <Link
              to="/agent"
              className={`nav-capsule-btn ${isCreateAgent ? 'active' : ''}`}
            >
              Create Agent
            </Link>
            <Link
              to="/deployed"
              className={`nav-capsule-btn ${isDeployed ? 'active' : ''}`}
            >
              Deployed Agents
            </Link>
          </div>
        )}

        {/* Right Nav Actions */}
        <div className="d-flex align-items-center gap-3 ms-auto">
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
                <button className="btn-cyan-primary btn-sm px-3">Sign In</button>
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
                  onClick={handleLogout}
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
