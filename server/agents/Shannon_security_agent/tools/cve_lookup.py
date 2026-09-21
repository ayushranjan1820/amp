import re
from typing import Dict, Any, List


KNOWN_VULNERABILITIES = {
    "apache": {
        "2.4.49": [
            {"cve": "CVE-2021-41773", "severity": "Critical", "description": "Path traversal and remote code execution via crafted request URIs"},
            {"cve": "CVE-2021-42013", "severity": "Critical", "description": "Path traversal fix bypass allowing RCE"},
        ],
        "2.4.50": [
            {"cve": "CVE-2021-42013", "severity": "Critical", "description": "Incomplete fix for CVE-2021-41773 path traversal"},
        ],
        "2.4.48": [
            {"cve": "CVE-2021-36160", "severity": "High", "description": "mod_proxy_uwsgi out-of-bounds read"},
        ],
        "_old_threshold": "2.4.52",
        "_old_message": "Apache versions before 2.4.52 have multiple known vulnerabilities. Upgrade recommended.",
    },
    "nginx": {
        "1.20.0": [
            {"cve": "CVE-2021-23017", "severity": "High", "description": "DNS resolver vulnerability allowing crash or code execution"},
        ],
        "_old_threshold": "1.25.0",
        "_old_message": "Nginx versions before 1.25.0 have known vulnerabilities including HTTP/2 rapid reset attack (CVE-2023-44487).",
    },
    "gunicorn": {
        "_old_threshold": "21.2.0",
        "_old_message": "Gunicorn versions before 21.2.0 may have HTTP request smuggling vulnerabilities. Upgrade recommended.",
        "19.9.0": [
            {"cve": "CVE-2018-1000164", "severity": "Medium", "description": "HTTP request smuggling via invalid Transfer-Encoding headers"},
        ],
        "20.0.0": [
            {"cve": "CVE-2018-1000164", "severity": "Medium", "description": "HTTP request smuggling via invalid Transfer-Encoding headers (partially fixed)"},
        ],
    },
    "express": {
        "_old_threshold": "4.18.0",
        "_old_message": "Express versions before 4.18.0 have known path traversal and open redirect vulnerabilities.",
    },
    "php": {
        "_old_threshold": "8.2.0",
        "_old_message": "PHP versions before 8.2.0 have multiple known vulnerabilities including buffer overflows and type confusion bugs.",
        "7.4": [
            {"cve": "CVE-2023-3247", "severity": "Medium", "description": "Missing error check and insufficient random bytes in HTTP Digest authentication"},
        ],
        "8.0": [
            {"cve": "CVE-2022-31631", "severity": "Medium", "description": "PDO::quote() integer overflow"},
        ],
    },
    "openssl": {
        "_old_threshold": "3.0.8",
        "_old_message": "OpenSSL versions before 3.0.8 have known vulnerabilities including X.400 buffer overflow (CVE-2023-0286).",
        "3.0.0": [
            {"cve": "CVE-2022-3602", "severity": "High", "description": "X.509 Email Address buffer overflow"},
        ],
    },
    "wordpress": {
        "_old_threshold": "6.4.0",
        "_old_message": "WordPress versions before 6.4.0 have known XSS and CSRF vulnerabilities.",
    },
    "jquery": {
        "_old_threshold": "3.5.0",
        "_old_message": "jQuery versions before 3.5.0 have known XSS vulnerabilities in htmlPrefilter (CVE-2020-11022, CVE-2020-11023).",
        "1.12.4": [
            {"cve": "CVE-2020-11022", "severity": "Medium", "description": "XSS via htmlPrefilter"},
            {"cve": "CVE-2015-9251", "severity": "Medium", "description": "XSS via cross-domain ajax request"},
        ],
        "2.2.4": [
            {"cve": "CVE-2020-11022", "severity": "Medium", "description": "XSS via htmlPrefilter"},
        ],
        "3.4.1": [
            {"cve": "CVE-2020-11022", "severity": "Medium", "description": "XSS via htmlPrefilter"},
        ],
    },
    "iis": {
        "_old_threshold": "10.0",
        "_old_message": "Older IIS versions have known vulnerabilities. Ensure latest security patches are applied.",
    },
    "tomcat": {
        "_old_threshold": "10.1.0",
        "_old_message": "Tomcat versions before 10.1.0 have known vulnerabilities including request smuggling and information disclosure.",
        "9.0.43": [
            {"cve": "CVE-2021-25122", "severity": "Medium", "description": "Request mix-up with h2c"},
        ],
    },
}


def _parse_version(version_str: str) -> str:
    match = re.search(r'(\d+(?:\.\d+)*)', version_str)
    return match.group(1) if match else ""


def _version_compare(v1: str, v2: str) -> int:
    parts1 = [int(x) for x in v1.split(".")]
    parts2 = [int(x) for x in v2.split(".")]
    max_len = max(len(parts1), len(parts2))
    parts1.extend([0] * (max_len - len(parts1)))
    parts2.extend([0] * (max_len - len(parts2)))
    for a, b in zip(parts1, parts2):
        if a < b:
            return -1
        elif a > b:
            return 1
    return 0


def lookup_cves(technologies: List[str], server_header: str = "") -> Dict[str, Any]:
    result = {
        "findings": [],
        "technologies_checked": [],
        "stats": {
            "technologies_analyzed": 0,
            "cves_found": 0,
        },
    }

    items_to_check = []

    if server_header:
        items_to_check.append(server_header)
    items_to_check.extend(technologies)

    for tech_str in items_to_check:
        tech_lower = tech_str.lower()

        for product_key, product_data in KNOWN_VULNERABILITIES.items():
            if product_key not in tech_lower:
                continue

            version = _parse_version(tech_str)
            if not version:
                continue

            result["technologies_checked"].append({
                "raw": tech_str,
                "product": product_key,
                "version": version,
            })
            result["stats"]["technologies_analyzed"] += 1

            exact_cves = product_data.get(version, [])
            for cve in exact_cves:
                result["findings"].append({
                    "title": f"Known Vulnerability: {cve['cve']} in {product_key} {version}",
                    "severity": cve["severity"],
                    "owasp_category": "A06:2021 — Vulnerable and Outdated Components",
                    "location": f"Detected: {tech_str}",
                    "description": f"{cve['description']} (affects {product_key} {version})",
                    "evidence": f"Server header or technology detection identified '{tech_str}'. "
                                f"Version {version} is known to be affected by {cve['cve']}.",
                    "recommendation": f"Upgrade {product_key} to the latest stable version. Apply security patches immediately.",
                })
                result["stats"]["cves_found"] += 1

            threshold = product_data.get("_old_threshold", "")
            old_msg = product_data.get("_old_message", "")
            if threshold and old_msg and not exact_cves:
                try:
                    if _version_compare(version, threshold) < 0:
                        result["findings"].append({
                            "title": f"Outdated {product_key.title()} Version: {version}",
                            "severity": "Medium",
                            "owasp_category": "A06:2021 — Vulnerable and Outdated Components",
                            "location": f"Detected: {tech_str}",
                            "description": old_msg,
                            "evidence": f"Server header or technology detection identified '{tech_str}'. "
                                        f"Version {version} is below the recommended threshold of {threshold}.",
                            "recommendation": f"Upgrade {product_key} to version {threshold} or later.",
                        })
                        result["stats"]["cves_found"] += 1
                except (ValueError, IndexError):
                    pass

    return result
