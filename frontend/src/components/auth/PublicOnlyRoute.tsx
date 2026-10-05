import React from 'react';
import { Navigate, Outlet } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';

/**
 * Route wrapper for auth routes (login/register).
 * If the user is already authenticated with a token, it redirects them to the main page (/).
 */
export const PublicOnlyRoute: React.FC = () => {
  const { token } = useAuth();

  if (token) {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
};
