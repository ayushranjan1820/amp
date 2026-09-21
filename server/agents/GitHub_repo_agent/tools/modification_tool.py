"""Code modification tool"""

import re
from pathlib import Path
from typing import Dict, Tuple, List
from ..ai_service import ai_service
from ..utils.file_operations import (
    get_file_tree,
    collect_source_files,
    format_files_for_prompt
)


def modify_code(repo_path: str, repo_name: str, query: str) -> Tuple[str, List[str]]:
    """
    Modify code in the repository based on user request.
    
    Args:
        repo_path: Path to the repository
        repo_name: Name of the repository
        query: User's modification request
        
    Returns:
        Tuple of (response message, list of modified files)
    """
    source_files = collect_source_files(repo_path)
    tree = get_file_tree(repo_path)

    # Find relevant files based on keywords
    relevant_files = {}
    for name, content in source_files.items():
        keywords = query.lower().split()
        if any(kw in name.lower() or kw in content.lower()[:500] for kw in keywords if len(kw) > 3):
            relevant_files[name] = content
        if len(relevant_files) >= 10:
            break

    if not relevant_files:
        relevant_files = dict(list(source_files.items())[:5])

    prompt = f"""You are a code modification assistant. The user wants to make changes to a repository.

Repository: {repo_name}
User Request: {query}

File Structure:
{tree}

Relevant Source Files:
{format_files_for_prompt(relevant_files)}

Analyze the request and provide:
1. Which files need to be modified
2. The exact changes needed (show before/after for each file)
3. Any new files that need to be created

Format your response as:

## ✏️ Code Modification Plan

### Files to Modify:
For each file, show:
**File: `path/to/file`**
```
(the complete modified file content or the specific changes)
```

### Summary of Changes:
(brief description of all changes made)

IMPORTANT: Provide complete, working code. Do not use placeholders or "..." to skip code."""

    response = ai_service.call_genai(prompt, max_tokens=8192)

    # Extract and apply code blocks
    code_blocks = re.findall(r'\*\*File:\s*`([^`]+)`\*\*\s*```[\w]*\n(.*?)```', response, re.DOTALL)
    files_modified = []

    for file_path, code_content in code_blocks:
        full_path = Path(repo_path) / file_path.strip()
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(code_content.strip() + '\n')
            files_modified.append(file_path.strip())
        except Exception as e:
            response += f"\n\n⚠️ Could not write `{file_path}`: {e}"

    if files_modified:
        response += f"\n\n✅ **Applied changes to {len(files_modified)} file(s):** {', '.join(f'`{f}`' for f in files_modified)}"
        response += "\n\nYou can now **push these changes** to GitHub (requires your GitHub token)."

    return response, files_modified
