import React, { createContext, useContext, useState, useEffect } from 'react';

export interface UserSession {
  name: string;
  email: string;
  token: string;
}

interface AuthContextType {
  user: UserSession | null;
  token: string | null;
  loginUser: (session: UserSession) => void;
  logoutUser: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const USER_STORAGE_KEY = 'agentmart_user_session';
export const TOKEN_STORAGE_KEY = 'token';

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<UserSession | null>(() => {
    try {
      const savedUser = sessionStorage.getItem(USER_STORAGE_KEY);
      return savedUser ? JSON.parse(savedUser) : null;
    } catch {
      return null;
    }
  });

  const [token, setToken] = useState<string | null>(() => {
    return sessionStorage.getItem(TOKEN_STORAGE_KEY);
  });

  useEffect(() => {
    if (user && user.token) {
      sessionStorage.setItem(USER_STORAGE_KEY, JSON.stringify(user));
      sessionStorage.setItem(TOKEN_STORAGE_KEY, user.token);
      setToken(user.token);
    } else {
      sessionStorage.removeItem(USER_STORAGE_KEY);
      sessionStorage.removeItem(TOKEN_STORAGE_KEY);
      setToken(null);
    }
  }, [user]);

  const loginUser = (session: UserSession) => {
    setUser(session);
    setToken(session.token);
    sessionStorage.setItem(USER_STORAGE_KEY, JSON.stringify(session));
    sessionStorage.setItem(TOKEN_STORAGE_KEY, session.token);
  };

  const logoutUser = () => {
    setUser(null);
    setToken(null);
    sessionStorage.removeItem(USER_STORAGE_KEY);
    sessionStorage.removeItem(TOKEN_STORAGE_KEY);
  };

  return (
    <AuthContext.Provider value={{ user, token, loginUser, logoutUser }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
