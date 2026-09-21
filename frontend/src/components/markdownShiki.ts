import type { BundledLanguage, Highlighter } from 'shiki/bundle/web';

const THEMES = ['github-light-default', 'github-dark-default'] as const;

/** Languages commonly seen in chat fences; must exist in `shiki/bundle/web`. */
const PRELOAD_LANGS = [
  'python',
  'javascript',
  'typescript',
  'tsx',
  'jsx',
  'json',
  'jsonc',
  'json5',
  'yaml',
  'shellscript',
  'sql',
  'html',
  'css',
  'markdown',
  'xml',
  'java',
  'php',
  'graphql',
  'scss',
  'sass',
  'less',
  'vue',
  'svelte',
  'astro',
  'mdx',
  'csv',
  'wasm',
  'r',
  'cpp',
  'c',
] as const satisfies readonly BundledLanguage[];

const ALIAS: Record<string, BundledLanguage> = {
  py: 'python',
  sh: 'shellscript',
  bash: 'shellscript',
  shell: 'shellscript',
  zsh: 'shellscript',
  yml: 'yaml',
  md: 'markdown',
  js: 'javascript',
  ts: 'typescript',
  postgresql: 'sql',
  postgres: 'sql',
  mysql: 'sql',
  mariadb: 'sql',
  sqlite: 'sql',
  tsql: 'sql',
  mssql: 'sql',
  sqlserver: 'sql',
  transactsql: 'sql',
  plsql: 'sql',
  bigquery: 'sql',
  snowflake: 'sql',
};

let highlighterPromise: Promise<Highlighter> | null = null;

export function getMarkdownHighlighter() {
  if (!highlighterPromise) {
    highlighterPromise = import('shiki/bundle/web').then((m) =>
      m.getSingletonHighlighter({
        themes: [...THEMES],
        langs: [...PRELOAD_LANGS],
      }),
    );
  }
  return highlighterPromise;
}

export function mapFenceToShikiLang(fence: string): BundledLanguage {
  const k = fence.trim().toLowerCase();
  if (!k) return 'markdown';
  if (ALIAS[k]) return ALIAS[k];
  if ((PRELOAD_LANGS as readonly string[]).includes(k)) return k as BundledLanguage;
  return 'markdown';
}

export function markdownShikiTheme(isDark: boolean): (typeof THEMES)[number] {
  return isDark ? 'github-dark-default' : 'github-light-default';
}
