"""Mermaid diagram sanitization utilities"""

import re


def sanitize_mermaid(mermaid_code: str) -> str:
    """
    Sanitize Mermaid diagram code to fix common syntax issues.
    
    Args:
        mermaid_code: Raw Mermaid diagram code
        
    Returns:
        Sanitized Mermaid code
    """
    lines = mermaid_code.split('\n')
    sanitized = []
    is_sequence = 'sequenceDiagram' in mermaid_code

    for line in lines:
        stripped = line.strip()

        # Skip empty lines and diagram type declarations
        if stripped in ('', 'end') or stripped.startswith('%%') or \
           stripped.startswith('graph ') or stripped.startswith('flowchart ') or \
           stripped.startswith('sequenceDiagram'):
            sanitized.append(line)
            continue

        # Handle sequence diagrams
        if is_sequence:
            # Fix participant declarations
            participant_match = re.match(r'(\s*participant\s+)(\S+.*?\S)\s*$', line)
            if participant_match and '(' in participant_match.group(2) and ' as ' not in participant_match.group(2):
                prefix = participant_match.group(1)
                name = participant_match.group(2)
                alias = re.sub(r'[^a-zA-Z0-9]', '', name)[:12]
                line = f"{prefix}{alias} as {name}"
            
            # Fix message lines
            msg_match = re.match(r'(\s*\S+\s*->>?\s*\S+\s*:\s*)(.+)$', line)
            if msg_match:
                line = msg_match.group(1) + re.sub(r'[<>{}\[\]]', '', msg_match.group(2))
            
            sanitized.append(line)
            continue

        # Fix subgraph declarations
        if stripped.startswith('subgraph '):
            subgraph_match = re.match(r'(\s*subgraph\s+)(\w+)\s+(.*)', line)
            if subgraph_match and any(c in subgraph_match.group(3) for c in '(){}|<>&') and '"' not in subgraph_match.group(3):
                line = f'{subgraph_match.group(1)}{subgraph_match.group(2)}["{subgraph_match.group(3)}"]'
            elif stripped.startswith('subgraph ') and not subgraph_match:
                raw_label_match = re.match(r'(\s*subgraph\s+)(.*)', line)
                if raw_label_match and any(c in raw_label_match.group(2) for c in '(){}|<>&') and '"' not in raw_label_match.group(2):
                    safe_id = re.sub(r'[^a-zA-Z0-9]', '', raw_label_match.group(2))[:12]
                    line = f'{raw_label_match.group(1)}{safe_id}["{raw_label_match.group(2)}"]'
            sanitized.append(line)
            continue

        # Quote labels in brackets
        def quote_label_in_brackets(m):
            node_id = m.group(1)
            label = m.group(2)
            if '"' in label:
                return m.group(0)
            if any(c in label for c in '(){}|<>&'):
                return f'{node_id}["{label.replace(chr(34), chr(39))}"]'
            return m.group(0)

        line = re.sub(r'(\w+)\[([^\]]+)\]', quote_label_in_brackets, line)

        # Fix nested parentheses
        line = re.sub(
            r'(\w+)\(([^)]*\([^)]*\)[^)]*)\)',
            lambda m: f'{m.group(1)}["{m.group(2).replace(chr(34), chr(39))}"]',
            line
        )

        sanitized.append(line)

    return '\n'.join(sanitized)


def enforce_architecture_section(raw_body: str, expected_heading: str) -> str:
    """
    Enforce proper section formatting for architecture diagrams.
    
    Args:
        raw_body: Raw response body
        expected_heading: Expected section heading
        
    Returns:
        Properly formatted section with heading
    """
    body = raw_body.strip()
    lines = body.split('\n')
    
    # Skip leading headings or empty lines
    cleaned_lines = []
    skipped_leading = False
    for line in lines:
        if not skipped_leading:
            stripped = line.strip()
            if stripped.startswith('#') or stripped == '':
                continue
            skipped_leading = True
        cleaned_lines.append(line)
    
    body = '\n'.join(cleaned_lines).strip()
    
    # Extract mermaid block if not at the start
    if not body.startswith('```mermaid'):
        mermaid_idx = body.find('```mermaid')
        if mermaid_idx > 0:
            body = body[mermaid_idx:]

    # Sanitize the mermaid code
    mermaid_match = re.search(r'```mermaid\s*\n(.*?)```', body, re.DOTALL)
    if mermaid_match:
        original_mermaid = mermaid_match.group(1)
        sanitized_mermaid = sanitize_mermaid(original_mermaid)
        body = body[:mermaid_match.start(1)] + sanitized_mermaid + body[mermaid_match.end(1):]

    return f"{expected_heading}\n{body}"
