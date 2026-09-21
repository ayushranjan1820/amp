import re
from typing import Dict, Any


def detect_intent(query: str) -> Dict[str, Any]:
    q = query.lower().strip()

    repo_url = None
    url_match = re.search(r'https?://github\.com/[\w\-\.]+/[\w\-\.]+', query)
    if url_match:
        repo_url = url_match.group(0)

    if any(kw in q for kw in ['push', 'commit and push', 'push to github', 'push changes', 'deploy code']):
        return {"intent": "push", "repo_url": repo_url}

    modify_patterns = [
        'modify', 'change', 'update', 'refactor', 'fix', 'add feature',
        'add a feature', 'implement', 'add endpoint', 'add route',
        'add function', 'add method', 'add class', 'add test',
        'add error handling', 'improve', 'optimize', 'rewrite',
        'remove', 'delete', 'rename', 'move', 'extract',
        'add to the repo', 'change the code', 'edit the code',
        'update the code', 'modify the code', 'in the repo',
        'in the repository', 'in the codebase', 'in the project',
    ]
    if any(kw in q for kw in modify_patterns):
        return {"intent": "modify", "repo_url": repo_url}

    analyze_patterns = [
        'analyze', 'analyse', 'explain the code', 'what does',
        'how does', 'understand', 'review', 'code review',
        'architecture', 'structure', 'tech stack', 'dependencies',
        'explain this', 'walk me through', 'describe',
    ]
    if any(kw in q for kw in analyze_patterns):
        return {"intent": "analyze", "repo_url": repo_url}

    generate_patterns = [
        'generate', 'create', 'write', 'build', 'make',
        'code for', 'script for', 'program for', 'function for',
        'class for', 'api for', 'app for', 'application for',
        'implement a', 'write a', 'create a', 'build a', 'make a',
        'generate a', 'design a', 'develop a', 'code a',
        'write me', 'create me', 'build me', 'make me',
        'can you write', 'can you create', 'can you build',
        'i need a', 'i want a',
    ]
    if any(kw in q for kw in generate_patterns) and not repo_url:
        return {"intent": "generate", "repo_url": repo_url}

    if repo_url or any(kw in q for kw in ['clone', 'clone repo', 'clone repository']):
        return {"intent": "clone", "repo_url": repo_url}

    return {"intent": "generate", "repo_url": repo_url}
