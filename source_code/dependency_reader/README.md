# Dependency Reader & Zombie Scanner

A fast, cross-ecosystem Supply Chain Security Assessment tool. It connects directly to public package registries and GitHub to perform a full-stack security audit of an entire repository's dependency tree.

## Core Features

* **Zombie Package Detection:** Identifies unmaintained, abandoned dependencies that pose a sleeper-cell security risk.
* **Cross-Ecosystem Resolution:** Analyzes `package.json`, `requirements.txt`, `go.mod`, and more. Correctly resolves Go Vanity URLs and NPM shorthands to their actual GitHub source repos.
* **Zero-Setup APIs:** Leverages direct integration with the free GitHub API and the OSV (Open Source Vulnerability) database. No expensive third-party keys required.
* **Unified Reporting:** Generates a real-time terminal dashboard and a structured `zombie_report.json`.

---

## How to Use

### 1. Setup
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```
*Optional but recommended:* Create a `.env` file in the root directory to configure the environment:
```env
GITHUB_TOKEN=ghp_your_personal_access_token # Drastically boosts API rate limits
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173,https://yoursite.com # Required for Web UI CORS
```

### 2. Run the CLI Scanner
The fastest way to scan a repository:
```bash
python main.py
```
*You will be prompted to paste a direct GitHub repository URL 

#### URLS tried so far 
- https://github.com/boto/boto3 (0) 
- https://github.com/axios/axios (100)
- https://github.com/gin-gonic/gin (100) 
- https://github.com/ansible/ansible (83) 

### 3. Run the REST API
If you want to integrate this tool into a web dashboard, you can launch the FastAPI server:
```bash
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```
* **POST `/scan`**: Scan a repository for standard OSV vulnerabilities.
* **POST `/zombie-scan`**: Scan for both vulnerabilities and abandoned (Zombie) vital signs.
* **GET `/docs`**: View the interactive Swagger endpoints.

---

## The Risk Score Heuristic (0 to 100)

Instead of overwhelming developers with plain text data, the **Risk Scorer** mathematically computes the danger of every dependency on a scale of `0` (Completely Safe) to `100` (Highly Dangerous / Zombie).

The score is calculated using four specific safety pillars:

* **CVEs (+ up to 50 pts):** Adds 10 points for every known vulnerability found in the OSV database.
* **Inactivity (+ up to 20 pts):** Adds 10 points for every 6 months without a commit.
* **Bus Factor (+ 15 pts):** Fully penalizes packages currently maintained by 1 or fewer active contributors.
* **Issue Neglect (+ up to 15 pts):** Adds 5 points for every 20 neglected open issues.

*Note: Any package that breaches 100 points, or has a direct explicit "deprecated" flag from its registry, is permanently marked as a **[ZOMBIE!]** package.*

## Overall Repository Heuristic

A repository is only as secure as its weakest link. Therefore, the **Overall Repository Security Score** is equivalent to the *highest* risk score found among any of its individual dependencies.

The repository is then graded into three tiers:
* **`SAFE`** (Score: 0-50): Strong maintenance and active security patching.
* **`WARNING`** (Score: 51-70): Aging dependencies or minor low-level vulnerabilities present.
* **`DANGEROUS`** (Score: 71-100): High probability of a supply chain attack due to severely critical CVEs or entirely abandoned dependencies.
