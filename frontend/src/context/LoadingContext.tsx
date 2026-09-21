import { createContext, useContext, useState, useCallback, type ReactNode } from 'react';
import FullScreenLoader from '../components/FullScreenLoader';

interface LoadingContextType {
  showLoader: (message: string) => void;
  hideLoader: () => void;
  withLoader: <T>(message: string, fn: () => Promise<T>) => Promise<T>;
}

const LoadingContext = createContext<LoadingContextType | null>(null);

export function LoadingProvider({ children }: { children: ReactNode }) {
  const [visible, setVisible] = useState(false);
  const [message, setMessage] = useState('Loading...');

  const showLoader = useCallback((msg: string) => {
    setMessage(msg);
    setVisible(true);
  }, []);

  const hideLoader = useCallback(() => {
    setVisible(false);
  }, []);

  const withLoader = useCallback(async <T,>(msg: string, fn: () => Promise<T>): Promise<T> => {
    setMessage(msg);
    setVisible(true);
    try {
      return await fn();
    } finally {
      setVisible(false);
    }
  }, []);

  return (
    <LoadingContext.Provider value={{ showLoader, hideLoader, withLoader }}>
      {children}
      <FullScreenLoader visible={visible} message={message} />
    </LoadingContext.Provider>
  );
}

export function useLoading() {
  const ctx = useContext(LoadingContext);
  if (!ctx) throw new Error('useLoading must be used within LoadingProvider');
  return ctx;
}
