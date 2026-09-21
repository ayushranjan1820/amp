"""JSON export tool for the Langchain agent."""

import json
from datetime import datetime
from pathlib import Path
from langchain_core.tools import tool


@tool
def save_to_json(data: dict, filename: str = "output.json") -> str:
    """Save data to a JSON file.
    
    Args:
        data: Dictionary containing the data to save
        filename: Name of the JSON file to create
        
    Returns:
        Success message with file path
    """
    try:
        output_dir = Path("./outputs")
        output_dir.mkdir(exist_ok=True)
        
        filepath = output_dir / filename
        
        # Add metadata
        data_with_metadata = {
            "timestamp": datetime.now().isoformat(),
            "data": data
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data_with_metadata, f, indent=2, ensure_ascii=False)
        
        return f"Data successfully saved to {filepath}"
    except Exception as e:
        return f"Error saving to JSON: {str(e)}"
