import React from 'react';
import {
  Pinecone, Qdrant, Chroma, Weaviate,
  Aws, AzureBadge, Googlecloud,
  Openai, Gemini, Cohere, AzureAzureOpenai, Mistral,
  Tavily, Duckduckgo
} from '@thesvg/react';

// ============================================================================
// Types & Interfaces
// ============================================================================

export interface HeaderRow {
  id: string;
  key: string;
  value: string;
}

export interface ParamRow {
  id: string;
  name: string;
  description: string;
  location: 'query' | 'path' | 'body';
  data_type: 'string' | 'integer' | 'decimal' | 'boolean';
  required: boolean;
}

export interface DiscoveredMcpTool {
  tool_name: string;
  tool_description: string;
}

export type EmbeddingProviderType = 'openai' | 'google' | 'cohere' | 'azure_openai' | 'mistral';
export type VectorDbProviderType = 'pinecone' | 'qdrant' | 'chroma' | 'weaviate';
export type CloudProviderType = 'aws' | 'azure' | 'gcp';
export type PreconfiguredProviderType = 'tavily_search' | 'duckduckgo_search';
export type ToolToggleType = 'PRECONFIGURED' | 'API' | 'MCP' | 'RAG';

export interface VectorDbProviderOption {
  id: VectorDbProviderType;
  label: string;
  renderIcon: () => React.ReactNode;
}

export interface CloudProviderOption {
  id: CloudProviderType;
  label: string;
  renderIcon: () => React.ReactNode;
}

export interface EmbeddingModelProviderOption {
  id: EmbeddingProviderType;
  label: string;
  renderIcon: () => React.ReactNode;
  defaultModel: string;
  defaultDimension: number;
}

export interface PreconfiguredToolOption {
  id: PreconfiguredProviderType;
  label: string;
  renderIcon: () => React.ReactNode;
}

export interface SelectOption<T = string> {
  value: T;
  label: string;
}

// ============================================================================
// Provider & Tool Option Lists
// ============================================================================

export const VECTOR_DB_PROVIDERS: VectorDbProviderOption[] = [
  {
    id: 'pinecone',
    label: 'Pinecone',
    renderIcon: () => <Pinecone variant="mono" className="h-6 w-6" />,
  },
  {
    id: 'qdrant',
    label: 'Qdrant',
    renderIcon: () => <Qdrant className="h-6 w-6" />,
  },
  {
    id: 'chroma',
    label: 'Chroma',
    renderIcon: () => <Chroma className="h-6 w-6" />,
  },
  {
    id: 'weaviate',
    label: 'Weaviate',
    renderIcon: () => <Weaviate className="h-6 w-6" />,
  },
];

export const CLOUD_PROVIDERS: CloudProviderOption[] = [
  {
    id: 'aws',
    label: 'AWS',
    renderIcon: () => <Aws className="h-6 w-6" />,
  },
  {
    id: 'azure',
    label: 'Azure',
    renderIcon: () => <AzureBadge className="h-6 w-6" />,
  },
  {
    id: 'gcp',
    label: 'GCP',
    renderIcon: () => <Googlecloud className="h-6 w-6" />,
  },
];

export const EMBEDDING_MODEL_PROVIDERS: EmbeddingModelProviderOption[] = [
  {
    id: 'openai',
    label: 'OpenAI',
    renderIcon: () => <Openai variant="light" className="h-6 w-6" />,
    defaultModel: 'text-embedding-3-small',
    defaultDimension: 1536,
  },
  {
    id: 'google',
    label: 'Google',
    renderIcon: () => <Gemini className="h-6 w-6" />,
    defaultModel: 'models/text-embedding-004',
    defaultDimension: 768,
  },
  {
    id: 'cohere',
    label: 'Cohere',
    renderIcon: () => <Cohere className="h-6 w-6" />,
    defaultModel: 'embed-english-v3.0',
    defaultDimension: 1024,
  },
  {
    id: 'azure_openai',
    label: 'Azure OpenAI',
    renderIcon: () => <AzureAzureOpenai className="h-6 w-6" />,
    defaultModel: 'text-embedding-3-small',
    defaultDimension: 1536,
  },
  {
    id: 'mistral',
    label: 'Mistral',
    renderIcon: () => <Mistral className="h-6 w-6" />,
    defaultModel: 'mistral-embed',
    defaultDimension: 1024,
  },
];

export const PRECONFIGURED_TOOLS: PreconfiguredToolOption[] = [
  {
    id: 'tavily_search',
    label: 'Tavily Search',
    renderIcon: () => <Tavily className="h-6 w-6" />,
  },
  {
    id: 'duckduckgo_search',
    label: 'DuckDuckGo Search',
    renderIcon: () => <Duckduckgo className="h-6 w-6" />,
  },
];

// ============================================================================
// Advanced RAG Select Dropdown Options
// ============================================================================

export const RETRIEVAL_STRATEGIES: SelectOption<'similarity' | 'mmr' | 'hybrid'>[] = [
  { value: 'similarity', label: 'Similarity' },
  { value: 'mmr', label: 'MMR' },
  { value: 'hybrid', label: 'Hybrid' },
];

export const DISTANCE_STRATEGIES: SelectOption<'dotproduct' | 'cosine' | 'euclidean' | 'manhattan'>[] = [
  { value: 'dotproduct', label: 'Dot Product' },
  { value: 'cosine', label: 'Cosine' },
  { value: 'euclidean', label: 'Euclidean' },
  { value: 'manhattan', label: 'Manhattan' },
];

export const VECTOR_TYPES: SelectOption<'dense' | 'sparse'>[] = [
  { value: 'dense', label: 'Dense' },
  { value: 'sparse', label: 'Sparse' },
];

export const RERANK_PROVIDERS: SelectOption<'cohere' | 'gemini' | 'openai'>[] = [
  { value: 'cohere', label: 'Cohere' },
  { value: 'gemini', label: 'Gemini' },
  { value: 'openai', label: 'OpenAI' },
];

// ============================================================================
// MCP Placeholder Templates
// ============================================================================

export const MCP_PLACEHOLDER_TEXT = `{\n  "mcpServers": {\n    "filesystem": {\n      "command": "npx",\n      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"]\n    }\n  }\n}`;
export const mcpPlaceholderText = MCP_PLACEHOLDER_TEXT;

// ============================================================================
// Initial States for Tool Forms
// ============================================================================

export const INITIAL_API_TOOL_STATE = {
  name: '',
  description: '',
  method: 'GET' as 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH',
  url: '',
};

export const INITIAL_MCP_TOOL_STATE = {
  name: '',
  description: '',
};

export const INITIAL_PRECONFIGURED_TOOL_STATE = {
  name: 'Tavily Search',
  description: 'Search the internet using Tavily.',
  apiKey: '',
  maxResults: 5,
};

export const INITIAL_RAG_TOOL_STATE = {
  name: '',
  description: '',
  selectedFile: null as File | null,
  // Embedding Model Config
  embeddingProvider: 'openai' as EmbeddingProviderType,
  embeddingModel: 'text-embedding-3-small',
  embeddingApiKey: '',
  // Vector DB Config
  vectorDbProvider: 'pinecone' as VectorDbProviderType,
  vectorDbUrl: '',
  vectorDbApiKey: '',
  collectionName: '',
  namespace: '',
  vectorDbTenant: '',
  vectorDimension: 1536,
  topK: 15,
  cloudProvider: 'aws' as 'aws' | 'azure' | 'gcp' | '',
  region: 'us-east-1',
  // Advanced Config
  retrievalStrategy: 'similarity' as 'similarity' | 'mmr' | 'hybrid',
  chunkingStrategy: 'recursive' as 'recursive' | 'token' | 'hierarchial' | 'semantic',
  chunkSize: 1000,
  chunkOverlap: 200,
  distanceStrategy: 'dotproduct' as 'dotproduct' | 'cosine' | 'euclidean' | 'manhattan',
  vectorType: 'dense' as 'dense' | 'sparse',
  rerankEnabled: false,
  rerankProvider: 'cohere' as 'cohere' | 'gemini' | 'openai',
  rerankModel: 'rerank-english-v3.0',
  rerankTopK: 5,
};
