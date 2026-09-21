"""Repository cloning tool"""

import subprocess
import shutil
from pathlib import Path
from typing import Dict, Any


def clone_repo(repo_url: str, repos_dir: Path, session_id: str) -> Dict[str, Any]:
    """
    Clone a GitHub repository.
    
    Args:
        repo_url: GitHub repository URL
        repos_dir: Base directory for storing repositories
        session_id: Session identifier for organizing repos
        
    Returns:
        Dictionary with success status and repository details or error message
    """
    parts = repo_url.rstrip('/').split('/')
    owner = parts[-2]
    repo_name = parts[-1].replace('.git', '')
    repo_dir = repos_dir / session_id / f"{owner}_{repo_name}"

    # Remove existing directory if present
    if repo_dir.exists():
        shutil.rmtree(repo_dir)

    repo_dir.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Try cloning with .git extension
        result = subprocess.run(
            ["git", "clone", "--depth", "50", repo_url + ".git", str(repo_dir)],
            capture_output=True, text=True, timeout=120
        )
        
        # If failed, try without .git extension
        if result.returncode != 0:
            result = subprocess.run(
                ["git", "clone", "--depth", "50", repo_url, str(repo_dir)],
                capture_output=True, text=True, timeout=120
            )
        
        if result.returncode != 0:
            return {
                "success": False, 
                "error": f"Failed to clone: {result.stderr.strip()}"
            }

        return {
            "success": True,
            "path": str(repo_dir),
            "name": repo_name,
            "owner": owner,
        }
        
    except subprocess.TimeoutExpired:
        return {
            "success": False, 
            "error": "Clone timed out (>120s). Repository may be too large."
        }
    except Exception as e:
        return {
            "success": False, 
            "error": str(e)
        }
