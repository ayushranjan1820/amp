export interface AgentModelConfig {
  model_name?: string;
  provider?: string;
  temperature?: number;
  max_tokens?: number;
  [key: string]: unknown;
}

export interface AgentItem {
  id?: string;
  _id?: string;
  name: string;
  description: string;
  system_prompt?: string;
  tools?: string[];
  model?: AgentModelConfig | string;
  capabilities?: string[];
  enabled?: boolean;
  version?: string;
  visibility?: string;
  status?: string;
  created_by?: string;
  created_at?: string;
  updated_at?: string;
}
