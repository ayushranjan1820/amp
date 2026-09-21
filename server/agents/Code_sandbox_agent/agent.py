import os
import re
from pathlib import Path
from typing import Dict, Any, Optional

if not os.getenv("_AGENTSERVER_RUNNING"):
    from user_config import load_dotenv_then_scrub_pwc
    load_dotenv_then_scrub_pwc(dotenv_path=Path(__file__).parent.parent.parent / ".env")


class CodeSandboxAgent:
    def __init__(self):
        self.sessions: Dict[str, Dict[str, Any]] = {}
        print("📦 Code Sandbox Agent initialized (StackBlitz mode)")

    def _get_session(self, session_id: str) -> Dict[str, Any]:
        if session_id not in self.sessions:
            self.sessions[session_id] = {
                "repo_url": None,
                "repo_slug": None,
                "embedded": False,
            }
        return self.sessions[session_id]

    def _extract_repo_info(self, text: str) -> Optional[Dict[str, str]]:
        patterns = [
            r'https?://github\.com/([\w\-\.]+)/([\w\-\.]+)',
            r'github\.com/([\w\-\.]+)/([\w\-\.]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                owner = match.group(1)
                repo = match.group(2).replace('.git', '').rstrip('/')
                return {
                    "owner": owner,
                    "repo": repo,
                    "slug": f"{owner}/{repo}",
                    "url": f"https://github.com/{owner}/{repo}",
                }
        return None

    def process_query(self, query: str, session_id: str) -> Dict[str, Any]:
        session = self._get_session(session_id)
        q = query.lower()

        if any(kw in q for kw in ['status', 'what is running', 'is it running', 'check']):
            if session.get("embedded"):
                return {
                    "success": True,
                    "response": f"**Sandbox Status**\n\n- **Repository**: [{session['repo_slug']}]({session['repo_url']})\n- **Status**: Embedded via StackBlitz\n\nThe sandbox is running in your browser. You can interact with the preview above.",
                    "thinking_steps": [{"type": "info", "content": "Retrieved sandbox status"}],
                }
            return {
                "success": True,
                "response": "No sandbox is set up yet. Share a GitHub repo URL and I'll open it in a StackBlitz sandbox for you.",
                "thinking_steps": [],
            }

        repo_info = self._extract_repo_info(query)

        if not repo_info and session.get("repo_slug"):
            return {
                "success": True,
                "response": f"Your sandbox for **{session['repo_slug']}** is running in the StackBlitz embed above.\n\nYou can:\n- Edit code directly in the embedded editor\n- See live preview updates instantly\n- Share a new GitHub repo URL to switch projects",
                "thinking_steps": [{"type": "info", "content": "Sandbox already active"}],
                "stackblitz_repo": session["repo_slug"],
            }

        if not repo_info:
            return {
                "success": False,
                "response": "Please provide a valid GitHub repository URL (e.g., `https://github.com/user/repo`) and I'll open it in a StackBlitz sandbox.",
                "thinking_steps": [],
            }

        session["repo_url"] = repo_info["url"]
        session["repo_slug"] = repo_info["slug"]
        session["embedded"] = True

        return {
            "success": True,
            "response": (
                f"Opening **{repo_info['repo']}** in StackBlitz sandbox!\n\n"
                f"- **Repository**: [{repo_info['slug']}]({repo_info['url']})\n"
                f"- **Powered by**: StackBlitz WebContainers\n\n"
                f"The project will be cloned, dependencies installed, and the app started — all directly in your browser. "
                f"You can edit code in the embedded editor and see live preview updates."
            ),
            "thinking_steps": [
                {"type": "action", "content": f"Opening repository: {repo_info['url']}"},
                {"type": "info", "content": "Launching StackBlitz sandbox in browser"},
            ],
            "stackblitz_repo": repo_info["slug"],
        }


code_sandbox_agent = CodeSandboxAgent()
