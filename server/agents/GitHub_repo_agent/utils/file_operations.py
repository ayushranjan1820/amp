"""File operations utilities for repository analysis"""

from pathlib import Path
from typing import Dict

# Configuration constants
IGNORE_DIRS = {
    '.git', 'node_modules', '__pycache__', '.next', 'dist', 'build',
    '.venv', 'venv', 'env', '.env', '.idea', '.vscode', 'vendor',
    'target', 'bin', 'obj', '.cache', '.nuxt', '.output', 'coverage',
    '.pytest_cache', '.mypy_cache', 'eggs', '*.egg-info',
}

IGNORE_EXTENSIONS = {
    '.pyc', '.pyo', '.class', '.o', '.so', '.dll', '.exe',
    '.ico', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.bmp',
    '.mp3', '.mp4', '.wav', '.avi', '.mov',
    '.zip', '.tar', '.gz', '.rar', '.7z',
    '.woff', '.woff2', '.ttf', '.eot',
    '.lock', '.min.js', '.min.css',
}

MAX_FILE_SIZE = 100_000
MAX_FILES_FOR_ANALYSIS = 80


def get_file_tree(repo_path: str, max_depth: int = 4) -> str:
    """
    Generate a tree structure of the repository.
    
    Args:
        repo_path: Path to the repository
        max_depth: Maximum depth to traverse
        
    Returns:
        String representation of the file tree
    """
    tree_lines = []
    root = Path(repo_path)

    def walk(path: Path, prefix: str = "", depth: int = 0):
        if depth > max_depth:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            return

        dirs = [e for e in entries if e.is_dir() and e.name not in IGNORE_DIRS and not e.name.startswith('.')]
        files = [e for e in entries if e.is_file() and e.suffix not in IGNORE_EXTENSIONS]

        for i, d in enumerate(dirs):
            connector = "└── " if i == len(dirs) - 1 and not files else "├── "
            tree_lines.append(f"{prefix}{connector}{d.name}/")
            ext = "    " if i == len(dirs) - 1 and not files else "│   "
            walk(d, prefix + ext, depth + 1)

        for i, f in enumerate(files[:30]):
            connector = "└── " if i == len(files[:30]) - 1 else "├── "
            tree_lines.append(f"{prefix}{connector}{f.name}")
        if len(files) > 30:
            tree_lines.append(f"{prefix}└── ... ({len(files) - 30} more files)")

    walk(root)
    return "\n".join(tree_lines[:500])


def read_key_files(repo_path: str) -> Dict[str, str]:
    """
    Read important configuration and documentation files from the repository.
    
    Args:
        repo_path: Path to the repository
        
    Returns:
        Dictionary mapping filename to content
    """
    key_files = [
        "README.md", "readme.md", "README.rst",
        "package.json", "requirements.txt", "Pipfile", "pyproject.toml",
        "pom.xml", "build.gradle", "go.mod", "Cargo.toml",
        "Gemfile", "composer.json", "mix.exs",
        "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
        ".env.example", "Makefile", "CMakeLists.txt",
        "tsconfig.json", "webpack.config.js", "vite.config.ts", "vite.config.js",
        "next.config.js", "next.config.ts", "angular.json",
        "setup.py", "setup.cfg",
    ]

    contents = {}
    root = Path(repo_path)
    for kf in key_files:
        fp = root / kf
        if fp.exists() and fp.is_file():
            try:
                text = fp.read_text(errors='ignore')
                if len(text) > MAX_FILE_SIZE:
                    text = text[:MAX_FILE_SIZE] + "\n... (truncated)"
                contents[kf] = text
            except Exception:
                pass
    return contents


def collect_source_files(repo_path: str) -> Dict[str, str]:
    """
    Collect source code files from the repository for analysis.
    
    Args:
        repo_path: Path to the repository
        
    Returns:
        Dictionary mapping relative file path to content
    """
    source_extensions = {
        '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.go', '.rs',
        '.rb', '.php', '.cs', '.cpp', '.c', '.h', '.hpp',
        '.swift', '.kt', '.scala', '.ex', '.exs',
        '.vue', '.svelte', '.html', '.css', '.scss',
        '.sql', '.graphql', '.proto',
    }
    files = {}
    root = Path(repo_path)

    for fp in root.rglob('*'):
        if any(part in IGNORE_DIRS for part in fp.parts):
            continue
        if fp.is_file() and fp.suffix in source_extensions:
            rel = str(fp.relative_to(root))
            try:
                text = fp.read_text(errors='ignore')
                if len(text) > MAX_FILE_SIZE:
                    text = text[:MAX_FILE_SIZE] + "\n... (truncated)"
                files[rel] = text
            except Exception:
                pass
            if len(files) >= MAX_FILES_FOR_ANALYSIS:
                break
    return files


def format_files_for_prompt(files: Dict[str, str]) -> str:
    """
    Format file contents for inclusion in AI prompts.
    
    Args:
        files: Dictionary of filename to content
        
    Returns:
        Formatted string suitable for prompts
    """
    parts = []
    total_len = 0
    for name, content in files.items():
        chunk = f"\n--- {name} ---\n{content}"
        if total_len + len(chunk) > 20000:
            chunk = f"\n--- {name} ---\n{content[:2000]}... (truncated)"
        parts.append(chunk)
        total_len += len(chunk)
        if total_len > 25000:
            break
    return "\n".join(parts)
