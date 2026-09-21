import { Settings } from 'lucide-react';

interface MaintenancePageProps {
  message: string;
}

export default function MaintenancePage({ message }: MaintenancePageProps) {
  return (
    <div className="min-h-screen bg-white dark:bg-gray-950 flex flex-col items-center justify-center relative overflow-hidden">
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-primary-500/5 rounded-full blur-3xl animate-pulse" />
        <div className="absolute bottom-1/4 right-1/4 w-80 h-80 bg-amber-500/5 rounded-full blur-3xl animate-pulse delay-1000" />
      </div>

      <div className="relative z-10 text-center px-6 max-w-lg">
        <div className="w-20 h-20 mx-auto mb-8 bg-amber-500/10 border border-amber-500/20 rounded-2xl flex items-center justify-center">
          <Settings className="w-10 h-10 text-amber-400 animate-[spin_4s_linear_infinite]" />
        </div>

        <h1 className="font-heading text-3xl md:text-4xl font-bold text-gray-900 dark:text-white mb-4">
          Under Maintenance
        </h1>

        <p className="font-body text-gray-600 dark:text-gray-400 text-base md:text-lg leading-relaxed mb-8">
          {message}
        </p>

        <div className="flex items-center justify-center gap-2 text-sm text-gray-500">
          <div className="w-2 h-2 bg-amber-500 rounded-full animate-pulse" />
          <span className="font-body">We'll be back online soon</span>
        </div>
      </div>

      <div className="absolute bottom-8 text-center">
        <p className="font-body text-xs text-gray-600">ET-Labs AI Agent Marketplace</p>
      </div>
    </div>
  );
}
