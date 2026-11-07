"""
risk_scorer.py 

Implements the "Zombie Packages" logic.
Combines data from the OSV API (CVE checking) and the GitHub API (vitality signs)
to dynamically rank the risk of every dependency in a codebase.

bus factor 
- number of active maintainer 

"""

import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config", "heuristic_config.json")
try:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        CONFIG = json.load(f)
except Exception:
    CONFIG = {}

WEIGHTS = CONFIG.get("weights", {})
ZOMBIE_RULES = CONFIG.get("zombie_rules", {})
THRESHOLDS = CONFIG.get("thresholds", {})

def calculate_package_risk(package_name: str, version: str, cve_details: list, vitals: dict) -> dict:
    """
    HEURISTIC SCORING LOGIC
    =======================
    This calculates the overall risk score based on the parameters defined in the config.json.
    
    1. Security Risk: Measured by active CVEs from the OSV API.
    2. Maintenance Risk: Measured by vitality metrics from GitHub API.
    """

    # Extract clean baseline metrics
    cve_count = len(cve_details)
    
    cve_penalty = WEIGHTS.get("cve_penalty_per_vuln", 10)
    cve_max = WEIGHTS.get("cve_max", 50)
    
    # Handle packages where GitHub enrichment failed
    if "error" in vitals:
        return {
            "package": package_name,
            "version": version,
            "status": "UNKNOWN (Vitality Fetch Failed)",
            "risk_score_100": min(cve_count * cve_penalty, cve_max),
            "cve_count": cve_count,
            "metrics": vitals,
            "risk_level": "HIGH" if cve_count > 0 else "LOW",
            "recommendation": "Check manually. Could not retrieve GitHub metadata."
        }

    days_old = vitals.get("days_since_last_commit", 0)
    open_issues = vitals.get("open_issues_count", 0)
    maintainers = vitals.get("maintainer_count", 0)
    is_deprecated = vitals.get("is_deprecated", False)

    # 1. Calculate Numeric Score (0 - 100)
    numeric_score = 0
    if is_deprecated:
        numeric_score = 100
    else:
        cve_score = min(cve_count * cve_penalty, cve_max)
        
        inactivity_score = min((days_old / 365.0) * WEIGHTS.get("inactivity_penalty_per_year", 20), WEIGHTS.get("inactivity_max", 20))
        
        bus_score = WEIGHTS.get("bus_factor_penalty", 15) if maintainers <= ZOMBIE_RULES.get("bus_factor_max", 1) else 0
        
        neglect_score = min((open_issues / 50.0) * WEIGHTS.get("neglect_penalty_per_50_issues", 15), WEIGHTS.get("neglect_max", 15))
        
        numeric_score = int(cve_score + inactivity_score + bus_score + neglect_score)
        numeric_score = min(numeric_score, 100)

    # 2. Determine Zombie Status
    is_zombie = False
    
    if is_deprecated:
        is_zombie = True
    elif (days_old > ZOMBIE_RULES.get("inactivity_days_threshold", 365)) and (open_issues > ZOMBIE_RULES.get("open_issues_threshold", 50)) and (maintainers <= ZOMBIE_RULES.get("bus_factor_max", 1)):
        is_zombie = True

    status = "ZOMBIE" if is_zombie else "ACTIVE"

    # 3. Calculate Final Risk Level
    if is_zombie and cve_count > 0:
        risk_level = "CRITICAL"
        recommendation = "IMMEDIATE ACTION REQUIRED: Package has vulnerabilities and is completely unmaintained. Replace immediately."
    elif cve_count > 0:
        risk_level = "HIGH"
        recommendation = "Update package to patch known vulnerabilities."
    elif is_zombie:
        risk_level = "MEDIUM"
        recommendation = "Package is dead. Technical debt warning. Plan migration to active alternative."
    else:
        risk_level = "LOW"
        recommendation = "Package is healthy and actively maintained."

    return {
        "package": package_name,
        "version": version,
        "status": status,
        "risk_score_100": numeric_score,
        "cve_count": cve_count,
        "cve_details": cve_details,   # expose raw CVE list to frontend
        "metrics": {
            "days_since_last_commit": days_old,
            "maintainer_count": maintainers,
            "open_issues": open_issues,
            "is_deprecated": is_deprecated,
            "github_repo": vitals.get("github_repo", "Unknown")
        },
        "risk_level": risk_level,
        "recommendation": recommendation
    }


def generate_zombie_report(repository_url: str, scanned_deps: dict, enriched_vitals: dict) -> dict:
    """
    Takes the full scan results (vulnerabilities + vitals) and builds the final JSON report.
    
    scanned_deps: From vulnerability_checker.py (contains {"vulnerability_report": {"vulnerable_packages": [...], "clean_packages": [...]}})
    enriched_vitals: From vitality_enricher.py
    """
    analysis = []
    total_zombies = 0
    total_deps = 0

    report_data = scanned_deps.get("vulnerability_report", {})

    # Process Vulnerable Packages
    for pkg in report_data.get("vulnerable_packages", []):
        name = pkg["package"]
        version = pkg["version"]
        cve_details = pkg["vulnerabilities"]
        vitals = enriched_vitals.get(name, {"error": "Missing info"})
        
        report = calculate_package_risk(name, version, cve_details, vitals)
        if report["status"] == "ZOMBIE":
            total_zombies += 1
        total_deps += 1
        analysis.append(report)

    # Process Clean Packages (No CVEs, but might be Zombies)
    for pkg_name in report_data.get("clean_packages", []):
        name = pkg_name
        version = scanned_deps.get("dependencies", {}).get(name, "unknown")
        cve_details = []  # Empty because clean
        vitals = enriched_vitals.get(name, {"error": "Missing info"})

        report = calculate_package_risk(name, version, cve_details, vitals)
        if report["status"] == "ZOMBIE":
            total_zombies += 1
        total_deps += 1
        analysis.append(report)

    # Sort analysis by Risk (CRITICAL -> HIGH -> MEDIUM -> LOW)
    risk_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    analysis.sort(key=lambda x: risk_order.get(x["risk_level"], 4))

    # Calculate overall repo score (A repository is only as secure as its weakest link)
    max_score = 0
    weighted_mean_score = 0
    
    if analysis:
        max_score = max(pkg["risk_score_100"] for pkg in analysis)
        weighted_mean_score = int(sum(pkg["risk_score_100"] for pkg in analysis) / len(analysis))
        
    if max_score >= THRESHOLDS.get("dangerous_min", 70):
        repo_status = "DANGEROUS (High probability of supply chain attack)"
    elif max_score >= THRESHOLDS.get("warning_min", 40):
        repo_status = "WARNING (Approaching technical debt limits)"
    else:
        repo_status = "SAFE (Healthy dependency tree)"

    return {
        "repository": repository_url,
        "scan_info": {
            "total_dependencies": total_deps,
            "zombies_found": total_zombies,
            "vulnerable_found": len(report_data.get("vulnerable_packages", [])),
            "repo_risk_score_100": max_score,
            "weighted_mean_score_100": weighted_mean_score,
            "repo_status": repo_status
        },
        "analysis": analysis
    }


def save_zombie_report_json(report: dict, filepath: str = "outputs/zombie_report.json"):
    """Writes the final output as JSON."""
    import os
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=4)
    print(f"✓ Zombie report saved directly to '{filepath}'")
