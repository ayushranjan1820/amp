import { Link, useLocation } from 'react-router-dom';
import { Moon, Sun, LayoutGrid, BookOpen, Menu, X, Sparkles, PlusCircle } from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import { useAuth } from '../context/AuthContext';
import { useState } from 'react';

export default function Header() {
  const { isDark, toggleTheme } = useTheme();
  const { isAuthenticated } = useAuth();
  const location = useLocation();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const isActive = (path: string) =>
    path === '/' ? location.pathname === '/' : location.pathname === path || location.pathname.startsWith(`${path}/`);

  return (
    <header className="sticky top-0 z-50 border-b border-gray-200/60 bg-white/80 shadow-[0_1px_0_rgba(255,255,255,0.7)_inset] backdrop-blur-2xl backdrop-saturate-150 dark:border-white/[0.05] dark:bg-gray-950/75 dark:shadow-[0_1px_0_rgba(255,255,255,0.03)_inset]">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between items-center h-16 lg:h-[4.25rem]">
          <Link to="/" className="flex items-center gap-3 group">
            <div className="relative">
              <div className="absolute -inset-0.5 rounded-xl bg-gradient-to-br from-primary-500/40 to-accent-pink/30 opacity-0 blur-md transition-opacity group-hover:opacity-100" aria-hidden />
              <div className="relative w-10 h-10 lg:w-11 lg:h-11 gradient-primary rounded-xl flex items-center justify-center shadow-lg shadow-primary-600/20 ring-1 ring-white/20 transition-transform group-hover:scale-[1.02]">
                <span className="text-gray-900 dark:text-white font-heading font-bold text-lg lg:text-xl">A</span>
              </div>
            </div>
            <div className="hidden sm:block">
              <span className="font-heading text-lg lg:text-xl font-bold text-gray-900 dark:text-white block leading-tight tracking-tight">
                Agent Marketplace
              </span>
              <span className="text-[0.65rem] text-gray-500 dark:text-gray-500 font-body uppercase tracking-[0.14em]">
                by ET-Labs
              </span>
            </div>
          </Link>

          <nav className="hidden md:flex items-center gap-0.5 rounded-full border border-gray-200/70 bg-gray-50/90 p-1 shadow-sm dark:border-white/[0.07] dark:bg-white/[0.04] dark:shadow-none">
            <Link 
              to="/" 
              className={`flex items-center gap-2 rounded-full px-4 py-2 font-body font-semibold text-sm transition-all ${
                location.pathname === '/'
                  ? 'bg-white text-gray-900 shadow-sm ring-1 ring-gray-200/80 dark:bg-white/10 dark:text-white dark:ring-white/10' 
                  : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
              }`}
            >
              <LayoutGrid className="w-4 h-4 opacity-80" />
              Marketplace
            </Link>
            <Link
              to="/agent-studio"
              className={`flex items-center gap-2 rounded-full px-4 py-2 font-body font-semibold text-sm transition-all ${
                isActive('/agent-studio')
                  ? 'bg-white text-gray-900 shadow-sm ring-1 ring-gray-200/80 dark:bg-white/10 dark:text-white dark:ring-white/10'
                  : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
              }`}
            >
              <Sparkles className="w-4 h-4 opacity-80" />
              Agent Studio
            </Link>
            <Link
              to="/create-agent"
              className={`flex items-center gap-2 rounded-full px-4 py-2 font-body font-semibold text-sm transition-all ${
                isActive('/create-agent')
                  ? 'bg-white text-gray-900 shadow-sm ring-1 ring-gray-200/80 dark:bg-white/10 dark:text-white dark:ring-white/10'
                  : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
              }`}
            >
              <PlusCircle className="w-4 h-4 opacity-80" />
              Create Agent
            </Link>
            {isAuthenticated && (
              <Link
                to="/docs"
                className={`flex items-center gap-2 rounded-full px-4 py-2 font-body font-semibold text-sm transition-all ${
                  isActive('/docs')
                    ? 'bg-white text-gray-900 shadow-sm ring-1 ring-gray-200/80 dark:bg-white/10 dark:text-white dark:ring-white/10'
                    : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
                }`}
              >
                <BookOpen className="w-4 h-4 opacity-80" />
                Docs
              </Link>
            )}
          </nav>

          <div className="flex items-center gap-2">
            <button
              onClick={toggleTheme}
              className="p-2.5 rounded-full border border-transparent bg-gray-100/90 hover:bg-gray-200/90 dark:bg-white/[0.06] dark:hover:bg-white/[0.1] transition-colors"
              aria-label="Toggle theme"
            >
              {isDark ? (
                <Sun className="w-5 h-5 text-amber-500" />
              ) : (
                <Moon className="w-5 h-5 text-gray-600" />
              )}
            </button>

            <button
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="md:hidden p-2.5 rounded-full bg-gray-100/90 dark:bg-white/[0.06] hover:bg-gray-200 dark:hover:bg-white/[0.1] transition-colors"
              aria-label="Toggle menu"
            >
              {mobileMenuOpen ? (
                <X className="w-5 h-5 text-gray-600 dark:text-gray-300" />
              ) : (
                <Menu className="w-5 h-5 text-gray-600 dark:text-gray-300" />
              )}
            </button>
          </div>
        </div>

        {mobileMenuOpen && (
          <div className="md:hidden py-4 border-t border-gray-200/80 dark:border-white/[0.06] animate-fadeIn space-y-1">
            <Link 
              to="/" 
              onClick={() => setMobileMenuOpen(false)}
              className={`flex items-center gap-3 px-4 py-3 rounded-xl font-body font-semibold transition-colors ${
                location.pathname === '/'
                  ? 'bg-gray-100 dark:bg-white/[0.08] text-gray-900 dark:text-white' 
                  : 'text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-white/[0.04]'
              }`}
            >
              <LayoutGrid className="w-5 h-5" />
              Marketplace
            </Link>
            <Link
              to="/agent-studio"
              onClick={() => setMobileMenuOpen(false)}
              className={`flex items-center gap-3 px-4 py-3 rounded-xl font-body font-semibold transition-colors ${
                isActive('/agent-studio')
                  ? 'bg-gray-100 dark:bg-white/[0.08] text-gray-900 dark:text-white'
                  : 'text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-white/[0.04]'
              }`}
            >
              <Sparkles className="w-5 h-5" />
              Agent Studio
            </Link>
            <Link
              to="/create-agent"
              onClick={() => setMobileMenuOpen(false)}
              className={`flex items-center gap-3 px-4 py-3 rounded-xl font-body font-semibold transition-colors ${
                isActive('/create-agent')
                  ? 'bg-gray-100 dark:bg-white/[0.08] text-gray-900 dark:text-white'
                  : 'text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-white/[0.04]'
              }`}
            >
              <PlusCircle className="w-5 h-5" />
              Create Agent
            </Link>
            {isAuthenticated && (
              <Link
                to="/docs"
                onClick={() => setMobileMenuOpen(false)}
                className={`flex items-center gap-3 px-4 py-3 rounded-xl font-body font-semibold transition-colors ${
                  isActive('/docs')
                    ? 'bg-gray-100 dark:bg-white/[0.08] text-gray-900 dark:text-white'
                    : 'text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-white/[0.04]'
                }`}
              >
                <BookOpen className="w-5 h-5" />
                Docs
              </Link>
            )}
          </div>
        )}
      </div>
    </header>
  );
}
