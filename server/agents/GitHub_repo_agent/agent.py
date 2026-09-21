"""GitHub Repository Agent - Main orchestration module"""

import os
from pathlib import Path
from typing import Dict, Any, Optional
from .ai_service import ai_service
from .utils import (
    get_file_tree,
    extract_repo_url,
    detect_intent,
    extract_user_query
)
from .tools import (
    clone_repo,
    push_to_github,
    analyze_tech_stack,
    extract_features,
    generate_documentation,
    analyze_general_query,
    generate_architecture,
    modify_code
)

# Repository storage configuration
REPOS_DIR = Path(__file__).parent.parent.parent.parent / "repos"
REPOS_DIR.mkdir(exist_ok=True)


class GitHubRepoAgent:
    """
    Main agent class for GitHub repository operations and analysis.
    Orchestrates various tools and utilities to provide comprehensive repository insights.
    """
    
    def __init__(self):
        self.sessions: Dict[str, Dict[str, Any]] = {}
        print("🐙 GitHub Repository Agent initialized")

    def _get_session(self, session_id: str) -> Dict[str, Any]:
        """Get or create a session for the given session ID."""
        if session_id not in self.sessions:
            self.sessions[session_id] = {
                "repo_url": None,
                "repo_path": None,
                "repo_name": None,
                "cloned": False,
                "analysis_cache": {},
            }
        return self.sessions[session_id]

    def _handle_clone_intent(self, query: str, session_id: str, thinking_steps: list) -> Dict[str, Any]:
        """Handle repository cloning requests."""
        repo_url = extract_repo_url(query)
        if not repo_url:
            return {
                "success": False,
                "response": "I couldn't find a valid GitHub URL in your message. Please provide a URL like `https://github.com/owner/repo`.",
                "thinking_steps": thinking_steps,
            }

        thinking_steps.append({
            "type": "tool_call",
            "content": f"Cloning repository: {repo_url}",
            "tool_name": "clone_repo"
        })
        
        result = clone_repo(repo_url, REPOS_DIR, session_id)

        if not result["success"]:
            return {
                "success": False,
                "response": f"Failed to clone the repository: {result['error']}",
                "thinking_steps": thinking_steps,
            }

        # Update session
        session = self._get_session(session_id)
        session["repo_url"] = repo_url
        session["repo_path"] = result["path"]
        session["repo_name"] = result["name"]
        session["cloned"] = True
        session["analysis_cache"] = {}

        tree = get_file_tree(result["path"])
        thinking_steps.append({"type": "tool_result", "content": "Repository cloned successfully"})

        return {
            "success": True,
            "response": f"Successfully cloned **{result['owner']}/{result['name']}**!\n\n**Repository Structure:**\n```\n{tree}\n```\n\nYou can now ask me to:\n- 📝 **Generate technical documentation** (reverse engineering)\n- 🛠️ **Extract the tech stack**\n- 🏗️ **Generate architecture/flow diagrams**\n- ✨ **Extract features**\n- ✏️ **Make code changes**\n- 🚀 **Push changes** (requires GitHub token)",
            "thinking_steps": thinking_steps,
            "repo_url": repo_url,
        }

    def _handle_push_intent(
        self, 
        query: str, 
        session: Dict[str, Any], 
        github_token: Optional[str],
        thinking_steps: list
    ) -> Dict[str, Any]:
        """Handle push to GitHub requests."""
        if not github_token:
            return {
                "success": True,
                "response": "To push changes to GitHub, I need your **GitHub Personal Access Token**.\n\nPlease provide your token with `repo` scope permissions. You can create one at [GitHub Settings > Tokens](https://github.com/settings/tokens).\n\n⚠️ Your token is used only for this push operation and is **not stored**.",
                "thinking_steps": thinking_steps,
                "requires_token": True,
            }

        # Generate commit message
        commit_msg_query = f"Based on this user request, generate a concise git commit message (one line, max 72 chars): {query}"
        try:
            commit_msg = ai_service.call_genai(commit_msg_query, temperature=0.2, max_tokens=100).strip().strip('"\'')
        except Exception:
            commit_msg = "Update code via AI agent"

        thinking_steps.append({
            "type": "tool_call",
            "content": f"Pushing to GitHub with commit: {commit_msg}",
            "tool_name": "push_to_github"
        })
        
        push_result = push_to_github(session["repo_path"], github_token, commit_msg, session["repo_url"])

        if push_result["success"]:
            branch_name = push_result.get("branch_name", "unknown")
            pr_url = push_result.get("pr_url", "")
            thinking_steps.append({"type": "tool_result", "content": f"Push successful to branch: {branch_name}"})
            
            response_msg = (
                f"Successfully pushed changes to **{session['repo_url']}**!\n\n"
                f"**Branch:** `{branch_name}`\n"
                f"**Commit message:** `{commit_msg}`\n\n"
                f"[**Create a Pull Request**]({pr_url})"
            )
            return {
                "success": True,
                "response": response_msg,
                "thinking_steps": thinking_steps,
            }
        else:
            return {
                "success": False,
                "response": f"Failed to push: {push_result['error']}",
                "thinking_steps": thinking_steps,
            }

    def process_query(
        self, 
        query: str, 
        session_id: str = "default", 
        github_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process a user query about a GitHub repository.
        
        Args:
            query: User's query or command
            session_id: Session identifier for maintaining context
            github_token: Optional GitHub personal access token for push operations
            
        Returns:
            Dictionary containing success status, response, and thinking steps
        """
        thinking_steps = []
        session = self._get_session(session_id)
        raw_query = extract_user_query(query)
        intent = detect_intent(raw_query)

        # Adjust intent detection if repo already cloned
        if session.get("cloned") and intent == 'clone' and not extract_repo_url(raw_query):
            intent = detect_intent(raw_query.replace('github.com', '').replace('github', ''))
            if intent == 'clone':
                intent = 'general'

        thinking_steps.append({"type": "thinking", "content": f"Detected intent: {intent}"})

        # Handle clone intent
        if intent == 'clone':
            return self._handle_clone_intent(query, session_id, thinking_steps)

        # Auto-clone if URL detected and no repo loaded
        if not session.get("cloned"):
            repo_url = extract_repo_url(raw_query)
            if repo_url:
                thinking_steps.append({
                    "type": "tool_call",
                    "content": f"Cloning repository first: {repo_url}",
                    "tool_name": "clone_repo"
                })
                result = clone_repo(repo_url, REPOS_DIR, session_id)
                if result["success"]:
                    session["repo_url"] = repo_url
                    session["repo_path"] = result["path"]
                    session["repo_name"] = result["name"]
                    session["cloned"] = True
                    session["analysis_cache"] = {}
                    thinking_steps.append({"type": "tool_result", "content": "Repository cloned successfully"})
                else:
                    return {
                        "success": False,
                        "response": f"Failed to clone: {result['error']}",
                        "thinking_steps": thinking_steps
                    }
            else:
                return {
                    "success": False,
                    "response": "No repository is loaded yet. Please provide a GitHub URL first, like:\n\n`Clone https://github.com/owner/repo`",
                    "thinking_steps": thinking_steps,
                }

        repo_path = session["repo_path"]
        repo_name = session["repo_name"]

        # Handle push intent
        if intent == 'push':
            return self._handle_push_intent(query, session, github_token, thinking_steps)

        # Handle tech stack analysis
        if intent == 'tech_stack':
            thinking_steps.append({
                "type": "tool_call",
                "content": "Analyzing tech stack...",
                "tool_name": "extract_tech_stack"
            })
            if "tech_stack" in session["analysis_cache"]:
                return {
                    "success": True,
                    "response": session["analysis_cache"]["tech_stack"],
                    "thinking_steps": thinking_steps
                }
            
            try:
                response = analyze_tech_stack(repo_path, repo_name)
                session["analysis_cache"]["tech_stack"] = response
                thinking_steps.append({"type": "tool_result", "content": "Tech stack analysis complete"})
                return {"success": True, "response": response, "thinking_steps": thinking_steps}
            except Exception as e:
                return {
                    "success": False,
                    "response": f"Error analyzing tech stack: {e}",
                    "thinking_steps": thinking_steps
                }

        # Handle architecture generation
        if intent == 'architecture':
            thinking_steps.append({
                "type": "tool_call",
                "content": "Generating architecture analysis (Step 1/3: Document)...",
                "tool_name": "generate_architecture"
            })
            try:
                thinking_steps.append({
                    "type": "thinking",
                    "content": "Step 1/3: Generating architecture document without diagrams..."
                })
                combined = generate_architecture(repo_path, repo_name)
                thinking_steps.append({
                    "type": "tool_result",
                    "content": "Architecture analysis complete (3 LLM calls merged)"
                })
                return {
                    "success": True,
                    "response": combined,
                    "thinking_steps": thinking_steps,
                    "architecture_diagram": combined
                }
            except Exception as e:
                return {
                    "success": False,
                    "response": f"Error generating architecture: {e}",
                    "thinking_steps": thinking_steps
                }

        # Handle feature extraction
        if intent == 'features':
            thinking_steps.append({
                "type": "tool_call",
                "content": "Extracting features...",
                "tool_name": "extract_features"
            })
            if "features" in session["analysis_cache"]:
                return {
                    "success": True,
                    "response": session["analysis_cache"]["features"],
                    "thinking_steps": thinking_steps
                }
            
            try:
                response = extract_features(repo_path, repo_name)
                session["analysis_cache"]["features"] = response
                thinking_steps.append({"type": "tool_result", "content": "Feature extraction complete"})
                return {"success": True, "response": response, "thinking_steps": thinking_steps}
            except Exception as e:
                return {
                    "success": False,
                    "response": f"Error extracting features: {e}",
                    "thinking_steps": thinking_steps
                }

        # Handle documentation generation
        if intent == 'documentation':
            thinking_steps.append({
                "type": "tool_call",
                "content": "Generating technical documentation...",
                "tool_name": "generate_documentation"
            })
            try:
                response = generate_documentation(repo_path, repo_name)
                thinking_steps.append({"type": "tool_result", "content": "Documentation generated"})
                return {"success": True, "response": response, "thinking_steps": thinking_steps}
            except Exception as e:
                return {
                    "success": False,
                    "response": f"Error generating documentation: {e}",
                    "thinking_steps": thinking_steps
                }

        # Handle code modification
        if intent == 'modify':
            thinking_steps.append({
                "type": "tool_call",
                "content": "Analyzing code modification request...",
                "tool_name": "modify_code"
            })
            try:
                response, files_modified = modify_code(repo_path, repo_name, query)
                thinking_steps.append({
                    "type": "tool_result",
                    "content": f"Modified {len(files_modified)} files"
                })
                return {"success": True, "response": response, "thinking_steps": thinking_steps}
            except Exception as e:
                return {
                    "success": False,
                    "response": f"Error modifying code: {e}",
                    "thinking_steps": thinking_steps
                }

        # Handle general queries
        thinking_steps.append({
            "type": "tool_call",
            "content": "Processing general query about the repository...",
            "tool_name": "analyze_repo"
        })
        try:
            response = analyze_general_query(repo_path, repo_name, query)
            thinking_steps.append({"type": "tool_result", "content": "Analysis complete"})
            return {"success": True, "response": response, "thinking_steps": thinking_steps}
        except Exception as e:
            return {
                "success": False,
                "response": f"Error analyzing repository: {e}",
                "thinking_steps": thinking_steps
            }


# Global agent instance
github_repo_agent = GitHubRepoAgent()
