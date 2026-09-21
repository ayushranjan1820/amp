import os
from pathlib import Path
from typing import List, Dict, Optional


LANGUAGE_EXTENSIONS = {
    '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
    '.tsx': 'typescript', '.jsx': 'javascript', '.java': 'java',
    '.cpp': 'cpp', '.c': 'c', '.h': 'c', '.hpp': 'cpp',
    '.cs': 'csharp', '.go': 'go', '.rs': 'rust', '.rb': 'ruby',
    '.php': 'php', '.swift': 'swift', '.kt': 'kotlin',
    '.scala': 'scala', '.r': 'r', '.R': 'r',
    '.html': 'html', '.css': 'css', '.scss': 'scss',
    '.sql': 'sql', '.sh': 'bash', '.bash': 'bash',
    '.yml': 'yaml', '.yaml': 'yaml', '.json': 'json',
    '.xml': 'xml', '.md': 'markdown', '.toml': 'toml',
    '.dart': 'dart', '.vue': 'vue', '.svelte': 'svelte',
}

SKIP_DIRS = {
    'node_modules', '.git', '__pycache__', '.next', 'dist', 'build',
    '.venv', 'venv', 'env', '.env', '.idea', '.vscode', 'vendor',
    'target', 'bin', 'obj', '.gradle', '.cache', 'coverage',
}

SKIP_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.woff', '.woff2',
    '.ttf', '.eot', '.mp3', '.mp4', '.wav', '.avi', '.mov',
    '.zip', '.tar', '.gz', '.rar', '.7z',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx',
    '.pyc', '.pyo', '.class', '.o', '.so', '.dll', '.exe',
    '.lock',
}


def detect_language(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return LANGUAGE_EXTENSIONS.get(ext, 'text')


def get_file_tree(repo_path: str, max_depth: int = 4, max_files: int = 200) -> str:
    lines = []
    count = 0
    repo = Path(repo_path)

    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in sorted(dirs) if d not in SKIP_DIRS]
        rel = Path(root).relative_to(repo)
        depth = len(rel.parts)
        if depth > max_depth:
            dirs.clear()
            continue

        indent = "  " * depth
        if depth > 0:
            lines.append(f"{indent}📁 {rel.name}/")

        for f in sorted(files):
            if count >= max_files:
                lines.append(f"{indent}  ... and more files")
                return "\n".join(lines)
            ext = Path(f).suffix.lower()
            if ext not in SKIP_EXTENSIONS:
                lines.append(f"{indent}  {f}")
                count += 1

    return "\n".join(lines) if lines else "(empty repository)"


def read_file_safe(file_path: str, max_lines: int = 500) -> Optional[str]:
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()[:max_lines]
            content = ''.join(lines)
            if len(lines) == max_lines:
                content += f"\n... (truncated, showing first {max_lines} lines)"
            return content
    except Exception:
        return None


def collect_source_files(
    repo_path: str,
    query: str = "",
    max_files: int = 15,
    max_chars: int = 60000,
) -> List[Dict[str, str]]:
    results = []
    total_chars = 0
    repo = Path(repo_path)
    query_lower = query.lower()

    scored_files = []
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            ext = Path(f).suffix.lower()
            if ext in SKIP_EXTENSIONS or ext not in LANGUAGE_EXTENSIONS:
                continue
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, repo)

            score = 0
            f_lower = f.lower()
            rel_lower = rel_path.lower()

            query_words = [w for w in query_lower.split() if len(w) > 2]
            for word in query_words:
                if word in f_lower:
                    score += 3
                if word in rel_lower:
                    score += 1

            important_files = [
                'main', 'app', 'index', 'server', 'api', 'routes',
                'config', 'settings', 'models', 'schema', 'utils',
            ]
            for imp in important_files:
                if imp in f_lower:
                    score += 2
                    break

            if ext in ('.py', '.js', '.ts', '.tsx', '.jsx', '.go', '.java', '.rs'):
                score += 1

            scored_files.append((score, full_path, rel_path))

    scored_files.sort(key=lambda x: -x[0])

    for _, full_path, rel_path in scored_files[:max_files]:
        content = read_file_safe(full_path, max_lines=300)
        if content:
            if total_chars + len(content) > max_chars:
                break
            results.append({"path": rel_path, "content": content})
            total_chars += len(content)

    return results
