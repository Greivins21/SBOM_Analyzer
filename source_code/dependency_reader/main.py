"""
Dependency Reader — main entry point.

Usage:
    python main.py [--no-save]

Flags:
    --no-save   Print dependencies to the terminal only (skip output.json).

Workflow:
    1. Prompt for a public repository URL
    2. Validate it (format + public visibility via GitHub API)
    3. Fetch the repository's root file listing
    4. Locate and parse the first supported dependency file
    5. Display results in the terminal
    6. Optionally save to output.json

Supported dependency files (checked in this order):
    requirements.txt, package.json, Pipfile, pyproject.toml,
    poetry.lock, yarn.lock, package-lock.json, Gemfile, go.mod, Cargo.toml

Setup:
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    python main.py

Try:
    python main.py --no-save
    https://github.com/boto/boto3 0 
    https://github.com/axios/axios 100
    https://github.com/gin-gonic/gin 100 
    https://github.com/ansible/ansible 83 

now check if they're deprecated - vulnerability checker 
- OSV API (Open Source Vulnerabilities)  https://osv.dev 

Authentication (Optional but Recommended):
    The app reads from the GitHub API. Without a token, GitHub limits your IP
    to 60 requests per hour. By providing a Personal Access Token (with NO scopes
    selected) via the `.env` file, the limit is boosted to 5,000 requests per hour.
    
    Setup your token in .env:
    GITHUB_TOKEN=ghp_yourtokenhere
"""

import sys
from utils import (
    get_repository_link,
    fetch_repository_metadata,
    parse_dependencies,
    display_dependencies,
    generate_output,
)
from vulnerability_checker import check_vulnerabilities, _get_ecosystem
from vitality_enricher import enrich_all_packages
from risk_scorer import generate_zombie_report, save_zombie_report_json

### Previous main function (before refactor to run web):  
def main() -> None:
    print("\n=== Dependency Reader & Zombie Scanner ===\n")

    # Check flags
    save_json = "--no-save" not in sys.argv

    # Step 1 — get & validate repository link
    repo_link = get_repository_link()
    if not repo_link:
        sys.exit(1)

    # Step 2 — fetch root-level file listing
    metadata = fetch_repository_metadata(repo_link)
    if metadata is None:
        print("[ERR] Could not retrieve repository metadata. Exiting.")
        sys.exit(1)

    # Step 3 — parse dependencies
    result = parse_dependencies(metadata)
    if result is None:
        print("No dependencies to display.")
        sys.exit(0)

    # Step 4 — display in terminal
    display_dependencies(result)

    # Step 5 — check vulnerabilities via OSV API (Phase 1)
    scan_result = check_vulnerabilities(result)

    # Step 6 — save output.json
    if save_json and scan_result:
        generate_output(scan_result)

    # Step 7 — enrich with GitHub Vitality Metrics (Phase 2)
    ecosystem = _get_ecosystem(result["source_file"])
    vitals_map = enrich_all_packages(result["dependencies"], ecosystem)

    # Step 8 — generate Zombie Report
    report = generate_zombie_report(repo_link, scan_result, vitals_map)

    # Display a quick summary of Zombies
    zombies_count = report["scan_info"]["zombies_found"]
    vulnerabilities_count = report["scan_info"]["vulnerable_found"]
    repo_score = report["scan_info"]["repo_risk_score_100"]
    repo_status = report["scan_info"]["repo_status"]

    # Print Metrics for EVERY package FIRST
    all_packages = report.get("analysis", [])
    if all_packages:
        print(f"  \n  [PACKAGE VITALITY METRICS]")
        print(f"  * Risk Score = CVEs (up to 50) + Inactivity (up to 20) + Bus Factor (up to 15) + Neglect (up to 15)")
        print(f"  ───────────────────────────────────────────────────")
        for pkg in all_packages:
            m = pkg["metrics"]
            dep_msg = " (DEPRECATED)" if m.get("is_deprecated") else ""
            zomb_msg = " [ZOMBIE!]" if pkg.get("status") == "ZOMBIE" else ""
            
            print(f"  {pkg['package']}{dep_msg}{zomb_msg}")
            print(f"    Days since last commit : {m.get('days_since_last_commit', 'Error')}")
            print(f"    Open issues            : {m.get('open_issues', 'Error')}")
            print(f"    Maintainers (Bus Fact) : {m.get('maintainer_count', 'Error')}")
            print(f"    Risk Score             : {pkg.get('risk_score_100', 0)} / 100")
            print()

    # Display a quick summary of Zombies
    print(f"  ───────────────────────────────────────────────────")
    print(f"  Zombie Scan Complete")
    print(f"  ───────────────────────────────────────────────────")
    print(f"  Vulnerable Packages found: {vulnerabilities_count}")
    print(f"  Zombie (Unmaintained) Packages found: {zombies_count}")
    print(f"  ───────────────────────────────────────────────────")
    print(f"  PEAK REPOSITORY SECURITY SCORE    : {repo_score} / 100  (Weakest Link)")
    print(f"  WEIGHTED MEAN SECURITY SCORE      : {report['scan_info'].get('weighted_mean_score_100', 0)} / 100  (Overall Trend)")
    print(f"  STATUS                            : {repo_status}")
    print(f"  ───────────────────────────────────────────────────")

    print(f"  Risk Score Formula (0-100):")
    print(f"  CVEs (up to 50) + Inactivity (up to 20) +")
    print(f"  Bus Factor (up to 15) + Issue Neglect (up to 15)")
    print(f"  ───────────────────────────────────────────────────\n")

    # Step 9 — save zombie_report.json
    if save_json:
        save_zombie_report_json(report)
    else:
        print("\n(Reports skipped — --no-save flag set)\n")


if __name__ == "__main__":
    main()