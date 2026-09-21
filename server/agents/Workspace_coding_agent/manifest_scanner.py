"""Deterministic tech-stack detection from repository manifests.

Reads dependency / build manifests at the repo root (and one level deep) to
produce a structured `RepoStack` summary. This is cheaper, more reliable, and
more reproducible than asking an LLM "what's the tech stack?".

Detected:
  - Languages         (from manifest presence + file-extension counts)
  - Frameworks        (heuristics over dependency names)
  - Build tools       (npm, pip, poetry, maven, gradle, cargo, go, dotnet, …)
  - Runtimes          (node engines, python_requires, java versions)
  - Test frameworks
  - Containerization  (Dockerfile, docker-compose, k8s manifests)
  - CI                (GitHub Actions, GitLab CI, CircleCI, Jenkinsfile)
  - Top dependencies  (most-likely 20 names)
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Framework heuristics — package-name → friendly framework label
# ---------------------------------------------------------------------------

_FRAMEWORK_HINTS: Dict[str, List[Tuple[str, str]]] = {
    # JS / TS
    "js": [
        ("react", "React"), ("next", "Next.js"), ("vue", "Vue"),
        ("nuxt", "Nuxt"), ("svelte", "Svelte"), ("@angular/core", "Angular"),
        ("express", "Express"), ("fastify", "Fastify"), ("koa", "Koa"),
        ("nestjs", "NestJS"), ("@nestjs/core", "NestJS"),
        ("redux", "Redux"), ("zustand", "Zustand"), ("@tanstack/react-query", "TanStack Query"),
        ("tailwindcss", "Tailwind CSS"), ("@mui/material", "MUI"),
        ("vite", "Vite"), ("webpack", "Webpack"),
        ("jest", "Jest"), ("vitest", "Vitest"), ("mocha", "Mocha"),
        ("playwright", "Playwright"), ("cypress", "Cypress"),
        ("typescript", "TypeScript"),
    ],
    "py": [
        ("django", "Django"), ("flask", "Flask"), ("fastapi", "FastAPI"),
        ("sqlalchemy", "SQLAlchemy"), ("pydantic", "Pydantic"),
        ("celery", "Celery"), ("pandas", "pandas"), ("numpy", "NumPy"),
        ("torch", "PyTorch"), ("tensorflow", "TensorFlow"),
        ("pytest", "pytest"), ("unittest2", "unittest2"),
        ("openai", "OpenAI SDK"), ("anthropic", "Anthropic SDK"),
        ("uvicorn", "uvicorn"), ("gunicorn", "Gunicorn"),
    ],
    "java": [
        ("spring-boot-starter", "Spring Boot"),
        ("spring-core", "Spring"),
        ("hibernate-core", "Hibernate"),
        ("junit", "JUnit"),
        ("lombok", "Lombok"),
    ],
    "go": [
        ("gin-gonic/gin", "Gin"), ("labstack/echo", "Echo"),
        ("gofiber/fiber", "Fiber"), ("gorilla/mux", "Gorilla Mux"),
        ("gorm.io/gorm", "GORM"),
    ],
    "rs": [
        ("axum", "Axum"), ("actix-web", "Actix Web"),
        ("rocket", "Rocket"), ("tokio", "Tokio"),
        ("serde", "Serde"),
    ],
    "rb": [
        ("rails", "Ruby on Rails"), ("sinatra", "Sinatra"),
        ("rspec", "RSpec"),
    ],
    "php": [
        ("laravel/framework", "Laravel"),
        ("symfony/symfony", "Symfony"),
    ],
}

_LANG_BY_EXT = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".java": "Java", ".kt": "Kotlin", ".scala": "Scala",
    ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".php": "PHP",
    ".cs": "C#", ".cpp": "C++", ".c": "C", ".swift": "Swift",
    ".vue": "Vue", ".svelte": "Svelte",
}

_IGNORE_DIRS = frozenset({
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", "target", ".next", ".nuxt", ".output", "vendor",
    "bin", "obj", ".idea", ".vscode", ".cache", "coverage",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
})


# ---------------------------------------------------------------------------
# Manifest readers
# ---------------------------------------------------------------------------

def _safe_read(path: Path, max_bytes: int = 500_000) -> Optional[str]:
    try:
        if path.stat().st_size > max_bytes:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _parse_package_json(path: Path) -> Dict[str, Any]:
    text = _safe_read(path) or ""
    out: Dict[str, Any] = {"deps": {}, "scripts": {}, "engines": {}}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return out
    deps: Dict[str, str] = {}
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        d = data.get(key) or {}
        if isinstance(d, dict):
            deps.update({str(k): str(v) for k, v in d.items()})
    out["deps"] = deps
    out["scripts"] = data.get("scripts") or {}
    out["engines"] = data.get("engines") or {}
    out["package_manager"] = data.get("packageManager")
    return out


def _parse_pyproject(path: Path) -> Dict[str, Any]:
    text = _safe_read(path) or ""
    out: Dict[str, Any] = {"deps": {}, "python": ""}
    # Avoid hard-depending on `tomllib` (Python 3.11+) — regex pull is enough
    # for the dependency *names*, which is all we need.
    pep621 = re.search(
        r"\[project\][^\[]*?dependencies\s*=\s*\[(.*?)\]", text, re.DOTALL,
    )
    poetry = re.search(
        r"\[tool\.poetry\.dependencies\](.*?)(?:\n\[|$)", text, re.DOTALL,
    )
    raw = (pep621.group(1) if pep621 else "") + "\n" + (poetry.group(1) if poetry else "")
    for m in re.finditer(r"['\"]([A-Za-z0-9_\-\.]+)\s*([<>=!~][^'\"]*)?['\"]", raw):
        out["deps"][m.group(1).lower()] = (m.group(2) or "*").strip()
    pyver = re.search(r"requires-python\s*=\s*['\"]([^'\"]+)['\"]", text)
    if pyver:
        out["python"] = pyver.group(1)
    return out


def _parse_requirements(path: Path) -> Dict[str, str]:
    text = _safe_read(path) or ""
    deps: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        m = re.match(r"([A-Za-z0-9_\-\.]+)\s*([<>=!~].*)?", line)
        if m:
            deps[m.group(1).lower()] = (m.group(2) or "*").strip()
    return deps


def _parse_go_mod(path: Path) -> Dict[str, Any]:
    text = _safe_read(path) or ""
    out: Dict[str, Any] = {"module": "", "go": "", "deps": {}}
    m = re.search(r"^module\s+(\S+)", text, re.MULTILINE)
    if m:
        out["module"] = m.group(1)
    g = re.search(r"^go\s+(\S+)", text, re.MULTILINE)
    if g:
        out["go"] = g.group(1)
    for r in re.finditer(r"^\s*([\w./\-]+)\s+v\S+", text, re.MULTILINE):
        out["deps"][r.group(1)] = "*"
    return out


def _parse_cargo(path: Path) -> Dict[str, str]:
    text = _safe_read(path) or ""
    deps: Dict[str, str] = {}
    block = re.search(r"\[dependencies\](.*?)(?:\n\[|$)", text, re.DOTALL)
    if not block:
        return deps
    for line in block.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"([A-Za-z0-9_\-]+)\s*=", line)
        if m:
            deps[m.group(1).lower()] = "*"
    return deps


def _parse_pom(path: Path) -> Dict[str, str]:
    text = _safe_read(path) or ""
    deps: Dict[str, str] = {}
    for m in re.finditer(
        r"<dependency>.*?<artifactId>([^<]+)</artifactId>.*?</dependency>",
        text, re.DOTALL,
    ):
        deps[m.group(1).strip()] = "*"
    return deps


def _parse_gradle(path: Path) -> Dict[str, str]:
    text = _safe_read(path) or ""
    deps: Dict[str, str] = {}
    for m in re.finditer(
        r"(?:implementation|api|compile|testImplementation)\s*[(\s]\s*['\"]([^'\":]+):([^'\":]+)",
        text,
    ):
        deps[f"{m.group(1)}:{m.group(2)}"] = "*"
    return deps


def _parse_gemfile(path: Path) -> Dict[str, str]:
    text = _safe_read(path) or ""
    deps: Dict[str, str] = {}
    for m in re.finditer(r"gem\s+['\"]([^'\"]+)['\"]", text):
        deps[m.group(1).lower()] = "*"
    return deps


def _parse_composer(path: Path) -> Dict[str, str]:
    text = _safe_read(path) or ""
    deps: Dict[str, str] = {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return deps
    for key in ("require", "require-dev"):
        d = data.get(key) or {}
        if isinstance(d, dict):
            deps.update({str(k): str(v) for k, v in d.items()})
    return deps


# ---------------------------------------------------------------------------
# Top-level scanner
# ---------------------------------------------------------------------------

def _walk_one_level(root: Path) -> List[Path]:
    """Return root + first-level subdirectories that look like sub-projects."""
    candidates = [root]
    try:
        for child in root.iterdir():
            if child.is_dir() and child.name not in _IGNORE_DIRS:
                candidates.append(child)
    except OSError:
        pass
    return candidates


def _count_languages(root: Path, max_files: int = 5_000) -> Dict[str, int]:
    counts: Counter = Counter()
    n = 0
    for fp in root.rglob("*"):
        if not fp.is_file():
            continue
        if any(p in _IGNORE_DIRS for p in fp.parts):
            continue
        ext = fp.suffix.lower()
        lang = _LANG_BY_EXT.get(ext)
        if lang:
            counts[lang] += 1
        n += 1
        if n >= max_files:
            break
    return dict(counts.most_common())


def _detect_frameworks(deps_by_eco: Dict[str, Dict[str, str]]) -> List[str]:
    found: List[str] = []
    seen: Set[str] = set()
    for eco, deps in deps_by_eco.items():
        hints = _FRAMEWORK_HINTS.get(eco, [])
        dep_keys = {k.lower() for k in deps.keys()}
        for needle, label in hints:
            if any(needle in k for k in dep_keys):
                if label not in seen:
                    seen.add(label)
                    found.append(label)
    return found


def _detect_ci(root: Path) -> List[str]:
    out: List[str] = []
    if (root / ".github" / "workflows").is_dir():
        out.append("GitHub Actions")
    if (root / ".gitlab-ci.yml").is_file():
        out.append("GitLab CI")
    if (root / ".circleci" / "config.yml").is_file():
        out.append("CircleCI")
    if (root / "Jenkinsfile").is_file():
        out.append("Jenkins")
    if (root / "azure-pipelines.yml").is_file():
        out.append("Azure Pipelines")
    return out


def _detect_containerization(root: Path) -> List[str]:
    out: List[str] = []
    for fname in ("Dockerfile", "dockerfile"):
        if (root / fname).is_file():
            out.append("Docker")
            break
    if (root / "docker-compose.yml").is_file() or (root / "docker-compose.yaml").is_file():
        out.append("docker-compose")
    if (root / "k8s").is_dir() or (root / "kubernetes").is_dir() or (root / "helm").is_dir():
        out.append("Kubernetes")
    return out


def scan_repo(repo_path: str) -> Dict[str, Any]:
    """Inspect ``repo_path`` and return a `RepoStack` dict."""
    root = Path(repo_path).resolve()

    deps_by_eco: Dict[str, Dict[str, str]] = {
        "js": {}, "py": {}, "java": {}, "go": {}, "rs": {},
        "rb": {}, "php": {},
    }
    runtime: Dict[str, str] = {}
    build_tools: Set[str] = set()

    for d in _walk_one_level(root):
        # JS / TS
        pkg = d / "package.json"
        if pkg.is_file():
            info = _parse_package_json(pkg)
            deps_by_eco["js"].update(info.get("deps", {}))
            engines = info.get("engines") or {}
            if engines.get("node"):
                runtime["node"] = engines["node"]
            pm = info.get("package_manager") or ""
            if pm:
                build_tools.add(pm.split("@", 1)[0])
            else:
                build_tools.add("npm")
            if (d / "yarn.lock").is_file():
                build_tools.add("yarn")
            if (d / "pnpm-lock.yaml").is_file():
                build_tools.add("pnpm")

        # Python
        if (d / "pyproject.toml").is_file():
            info = _parse_pyproject(d / "pyproject.toml")
            deps_by_eco["py"].update(info.get("deps", {}))
            if info.get("python"):
                runtime["python"] = info["python"]
            text = _safe_read(d / "pyproject.toml") or ""
            if "[tool.poetry" in text:
                build_tools.add("poetry")
            if "[tool.hatch" in text:
                build_tools.add("hatch")
            if "[tool.setuptools" in text or "build-backend" in text:
                build_tools.add("setuptools")
        for req in ("requirements.txt", "requirements-dev.txt"):
            if (d / req).is_file():
                deps_by_eco["py"].update(_parse_requirements(d / req))
                build_tools.add("pip")

        # Java
        if (d / "pom.xml").is_file():
            deps_by_eco["java"].update(_parse_pom(d / "pom.xml"))
            build_tools.add("maven")
        for g in ("build.gradle", "build.gradle.kts"):
            if (d / g).is_file():
                deps_by_eco["java"].update(_parse_gradle(d / g))
                build_tools.add("gradle")

        # Go
        if (d / "go.mod").is_file():
            info = _parse_go_mod(d / "go.mod")
            deps_by_eco["go"].update(info.get("deps", {}))
            if info.get("go"):
                runtime["go"] = info["go"]
            build_tools.add("go-modules")

        # Rust
        if (d / "Cargo.toml").is_file():
            deps_by_eco["rs"].update(_parse_cargo(d / "Cargo.toml"))
            build_tools.add("cargo")

        # Ruby
        if (d / "Gemfile").is_file():
            deps_by_eco["rb"].update(_parse_gemfile(d / "Gemfile"))
            build_tools.add("bundler")

        # PHP
        if (d / "composer.json").is_file():
            deps_by_eco["php"].update(_parse_composer(d / "composer.json"))
            build_tools.add("composer")

    languages = _count_languages(root)
    frameworks = _detect_frameworks(deps_by_eco)
    ci = _detect_ci(root)
    containers = _detect_containerization(root)

    # Test framework rollup
    test_hints = {
        "pytest": "pytest", "unittest": "unittest",
        "jest": "Jest", "vitest": "Vitest", "mocha": "Mocha",
        "playwright": "Playwright", "cypress": "Cypress",
        "junit": "JUnit", "rspec": "RSpec",
    }
    tests: List[str] = []
    flat = {k.lower() for ds in deps_by_eco.values() for k in ds.keys()}
    for needle, label in test_hints.items():
        if any(needle in k for k in flat) and label not in tests:
            tests.append(label)

    # Top dependencies — sample 20 most "framework-y" ones across ecosystems
    flat_deps: Counter = Counter()
    for ds in deps_by_eco.values():
        for k in ds.keys():
            flat_deps[k] += 1
    top_deps = [k for k, _ in flat_deps.most_common(20)]

    return {
        "languages": languages,
        "frameworks": frameworks,
        "build_tools": sorted(build_tools),
        "runtime": runtime,
        "test_frameworks": tests,
        "ci": ci,
        "containerization": containers,
        "top_dependencies": top_deps,
        "manifests_found": _list_manifests(root),
    }


def _list_manifests(root: Path) -> List[str]:
    names = [
        "package.json", "pyproject.toml", "requirements.txt",
        "pom.xml", "build.gradle", "build.gradle.kts",
        "go.mod", "Cargo.toml", "Gemfile", "composer.json",
        "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
        ".github/workflows", ".gitlab-ci.yml", "Jenkinsfile",
    ]
    found: List[str] = []
    for d in _walk_one_level(root):
        for n in names:
            target = d / n
            if target.exists():
                try:
                    found.append(str(target.relative_to(root)))
                except ValueError:
                    found.append(str(target))
    return sorted(set(found))


def render_stack_markdown(stack: Dict[str, Any]) -> str:
    """Pretty-print a stack dict as Markdown for inclusion in a report."""
    lines: List[str] = []
    langs = stack.get("languages") or {}
    if langs:
        top = ", ".join(f"{k} ({v})" for k, v in list(langs.items())[:6])
        lines.append(f"- **Languages:** {top}")
    if stack.get("frameworks"):
        lines.append(f"- **Frameworks:** {', '.join(stack['frameworks'])}")
    if stack.get("build_tools"):
        lines.append(f"- **Build tools:** {', '.join(stack['build_tools'])}")
    rt = stack.get("runtime") or {}
    if rt:
        lines.append(
            "- **Runtimes:** "
            + ", ".join(f"{k} {v}" for k, v in rt.items())
        )
    if stack.get("test_frameworks"):
        lines.append(f"- **Test frameworks:** {', '.join(stack['test_frameworks'])}")
    if stack.get("containerization"):
        lines.append(f"- **Containerization:** {', '.join(stack['containerization'])}")
    if stack.get("ci"):
        lines.append(f"- **CI:** {', '.join(stack['ci'])}")
    if stack.get("top_dependencies"):
        lines.append(
            "- **Top dependencies:** "
            + ", ".join(f"`{d}`" for d in stack["top_dependencies"][:15])
        )
    return "\n".join(lines) if lines else "_(no manifests detected)_"
