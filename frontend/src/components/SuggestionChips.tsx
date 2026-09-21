import { Zap } from 'lucide-react';

interface SuggestionChipsProps {
  content: string;
  onSuggestionClick: (text: string) => void;
  disabled?: boolean;
  darkMode?: boolean;
}

function extractSuggestions(content: string): string[] {
  const suggestions: string[] = [];

  const emojiBoldPattern = /^-\s+(?:📝|🛠️|🏗️|✨|✏️|🚀|🧪|📊|🔍|💡|⚡|📋|🎯)\s*\*\*(.+?)\*\*/gm;
  let match;
  while ((match = emojiBoldPattern.exec(content)) !== null) {
    let text = match[1].trim();
    text = text.replace(/\*\*/g, '');
    suggestions.push(text);
  }

  const sayPattern = /Say\s+\*\*["""]?(.+?)["""]?\*\*/g;
  while ((match = sayPattern.exec(content)) !== null) {
    const text = match[1].trim().replace(/^[""]|[""]$/g, '');
    if (text && !suggestions.includes(text)) {
      suggestions.push(text);
    }
  }

  if (suggestions.length === 0) {
    const genericBoldListPattern = /^-\s+\*\*[""]?(.+?)[""]?\*\*(?:\s*[-–—:]|\s*to\b|\s*\()/gm;
    while ((match = genericBoldListPattern.exec(content)) !== null) {
      const text = match[1].trim();
      if (text.length > 3 && text.length < 60 && !suggestions.includes(text)) {
        suggestions.push(text);
      }
    }
  }

  return suggestions;
}

export default function SuggestionChips({ content, onSuggestionClick, disabled = false, darkMode = false }: SuggestionChipsProps) {
  const suggestions = extractSuggestions(content);

  if (suggestions.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-2 mt-3">
      {suggestions.map((suggestion, index) => (
        <button
          key={index}
          onClick={() => !disabled && onSuggestionClick(suggestion)}
          disabled={disabled}
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-all duration-200 border cursor-pointer
            ${disabled
              ? 'opacity-50 cursor-not-allowed'
              : darkMode
                ? 'bg-gray-100 hover:bg-orange-50 text-gray-700 hover:text-orange-700 border-gray-200 hover:border-orange-400 shadow-sm hover:shadow dark:bg-gray-800 dark:hover:bg-orange-900/40 dark:text-gray-300 dark:hover:text-orange-300 dark:border-gray-700 dark:hover:border-orange-600/50 dark:shadow-none'
                : 'bg-white hover:bg-orange-50 text-gray-700 hover:text-orange-700 border-gray-200 hover:border-orange-400 shadow-sm hover:shadow dark:bg-gray-800 dark:hover:bg-orange-900/40 dark:text-gray-300 dark:hover:text-orange-300 dark:border-gray-700 dark:hover:border-orange-600/50 dark:shadow-none'
            }`}
        >
          <Zap className="w-3 h-3" />
          {suggestion}
        </button>
      ))}
    </div>
  );
}
