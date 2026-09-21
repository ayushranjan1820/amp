"""
Catalog Configuration Module for Router Agent
Handles loading and querying the agents catalog.
"""

import json
from pathlib import Path
from typing import Dict, Optional, List, Set


class CatalogLoader:
    """Loads and provides access to the agents catalog."""
    
    def __init__(self):
        self.catalog = self._load_catalog()
    
    def _load_catalog(self) -> Dict:
        """Load agents catalog from JSON file."""
        catalog_path = Path(__file__).parent.parent.parent.parent / "agents_catalog.json"
        with open(catalog_path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    def get_agent_info(self, agent_id: str) -> Optional[Dict]:
        """Get information about a specific agent by ID."""
        for agent in self.catalog.get("agents", []):
            if agent["id"] == agent_id:
                return agent
        return None
    
    def get_all_agents(self) -> List[Dict]:
        """Get list of all agents in the catalog."""
        return self.catalog.get("agents", [])
    
    def _agents_filtered(self, allowed_ids: Optional[Set[str]]) -> List[Dict]:
        agents = self.catalog.get("agents", [])
        if not allowed_ids:
            return agents
        return [a for a in agents if a.get("id") in allowed_ids]
    
    def get_agent_summaries(self, allowed_ids: Optional[Set[str]] = None) -> str:
        """Generate formatted summary of all agents for LLM prompts."""
        lines = []
        for agent in self._agents_filtered(allowed_ids):
            agent_id = agent["id"]
            name = agent["name"]
            desc = agent["description"]
            caps = ", ".join(agent.get("capabilities", []))
            endpoint = agent.get("usage", {}).get("api_endpoint", "")
            examples = agent.get("usage", {}).get("example_prompts", [])
            lines.append(
                f"- ID: {agent_id}\n"
                f"  Name: {name}\n"
                f"  Description: {desc}\n"
                f"  Capabilities: {caps}\n"
                f"  Endpoint: {endpoint}\n"
                f"  Example queries: {json.dumps(examples[:3])}"
            )
        return "\n\n".join(lines)
    
    def get_routing_guidelines(self, allowed_ids: Optional[Set[str]] = None) -> str:
        """Generate routing guidelines from catalog for LLM prompts."""
        lines = []
        for agent in self._agents_filtered(allowed_ids):
            agent_id = agent["id"]
            name = agent["name"]
            routing = agent.get("routing", {})
            keywords = routing.get("keywords", [])
            
            # Build concise guidance from keywords and description
            if keywords:
                # Take the most relevant keywords (first 5-7)
                key_terms = ", ".join(keywords[:7])
                lines.append(f"- {name} ({agent_id}): {key_terms}")
            else:
                # Fallback to short description
                desc = agent.get("description", "")[:80]
                lines.append(f"- {name} ({agent_id}): {desc}")
        
        return "\n".join(lines)
    
    def get_valid_agent_ids(self) -> List[str]:
        """Get list of all valid agent IDs."""
        return [agent["id"] for agent in self.catalog.get("agents", [])]
