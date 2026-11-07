"""
vitality_enricher.py 

Extracts "health" metrics for packages to determine if they are abandoned (Zombies).
Queries public registries (PyPI, npm, crates.io) to find the GitHub repository URL,
and then uses the GitHub API to gather metrics.


"""

import re
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.exceptions import RequestException

from utils import _github_get


# Reusable session with a User-Agent makes requests more efficient (TCP pooling)
# and secure (prevents registries from blocking us as a generic bot).
_session = requests.Session()
_session.headers.update({
    "User-Agent": "DependencyReader/1.0 (Security Academic Project)"
})


def _extract_github_repo(url: str) -> str | None:
    """Securely extracts 'owner/repo' from any github.com URL, ignoring specific paths."""
    if not url or not isinstance(url, str):
        return None
    # Stops matching at the end of the repo name (ignore /issues, /tree/master, etc.)
    match = re.search(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", url)
    if match:
        owner, repo = match.groups()
        if repo.endswith(".git"):
            repo = repo[:-4]
        return f"{owner}/{repo}"
    return None


def _resolve_repo_pypi(package_name: str) -> str | None:
    """Finds the GitHub repo for a PyPI package."""
    try:
        r = _session.get(f"https://pypi.org/pypi/{package_name}/json", timeout=10)
        r.raise_for_status()
        urls = r.json().get("info", {}).get("project_urls", {})
        if urls:
            for url in urls.values():
                repo = _extract_github_repo(url)
                if repo:
                    return repo
    except RequestException:
        pass  # Fail gracefully
    return None


def _resolve_repo_npm(package_name: str) -> str | None:
    """Finds the GitHub repo for an npm package."""
    try:
        r = _session.get(f"https://registry.npmjs.org/{package_name}", timeout=10)
        if r.status_code == 200:
            repo_field = r.json().get("repository")
            if isinstance(repo_field, dict):
                repo_url = repo_field.get("url", "")
            elif isinstance(repo_field, str):
                repo_url = repo_field
            else:
                repo_url = ""
                
            if repo_url:
                # Handle NPM shorthand syntax (e.g. "github:node-formidable/formidable" or "node-formidable/formidable")
                if repo_url.startswith("github:"):
                    repo_url = "https://github.com/" + repo_url[7:]
                elif "://" not in repo_url and repo_url.count("/") == 1:
                    repo_url = "https://github.com/" + repo_url
                    
            return _extract_github_repo(repo_url)
    except RequestException:
        pass
    return None


def _resolve_repo_crates(package_name: str) -> str | None:
    """Finds the GitHub repo for a Rust/Cargo package."""
    try:
        r = _session.get(f"https://crates.io/api/v1/crates/{package_name}", timeout=10)
        r.raise_for_status()
        repo_url = r.json().get("crate", {}).get("repository", "")
        return _extract_github_repo(repo_url)
    except RequestException:
        pass
    return None


def _resolve_repo_go(package_name: str) -> str | None:
    """Finds the GitHub repo for a Go package, handling Go vanity URLs."""
    if package_name.startswith("golang.org/x/"):
        # Map official Go extensions to their GitHub mirrors
        repo = package_name.replace("golang.org/x/", "https://github.com/golang/")
        return _extract_github_repo(repo)
        
    try:
        # Fetch the Go vanity URL which typically contains meta redirect tags
        r = _session.get(f"https://{package_name}?go-get=1", timeout=5)
        if r.status_code == 200:
            # Search the HTML source for any underlying Github repository link
            match = re.search(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", r.text)
            if match:
                owner, repo = match.groups()
                if repo.endswith(".git"):
                    repo = repo[:-4]
                return f"{owner}/{repo}"
    except RequestException:
        pass
    return None


def get_github_repo_for_package(package_name: str, ecosystem: str) -> str | None:
    """
    Attempts to map a package to its GitHub 'owner/repo' using public package registries.
    """
    if "github.com/" in package_name:
        return _extract_github_repo(package_name)

    if ecosystem == "PyPI":
        return _resolve_repo_pypi(package_name)
    elif ecosystem == "npm":
        return _resolve_repo_npm(package_name)
    elif ecosystem == "Go":
        return _resolve_repo_go(package_name)
    elif ecosystem == "crates.io":
        return _resolve_repo_crates(package_name)

    return None


def fetch_github_vital_signs(repo_name: str) -> dict:
    """
    Queries the central GitHub API to gather vital signs for a repository.
    Relies on utils._github_get() which already has robust rate-limit handling.
    """
    vitals = {
        "days_since_last_commit": -1,
        "maintainer_count": 0,
        "is_deprecated": False,
        "open_issues_count": 0,
        "closed_issues_count": 0,
        "stars": 0
    }

    # 1. Main repo metadata
    repo_url = f"https://api.github.com/repos/{repo_name}"
    response = _github_get(repo_url)
    if response and response.status_code == 200:
        repo_data = response.json()
        vitals["is_deprecated"] = repo_data.get("archived", False)
        vitals["open_issues_count"] = repo_data.get("open_issues_count", 0)
        vitals["stars"] = repo_data.get("stargazers_count", 0)

    # 2. Last commit date (efficiently fetch only 1 item)
    commits_url = f"https://api.github.com/repos/{repo_name}/commits?per_page=1"
    response = _github_get(commits_url)
    if response and response.status_code == 200:
        commits_data = response.json()
        if commits_data and isinstance(commits_data, list):
            date_str = commits_data[0]["commit"]["committer"]["date"]
            last_commit = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            vitals["days_since_last_commit"] = (now - last_commit).days

    # 3. Contributors count (Bus Factor)
    contrib_url = f"https://api.github.com/repos/{repo_name}/contributors?per_page=30&anon=true"
    response = _github_get(contrib_url)
    if response and response.status_code == 200:
        contrib_data = response.json()
        if isinstance(contrib_data, list):
            human_contributors = 0
            for contributor in contrib_data:
                ctype = contributor.get("type", "User")
                login = contributor.get("login", "")
                # Ignore GitHub bots and dependabot
                if ctype != "Bot" and not login.endswith("[bot]"):
                    human_contributors += 1
            vitals["maintainer_count"] = human_contributors

    return vitals


def enrich_package_vitality(package_name: str, ecosystem: str) -> dict:
    """
    End-to-end enrichment for a single package.
    Resolves the repo URL and fetches GitHub vital signs.
    """
    repo_name = get_github_repo_for_package(package_name, ecosystem)
    if not repo_name:
        return {"error": "Could not identify GitHub repository for package."}
    
    vitals = fetch_github_vital_signs(repo_name)
    vitals["github_repo"] = repo_name
    return vitals


def enrich_all_packages(dependencies: dict, ecosystem: str) -> dict:
    """
    Takes a mapping of {package_name: version} and parallelizes the 
    fetching of vitality metrics for all using ThreadPoolExecutor.
    """
    results = {}
    print(f"\n Enriching vitality metrics for {len(dependencies)} packages... ", end="", flush=True)

    # Parallel processing ensures high efficiency even with blocking I/O calls
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_pkg = {
            executor.submit(enrich_package_vitality, pkg, ecosystem): pkg
            for pkg in dependencies.keys()
        }
        for future in as_completed(future_to_pkg):
            pkg = future_to_pkg[future]
            try:
                results[pkg] = future.result()
            except Exception as e:
                results[pkg] = {"error": f"Enrichment failed: {str(e)}"}
    
    print("done.")
    return results
