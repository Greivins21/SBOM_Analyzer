"""
api.py — Dependency Reader REST API

References
- https://github.com/zhanymkanov/fastapi-best-practices
- https://github.com/tiangolo/full-stack-fastapi-template
- https://github.com/laurentS/slowap

Serves the vulnerability scan output for use in the web UI.

Endpoints:
    GET  /report         Return the last saved output.json
    POST /scan           Trigger a new scan for a given repo URL

Security:
    - CORS restricted to ALLOWED_ORIGINS in .env
    - Rate limiting via slowapi (10 scans/minute per IP)
    - Security headers on every response
    - Input validated via Pydantic before any processing
    - GITHUB_TOKEN never exposed in responses
    - Generic error messages to avoid leaking internals

Run:
    uvicorn api:app --host 0.0.0.0 --port 8000 --reload

.env keys used:
    GITHUB_TOKEN   — GitHub PAT (optional, boosts rate limit)
    ALLOWED_ORIGINS — comma-separated list of allowed CORS origins
                      e.g. http://localhost:3000,https://yoursite.com

try scan

curl -X 'POST' \
  'http://localhost:8000/scan' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "repo_url": "https://github.com/axios/axios"
}'

"""

import json
import os
from pathlib import Path
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

import asyncio
from concurrent.futures import ThreadPoolExecutor

# ── Load environment ────────────────────────────────────────────────────────
load_dotenv()

OUTPUT_FILE = Path(__file__).parent / "outputs" / "output.json"

# CORS: read from .env — defaults to localhost only for safety
_raw_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000")
ALLOWED_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()]

# Thread pool for running the blocking scan in the background
# We use max_workers=10 because vitality enrichment is highly I/O-bound (network calls).
# Increasing this resolves the concurrency bottleneck when scanning large repos.
_executor = ThreadPoolExecutor(max_workers=10)

# ── Rate limiter ─────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])


# ── App factory ──────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    _executor.shutdown(wait=False)


app = FastAPI(
    title="Ship Happens - Dependency Scanner API",
    description="Fetch and scan GitHub repository dependencies for vulnerabilities.",
    version="1.0.0",
    lifespan=lifespan,
    root_path="/api"
    # Disable auto-generated docs in production if needed:
    # docs_url=None, redoc_url=None,
)

# ── Middleware: CORS ──────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# ── Middleware: Security headers ──────────────────────────────────────────────
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response

# ── Rate limit error handler ──────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── Pydantic models ───────────────────────────────────────────────────────────
class ScanRequest(BaseModel):
    repo_url: str

    @field_validator("repo_url")
    @classmethod
    def validate_github_url(cls, v: str) -> str:
        v = v.strip()
        if "gitlab.com" in v:
            raise ValueError("GitLab repositories are not currently supported. Please provide a GitHub URL.")
        if not v.startswith("https://github.com/"):
            raise ValueError("Only public GitHub URLs are supported (https://github.com/...).")
        parts = v.rstrip("/").split("/")
        # must have at least owner + repo after github.com
        if len(parts) < 5:
            raise ValueError("URL must be in the format https://github.com/<owner>/<repo>.")
        return v


# ── Helpers ───────────────────────────────────────────────────────────────────
def _run_scan(repo_url: str) -> dict:
    """Runs the full scan pipeline synchronously (called in thread pool)."""
    from utils import (
        validate_repository_link,
        fetch_repository_metadata,
        parse_dependencies,
        generate_output,
    )
    from vulnerability_checker import check_vulnerabilities

    if not validate_repository_link(repo_url):
        raise ValueError("Repository validation failed.")

    metadata = fetch_repository_metadata(repo_url)
    if metadata is None:
        raise RuntimeError("Could not fetch repository metadata.")

    result = parse_dependencies(metadata)
    if result is None:
        raise RuntimeError("No supported dependency file found in the repository root.")

    result = check_vulnerabilities(result)
    generate_output(result)
    return result


def _run_zombie_scan(repo_url: str) -> dict:
    """Runs Phase 2: Vulnerability Scan + Github Vital Signs -> Risk Score."""
    from utils import (
        validate_repository_link,
        fetch_repository_metadata,
        parse_dependencies,
    )
    from vulnerability_checker import check_vulnerabilities, _get_ecosystem
    from vitality_enricher import enrich_all_packages
    from risk_scorer import generate_zombie_report, save_zombie_report_json

    if not validate_repository_link(repo_url):
        raise ValueError("Repository validation failed.")

    # FORCE CRASH TO TEST TASK 4
    # raise Exception("Simulated Internal Server Error: Database timeout!")

    metadata = fetch_repository_metadata(repo_url)
    if metadata is None:
        raise RuntimeError("Could not fetch repository metadata.")

    result = parse_dependencies(metadata)
    if result is None:
        raise RuntimeError("No supported dependency file found in the repository root.")

    # 1. Run standard vulnerability scan
    scan_result = check_vulnerabilities(result)
    
    # 2. Enrich with vitality (GitHub metrics)
    ecosystem = _get_ecosystem(result["source_file"])
    vitals_map = enrich_all_packages(result["dependencies"], ecosystem)
    
    # 3. Generate Zombie Report
    report = generate_zombie_report(repo_url, scan_result, vitals_map)
    
    # Enrich report with source file info for the frontend
    report["source_file"] = result.get("source_file", "unknown")
    report["dependencies"] = result.get("dependencies", {})
    
    # Save the output file
    target_path = str(Path(__file__).parent / "outputs" / "zombie_report.json")
    save_zombie_report_json(report, target_path)
    
    return report


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/report", summary="Return the latest vulnerability report")
@limiter.limit("60/minute")
async def get_report(request: Request):
    """
    Returns the contents of the last generated output.json (Phase 1).
    """
    if not OUTPUT_FILE.exists():
        raise HTTPException(
            status_code=404,
            detail="No report found. Run POST /scan to generate one."
        )
    try:
        data = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        raise HTTPException(status_code=500, detail="Failed to read report file.")
    return JSONResponse(content=data)


@app.post("/scan", summary="Trigger a new vulnerability scan")
@limiter.limit("10/minute")
async def post_scan(request: Request, body: ScanRequest):
    """
    Phase 1 pipeline: CVE check only, saves output.json.
    """
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(_executor, _run_scan, body.repo_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred during the scan.")

    return JSONResponse(content=result)


@app.get("/zombie-report", summary="Return the latest zombie report")
@limiter.limit("60/minute")
async def get_zombie_report(request: Request):
    """
    Returns the contents of the last generated zombie_report.json (Phase 2).
    """
    zombie_file = Path(__file__).parent / "outputs" / "zombie_report.json"
    if not zombie_file.exists():
        raise HTTPException(
            status_code=404,
            detail="No report found. Run POST /zombie-scan to generate one."
        )
    try:
        data = json.loads(zombie_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        raise HTTPException(status_code=500, detail="Failed to read report file.")
    return JSONResponse(content=data)


@app.post("/zombie-scan", summary="Trigger a full Zombie detection scan")
@limiter.limit("100/minute")
async def post_zombie_scan(request: Request, body: ScanRequest):
    """
    Phase 2 pipeline: Vulnerability Scan + Github Vital Signs.
    Saves and returns zombie_report.json.
    """
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(_executor, _run_zombie_scan, body.repo_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        print(f"[ERROR] Internal scan error: {exc}")
        raise HTTPException(status_code=500, detail="An internal error occurred. Please try again.")

    return JSONResponse(content=result)


@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}
