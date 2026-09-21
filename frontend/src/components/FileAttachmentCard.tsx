import { X, FileText, FileSpreadsheet, Presentation, FileCode, Image, File } from 'lucide-react';

interface FileInfo {
  name: string;
  type: string;
  size?: number;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getFileCategory(ext: string): { icon: typeof FileText; label: string; color: string; bgColor: string; borderColor: string } {
  const map: Record<string, { icon: typeof FileText; label: string; color: string; bgColor: string; borderColor: string }> = {
    pdf: { icon: FileText, label: 'PDF', color: 'text-red-400', bgColor: 'bg-red-500/10', borderColor: 'border-red-500/30' },
    docx: { icon: FileText, label: 'Word', color: 'text-blue-400', bgColor: 'bg-blue-500/10', borderColor: 'border-blue-500/30' },
    doc: { icon: FileText, label: 'Word', color: 'text-blue-400', bgColor: 'bg-blue-500/10', borderColor: 'border-blue-500/30' },
    pptx: { icon: Presentation, label: 'PowerPoint', color: 'text-orange-400', bgColor: 'bg-orange-500/10', borderColor: 'border-orange-500/30' },
    ppt: { icon: Presentation, label: 'PowerPoint', color: 'text-orange-400', bgColor: 'bg-orange-500/10', borderColor: 'border-orange-500/30' },
    xlsx: { icon: FileSpreadsheet, label: 'Excel', color: 'text-green-400', bgColor: 'bg-green-500/10', borderColor: 'border-green-500/30' },
    xls: { icon: FileSpreadsheet, label: 'Excel', color: 'text-green-400', bgColor: 'bg-green-500/10', borderColor: 'border-green-500/30' },
    csv: { icon: FileSpreadsheet, label: 'CSV', color: 'text-green-400', bgColor: 'bg-green-500/10', borderColor: 'border-green-500/30' },
    txt: { icon: FileText, label: 'Text', color: 'text-gray-400', bgColor: 'bg-gray-500/10', borderColor: 'border-gray-500/30' },
    md: { icon: FileText, label: 'Markdown', color: 'text-gray-400', bgColor: 'bg-gray-500/10', borderColor: 'border-gray-500/30' },
    html: { icon: FileCode, label: 'HTML', color: 'text-purple-400', bgColor: 'bg-purple-500/10', borderColor: 'border-purple-500/30' },
    htm: { icon: FileCode, label: 'HTML', color: 'text-purple-400', bgColor: 'bg-purple-500/10', borderColor: 'border-purple-500/30' },
    json: { icon: FileCode, label: 'JSON', color: 'text-yellow-400', bgColor: 'bg-yellow-500/10', borderColor: 'border-yellow-500/30' },
    xml: { icon: FileCode, label: 'XML', color: 'text-yellow-400', bgColor: 'bg-yellow-500/10', borderColor: 'border-yellow-500/30' },
    png: { icon: Image, label: 'Image', color: 'text-pink-400', bgColor: 'bg-pink-500/10', borderColor: 'border-pink-500/30' },
    jpg: { icon: Image, label: 'Image', color: 'text-pink-400', bgColor: 'bg-pink-500/10', borderColor: 'border-pink-500/30' },
    jpeg: { icon: Image, label: 'Image', color: 'text-pink-400', bgColor: 'bg-pink-500/10', borderColor: 'border-pink-500/30' },
    gif: { icon: Image, label: 'Image', color: 'text-pink-400', bgColor: 'bg-pink-500/10', borderColor: 'border-pink-500/30' },
    webp: { icon: Image, label: 'Image', color: 'text-pink-400', bgColor: 'bg-pink-500/10', borderColor: 'border-pink-500/30' },
  };
  return map[ext] || { icon: File, label: ext.toUpperCase(), color: 'text-gray-400', bgColor: 'bg-gray-500/10', borderColor: 'border-gray-500/30' };
}

interface FileAttachmentInputProps {
  file: FileInfo;
  onRemove: () => void;
  variant?: 'dark' | 'light';
}

export function FileAttachmentInput({ file, onRemove, variant = 'dark' }: FileAttachmentInputProps) {
  const cat = getFileCategory(file.type);
  const Icon = cat.icon;

  return (
    <div className={`group flex items-center gap-3 px-3 py-2.5 rounded-xl border transition-all duration-200 ${
      variant === 'dark'
        ? `${cat.bgColor} ${cat.borderColor} hover:border-opacity-60`
        : `bg-white dark:${cat.bgColor} border-gray-200 dark:${cat.borderColor}`
    }`}>
      <div className={`w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 ${
        variant === 'dark' ? cat.bgColor : `bg-gray-100 dark:${cat.bgColor}`
      }`}>
        <Icon className={`w-4.5 h-4.5 ${cat.color}`} />
      </div>
      <div className="flex-1 min-w-0">
        <p className={`text-sm font-medium truncate ${
          variant === 'dark' ? 'text-gray-200' : 'text-gray-800 dark:text-gray-200'
        }`}>
          {file.name}
        </p>
        <p className={`text-xs ${variant === 'dark' ? 'text-gray-500' : 'text-gray-400 dark:text-gray-500'}`}>
          {cat.label}{file.size ? ` · ${formatFileSize(file.size)}` : ''}
        </p>
      </div>
      <button
        onClick={onRemove}
        className={`p-1 rounded-md transition-all duration-150 opacity-60 hover:opacity-100 ${
          variant === 'dark'
            ? 'hover:bg-white/10 text-gray-400 hover:text-red-400'
            : 'hover:bg-gray-100 dark:hover:bg-white/10 text-gray-400 hover:text-red-500 dark:hover:text-red-400'
        }`}
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}

interface FileAttachmentBubbleProps {
  fileName: string;
  variant?: 'dark' | 'light';
}

export function FileAttachmentBubble({ fileName, variant = 'dark' }: FileAttachmentBubbleProps) {
  const ext = fileName.split('.').pop()?.toLowerCase() || '';
  const cat = getFileCategory(ext);
  const Icon = cat.icon;

  return (
    <div className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium ${
      variant === 'dark'
        ? 'bg-white/10 text-white/80'
        : 'bg-gray-100 dark:bg-white/10 text-gray-600 dark:text-white/80'
    }`}>
      <Icon className={`w-3.5 h-3.5 ${variant === 'dark' ? 'text-white/60' : cat.color}`} />
      <span className="truncate max-w-[200px]">{fileName}</span>
    </div>
  );
}

export { getFileCategory, formatFileSize };
export type { FileInfo };
