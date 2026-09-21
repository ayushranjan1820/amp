"""Git utilities for repository operations"""

import re
from typing import Optional


def extract_repo_url(text: str) -> Optional[str]:
    """
    Extract a GitHub repository URL from text.
    
    Args:
        text: Input text that may contain a GitHub URL
        
    Returns:
        Normalized GitHub URL or None if not found
    """
    patterns = [
        r'https?://github\.com/[\w\-\.]+/[\w\-\.]+(?:\.git)?',
        r'github\.com/([\w\-\.]+/[\w\-\.]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            url = match.group(0)
            if not url.startswith('http'):
                url = f"https://github.com/{match.group(1)}"
            return url.rstrip('.git').rstrip('/')
    return None
