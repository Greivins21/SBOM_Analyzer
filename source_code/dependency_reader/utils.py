import re
import json
import time
import requests
import os
from dotenv import load_dotenv

load_dotenv()

# ── Constants ────────────────────────────────────────────────────────────────

GITHUB_API_BASE = "https://api.github.com"

# All dependency file names the tool understands (ordered by priority)
SUPPORTED_DEPENDENCY_FILES = [
    "requirements.txt",   # Python (pip)
    "package.json",       # Node.js / npm
    "Pipfile",            # Python (pipenv)
    "pyproject.toml",     # Python (Poetry / PEP 517)
    "poetry.lock",        # Python (Poetry lockfile)
    "yarn.lock",          # Node.js (Yarn)
    "package-lock.json",  # Node.js (npm lockfile)
    "Gemfile",            # Ruby
    "go.mod",             # Go
    "Cargo.toml",         # Rust
]

# ── Helper: GitHub API request with rate-limit handling ──────────────────────

def _github_get(url: str, retries: int = 3) -> requests.Response | None:
    """
    Performs a GET request to the GitHub API.
    Handles:
      - 403/429 rate-limit responses (waits and retries up to `retries` times).
      - Network / connection errors.
    Returns the Response object on success, None on failure.
    """
    headers = {"Accept": "application/vnd.github+json"}
    
    github_token = os.environ.get("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, headers=headers, timeout=10)

            # Rate-limited
            if response.status_code in (403, 429):
                reset_ts = response.headers.get("X-RateLimit-Reset")
                if reset_ts:
                    wait = max(int(reset_ts) - int(time.time()), 1)
                    print(
                        f"  ⚠  GitHub API rate limit hit. "
                        f"Waiting {wait}s before retry ({attempt}/{retries})…"
                    )
                    time.sleep(wait)
                else:
                    print(
                        f"  ⚠  Rate limited (no reset header). "
                        f"Waiting 60s before retry ({attempt}/{retries})…"
                    )
                    time.sleep(60)
                continue  # retry

            return response

        except requests.exceptions.ConnectionError:
            print("  ✗  Network error: could not reach github.com. Check your connection.")
            return None
        except requests.exceptions.Timeout:
            print(f"  ✗  Request timed out (attempt {attempt}/{retries}).")
            if attempt < retries:
                time.sleep(2)
        except requests.exceptions.RequestException as exc:
            print(f"  ✗  Unexpected request error: {exc}")
            return None

    print("  ✗  All retry attempts exhausted.")
    return None


# ── Step 1: Input & Validation ───────────────────────────────────────────────

def get_repository_link() -> str | None:
    """
    Prompts the user for a public repository URL, validates format and
    reachability, then returns it (or None on failure).
    """
    repo_link = input("Enter the public repository link: ").strip()
    if not repo_link:
        print("✗  No URL entered.")
        return None

    result = validate_repository_link(repo_link)
    if result is True:
        print("✓  Valid public repository.")
        return repo_link
    return None  # error already printed inside validate_repository_link


def validate_repository_link(link: str) -> bool:
    """
    Validates that `link` is a well-formed GitHub/GitLab URL pointing to a
    *public* repository.

    Returns True if valid & public, False otherwise.
    """
    url_pattern = re.compile(
        r"^(https?://)?(www\.)?(github\.com/|gitlab\.com/)"
        r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+"
        r"(/.*)?$"
    )
    if not url_pattern.match(link):
        print("✗  Invalid URL format. Expected: https://github.com/<owner>/<repo>")
        return False

    parts = link.rstrip("/").split("/")
    # Find the index of 'github.com' or 'gitlab.com' in the split URL
    for i, part in enumerate(parts):
        if part in ("github.com", "gitlab.com"):
            try:
                owner, repo = parts[i + 1], parts[i + 2]
            except IndexError:
                print("✗  Could not extract owner/repo from the URL.")
                return False
            break
    else:
        print("✗  Could not locate github.com/gitlab.com in the URL.")
        return False

    # Only GitHub's API is supported for validation
    api_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}"
    response = _github_get(api_url)

    if response is None:
        return False

    if response.status_code == 404:
        print("[ERR] Repository not found (or it is private / does not exist).")
        return False

    if response.status_code == 401:
        print("[ERR] Invalid GitHub Token. Please check the GITHUB_TOKEN in your .env file.")
        return False

    if response.status_code != 200:
        print(f"[ERR] GitHub API returned HTTP {response.status_code} while checking visibility.")
        return False

    repo_data = response.json()
    if repo_data.get("private", True):
        print("✗  Repository is private. Only public repositories are supported.")
        return False

    return True


# ── Step 2: Fetch Metadata ───────────────────────────────────────────────────

def fetch_repository_metadata(repo_link: str) -> list | None:
    """
    Fetches the root-level contents of the repository via the GitHub API.
    Returns a list of file/directory metadata dicts, or None on failure.
    """
    parts = repo_link.rstrip("/").split("/")
    for i, part in enumerate(parts):
        if part in ("github.com", "gitlab.com"):
            owner, repo = parts[i + 1], parts[i + 2].split(".git")[0]
            break
    else:
        print("✗  Cannot parse owner/repo from URL.")
        return None

    api_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents"
    response = _github_get(api_url)

    if response is None:
        return None

    if response.status_code == 200:
        print(f"✓  Fetched root contents for '{owner}/{repo}'.")
        return response.json()
    else:
        print(f"✗  Failed to fetch repository contents. HTTP {response.status_code}.")
        return None


# ── Step 3: Parse Dependencies ───────────────────────────────────────────────

def parse_dependencies(metadata: list) -> dict | None:
    """
    Searches the root-level file listing for a known dependency file.
    Downloads the first match and parses it.

    Returns a dict  {package_name: version_string}  (version may be "" if
    unspecified), or None if no file was found / parsing failed.
    """
    name_to_meta = {item["name"]: item for item in metadata if item.get("type") == "file"}

    for dep_file in SUPPORTED_DEPENDENCY_FILES:
        if dep_file in name_to_meta:
            print(f"  ↳  Dependency file detected: {dep_file}")
            file_meta = name_to_meta[dep_file]
            download_url = file_meta.get("download_url")

            if not download_url:
                print(f"  ⚠  No download URL for '{dep_file}'. Skipping.")
                continue

            try:
                raw = requests.get(download_url, timeout=10)
                raw.raise_for_status()
            except requests.exceptions.RequestException as exc:
                print(f"  ✗  Could not download '{dep_file}': {exc}")
                continue

            deps = parse_file_content(dep_file, raw.text)
            if deps is not None:
                return {"source_file": dep_file, "dependencies": deps}

    print("  ⚠  No supported dependency file found in the repository root.")
    return None


def parse_file_content(file_name: str, content: str) -> dict | None:
    """
    Dispatches to the appropriate parser based on `file_name`.
    Returns a {name: version} dict or None on unrecoverable parse error.
    """
    parsers = {
        "requirements.txt":  _parse_requirements_txt,
        "package.json":      _parse_package_json,
        "Pipfile":            _parse_pipfile,
        "pyproject.toml":    _parse_pyproject_toml,
        "poetry.lock":       _parse_poetry_lock,
        "yarn.lock":         _parse_yarn_lock,
        "package-lock.json": _parse_package_lock_json,
        "Gemfile":           _parse_gemfile,
        "go.mod":            _parse_go_mod,
        "Cargo.toml":        _parse_cargo_toml,
    }
    parser = parsers.get(file_name)
    if parser is None:
        print(f"  ⚠  No parser available for '{file_name}'.")
        return None

    try:
        return parser(content)
    except Exception as exc:
        print(f"  ✗  Error parsing '{file_name}': {exc}")
        return None


# ── Individual Parsers ───────────────────────────────────────────────────────

def _parse_requirements_txt(content: str) -> dict:
    """Parses pip requirements.txt — supports ==, >=, <=, ~=, !=, >, <, and -e git+... installs."""
    deps = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "!")):
            continue

        # Handle editable installs BEFORE stripping #comments,
        # because the egg name lives in the #egg= fragment
        if line.startswith("-e "):
            egg_match = re.search(r"#egg=([A-Za-z0-9_.\-]+)", line)
            if egg_match:
                deps[egg_match.group(1)] = "editable"
            continue

        # Skip other options like -r, --index-url, etc.
        if line.startswith("-"):
            continue

        # Strip inline comments
        line = line.split("#")[0].strip()

        # Extract name and version specifier
        match = re.match(r"^([A-Za-z0-9_.\-\[\]]+)\s*([><!=~,\s0-9.*]+)?", line)
        if match:
            name = match.group(1).strip()
            version = (match.group(2) or "").strip()
            deps[name] = version
    return deps



def _parse_package_json(content: str) -> dict:
    """Parses npm package.json — merges dependencies + devDependencies."""
    data = json.loads(content)
    deps = {}
    deps.update(data.get("dependencies", {}))
    deps.update(data.get("devDependencies", {}))
    return deps


def _parse_pipfile(content: str) -> dict:
    """Parses Pipenv Pipfile (simple TOML-like, no full TOML parser needed)."""
    deps = {}
    in_packages = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped in ("[packages]", "[dev-packages]"):
            in_packages = True
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            in_packages = False
            continue
        if in_packages and "=" in stripped and not stripped.startswith("#"):
            name, _, version = stripped.partition("=")
            deps[name.strip()] = version.strip().strip('"').strip("'")
    return deps


def _parse_pyproject_toml(content: str) -> dict:
    """
    Extracts package dependencies from pyproject.toml.

    Handles two common styles:
      • Poetry  → [tool.poetry.dependencies] / [tool.poetry.dev-dependencies]
                  Each line is:  package = "^1.2.3"
      • PEP 621 → [project] block, looking for the 'dependencies' list
                  Each entry is a PEP 508 string:  "requests>=2.28"

    Skips virtual keys that are not package names (python, name, version, etc.).
    """
    deps: dict = {}

    # ── Poetry style ─────────────────────────────────────────────────────────
    poetry_sections = {
        "[tool.poetry.dependencies]",
        "[tool.poetry.dev-dependencies]",
        "[tool.poetry.group.dev.dependencies]",
    }
    # Non-package keys that appear in Poetry dependency sections
    _SKIP = {"python", "name", "version", "description", "authors", "readme",
              "license", "homepage", "repository", "documentation", "keywords",
              "classifiers", "packages", "include", "exclude"}

    in_poetry_deps = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped in poetry_sections:
            in_poetry_deps = True
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            in_poetry_deps = False
            continue
        if (
            in_poetry_deps
            and "=" in stripped
            and not stripped.startswith("#")
        ):
            name, _, value = stripped.partition("=")
            name = name.strip()
            if name.lower() in _SKIP:
                continue
            # value might be "^1.2.3", {version="^1.2"}, etc.
            version = value.strip().strip('"').strip("'")
            deps[name] = version

    # ── PEP 621 style ────────────────────────────────────────────────────────
    # dependencies = ["requests>=2.28", "click~=8.0"]
    in_project = False
    in_dep_list = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == "[project]":
            in_project = True
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            in_project = False
            in_dep_list = False
            continue
        if in_project:
            if re.match(r"^dependencies\s*=\s*\[", stripped):
                in_dep_list = True
                # Inline single-line list: dependencies = ["a", "b"]
                items = re.findall(r'"([^"]+)"', stripped)
                for item in items:
                    m = re.match(r"^([A-Za-z0-9_.\-\[\]]+)\s*([><=!~,\s0-9.*]+)?", item)
                    if m:
                        deps[m.group(1).strip()] = (m.group(2) or "").strip()
                if "]" in stripped:
                    in_dep_list = False
                continue
            if in_dep_list:
                if "]" in stripped:
                    in_dep_list = False
                    continue
                # Lines like:  "requests>=2.28",
                m2 = re.search(r'"([^"]+)"', stripped)
                if m2:
                    item = m2.group(1)
                    m3 = re.match(r"^([A-Za-z0-9_.\-\[\]]+)\s*([><=!~,\s0-9.*]+)?", item)
                    if m3:
                        deps[m3.group(1).strip()] = (m3.group(2) or "").strip()

    return deps


def _parse_poetry_lock(content: str) -> dict:
    """Extracts locked package versions from poetry.lock."""
    deps = {}
    current_name = None
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == "[[package]]":
            current_name = None
        elif stripped.startswith("name ="):
            current_name = stripped.split("=", 1)[1].strip().strip('"')
        elif stripped.startswith("version =") and current_name:
            version = stripped.split("=", 1)[1].strip().strip('"')
            deps[current_name] = version
            current_name = None
    return deps


def _parse_yarn_lock(content: str) -> dict:
    """Extracts package names and resolved versions from yarn.lock."""
    deps = {}
    current_name = None
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        # Block header: "package-name@^1.0.0:" or multiple separated by ", "
        if not line.startswith(" ") and stripped.endswith(":"):
            # Take the first package name, strip version specifier
            first = stripped.rstrip(":").split(",")[0].strip().strip('"')
            current_name = re.sub(r"@[^@]+$", "", first)
        elif stripped.startswith("version") and current_name:
            version = stripped.split(None, 1)[1].strip().strip('"')
            deps[current_name] = version
            current_name = None
    return deps


def _parse_package_lock_json(content: str) -> dict:
    """Extracts top-level dependencies from package-lock.json (v1 & v2)."""
    data = json.loads(content)
    # v2 / v3 format uses "packages" key, v1 uses "dependencies"
    packages = data.get("packages", {})
    if packages:
        deps = {}
        for pkg_path, meta in packages.items():
            if not pkg_path:  # root package entry
                continue
            name = pkg_path.replace("node_modules/", "")
            deps[name] = meta.get("version", "")
        return deps
    # Fallback to v1
    return {
        name: info.get("version", "")
        for name, info in data.get("dependencies", {}).items()
    }


def _parse_gemfile(content: str) -> dict:
    """Parses Ruby Gemfile — extracts gem name and optional version."""
    deps = {}
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("gem "):
            parts = stripped[4:].split(",")
            name = parts[0].strip().strip("'\"")
            version = parts[1].strip().strip("'\"") if len(parts) > 1 else ""
            deps[name] = version
    return deps


def _parse_go_mod(content: str) -> dict:
    """Parses go.mod — extracts require statements."""
    deps = {}
    in_require = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("require ("):
            in_require = True
            continue
        if in_require and stripped == ")":
            in_require = False
            continue
        if in_require or stripped.startswith("require "):
            entry = stripped.replace("require ", "").strip()
            parts = entry.split()
            if len(parts) >= 2:
                deps[parts[0]] = parts[1]
    return deps


def _parse_cargo_toml(content: str) -> dict:
    """Parses Rust Cargo.toml — extracts [dependencies] section."""
    deps = {}
    in_deps = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped in ("[dependencies]", "[dev-dependencies]", "[build-dependencies]"):
            in_deps = True
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            in_deps = False
            continue
        if in_deps and "=" in stripped and not stripped.startswith("#"):
            name, _, version = stripped.partition("=")
            version = version.strip().strip('"').strip("'").strip("{").strip()
            deps[name.strip()] = version
    return deps


# ── Step 4: Output ───────────────────────────────────────────────────────────

def display_dependencies(result: dict) -> None:
    """Pretty-prints the parsed dependency list to the terminal."""
    source = result.get("source_file", "unknown")
    deps   = result.get("dependencies", {})

    print(f"\n{'─' * 50}")
    print(f"  Source file : {source}")
    print(f"  Packages    : {len(deps)}")
    print(f"{'─' * 50}")

    if not deps:
        print("  (no dependencies found)")
    else:
        max_len = max(len(k) for k in deps)
        for name, version in deps.items():
            ver_str = version if version else "any"
            print(f"  {name:<{max_len}}  {ver_str}")

    print(f"{'─' * 50}\n")


def generate_output(result: dict, path: str = "outputs/output.json") -> None:
    """
    Saves the full result dict (source file + dependencies) to `path` as JSON.
    """
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=4)
        print(f"✓  Saved to '{path}'.")
    except OSError as exc:
        print(f"✗  Could not write output file: {exc}")