from typing import Dict, List

OWASP_TOP_10 = {
    "A01": {
        "id": "A01:2021",
        "name": "Broken Access Control",
        "description": "Restrictions on what authenticated users can do are not properly enforced.",
        "check_areas": [
            "URL parameter manipulation",
            "IDOR (Insecure Direct Object Reference)",
            "Missing access controls on API endpoints",
            "CORS misconfiguration",
            "Path traversal",
            "Force browsing to authenticated pages",
        ],
    },
    "A02": {
        "id": "A02:2021",
        "name": "Cryptographic Failures",
        "description": "Failures related to cryptography which often lead to sensitive data exposure.",
        "check_areas": [
            "Data transmitted in clear text (HTTP)",
            "Weak cryptographic algorithms",
            "Missing HSTS header",
            "Sensitive data in URL parameters",
            "Weak or default encryption keys",
        ],
    },
    "A03": {
        "id": "A03:2021",
        "name": "Injection",
        "description": "User-supplied data is not validated, filtered, or sanitized by the application.",
        "check_areas": [
            "SQL injection in form inputs",
            "NoSQL injection",
            "Command injection",
            "LDAP injection",
            "XPath injection",
            "Template injection (SSTI)",
        ],
    },
    "A04": {
        "id": "A04:2021",
        "name": "Insecure Design",
        "description": "Missing or ineffective security controls in the application design.",
        "check_areas": [
            "Missing rate limiting",
            "No CAPTCHA on critical forms",
            "Lack of input validation patterns",
            "Missing anti-automation controls",
        ],
    },
    "A05": {
        "id": "A05:2021",
        "name": "Security Misconfiguration",
        "description": "Missing appropriate security hardening across the application stack.",
        "check_areas": [
            "Default credentials",
            "Unnecessary features enabled",
            "Missing security headers",
            "Verbose error messages",
            "Directory listing enabled",
            "Outdated software versions",
        ],
    },
    "A06": {
        "id": "A06:2021",
        "name": "Vulnerable and Outdated Components",
        "description": "Using components with known vulnerabilities.",
        "check_areas": [
            "Outdated JavaScript libraries",
            "Known vulnerable frameworks",
            "Unpatched server software",
        ],
    },
    "A07": {
        "id": "A07:2021",
        "name": "Identification and Authentication Failures",
        "description": "Confirmation of the user's identity, authentication, and session management.",
        "check_areas": [
            "Weak password policies",
            "Missing brute force protection",
            "Session fixation",
            "Session token in URL",
            "Missing multi-factor authentication",
            "Credential stuffing vulnerability",
        ],
    },
    "A08": {
        "id": "A08:2021",
        "name": "Software and Data Integrity Failures",
        "description": "Code and infrastructure that does not protect against integrity violations.",
        "check_areas": [
            "Insecure deserialization",
            "CI/CD pipeline vulnerabilities",
            "Unsigned or unverified updates",
            "Untrusted CDN resources without SRI",
        ],
    },
    "A09": {
        "id": "A09:2021",
        "name": "Security Logging and Monitoring Failures",
        "description": "Insufficient logging, detection, monitoring, and active response.",
        "check_areas": [
            "No audit logging",
            "Logs not monitored",
            "Error messages revealing stack traces",
        ],
    },
    "A10": {
        "id": "A10:2021",
        "name": "Server-Side Request Forgery (SSRF)",
        "description": "Web application fetching a remote resource without validating the user-supplied URL.",
        "check_areas": [
            "URL parameters that fetch remote resources",
            "Webhook URLs",
            "File import from URL",
            "PDF generators with URL input",
        ],
    },
}


def get_owasp_checklist() -> str:
    lines = ["# OWASP Top 10 (2021) Security Checklist\n"]
    for key in sorted(OWASP_TOP_10.keys()):
        item = OWASP_TOP_10[key]
        lines.append(f"## {item['id']} — {item['name']}")
        lines.append(f"{item['description']}\n")
        lines.append("Check areas:")
        for area in item["check_areas"]:
            lines.append(f"  - {area}")
        lines.append("")
    return "\n".join(lines)


def get_owasp_category(category_key: str) -> Dict:
    return OWASP_TOP_10.get(category_key, {})


def map_finding_to_owasp(finding_type: str) -> str:
    mapping = {
        "xss": "A03",
        "cross-site scripting": "A03",
        "sql injection": "A03",
        "sqli": "A03",
        "injection": "A03",
        "command injection": "A03",
        "ssti": "A03",
        "template injection": "A03",
        "ssrf": "A10",
        "server-side request forgery": "A10",
        "broken access": "A01",
        "idor": "A01",
        "access control": "A01",
        "cors": "A01",
        "path traversal": "A01",
        "authentication": "A07",
        "auth bypass": "A07",
        "brute force": "A07",
        "session": "A07",
        "password": "A07",
        "credential": "A07",
        "encryption": "A02",
        "cryptographic": "A02",
        "hsts": "A02",
        "tls": "A02",
        "ssl": "A02",
        "http": "A02",
        "security header": "A05",
        "misconfiguration": "A05",
        "default credential": "A05",
        "directory listing": "A05",
        "verbose error": "A05",
        "outdated": "A06",
        "vulnerable component": "A06",
        "cve": "A06",
        "deserialization": "A08",
        "integrity": "A08",
        "logging": "A09",
        "monitoring": "A09",
        "rate limit": "A04",
        "captcha": "A04",
        "insecure design": "A04",
    }

    finding_lower = finding_type.lower()
    for keyword, category in mapping.items():
        if keyword in finding_lower:
            return category
    return "A05"
