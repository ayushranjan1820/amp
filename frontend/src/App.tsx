import { useState, useEffect, lazy, Suspense } from 'react';
import { BrowserRouter as Router, Routes, Route, useLocation, Navigate } from 'react-router-dom';
import { ThemeProvider } from './context/ThemeContext';
import { AuthProvider, useAuth } from './context/AuthContext';
import Header from './components/Header';
import Footer from './components/Footer';
import { getAgents, getMaintenanceStatus } from './services/api';
import { applyPrimaryColorsFromCatalog } from './utils/catalogPrimaryColors';
import './index.css';

const Home = lazy(() => import('./pages/Home'));
const AgentStudioPage = lazy(() => import('./pages/AgentStudioPage'));
const AgentBuilderPage = lazy(() => import('./pages/AgentBuilderPage'));
const AgentPage = lazy(() => import('./pages/AgentPage'));
const DocsPage = lazy(() => import('./pages/DocsPage'));
const GlobalChat = lazy(() => import('./pages/GlobalChat'));
const AdminDashboard = lazy(() => import('./pages/AdminDashboard'));
const AdminLayout = lazy(() => import('./layouts/AdminLayout'));
const AdminLogin = lazy(() => import('./pages/AdminLogin'));
const MaintenancePage = lazy(() => import('./pages/MaintenancePage'));

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-white dark:bg-gray-950">
        <div className="relative w-12 h-12">
          <div className="absolute inset-0 rounded-full border-2 border-gray-800"></div>
          <div className="absolute inset-0 rounded-full border-2 border-transparent border-t-primary-500 animate-spin"></div>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/admin/login" replace />;
  }

  return <>{children}</>;
}

function AppLayout() {
  const location = useLocation();
  const { role, isLoading: authLoading } = useAuth();
  const isChatPage = location.pathname === '/chat';
  const isAdminPage = location.pathname.startsWith('/admin');
  const isAdminLogin = location.pathname === '/admin/login';
  const isAdminDashboard = isAdminPage && !isAdminLogin;
  const hideFooter = isChatPage || isAdminDashboard;

  const [maintenanceMode, setMaintenanceMode] = useState(false);
  const [maintenanceMessage, setMaintenanceMessage] = useState('');

  useEffect(() => {
    getAgents()
      .then((catalog) => {
        applyPrimaryColorsFromCatalog(catalog.metadata?.primary_colors);
      })
      .catch(() => {});

    getMaintenanceStatus()
      .then((data) => {
        setMaintenanceMode(data.enabled);
        setMaintenanceMessage(data.message);
      })
      .catch(() => {});

    const interval = setInterval(() => {
      getMaintenanceStatus()
        .then((data) => {
          setMaintenanceMode(data.enabled);
          setMaintenanceMessage(data.message);
        })
        .catch(() => {});
    }, 30000);

    return () => clearInterval(interval);
  }, []);

  // When maintenance mode is on, only the super_admin may use the app.
  // The admin login page stays reachable so the super_admin can sign in;
  // everyone else (unauthenticated, users, regular admins) sees the page.
  if (maintenanceMode && role !== 'super_admin' && !isAdminLogin && !authLoading) {
    return <MaintenancePage message={maintenanceMessage} />;
  }

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950 flex flex-col">
      <Header />
      <main
        className={
          isChatPage ? 'flex min-h-0 flex-1 flex-col overflow-hidden' : 'flex-1'
        }
      >
        <Suspense fallback={
          <div className="min-h-screen flex items-center justify-center bg-white dark:bg-gray-950">
            <div className="relative w-12 h-12">
              <div className="absolute inset-0 rounded-full border-2 border-gray-800"></div>
              <div className="absolute inset-0 rounded-full border-2 border-transparent border-t-primary-500 animate-spin"></div>
            </div>
          </div>
        }>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/agent-studio" element={<AgentStudioPage />} />
            <Route path="/agent-studio/:workflowId" element={<AgentStudioPage />} />
            <Route path="/create-agent" element={<AgentBuilderPage />} />
            <Route path="/create-agent/:id" element={<AgentBuilderPage />} />
            <Route
              path="/docs"
              element={
                <ProtectedRoute>
                  <DocsPage />
                </ProtectedRoute>
              }
            />
            <Route path="/agent/:id" element={<AgentPage />} />
            <Route
              path="/chat"
              element={
                <ProtectedRoute>
                  <AdminLayout>
                    <GlobalChat embedded />
                  </AdminLayout>
                </ProtectedRoute>
              }
            />
            <Route path="/admin/login" element={<AdminLogin />} />
            <Route path="/admin/*" element={
              <ProtectedRoute>
                <AdminDashboard />
              </ProtectedRoute>
            } />
            <Route path="/catalog" element={<Navigate to="/admin/agents" replace />} />
          </Routes>
        </Suspense>
      </main>
      {!hideFooter && <Footer />}
    </div>
  );
}

function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <Router>
          <AppLayout />
        </Router>
      </AuthProvider>
    </ThemeProvider>
  );
}

export default App;
