import { Bot, Mail, Globe, Linkedin, Twitter } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export default function Footer() {
  const { isAuthenticated } = useAuth();
  const currentYear = new Date().getFullYear();

  return (
    <footer className="relative overflow-hidden border-t border-gray-200 dark:border-white/[0.06] bg-white dark:bg-gray-950 bg-grain">
      <div className="pointer-events-none absolute inset-0" aria-hidden>
        <div className="absolute -left-20 top-0 h-72 w-72 rounded-full bg-primary-600/20 blur-[100px]" />
        <div className="absolute bottom-0 right-0 h-96 w-96 rounded-full bg-accent-pink/10 blur-[120px]" />
        <img
          src="/images/footer-banner.png"
          alt=""
          className="h-full w-full object-cover object-center opacity-[0.12] mix-blend-overlay"
        />
        <div className="absolute inset-0 bg-gradient-to-b from-white via-white/95 to-white dark:from-gray-950 dark:via-gray-950/95 dark:to-gray-950" />
      </div>

      <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-20 pb-10">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-12 mb-14">
          <div className="md:col-span-2">
            <div className="flex items-center gap-3 mb-5">
              <div className="w-11 h-11 bg-gradient-to-br from-primary-600 to-primary-500 rounded-xl flex items-center justify-center shadow-lg shadow-primary-600/25 ring-1 ring-white/10">
                <Bot className="w-5 h-5 text-white" />
              </div>
              <div>
                <div className="font-heading text-lg font-bold text-gray-900 dark:text-white tracking-tight">Agent Marketplace</div>
                <div className="text-[0.65rem] text-gray-500 font-body uppercase tracking-[0.14em]">by ET-Labs</div>
              </div>
            </div>
            <p className="font-body text-sm text-gray-600 dark:text-gray-400 mb-8 max-w-md leading-relaxed">
              Intelligent agents for enterprise workflows—automate the repetitive, keep humans in the loop, and ship faster with guardrails built in.
            </p>
            <div className="flex flex-wrap gap-2">
              <a href="#" className="w-10 h-10 rounded-full border border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-white/[0.03] flex items-center justify-center text-gray-600 dark:text-gray-400 transition-colors hover:border-primary-500/40 hover:bg-primary-500/10 hover:text-primary-300">
                <Linkedin className="w-4 h-4" />
              </a>
              <a href="#" className="w-10 h-10 rounded-full border border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-white/[0.03] flex items-center justify-center text-gray-600 dark:text-gray-400 transition-colors hover:border-primary-500/40 hover:bg-primary-500/10 hover:text-primary-300">
                <Twitter className="w-4 h-4" />
              </a>
              <a href="#" className="w-10 h-10 rounded-full border border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-white/[0.03] flex items-center justify-center text-gray-600 dark:text-gray-400 transition-colors hover:border-primary-500/40 hover:bg-primary-500/10 hover:text-primary-300">
                <Globe className="w-4 h-4" />
              </a>
              <a href="#" className="w-10 h-10 rounded-full border border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-white/[0.03] flex items-center justify-center text-gray-600 dark:text-gray-400 transition-colors hover:border-primary-500/40 hover:bg-primary-500/10 hover:text-primary-300">
                <Mail className="w-4 h-4" />
              </a>
            </div>
          </div>

          <div>
            <h4 className="font-heading text-xs font-bold uppercase tracking-[0.16em] mb-5 text-gray-700 dark:text-gray-300">Platform</h4>
            <ul className="space-y-3">
              <li><a href="#agents" className="font-body text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-colors">Browse agents</a></li>
              {isAuthenticated && (
                <li>
                  <Link to="/docs" className="font-body text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-colors">
                    API documentation
                  </Link>
                </li>
              )}
              <li><a href="#" className="font-body text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-colors">Enterprise plans</a></li>
              <li><a href="/admin" className="font-body text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-colors">Admin dashboard</a></li>
            </ul>
          </div>

          <div>
            <h4 className="font-heading text-xs font-bold uppercase tracking-[0.16em] mb-5 text-gray-700 dark:text-gray-300">Resources</h4>
            <ul className="space-y-3">
              {isAuthenticated && (
                <li>
                  <Link to="/docs" className="font-body text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-colors">
                    Documentation
                  </Link>
                </li>
              )}
              <li><a href="#" className="font-body text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-colors">Support</a></li>
              <li><a href="#" className="font-body text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-colors">Privacy</a></li>
              <li><a href="#" className="font-body text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-colors">Terms</a></li>
            </ul>
          </div>
        </div>

        <div className="pt-10 border-t border-gray-200 dark:border-white/[0.06]">
          <div className="flex flex-col md:flex-row justify-between items-center gap-4">
            <div className="font-body text-sm text-gray-500">
              © {currentYear} ET-Labs. All rights reserved.
            </div>
            <div className="flex items-center gap-2 rounded-full border border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-white/[0.03] px-3 py-1.5 text-xs text-gray-600 dark:text-gray-400">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400/50 opacity-75" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
              </span>
              <span>All systems operational</span>
            </div>
          </div>
        </div>
      </div>
    </footer>
  );
}
