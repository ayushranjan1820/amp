const STORAGE_PREFIX = 'agent_config_files_';

export interface StoredAgentFile {
  file_name: string;
  file_type: string;
  file_content: string;
  size?: number;
  uploaded_at?: string;
}

export const AGENTS_WITH_FILE_CONFIG: Record<string, { label: string; description: string; accept: string; maxCount: number }> = {
  company_solution_advisor: {
    label: 'Existing AI solutions catalog',
    description:
      'Optional: upload a PDF / Word / text file listing your existing AI solutions. The agent will prefer matches from this catalog before suggesting new ones.',
    accept: '.pdf,.docx,.doc,.txt,.md,.html,.htm',
    maxCount: 5,
  },
};

export function supportsFileConfig(agentId: string): boolean {
  return Object.prototype.hasOwnProperty.call(AGENTS_WITH_FILE_CONFIG, agentId);
}

export function loadAgentFiles(agentId: string): StoredAgentFile[] {
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + agentId);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function saveAgentFiles(agentId: string, files: StoredAgentFile[]): void {
  try {
    if (!files.length) {
      localStorage.removeItem(STORAGE_PREFIX + agentId);
      return;
    }
    localStorage.setItem(STORAGE_PREFIX + agentId, JSON.stringify(files));
  } catch (e) {
    console.warn('[agentConfigFiles] save failed', e);
  }
}

export function clearAgentFiles(agentId: string): void {
  localStorage.removeItem(STORAGE_PREFIX + agentId);
}

/** Normalize extension sent to agents (MIME first — many spreadsheets arrive without ".xlsx" in the filename). */
const MIME_TO_EXTENSION: Record<string, string> = {
  'application/pdf': 'pdf',
  'application/msword': 'doc',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
  'text/plain': 'txt',
  'text/markdown': 'md',
  'text/html': 'html',
  'text/csv': 'csv',
  'application/csv': 'csv',
  'application/vnd.ms-excel': 'xls',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
  'application/vnd.ms-excel.sheet.macroenabled.12': 'xlsm',
  'application/vnd.ms-excel.sheet.binary.macroenabled.12': 'xlsb',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.template': 'xltx',
  'application/vnd.ms-excel.template.macroenabled.12': 'xltm',
  'application/vnd.oasis.opendocument.spreadsheet': 'ods',
  'application/vnd.ms-powerpoint': 'ppt',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'pptx',
  'application/json': 'json',
  'application/xml': 'xml',
  'text/xml': 'xml',
  'image/png': 'png',
  'image/jpeg': 'jpg',
  'image/webp': 'webp',
};

export function inferUploadedFileExtension(file: File): string {
  const raw = (file.type || '').trim().toLowerCase();
  const mime = raw.split(';')[0].trim();
  if (mime && MIME_TO_EXTENSION[mime]) {
    return MIME_TO_EXTENSION[mime];
  }
  const name = file.name.trim();
  const dot = name.lastIndexOf('.');
  if (dot >= 0 && dot < name.length - 1) {
    const fromName = name.slice(dot + 1).toLowerCase();
    if (/^[a-z0-9]{1,12}$/.test(fromName)) {
      return fromName;
    }
  }
  return 'bin';
}

export async function fileToStored(file: File): Promise<StoredAgentFile> {
  const base64 = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      const comma = result.indexOf(',');
      resolve(comma >= 0 ? result.slice(comma + 1) : result);
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
  const ext = inferUploadedFileExtension(file);
  return {
    file_name: file.name,
    file_type: ext,
    file_content: base64,
    size: file.size,
    uploaded_at: new Date().toISOString(),
  };
}

/** Build the agent-extra-kwargs map for the workflow execute request. */
export function buildAgentExtraKwargsForAgents(
  agentIds: string[],
): Record<string, Record<string, unknown>> {
  const out: Record<string, Record<string, unknown>> = {};
  for (const id of agentIds) {
    if (id !== 'company_solution_advisor') continue;
    const files = loadAgentFiles(id);
    if (!files.length) continue;
    out[id] = {
      uploaded_files: files.map((f) => ({
        file_content: f.file_content,
        file_type: f.file_type,
        file_name: f.file_name,
      })),
    };
  }
  return out;
}
