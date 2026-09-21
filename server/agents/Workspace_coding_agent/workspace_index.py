"""Workspace file index with TF-IDF-based relevance scoring.

No external ML libraries required — pure-Python term-frequency /
inverse-document-frequency implementation.  The index is built once per
workspace bind, persisted to disk, and reloaded on subsequent calls unless
the workspace fingerprint has changed.

Covers a much wider set of file types than the original keyword scan:
  - Source code (Python, JS/TS, Java, Go, Rust, …)
  - Config/structured data (JSON, YAML, TOML, INI, XML, CSV)
  - Docs (Markdown, RST, plain text)
  - API specs (GraphQL, Protobuf, Prisma, HCL/Terraform)
  - Shell scripts, Dockerfiles, Makefiles
  - Jupyter notebooks (code + markdown cells extracted as text)
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_INDEX_CACHE_DIR = Path(__file__).parent / "index_cache"

# ---------------------------------------------------------------------------
# File-type configuration
# ---------------------------------------------------------------------------

SOURCE_EXTENSIONS: frozenset = frozenset({
    # Source code
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs",
    ".rb", ".php", ".cs", ".cpp", ".c", ".h", ".hpp",
    ".swift", ".kt", ".scala", ".ex", ".exs",
    ".vue", ".svelte",
    # Web
    ".html", ".css", ".scss", ".sass", ".less",
    # API / schema
    ".sql", ".graphql", ".gql", ".proto",
    # Config / structured data
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".xml", ".csv",
    # Docs / unstructured
    ".md", ".rst", ".txt", ".adoc",
    # Infrastructure
    ".tf", ".hcl",
    ".sh", ".bash", ".zsh", ".ps1", ".bat",
    ".dockerfile",
    # Notebook
    ".ipynb",
    # Schema / migrations
    ".prisma", ".migration",
})

NAMED_FILES: frozenset = frozenset({
    "dockerfile", "makefile", "jenkinsfile", "vagrantfile",
    "procfile", "gemfile", "rakefile", "brewfile", "cmakelists.txt",
    ".env.example", ".env.sample", ".env.template",
    ".gitignore", ".dockerignore", ".eslintrc", ".prettierrc",
    "cargo.toml", "go.mod", "go.sum",
})

IGNORE_DIRS: frozenset = frozenset({
    ".git", "node_modules", "__pycache__", ".next", "dist", "build",
    ".venv", "venv", "env", ".idea", ".vscode", "vendor",
    "target", "bin", "obj", ".cache", ".nuxt", ".output", "coverage",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "eggs", ".eggs",
    "htmlcov", ".tox", "site-packages",
})

IGNORE_EXTENSIONS: frozenset = frozenset({
    ".pyc", ".pyo", ".class", ".o", ".so", ".dll", ".exe",
    ".ico", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".bmp", ".webp",
    ".mp3", ".mp4", ".wav", ".avi", ".mov",
    ".zip", ".tar", ".gz", ".rar", ".7z", ".whl", ".egg",
    ".woff", ".woff2", ".ttf", ".eot",
    ".min.js", ".min.css",
    ".lock",
    ".map",
})

MAX_FILE_BYTES = 200_000    # 200 KB per file
MAX_INDEX_FILES = 500       # cap to avoid memory issues on huge mono-repos
MAX_TOKENS_FOR_TF = 50_000  # chars per file used for TF calculation


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _workspace_fingerprint(root: Path) -> str:
    """Lightweight fingerprint based on mtime + size of top-level entries."""
    try:
        entries = sorted(root.iterdir(), key=lambda e: e.name)[:60]
        parts: List[str] = []
        for e in entries:
            try:
                st = e.stat()
                parts.append(f"{e.name}:{st.st_mtime:.0f}:{st.st_size}")
            except OSError:
                pass
        return hashlib.sha1("\n".join(parts).encode()).hexdigest()[:16]
    except OSError:
        return "unknown"


def _extract_ipynb_text(raw: str) -> str:
    """Extract markdown + code cell sources from a Jupyter notebook."""
    try:
        nb = json.loads(raw)
        parts: List[str] = []
        for cell in nb.get("cells", []):
            src = cell.get("source", "")
            if isinstance(src, list):
                src = "".join(src)
            parts.append(src)
        return "\n".join(parts)
    except Exception:
        return raw[:5_000]


def _read_file_text(path: Path) -> Optional[str]:
    """Read a file, applying special handling for binary-ish formats."""
    try:
        size = path.stat().st_size
        if size == 0 or size > MAX_FILE_BYTES:
            return None
        raw = path.read_bytes()
        if b"\x00" in raw[:512]:   # binary sniff
            return None
        text = raw.decode("utf-8", errors="replace")
        if path.suffix == ".ipynb":
            return _extract_ipynb_text(text)
        return text
    except OSError:
        return None


def _should_include(path: Path) -> bool:
    if any(part in IGNORE_DIRS for part in path.parts):
        return False
    if path.suffix.lower() in IGNORE_EXTENSIONS:
        return False
    if path.suffix.lower() in SOURCE_EXTENSIONS:
        return True
    if path.name.lower() in NAMED_FILES:
        return True
    return False


def _tokenize(text: str) -> List[str]:
    """Lowercase, split on non-word chars, keep tokens ≥ 2 chars."""
    return [t for t in re.split(r"\W+", text.lower()) if len(t) >= 2]


# ---------------------------------------------------------------------------
# Index builder
# ---------------------------------------------------------------------------

def _build_tf_index(root: Path) -> Dict[str, Dict[str, float]]:
    """Walk workspace and compute TF scores per file.

    Returns ``{rel_path: {term: tf_score}}``.
    """
    index: Dict[str, Dict[str, float]] = {}
    for fp in root.rglob("*"):
        if not fp.is_file():
            continue
        if not _should_include(fp):
            continue
        text = _read_file_text(fp)
        if not text:
            continue
        rel = str(fp.relative_to(root))
        tokens = _tokenize(text[:MAX_TOKENS_FOR_TF])
        if not tokens:
            continue
        tf_raw: Dict[str, int] = {}
        for t in tokens:
            tf_raw[t] = tf_raw.get(t, 0) + 1
        total = len(tokens)
        index[rel] = {t: c / total for t, c in tf_raw.items()}
        if len(index) >= MAX_INDEX_FILES:
            break
    return index


def _compute_idf(index: Dict[str, Dict[str, float]]) -> Dict[str, float]:
    """IDF = log(N / df) for each term."""
    N = len(index)
    if N == 0:
        return {}
    df: Dict[str, int] = {}
    for doc_tf in index.values():
        for term in doc_tf:
            df[term] = df.get(term, 0) + 1
    return {term: math.log(N / count) for term, count in df.items()}


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------

class WorkspaceIndex:
    """Lazily-built, disk-cached TF-IDF index for a single workspace root."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._index: Optional[Dict[str, Dict[str, float]]] = None
        self._idf: Optional[Dict[str, float]] = None
        self._fingerprint: Optional[str] = None
        h = hashlib.sha1(str(self.root).encode()).hexdigest()[:16]
        self._cache_path = _INDEX_CACHE_DIR / f"{h}.json"

    # -- Disk cache ----------------------------------------------------------

    def _load_cache(self) -> bool:
        if not self._cache_path.exists():
            return False
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            fp = _workspace_fingerprint(self.root)
            if data.get("fingerprint") != fp:
                return False
            self._index = data["index"]
            self._idf = data["idf"]
            self._fingerprint = fp
            return True
        except Exception:
            return False

    def _save_cache(self) -> None:
        try:
            _INDEX_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = self._cache_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(
                    {
                        "fingerprint": self._fingerprint,
                        "index": self._index,
                        "idf": self._idf,
                        "built_at": time.time(),
                        "file_count": len(self._index or {}),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            tmp.replace(self._cache_path)
        except Exception:
            pass

    # -- Build / refresh -----------------------------------------------------

    def build(self, force: bool = False) -> None:
        """Build (or reload from cache) the index."""
        if not force and self._load_cache():
            print(
                f"[WorkspaceIndex] Cache hit for {self.root.name} "
                f"({len(self._index)} files)"
            )
            return
        print(f"[WorkspaceIndex] Building index for {self.root.name} …")
        t0 = time.time()
        self._index = _build_tf_index(self.root)
        self._idf = _compute_idf(self._index)
        self._fingerprint = _workspace_fingerprint(self.root)
        self._save_cache()
        print(
            f"[WorkspaceIndex] Indexed {len(self._index)} files "
            f"in {time.time() - t0:.2f}s"
        )

    # -- Query ---------------------------------------------------------------

    def score(self, query: str, rel_path: str) -> float:
        """TF-IDF score of query terms against a single document."""
        if not self._index or not self._idf:
            return 0.0
        doc_tf = self._index.get(rel_path, {})
        if not doc_tf:
            return 0.0
        score = 0.0
        for term in _tokenize(query):
            score += doc_tf.get(term, 0.0) * self._idf.get(term, 0.0)
        return score

    def top_k(
        self,
        query: str,
        k: int = 20,
        min_score: float = 0.0,
    ) -> List[Tuple[str, float]]:
        """Return top-k ``(rel_path, score)`` pairs for a query."""
        if not self._index:
            return []
        scores = [
            (path, self.score(query, path))
            for path in self._index
        ]
        filtered = [(p, s) for p, s in scores if s > min_score]
        filtered.sort(key=lambda x: x[1], reverse=True)
        return filtered[:k]

    def read_file(self, rel_path: str) -> Optional[str]:
        """Read a workspace file by relative path."""
        return _read_file_text(self.root / rel_path)

    def all_files(self) -> List[str]:
        return list(self._index.keys()) if self._index else []

    @property
    def file_count(self) -> int:
        return len(self._index) if self._index else 0

    def is_ready(self) -> bool:
        return self._index is not None
