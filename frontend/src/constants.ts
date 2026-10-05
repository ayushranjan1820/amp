// Base API Configuration
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

// API Endpoints Registry
export const API_ENDPOINTS = {
  AUTH: {
    LOGIN: '/api/v1/users/login',
    REGISTER: '/api/v1/users/register',
  },
  AGENTS: {
    FETCH: '/api/v1/agents/fetch',
    CREATE_OR_UPDATE: '/api/v1/agents/',
    ADD_TOOLS: (agentId: string) => `/api/v1/agents/tools/${agentId}`,
    TOOLS_FROM_MCP: '/api/v1/agents/tools-from-mcp',
  },
} as const;
