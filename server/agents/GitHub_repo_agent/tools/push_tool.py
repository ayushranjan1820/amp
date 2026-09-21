"""Git push tool for committing changes to GitHub"""

import re
import subprocess
from datetime import datetime
from typing import Dict, Any


def push_to_github(repo_path: str, token: str, commit_message: str, repo_url: str) -> Dict[str, Any]:
    """
    Push changes to GitHub by creating a new branch and pushing commits.
    
    Args:
        repo_path: Local path to the repository
        token: GitHub personal access token
        commit_message: Commit message for the changes
        repo_url: GitHub repository URL
        
    Returns:
        Dictionary with success status, branch name, and PR URL or error message
    """
    try:
        # Parse repository URL
        parts = repo_url.rstrip('/').split('/')
        owner = parts[-2]
        repo_name = parts[-1].replace('.git', '')
        auth_url = f"https://{token}@github.com/{owner}/{repo_name}.git"

        # Configure git user
        config_cmds = [
            ["git", "config", "user.email", "ai-agent@users.noreply.github.com"],
            ["git", "config", "user.name", "AI Agent"],
        ]
        for cmd in config_cmds:
            subprocess.run(cmd, capture_output=True, text=True, cwd=repo_path, timeout=10)

        # Create unique branch name
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = commit_message[:40].lower().strip()
        slug = re.sub(r'[^a-z0-9]+', '-', slug).strip('-')
        branch_name = f"ai-agent/{slug}-{timestamp}"

        # Create and checkout new branch
        r = subprocess.run(
            ["git", "checkout", "-b", branch_name],
            capture_output=True, text=True, cwd=repo_path, timeout=10
        )
        if r.returncode != 0:
            error_msg = r.stderr.replace(token, "***")
            return {
                "success": False, 
                "error": f"Failed to create branch: {error_msg}"
            }

        # Add, commit, and push changes
        cmds = [
            ["git", "add", "-A"],
            ["git", "commit", "-m", commit_message],
            ["git", "push", auth_url, branch_name],
        ]

        for cmd in cmds:
            r = subprocess.run(cmd, capture_output=True, text=True, cwd=repo_path, timeout=60)
            if r.returncode != 0 and "nothing to commit" not in r.stdout + r.stderr:
                error_msg = r.stderr.replace(token, "***")
                return {
                    "success": False, 
                    "error": f"Git command failed: {error_msg}"
                }

        # Generate PR URL
        pr_url = f"https://github.com/{owner}/{repo_name}/compare/{branch_name}?expand=1"
        
        return {
            "success": True,
            "message": f"Successfully pushed changes to {repo_url}",
            "branch_name": branch_name,
            "pr_url": pr_url,
        }
        
    except Exception as e:
        error_msg = str(e).replace(token, "***")
        return {
            "success": False, 
            "error": error_msg
        }
