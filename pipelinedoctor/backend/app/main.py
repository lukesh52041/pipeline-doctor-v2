import asyncio
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import db, github
from .config import get_settings
from .diagnose import diagnose
from .flaky import detect_flaky
from .report import weekly_report
from .risk import score_risk
from .samples import SAMPLES, get_sample
from .tinyfish_service import perform_research

log = logging.getLogger("pipelinedoctor")
FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
RANK = {"developer": 1, "lead": 2, "admin": 3}


@asynccontextmanager
async def lifespan(_app):
    db.init_db()
    yield


app = FastAPI(title="PipelineDoctor", version="1.0.0", lifespan=lifespan)


def require_role(minimum: str):
    def dependency(x_api_key: str | None = Header(default=None)) -> str:
        keys = get_settings().api_keys
        if not keys:  # local development: no keys configured
            return "admin"
        if not x_api_key:
            raise HTTPException(401, "Missing API key. Send it in the X-API-Key header.")
        role = next((r for k, r in keys.items() if secrets.compare_digest(k.encode(), x_api_key.encode())), None)
        if role is None:
            raise HTTPException(401, "Invalid API key.")
        if RANK.get(role, 0) < RANK[minimum]:
            raise HTTPException(403, f"Access denied: this action needs the {minimum} role.")
        return role
    return dependency


class DiagnoseRequest(BaseModel):
    log: str = Field(min_length=1)
    repo: str = "demo/repo"
    run_id: str | None = None
    commit_sha: str | None = None
    branch: str | None = None
    duration_s: int = 0
    use_llm: bool = True
    use_research: bool = True


class ResearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    location: str | None = None
    language: str | None = None


class RiskRequest(BaseModel):
    repo: str = "demo/repo"
    files: list[str] = Field(min_length=1, max_length=2000)
    additions: int = 0
    deletions: int = 0


@app.get("/api/health")
def health():
    settings = get_settings()
    has_tinyfish_key = bool(settings.tinyfish_api_key or os.getenv("TINYFISH_API_KEY"))
    return {
        "status": "ok",
        "ai_enabled": bool(settings.anthropic_api_key),
        "tinyfish_enabled": bool(settings.tinyfish_enabled and has_tinyfish_key),
    }


@app.get("/api/samples")
def list_samples():
    return [{"id": s["id"], "title": s["title"]} for s in SAMPLES]


@app.get("/api/samples/{sample_id}")
def sample(sample_id: str):
    s = get_sample(sample_id)
    if not s:
        raise HTTPException(404, "Sample not found.")
    return s


@app.post("/api/diagnose")
async def api_diagnose(req: DiagnoseRequest, role: str = Depends(require_role("developer"))):
    if len(req.log.encode()) > get_settings().max_log_bytes:
        raise HTTPException(413, "Log is too large. Send the part from the first failing step.")
    run_pk = db.record_run(req.repo, req.run_id, req.commit_sha, req.branch, "failed", req.duration_s)
    diag = await diagnose(req.log, use_llm=req.use_llm, use_research=req.use_research)
    tests = diag.pop("tests", [])
    diag_id = db.save_diagnosis(run_pk, req.repo, diag)
    db.save_tests(run_pk, req.repo, req.commit_sha, tests)
    db.audit(role, "diagnose", f"repo={req.repo} id={diag_id}")
    diag["id"] = diag_id
    return diag


@app.post("/api/research")
async def api_research(req: ResearchRequest, role: str = Depends(require_role("developer"))):
    cleaned_query = req.query.strip()
    if not cleaned_query:
        raise HTTPException(422, "Query cannot be empty.")
    settings = get_settings()
    location = req.location or settings.tinyfish_location
    language = req.language or settings.tinyfish_language
    api_key = settings.tinyfish_api_key or os.getenv("TINYFISH_API_KEY")
    db.audit(role, "research", f"query={cleaned_query[:100]}")
    res = await asyncio.to_thread(
        perform_research,
        cleaned_query,
        location=location,
        language=language,
        api_key=api_key,
    )
    return res


@app.get("/api/diagnoses")
def api_list(repo: str | None = None, limit: int = 50, _role: str = Depends(require_role("developer"))):
    return db.list_diagnoses(repo, limit)


@app.get("/api/diagnoses/{diag_id}")
def api_get(diag_id: int, _role: str = Depends(require_role("developer"))):
    data = db.get_diagnosis(diag_id)
    if not data:
        raise HTTPException(404, "Diagnosis not found.")
    return data


@app.post("/api/risk")
def api_risk(req: RiskRequest, _role: str = Depends(require_role("developer"))):
    total, failed = db.run_counts(req.repo, 30)
    rate = failed / total if total else 0.0
    return score_risk(req.files, req.additions, req.deletions, rate)


@app.get("/api/flaky")
def api_flaky(repo: str, _role: str = Depends(require_role("developer"))):
    return detect_flaky(repo)


@app.get("/api/report")
def api_report(repo: str, days: int = 7, _role: str = Depends(require_role("lead"))):
    return weekly_report(repo, min(max(days, 1), 90))


@app.get("/api/admin/stats")
def api_admin(role: str = Depends(require_role("admin"))):
    db.audit(role, "view_admin_stats")
    return db.admin_stats()


# ---- GitHub webhook -------------------------------------------------------

async def analyze_failed_run(repo: str, run: dict, run_pk: int) -> None:
    settings = get_settings()
    try:
        logs = await github.fetch_run_logs(repo, run["id"], settings.github_token, settings.max_log_bytes)
        diag = await diagnose(logs)
        tests = diag.pop("tests", [])
        diag["id"] = db.save_diagnosis(run_pk, repo, diag)
        db.save_tests(run_pk, repo, run.get("head_sha"), tests)
        for pr in run.get("pull_requests", []):
            await github.post_pr_comment(repo, pr["number"], github.format_comment(diag), settings.github_token)
    except Exception:
        log.exception("Could not analyze run %s for %s", run.get("id"), repo)


@app.post("/webhooks/github")
async def github_webhook(
    request: Request,
    background: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
):
    settings = get_settings()
    if not settings.webhook_secret:
        raise HTTPException(503, "Set GITHUB_WEBHOOK_SECRET to enable the webhook.")
    body = await request.body()
    if not github.verify_signature(settings.webhook_secret, body, x_hub_signature_256):
        raise HTTPException(401, "Invalid signature.")
    if x_github_event != "workflow_run":
        return {"ignored": x_github_event}
    payload = json.loads(body)
    if payload.get("action") != "completed":
        return {"ignored": "run not completed"}

    run, repo = payload["workflow_run"], payload["repository"]["full_name"]
    try:
        start = datetime.fromisoformat(run["run_started_at"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(run["updated_at"].replace("Z", "+00:00"))
        duration = int((end - start).total_seconds())
    except (KeyError, ValueError):
        duration = 0
    failed = run.get("conclusion") == "failure"
    run_pk = db.record_run(repo, str(run["id"]), run.get("head_sha"), run.get("head_branch"),
                           "failed" if failed else "passed", duration)
    if failed:
        background.add_task(analyze_failed_run, repo, run, run_pk)
    return {"accepted": True, "failed": failed}


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")
