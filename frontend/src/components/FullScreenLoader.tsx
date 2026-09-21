import { Loader2 } from 'lucide-react';

interface FullScreenLoaderProps {
  visible: boolean;
  message?: string;
}

export default function FullScreenLoader({ visible, message = 'Loading...' }: FullScreenLoaderProps) {
  if (!visible) return null;

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-gray-900/40 dark:bg-gray-950/80 backdrop-blur-sm">
      <div className="flex flex-col items-center gap-4 p-8 rounded-2xl bg-white dark:bg-gray-900/90 border border-gray-200 dark:border-gray-700/60 shadow-2xl max-w-sm mx-4">
        <div className="relative">
          <div className="w-16 h-16 rounded-full border-4 border-gray-200 dark:border-gray-700/40 border-t-primary-500 animate-spin" />
          <Loader2 className="w-6 h-6 text-primary-400 absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 animate-pulse" />
        </div>
        <p className="text-gray-900 dark:text-white font-body text-sm text-center leading-relaxed">{message}</p>
      </div>
    </div>
  );
}
