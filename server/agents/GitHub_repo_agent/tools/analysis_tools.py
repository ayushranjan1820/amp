"""Repository analysis tools"""

from typing import Dict
from ..ai_service import ai_service
from ..utils.file_operations import (
    get_file_tree,
    read_key_files,
    collect_source_files,
    format_files_for_prompt
)


def analyze_tech_stack(repo_path: str, repo_name: str) -> str:
    """
    Analyze and extract the technology stack of a repository.
    
    Args:
        repo_path: Path to the repository
        repo_name: Name of the repository
        
    Returns:
        Formatted tech stack analysis
    """
    key_files = read_key_files(repo_path)
    tree = get_file_tree(repo_path)

    prompt = f"""Analyze this repository and extract a comprehensive tech stack report.

Repository: {repo_name}
File Structure:
{tree}

Key Configuration Files:
{format_files_for_prompt(key_files)}

Provide a detailed tech stack analysis in this markdown format:
## 🛠️ Tech Stack Analysis: {repo_name}

### Programming Languages
(list with versions if detectable)

### Frameworks & Libraries
(categorized: Frontend, Backend, Testing, etc.)

### Build Tools & Package Managers
(list detected build tools)

### Infrastructure & DevOps
(Docker, CI/CD, cloud services, etc.)

### Databases & Storage
(if any detected)

### Key Dependencies
(list the most important dependencies with brief descriptions)

Be specific with version numbers when available from config files."""

    response = ai_service.call_genai(prompt, max_tokens=4096)
    return response


def extract_features(repo_path: str, repo_name: str) -> str:
    """
    Extract features and functionalities from a repository.
    
    Args:
        repo_path: Path to the repository
        repo_name: Name of the repository
        
    Returns:
        Formatted feature analysis
    """
    key_files = read_key_files(repo_path)
    source_files = collect_source_files(repo_path)
    tree = get_file_tree(repo_path)

    # Extract routes and endpoints
    routes_and_endpoints = ""
    for name, content in source_files.items():
        if any(k in content for k in ['@app.', '@router.', 'app.get', 'app.post', 'Router()', 'express()', 'Route']):
            routes = [l.strip() for l in content.split('\n') if any(k in l for k in ['@app.', '@router.', 'app.get', 'app.post', 'app.put', 'app.delete', 'path:', 'route('])]
            if routes:
                routes_and_endpoints += f"\n{name}:\n" + "\n".join(routes[:20])

    prompt = f"""Analyze this repository and extract all features and functionalities.

Repository: {repo_name}
File Structure:
{tree}

Key Files:
{format_files_for_prompt(key_files)}

Routes/Endpoints Found:
{routes_and_endpoints[:4000]}

Provide a comprehensive feature extraction in this format:

## ✨ Feature Analysis: {repo_name}

### Core Features
(numbered list of main features with descriptions)

### API Endpoints / Routes
(if applicable, list all detected endpoints with methods and descriptions)

### User-Facing Features
(features visible to end users)

### Backend / Internal Features
(background processes, integrations, etc.)

### Authentication & Security
(any auth features detected)

### Notable Implementation Details
(interesting technical implementations worth noting)

Be thorough but concise. Group related features together."""

    response = ai_service.call_genai(prompt, max_tokens=6144)
    return response


def generate_documentation(repo_path: str, repo_name: str) -> str:
    """
    Generate comprehensive technical documentation for a repository.
    
    Args:
        repo_path: Path to the repository
        repo_name: Name of the repository
        
    Returns:
        Formatted technical documentation
    """
    key_files = read_key_files(repo_path)
    source_files = collect_source_files(repo_path)
    tree = get_file_tree(repo_path)

    # Build source context
    source_context = ""
    for name, content in list(source_files.items())[:25]:
        source_context += f"\n\n--- {name} ---\n{content[:3000]}"

    prompt = f"""Perform reverse engineering on this repository and generate comprehensive technical documentation.

Repository: {repo_name}
File Structure:
{tree}

Key Configuration Files:
{format_files_for_prompt(key_files)}

Source Code (selected files):
{source_context[:15000]}

Generate professional technical documentation in this format:

## 📚 Technical Documentation: {repo_name}

### 1. Project Overview
(what the project does, its purpose, and target audience)

### 2. System Architecture
(high-level architecture description, patterns used)

### 3. Tech Stack
(languages, frameworks, key dependencies)

### 4. Project Structure
```
(cleaned up file tree with descriptions of key directories)
```

### 5. Core Components
(detailed description of each major component/module)

### 6. API Reference
(if applicable: endpoints, parameters, responses)

### 7. Data Models
(database schemas, data structures, key types)

### 8. Configuration
(environment variables, config files, setup requirements)

### 9. Setup & Installation
(step-by-step setup instructions derived from the codebase)

### 10. Key Workflows
(main user flows and how they map to code)

### 11. Dependencies
(key external dependencies and their purposes)

Be thorough and professional. This should serve as complete technical documentation for a new developer joining the project."""

    response = ai_service.call_genai(prompt, max_tokens=8192)
    return response


def analyze_general_query(repo_path: str, repo_name: str, query: str) -> str:
    """
    Answer general questions about a repository.
    
    Args:
        repo_path: Path to the repository
        repo_name: Name of the repository
        query: User's question
        
    Returns:
        Answer to the query
    """
    key_files = read_key_files(repo_path)
    tree = get_file_tree(repo_path)

    prompt = f"""You are an AI assistant analyzing a GitHub repository.

Repository: {repo_name}
User Question: {query}

File Structure:
{tree}

Key Configuration Files:
{format_files_for_prompt(key_files)}

Answer the user's question thoroughly based on the repository analysis. Be specific and reference actual files/code when relevant."""

    response = ai_service.call_genai(prompt, max_tokens=4096)
    return response
