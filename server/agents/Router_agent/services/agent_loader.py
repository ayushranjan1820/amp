"""
Agent Loader Service Module for Router Agent
Handles dynamic loading and caching of agent instances.
"""

from typing import Dict, Any, Optional
from ..config.catalog_loader import CatalogLoader


class AgentLoader:
    """Dynamically loads and caches agent instances based on catalog configuration."""
    
    def __init__(self, catalog_loader: CatalogLoader):
        self.catalog_loader = catalog_loader
        self._agents_cache: Dict[str, Any] = {}
    
    def get_agent_instance(self, agent_id: str):
        """Dynamically load agent instance based on catalog configuration."""
        if agent_id in self._agents_cache:
            return self._agents_cache[agent_id]

        agent_info = self.catalog_loader.get_agent_info(agent_id)
        if not agent_info:
            print(f"⚠️ Agent {agent_id} not found in catalog")
            return None

        import_config = agent_info.get("import_config")
        if not import_config:
            print(f"⚠️ No import configuration for agent {agent_id}")
            return None

        instance = None
        try:
            import importlib
            module_path = import_config["module"]
            import_type = import_config["type"]
            
            module = importlib.import_module(module_path)
            
            if import_type == "instance":
                # Import a pre-instantiated object
                instance_name = import_config["instance_name"]
                instance = getattr(module, instance_name)
            elif import_type == "class":
                # Import and instantiate a class
                class_name = import_config["class_name"]
                agent_class = getattr(module, class_name)
                instance = agent_class()
            elif import_type == "function":
                # Import a function/callable
                instance_name = import_config["instance_name"]
                instance = getattr(module, instance_name)
            else:
                print(f"⚠️ Unknown import type '{import_type}' for agent {agent_id}")
                return None
                
        except Exception as e:
            print(f"⚠️ Could not load agent {agent_id}: {e}")
            return None

        if instance:
            self._agents_cache[agent_id] = instance
        return instance
