import { useState, useEffect } from 'react';
import {
  Plus, Edit2, Save, X, Trash2, Package, Layers, Settings,
  ChevronDown, ChevronUp, AlertCircle, CheckCircle, Search,
  Bot, Zap, Shield, Activity, ExternalLink
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { getCatalog, updateCatalog, type Agent, type AgentsCatalog as CatalogData } from '../services/api';

function getAutonomyColor(quotient: number): string {
  if (quotient >= 80) return '#10b981';
  if (quotient >= 60) return '#f59e0b';
  return '#f97316';
}

function getStatusStyle(status: string) {
  switch (status) {
    case 'active':
      return 'bg-green-500/10 text-green-400 border-green-500/20';
    case 'inactive':
      return 'bg-gray-500/10 text-gray-400 border-gray-500/20';
    case 'development':
      return 'bg-amber-500/10 text-amber-400 border-amber-500/20';
    default:
      return 'bg-gray-500/10 text-gray-400 border-gray-500/20';
  }
}

export default function AgentCatalogManager() {
  const [catalogData, setCatalogData] = useState<CatalogData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [editingAgent, setEditingAgent] = useState<Agent | null>(null);
  const [isAddingNew, setIsAddingNew] = useState(false);
  const [expandedAgents, setExpandedAgents] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState('');
  const [filterCategory, setFilterCategory] = useState('all');

  useEffect(() => {
    fetchCatalog();
  }, []);

  const fetchCatalog = async () => {
    try {
      setIsLoading(true);
      const data = await getCatalog();
      setCatalogData(data);
      setError(null);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  };

  const saveCatalog = async (updatedData: CatalogData) => {
    try {
      await updateCatalog(updatedData);
      setCatalogData(updatedData);
      setSuccessMessage('Catalog saved successfully!');
      setTimeout(() => setSuccessMessage(null), 3000);
      return true;
    } catch (err: any) {
      setError(err.message);
      return false;
    }
  };

  const handleAddAgent = () => {
    const newAgent: Agent = {
      id: `agent_${Date.now()}`,
      name: 'New Agent',
      type: 'AI Agent',
      category: 'general',
      status: 'active',
      admin_only: false,
      autonomy_quotient: 50,
      description: 'Description of the new agent',
      logo: '',
      version: '1.0.0',
      path: 'agents/New_Agent',
      capabilities: [],
      tools: [],
      llm_providers: [],
      usage: {
        entry_point: 'agent.py',
        class_name: 'NewAgent',
        api_endpoint: '/api/new-agent',
        example_prompts: []
      }
    };
    setEditingAgent(newAgent);
    setIsAddingNew(true);
  };

  const handleSaveAgent = async () => {
    if (!editingAgent || !catalogData) return;

    let updatedAgents: Agent[];
    if (isAddingNew) {
      updatedAgents = [...catalogData.agents, editingAgent];
    } else {
      updatedAgents = catalogData.agents.map(a =>
        a.id === editingAgent.id ? editingAgent : a
      );
    }

    const updatedData: CatalogData = {
      ...catalogData,
      agents: updatedAgents,
      metadata: {
        ...catalogData.metadata,
        total_agents: updatedAgents.length,
        last_updated: new Date().toISOString().split('T')[0],
      },
    };

    const success = await saveCatalog(updatedData);
    if (success) {
      setEditingAgent(null);
      setIsAddingNew(false);
    }
  };

  const handleDeleteAgent = async (agentId: string) => {
    if (!catalogData) return;
    if (!confirm('Are you sure you want to delete this agent?')) return;

    const updatedAgents = catalogData.agents.filter(a => a.id !== agentId);
    const updatedData: CatalogData = {
      ...catalogData,
      agents: updatedAgents,
      metadata: {
        ...catalogData.metadata,
        total_agents: updatedAgents.length,
        last_updated: new Date().toISOString().split('T')[0],
      },
    };

    await saveCatalog(updatedData);
  };

  const toggleExpanded = (agentId: string) => {
    const newExpanded = new Set(expandedAgents);
    if (newExpanded.has(agentId)) {
      newExpanded.delete(agentId);
    } else {
      newExpanded.add(agentId);
    }
    setExpandedAgents(newExpanded);
  };

  const filteredAgents = catalogData?.agents.filter((agent) => {
    const matchesSearch = !searchQuery ||
      agent.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      agent.description.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesCategory = filterCategory === 'all' || agent.category === filterCategory;
    return matchesSearch && matchesCategory;
  }) || [];

  const activeCount = catalogData?.agents.filter(a => a.status === 'active').length || 0;
  const avgAutonomy = catalogData?.agents.length
    ? Math.round(catalogData.agents.reduce((sum, a) => sum + (a.autonomy_quotient || 0), 0) / catalogData.agents.length)
    : 0;

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-white dark:bg-gray-950">
        <div className="text-center">
          <div className="relative w-16 h-16 mx-auto mb-4">
            <div className="absolute inset-0 rounded-full border-2 border-gray-200 dark:border-gray-800"></div>
            <div className="absolute inset-0 rounded-full border-2 border-transparent border-t-primary-500 animate-spin"></div>
          </div>
          <p className="font-body text-sm text-gray-600 dark:text-gray-400">Loading catalog...</p>
        </div>
      </div>
    );
  }

  if (error && !catalogData) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-white dark:bg-gray-950 px-4">
        <div className="max-w-md w-full bg-white dark:bg-gray-900 border border-red-500/20 rounded-2xl p-8 text-center">
          <div className="w-14 h-14 mx-auto mb-4 bg-red-500/10 rounded-xl flex items-center justify-center">
            <AlertCircle className="w-7 h-7 text-red-500 dark:text-red-400" />
          </div>
          <h3 className="font-heading text-lg font-bold text-gray-900 dark:text-white mb-2">Failed to Load Catalog</h3>
          <p className="font-body text-sm text-gray-600 dark:text-gray-400 mb-6">{error}</p>
          <button onClick={fetchCatalog} className="btn-primary py-2.5 px-6 text-sm">
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-white dark:bg-gray-950">
      <section className="relative overflow-hidden border-b border-gray-200 dark:border-gray-800/60">
        <div className="absolute inset-0">
          <div className="absolute top-0 left-1/4 w-80 h-80 bg-primary-600/8 rounded-full blur-3xl"></div>
          <div className="absolute bottom-0 right-1/3 w-64 h-64 bg-blue-600/5 rounded-full blur-3xl"></div>
        </div>

        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 lg:py-10">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-8">
            <div>
              <div className="flex items-center gap-3 mb-2">
                <div className="w-10 h-10 bg-gradient-to-br from-primary-600 to-primary-500 rounded-xl flex items-center justify-center shadow-lg shadow-primary-500/20">
                  <Package className="w-5 h-5 text-white" />
                </div>
                <h1 className="font-heading text-2xl lg:text-3xl font-bold text-gray-900 dark:text-white">
                  Agent Catalog
                </h1>
              </div>
              <p className="font-body text-sm text-gray-600 dark:text-gray-400 ml-[52px]">
                Manage, configure, and monitor your AI agent registry
              </p>
            </div>
            <button
              onClick={handleAddAgent}
              className="flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-primary-600 to-primary-500 text-white text-sm font-semibold rounded-xl hover:from-primary-500 hover:to-primary-400 transition-all shadow-lg shadow-primary-500/20 hover:shadow-primary-500/30"
            >
              <Plus className="w-4 h-4" />
              Add Agent
            </button>
          </div>

          {successMessage && (
            <div className="mb-6 bg-green-500/10 border border-green-500/20 rounded-xl p-4 flex items-center gap-3 animate-fadeIn">
              <CheckCircle className="w-5 h-5 text-green-500 dark:text-green-400 shrink-0" />
              <p className="font-body text-sm text-green-700 dark:text-green-300">{successMessage}</p>
            </div>
          )}

          {error && catalogData && (
            <div className="mb-6 bg-red-500/10 border border-red-500/20 rounded-xl p-4 flex items-center gap-3 animate-fadeIn">
              <AlertCircle className="w-5 h-5 text-red-500 dark:text-red-400 shrink-0" />
              <p className="font-body text-sm text-red-700 dark:text-red-300">{error}</p>
            </div>
          )}

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 lg:gap-4">
            <div className="bg-white dark:bg-gray-900/60 backdrop-blur border border-gray-200 dark:border-gray-800/60 rounded-xl p-4 hover:border-primary-500/30 transition-all group">
              <div className="flex items-center gap-3 mb-3">
                <div className="w-9 h-9 bg-primary-500/10 rounded-lg flex items-center justify-center group-hover:bg-primary-500/20 transition-colors">
                  <Bot className="w-4.5 h-4.5 text-primary-500 dark:text-primary-400" />
                </div>
                <span className="font-body text-xs text-gray-500 uppercase tracking-wider">Total</span>
              </div>
              <div className="font-heading text-2xl font-bold text-gray-900 dark:text-white">{catalogData?.metadata.total_agents || 0}</div>
              <div className="font-body text-xs text-gray-500 mt-0.5">Registered agents</div>
            </div>

            <div className="bg-white dark:bg-gray-900/60 backdrop-blur border border-gray-200 dark:border-gray-800/60 rounded-xl p-4 hover:border-green-500/30 transition-all group">
              <div className="flex items-center gap-3 mb-3">
                <div className="w-9 h-9 bg-green-500/10 rounded-lg flex items-center justify-center group-hover:bg-green-500/20 transition-colors">
                  <Activity className="w-4.5 h-4.5 text-green-500 dark:text-green-400" />
                </div>
                <span className="font-body text-xs text-gray-500 uppercase tracking-wider">Active</span>
              </div>
              <div className="font-heading text-2xl font-bold text-gray-900 dark:text-white">{activeCount}</div>
              <div className="font-body text-xs text-gray-500 mt-0.5">Production ready</div>
            </div>

            <div className="bg-white dark:bg-gray-900/60 backdrop-blur border border-gray-200 dark:border-gray-800/60 rounded-xl p-4 hover:border-blue-500/30 transition-all group">
              <div className="flex items-center gap-3 mb-3">
                <div className="w-9 h-9 bg-blue-500/10 rounded-lg flex items-center justify-center group-hover:bg-blue-500/20 transition-colors">
                  <Layers className="w-4.5 h-4.5 text-blue-500 dark:text-blue-400" />
                </div>
                <span className="font-body text-xs text-gray-500 uppercase tracking-wider">Categories</span>
              </div>
              <div className="font-heading text-2xl font-bold text-gray-900 dark:text-white">{catalogData?.categories.length || 0}</div>
              <div className="font-body text-xs text-gray-500 mt-0.5">Agent groups</div>
            </div>

            <div className="bg-white dark:bg-gray-900/60 backdrop-blur border border-gray-200 dark:border-gray-800/60 rounded-xl p-4 hover:border-amber-500/30 transition-all group">
              <div className="flex items-center gap-3 mb-3">
                <div className="w-9 h-9 bg-amber-500/10 rounded-lg flex items-center justify-center group-hover:bg-amber-500/20 transition-colors">
                  <Zap className="w-4.5 h-4.5 text-amber-500 dark:text-amber-400" />
                </div>
                <span className="font-body text-xs text-gray-500 uppercase tracking-wider">Avg. AQ</span>
              </div>
              <div className="font-heading text-2xl font-bold text-gray-900 dark:text-white">{avgAutonomy}%</div>
              <div className="font-body text-xs text-gray-500 mt-0.5">Autonomy quotient</div>
            </div>
          </div>
        </div>
      </section>

      <section className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 lg:py-8">
        <div className="flex flex-col sm:flex-row gap-3 mb-6">
          <div className="relative flex-1">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
            <input
              type="text"
              placeholder="Search agents by name or description..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-10 pr-4 py-2.5 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl text-sm text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 font-body focus:ring-2 focus:ring-primary-500/30 focus:border-primary-500/50 transition-all"
            />
          </div>
          <select
            value={filterCategory}
            onChange={(e) => setFilterCategory(e.target.value)}
            className="px-4 py-2.5 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl text-sm text-gray-700 dark:text-gray-300 font-body focus:ring-2 focus:ring-primary-500/30 focus:border-primary-500/50 transition-all cursor-pointer"
          >
            <option value="all">All Categories</option>
            {catalogData?.categories.map(cat => (
              <option key={cat.id} value={cat.id}>{cat.name}</option>
            ))}
          </select>
        </div>

        <div className="space-y-3">
          {filteredAgents.map((agent, index) => {
            const isExpanded = expandedAgents.has(agent.id);
            const autonomy = agent.autonomy_quotient || 0;
            const barColor = getAutonomyColor(autonomy);

            return (
              <div
                key={agent.id}
                className="bg-white dark:bg-gray-900/60 border border-gray-200 dark:border-gray-800/60 rounded-xl overflow-hidden hover:border-gray-300 dark:hover:border-gray-700/80 transition-all duration-200 animate-fadeIn"
                style={{ animationDelay: `${index * 30}ms` }}
              >
                <div className="p-4 lg:p-5">
                  <div className="flex items-start gap-4">
                    <div className="w-11 h-11 shrink-0 flex items-center justify-center bg-gray-100 dark:bg-gray-800/80 rounded-xl border border-gray-200 dark:border-gray-700/40 overflow-hidden">
                      {agent.logo && (agent.logo.startsWith('/') || agent.logo.startsWith('http')) ? (
                        <img src={agent.logo} alt={agent.name} className="w-7 h-7 object-contain" />
                      ) : (
                        <Bot className="w-5 h-5 text-gray-500 dark:text-gray-400" />
                      )}
                    </div>

                    <div className="flex-1 min-w-0">
                      <div className="flex flex-wrap items-center gap-2 mb-1.5">
                        <h3 className="font-heading text-base font-semibold text-gray-900 dark:text-white">
                          {agent.name}
                        </h3>
                        <span className={`px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider rounded-md border ${getStatusStyle(agent.status)}`}>
                          {agent.status}
                        </span>
                        {agent.admin_only && (
                          <span className="px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider rounded-md bg-purple-500/10 text-purple-600 dark:text-purple-400 border border-purple-500/20">
                            <Shield className="w-2.5 h-2.5 inline mr-0.5 -mt-px" />
                            Admin
                          </span>
                        )}
                        <span className="px-2 py-0.5 text-[10px] font-medium rounded-md bg-gray-100 dark:bg-gray-800 text-gray-500 border border-gray-200 dark:border-gray-700/40">
                          v{agent.version}
                        </span>
                      </div>

                      <p className="font-body text-sm text-gray-600 dark:text-gray-400 leading-relaxed mb-3 line-clamp-2">
                        {agent.description}
                      </p>

                      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
                        <div className="flex items-center gap-1.5">
                          <span className="font-body text-[11px] text-gray-500 uppercase tracking-wider">Type</span>
                          <span className="font-body text-xs text-gray-700 dark:text-gray-300">{agent.type}</span>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <span className="font-body text-[11px] text-gray-500 uppercase tracking-wider">Category</span>
                          <span className="font-body text-xs text-gray-700 dark:text-gray-300 capitalize">{agent.category}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="font-body text-[11px] text-gray-500 uppercase tracking-wider">AQ</span>
                          <div className="flex items-center gap-1.5">
                            <div className="w-16 h-1.5 bg-gray-200 dark:bg-gray-800 rounded-full overflow-hidden">
                              <div
                                className="h-full rounded-full transition-all duration-500"
                                style={{ width: `${autonomy}%`, backgroundColor: barColor }}
                              />
                            </div>
                            <span className="font-body text-xs font-semibold" style={{ color: barColor }}>{autonomy}%</span>
                          </div>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <Zap className="w-3 h-3 text-gray-500" />
                          <span className="font-body text-xs text-gray-600 dark:text-gray-400">{agent.capabilities.length} capabilities</span>
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-1 shrink-0">
                      <Link
                        to={`/agent/${agent.id}`}
                        className="p-2 text-gray-500 hover:text-primary-500 dark:hover:text-primary-400 hover:bg-primary-500/10 rounded-lg transition-all"
                        title="Open agent"
                      >
                        <ExternalLink className="w-4 h-4" />
                      </Link>
                      <button
                        onClick={() => toggleExpanded(agent.id)}
                        className="p-2 text-gray-500 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-all"
                        title="Toggle details"
                      >
                        {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                      </button>
                      <button
                        onClick={() => setEditingAgent(agent)}
                        className="p-2 text-gray-500 hover:text-blue-500 dark:hover:text-blue-400 hover:bg-blue-500/10 rounded-lg transition-all"
                        title="Edit agent"
                      >
                        <Edit2 className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => handleDeleteAgent(agent.id)}
                        className="p-2 text-gray-500 hover:text-red-500 dark:hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-all"
                        title="Delete agent"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                </div>

                {isExpanded && (
                  <div className="border-t border-gray-200 dark:border-gray-800/60 bg-gray-50 dark:bg-gray-900/40 p-4 lg:p-5 animate-fadeIn">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      <div>
                        <div className="flex items-center gap-2 mb-3">
                          <Zap className="w-4 h-4 text-primary-500 dark:text-primary-400" />
                          <h4 className="font-heading text-sm font-semibold text-gray-900 dark:text-white">Capabilities</h4>
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                          {agent.capabilities.map((cap, idx) => (
                            <span
                              key={idx}
                              className="px-2.5 py-1 text-[11px] font-medium bg-gray-100 dark:bg-gray-800/80 text-gray-700 dark:text-gray-300 rounded-lg border border-gray-200 dark:border-gray-700/40"
                            >
                              {cap}
                            </span>
                          ))}
                          {agent.capabilities.length === 0 && (
                            <span className="font-body text-xs text-gray-500 italic">No capabilities defined</span>
                          )}
                        </div>
                      </div>
                      <div>
                        <div className="flex items-center gap-2 mb-3">
                          <Settings className="w-4 h-4 text-blue-500 dark:text-blue-400" />
                          <h4 className="font-heading text-sm font-semibold text-gray-900 dark:text-white">Tools</h4>
                        </div>
                        <div className="space-y-2">
                          {agent.tools.map((tool, idx) => (
                            <div key={idx} className="bg-white dark:bg-gray-800/50 rounded-lg p-2.5 border border-gray-200 dark:border-gray-700/30">
                              <span className="font-body text-xs font-semibold text-gray-800 dark:text-gray-200">{tool.name}</span>
                              <p className="font-body text-[11px] text-gray-500 mt-0.5 leading-relaxed">{tool.description}</p>
                            </div>
                          ))}
                          {agent.tools.length === 0 && (
                            <span className="font-body text-xs text-gray-500 italic">No tools defined</span>
                          )}
                        </div>
                      </div>
                    </div>

                    {agent.usage && (
                      <div className="mt-5 pt-4 border-t border-gray-200 dark:border-gray-800/40">
                        <div className="flex items-center gap-2 mb-3">
                          <Settings className="w-4 h-4 text-green-500 dark:text-green-400" />
                          <h4 className="font-heading text-sm font-semibold text-gray-900 dark:text-white">Configuration</h4>
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                          <div className="bg-white dark:bg-gray-800/50 rounded-lg p-3 border border-gray-200 dark:border-gray-700/30">
                            <span className="font-body text-[10px] text-gray-500 uppercase tracking-wider">Endpoint</span>
                            <p className="font-body text-xs text-gray-800 dark:text-gray-200 mt-1 font-mono">{agent.usage.api_endpoint}</p>
                          </div>
                          <div className="bg-white dark:bg-gray-800/50 rounded-lg p-3 border border-gray-200 dark:border-gray-700/30">
                            <span className="font-body text-[10px] text-gray-500 uppercase tracking-wider">Entry Point</span>
                            <p className="font-body text-xs text-gray-800 dark:text-gray-200 mt-1 font-mono">{agent.usage.entry_point}</p>
                          </div>
                          <div className="bg-white dark:bg-gray-800/50 rounded-lg p-3 border border-gray-200 dark:border-gray-700/30">
                            <span className="font-body text-[10px] text-gray-500 uppercase tracking-wider">Class</span>
                            <p className="font-body text-xs text-gray-800 dark:text-gray-200 mt-1 font-mono">{agent.usage.class_name}</p>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}

          {filteredAgents.length === 0 && (
            <div className="text-center py-16">
              <div className="w-14 h-14 mx-auto mb-4 bg-gray-100 dark:bg-gray-800 rounded-xl flex items-center justify-center">
                <Search className="w-6 h-6 text-gray-500" />
              </div>
              <p className="font-body text-sm text-gray-600 dark:text-gray-400 mb-1">No agents found</p>
              <p className="font-body text-xs text-gray-500">Try adjusting your search or filter criteria</p>
              <button
                onClick={() => { setSearchQuery(''); setFilterCategory('all'); }}
                className="mt-4 font-body text-xs text-primary-500 dark:text-primary-400 hover:text-primary-600 dark:hover:text-primary-300 font-semibold"
              >
                Clear filters
              </button>
            </div>
          )}
        </div>
      </section>

      {editingAgent && (
        <div className="fixed inset-0 bg-gray-900/40 dark:bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4 overflow-y-auto">
          <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-2xl max-w-4xl w-full max-h-[90vh] overflow-y-auto shadow-2xl">
            <div className="sticky top-0 bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 p-5 lg:p-6 flex items-center justify-between z-10">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 bg-primary-500/10 rounded-lg flex items-center justify-center">
                  {isAddingNew ? <Plus className="w-4.5 h-4.5 text-primary-500 dark:text-primary-400" /> : <Edit2 className="w-4.5 h-4.5 text-primary-500 dark:text-primary-400" />}
                </div>
                <h2 className="font-heading text-xl font-bold text-gray-900 dark:text-white">
                  {isAddingNew ? 'Add New Agent' : 'Edit Agent'}
                </h2>
              </div>
              <button
                onClick={() => { setEditingAgent(null); setIsAddingNew(false); }}
                className="p-2 text-gray-500 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-all"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-5 lg:p-6 space-y-5">
              <div>
                <h3 className="font-heading text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3 flex items-center gap-2">
                  <Bot className="w-4 h-4 text-primary-500 dark:text-primary-400" />
                  Basic Information
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div>
                    <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">ID</label>
                    <input
                      type="text"
                      value={editingAgent.id}
                      onChange={(e) => setEditingAgent({ ...editingAgent, id: e.target.value })}
                      className="w-full px-3.5 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body placeholder-gray-400 dark:placeholder-gray-500 disabled:opacity-50"
                      disabled={!isAddingNew}
                    />
                  </div>
                  <div>
                    <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">Name</label>
                    <input
                      type="text"
                      value={editingAgent.name}
                      onChange={(e) => setEditingAgent({ ...editingAgent, name: e.target.value })}
                      className="w-full px-3.5 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body placeholder-gray-400 dark:placeholder-gray-500"
                    />
                  </div>
                  <div>
                    <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">Type</label>
                    <input
                      type="text"
                      value={editingAgent.type}
                      onChange={(e) => setEditingAgent({ ...editingAgent, type: e.target.value })}
                      className="w-full px-3.5 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body placeholder-gray-400 dark:placeholder-gray-500"
                    />
                  </div>
                  <div>
                    <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">Category</label>
                    <select
                      value={editingAgent.category}
                      onChange={(e) => setEditingAgent({ ...editingAgent, category: e.target.value })}
                      className="w-full px-3.5 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body cursor-pointer"
                    >
                      {catalogData?.categories.map(cat => (
                        <option key={cat.id} value={cat.id}>{cat.name}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">Status</label>
                    <select
                      value={editingAgent.status}
                      onChange={(e) => setEditingAgent({ ...editingAgent, status: e.target.value })}
                      className="w-full px-3.5 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body cursor-pointer"
                    >
                      <option value="active">Active</option>
                      <option value="inactive">Inactive</option>
                      <option value="development">Development</option>
                    </select>
                  </div>
                  <div>
                    <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">Autonomy Quotient</label>
                    <input
                      type="number"
                      min="0"
                      max="100"
                      value={editingAgent.autonomy_quotient}
                      onChange={(e) => setEditingAgent({ ...editingAgent, autonomy_quotient: parseInt(e.target.value) })}
                      className="w-full px-3.5 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body"
                    />
                  </div>
                  <div>
                    <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">Logo</label>
                    <input
                      type="text"
                      value={editingAgent.logo}
                      onChange={(e) => setEditingAgent({ ...editingAgent, logo: e.target.value })}
                      className="w-full px-3.5 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body placeholder-gray-400 dark:placeholder-gray-500"
                      placeholder="/images/logo.png"
                    />
                  </div>
                  <div>
                    <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">Version</label>
                    <input
                      type="text"
                      value={editingAgent.version}
                      onChange={(e) => setEditingAgent({ ...editingAgent, version: e.target.value })}
                      className="w-full px-3.5 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body placeholder-gray-400 dark:placeholder-gray-500"
                    />
                  </div>
                  <div>
                    <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">Path</label>
                    <input
                      type="text"
                      value={editingAgent.path}
                      onChange={(e) => setEditingAgent({ ...editingAgent, path: e.target.value })}
                      className="w-full px-3.5 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body placeholder-gray-400 dark:placeholder-gray-500"
                    />
                  </div>
                  <div className="flex items-end pb-1">
                    <label className="flex items-center gap-2.5 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={editingAgent.admin_only}
                        onChange={(e) => setEditingAgent({ ...editingAgent, admin_only: e.target.checked })}
                        className="w-4 h-4 rounded border-gray-300 dark:border-gray-600 bg-gray-100 dark:bg-gray-800 text-primary-500 focus:ring-primary-500/30"
                      />
                      <span className="font-body text-sm text-gray-700 dark:text-gray-300">Admin Only</span>
                    </label>
                  </div>
                </div>
              </div>

              <div>
                <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">Description</label>
                <textarea
                  value={editingAgent.description}
                  onChange={(e) => setEditingAgent({ ...editingAgent, description: e.target.value })}
                  rows={3}
                  className="w-full px-3.5 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body placeholder-gray-400 dark:placeholder-gray-500 resize-none"
                />
              </div>

              <div>
                <label className="block font-body text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">Capabilities (comma-separated)</label>
                <textarea
                  value={editingAgent.capabilities.join(', ')}
                  onChange={(e) => setEditingAgent({
                    ...editingAgent,
                    capabilities: e.target.value.split(',').map(s => s.trim()).filter(s => s)
                  })}
                  rows={3}
                  className="w-full px-3.5 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-900 dark:text-white font-body placeholder-gray-400 dark:placeholder-gray-500 resize-none"
                />
              </div>
            </div>

            <div className="sticky bottom-0 bg-white dark:bg-gray-900 border-t border-gray-200 dark:border-gray-800 p-5 lg:p-6 flex justify-end gap-3">
              <button
                onClick={() => { setEditingAgent(null); setIsAddingNew(false); }}
                className="px-5 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300 text-sm font-medium rounded-xl hover:bg-gray-200 dark:hover:bg-gray-700 transition-all"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveAgent}
                className="flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-primary-600 to-primary-500 text-white text-sm font-semibold rounded-xl hover:from-primary-500 hover:to-primary-400 transition-all shadow-lg shadow-primary-500/20"
              >
                <Save className="w-4 h-4" />
                Save Agent
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
