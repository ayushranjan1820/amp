"""Prompt management for JIRA agent."""
import os
import yaml
from typing import Dict, Any
from pathlib import Path


class PromptLoader:
    """Load and manage prompts from YAML files."""
    
    def __init__(self):
        self.prompts_dir = Path(__file__).parent
        self._cache: Dict[str, Dict[str, Any]] = {}
    
    def load_prompts(self, filename: str) -> Dict[str, Any]:
        """Load prompts from a YAML file.
        
        Args:
            filename: Name of the YAML file (without path)
            
        Returns:
            Dictionary containing all prompts from the file
        """
        if filename in self._cache:
            return self._cache[filename]
        
        file_path = self.prompts_dir / filename
        
        if not file_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {file_path}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            prompts = yaml.safe_load(f)
        
        self._cache[filename] = prompts
        return prompts
    
    def get_prompt(self, filename: str, key: str) -> str:
        """Get a specific prompt by key.
        
        Args:
            filename: Name of the YAML file
            key: Key of the prompt to retrieve
            
        Returns:
            Prompt template string
        """
        prompts = self.load_prompts(filename)
        
        if key not in prompts:
            raise KeyError(f"Prompt key '{key}' not found in {filename}")
        
        return prompts[key]


# Global instance
prompt_loader = PromptLoader()
