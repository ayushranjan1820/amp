import { Mail, Send, CheckCircle2, User, Clock, Hash } from 'lucide-react';

export interface EmailPreviewData {
  recipients: string[];
  subject: string;
  body: string;
  status: 'preview' | 'sent';
  email_id?: string;
}

export function isEmailPreview(data: any): data is EmailPreviewData {
  return data && Array.isArray(data.recipients) && typeof data.subject === 'string' && typeof data.status === 'string';
}

export default function EmailPreviewCard({ data }: { data: EmailPreviewData }) {
  const isSent = data.status === 'sent';

  return (
    <div className={`my-3 rounded-xl overflow-hidden border ${isSent ? 'border-green-500/30 dark:border-green-500/20' : 'border-gray-200 dark:border-gray-700'} shadow-lg`}>
      <div className={`px-4 py-3 flex items-center gap-3 ${isSent ? 'bg-gradient-to-r from-green-500/10 to-emerald-500/10 dark:from-green-500/5 dark:to-emerald-500/5' : 'bg-gradient-to-r from-primary-500/10 to-primary-600/10 dark:from-primary-500/5 dark:to-primary-600/5'}`}>
        <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${isSent ? 'bg-green-500/20 dark:bg-green-500/10' : 'bg-primary-500/20 dark:bg-primary-500/10'}`}>
          {isSent ? (
            <CheckCircle2 className="w-5 h-5 text-green-500" />
          ) : (
            <Mail className="w-5 h-5 text-primary-500" />
          )}
        </div>
        <div className="flex-1 min-w-0">
          <p className={`text-sm font-semibold ${isSent ? 'text-green-700 dark:text-green-400' : 'text-gray-900 dark:text-white'}`}>
            {isSent ? 'Email Delivered' : 'Email Preview'}
          </p>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            {isSent ? 'Successfully sent' : 'Review before sending'}
          </p>
        </div>
        {isSent && (
          <div className="flex items-center gap-1.5 px-2.5 py-1 bg-green-500/15 rounded-full">
            <Send className="w-3 h-3 text-green-600 dark:text-green-400" />
            <span className="text-xs font-medium text-green-600 dark:text-green-400">Sent</span>
          </div>
        )}
      </div>

      <div className="bg-white dark:bg-gray-900/80 px-4 py-3 space-y-3">
        <div className="flex items-start gap-3">
          <div className="w-7 h-7 rounded-full bg-gray-100 dark:bg-gray-800 flex items-center justify-center flex-shrink-0 mt-0.5">
            <User className="w-3.5 h-3.5 text-gray-500 dark:text-gray-400" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-[10px] uppercase tracking-wider text-gray-400 dark:text-gray-500 font-semibold mb-0.5">To</p>
            <div className="flex flex-wrap gap-1.5">
              {data.recipients.map((r, i) => (
                <span key={i} className="inline-flex items-center gap-1 px-2 py-0.5 bg-gray-100 dark:bg-gray-800 rounded-md text-xs font-medium text-gray-700 dark:text-gray-300 border border-gray-200 dark:border-gray-700">
                  <Mail className="w-3 h-3 text-gray-400" />
                  {r}
                </span>
              ))}
            </div>
          </div>
        </div>

        <div className="h-px bg-gray-100 dark:bg-gray-800" />

        <div>
          <p className="text-[10px] uppercase tracking-wider text-gray-400 dark:text-gray-500 font-semibold mb-1">Subject</p>
          <p className="text-sm font-semibold text-gray-900 dark:text-white">{data.subject}</p>
        </div>

        <div className="h-px bg-gray-100 dark:bg-gray-800" />

        <div>
          <p className="text-[10px] uppercase tracking-wider text-gray-400 dark:text-gray-500 font-semibold mb-1.5">Body</p>
          <div className="bg-gray-50 dark:bg-gray-800/60 rounded-lg p-3 border border-gray-100 dark:border-gray-700/50">
            <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed whitespace-pre-wrap">{data.body}</p>
          </div>
        </div>

        {data.email_id && (
          <>
            <div className="h-px bg-gray-100 dark:bg-gray-800" />
            <div className="flex items-center gap-4 text-xs text-gray-400 dark:text-gray-500">
              <span className="flex items-center gap-1">
                <Hash className="w-3 h-3" />
                {data.email_id}
              </span>
              <span className="flex items-center gap-1">
                <Clock className="w-3 h-3" />
                Just now
              </span>
            </div>
          </>
        )}
      </div>

      {!isSent && (
        <div className="bg-amber-50/80 dark:bg-amber-900/10 px-4 py-2.5 border-t border-amber-200/50 dark:border-amber-800/30">
          <p className="text-xs text-amber-700 dark:text-amber-400 flex items-center gap-1.5">
            <Send className="w-3 h-3" />
            Say <span className="font-semibold">"yes"</span> to send, or describe changes
          </p>
        </div>
      )}
    </div>
  );
}
