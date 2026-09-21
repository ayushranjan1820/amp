import re
from typing import List, Dict
from difflib import SequenceMatcher


def tokenize(text: str) -> set:
    return set(re.findall(r'[a-z0-9]+', text.lower()))


def search_inventory(inventory_files: List[Dict], query: str, top_k: int = 10) -> List[Dict]:
    query_tokens = tokenize(query)
    query_lower = query.lower()

    scored_files = []
    for item in inventory_files:
        name_lower = item.get('keywords', item['name'].lower())
        path_lower = item.get('path', '').lower()
        combined = f"{name_lower} {path_lower}"
        file_tokens = tokenize(combined)

        overlap = query_tokens & file_tokens
        if not overlap:
            seq_score = SequenceMatcher(None, query_lower, combined).ratio()
            if seq_score < 0.3:
                continue
            score = seq_score * 0.5
        else:
            token_score = len(overlap) / max(len(query_tokens), 1)
            exact_bonus = 0
            for qt in query_tokens:
                if qt in name_lower:
                    exact_bonus += 0.2
            score = token_score + exact_bonus

        ext = item.get('extension', '')
        if ext in ('.pdf', '.doc', '.docx'):
            score *= 1.2
        elif ext == '.txt':
            score *= 1.1

        scored_files.append({**item, '_score': score})

    scored_files.sort(key=lambda x: x['_score'], reverse=True)
    return scored_files[:top_k]
