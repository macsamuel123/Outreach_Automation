"""
FastAPI backend for B2B prospecting pipeline UI.
Provides REST endpoints for dashboard, partner management, audit logs, and config.
"""
import os
from datetime import datetime, timedelta
from typing import Optional, List
import requests
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
import httpx

from outreach_agent import db_store, config as cfg

# Initialize FastAPI app
app = FastAPI(title="B2B Pipeline API", version="1.0.0")

# CORS for Vercel frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://*.vercel.app", "localhost:3000", "localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GitHub OAuth config
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # For API access (workflow dispatch, logs)
REPO_OWNER = "macsamuel123"
REPO_NAME = "Outreach_Automation"
WORKFLOW_ID = "daily-pipeline.yml"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/github/callback", auto_error=False)


# ============================================================================
# Auth Models & Helpers
# ============================================================================

class User(BaseModel):
    username: str
    avatar_url: Optional[str] = None


async def get_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> User:
    """Verify GitHub OAuth token and return user info."""
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Verify token with GitHub API
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {token}"}
            )
            if resp.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid token")
            data = resp.json()
            return User(username=data["login"], avatar_url=data.get("avatar_url"))
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Auth failed: {e}")


# ============================================================================
# Data Models
# ============================================================================

class PartnerRow(BaseModel):
    id: int
    company_name: str
    website: str
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    status: str
    email_confidence: Optional[float] = None
    notes: Optional[str] = None


class LeadRow(BaseModel):
    id: int
    company_name: str
    website: str
    source: str
    status: str
    date_added: str


class AuditRow(BaseModel):
    id: int
    stage: str
    company_name: str
    decision: str
    reasoning: Optional[str] = None
    run_id: str
    created_at: str


class PipelineRun(BaseModel):
    run_id: str
    status: str  # success, failure, running
    triggered_at: str
    completed_at: Optional[str] = None
    github_run_id: Optional[int] = None
    stage_results: dict


class DashboardStats(BaseModel):
    discovered_this_week: int
    qualified_count: int
    verified_count: int
    sent_count: int
    avg_email_confidence: float
    last_run: Optional[datetime] = None
    last_run_status: Optional[str] = None


# ============================================================================
# Auth Endpoints
# ============================================================================

@app.get("/auth/github/url")
async def github_auth_url():
    """Return GitHub OAuth login URL."""
    params = {
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": os.getenv("GITHUB_REDIRECT_URI", "http://localhost:3000/auth/callback"),
        "scope": "user:email",
    }
    url = "https://github.com/login/oauth/authorize?" + "&".join(f"{k}={v}" for k, v in params.items())
    return {"url": url}


@app.post("/auth/github/callback")
async def github_callback(code: str):
    """Exchange GitHub code for access token."""
    try:
        resp = requests.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
            },
            headers={"Accept": "application/json"}
        )
        data = resp.json()
        if "error" in data:
            raise HTTPException(status_code=400, detail=data.get("error_description"))
        return {"access_token": data["access_token"], "token_type": "bearer"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============================================================================
# Dashboard Endpoints
# ============================================================================

@app.get("/api/health")
async def health():
    """Liveness check."""
    return {"status": "ok"}


@app.get("/api/stats", response_model=DashboardStats)
async def get_dashboard_stats(user: User = Depends(get_current_user)):
    """Get dashboard metrics (discovered this week, qualified %, etc)."""
    engine = db_store.get_engine()

    # Count leads discovered this week
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    all_leads = db_store.load_leads(engine, status="*")
    discovered_week = sum(1 for l in all_leads if l.get("date_added", "") > week_ago)

    # Count partners by status
    all_partners = db_store.load_partners(engine, status="*")
    qualified = sum(1 for p in all_partners if p.get("status") == "PARTNER_STATUS_QUALIFIED")
    verified = sum(1 for p in all_partners if p.get("status") == "PARTNER_STATUS_VERIFIED")
    sent = sum(1 for p in all_partners if p.get("status") == "PARTNER_STATUS_SENT")

    # Avg email confidence
    confidences = [p.get("email_confidence", 0) for p in all_partners if p.get("email_confidence")]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0

    # Last run (from audit_log)
    audit = db_store.load_review_queue(engine)
    last_run = max((a.get("created_at") for a in audit if a.get("created_at")), default=None)

    return DashboardStats(
        discovered_this_week=discovered_week,
        qualified_count=qualified,
        verified_count=verified,
        sent_count=sent,
        avg_email_confidence=avg_confidence,
        last_run=datetime.fromisoformat(last_run) if last_run else None,
        last_run_status="success"  # TODO: fetch from GitHub Actions
    )


# ============================================================================
# Partner Management Endpoints
# ============================================================================

@app.get("/api/partners", response_model=List[PartnerRow])
async def list_partners(
    status: Optional[str] = Query(None),
    skip: int = Query(0),
    limit: int = Query(50),
    user: User = Depends(get_current_user)
):
    """List partners with optional filtering."""
    engine = db_store.get_engine()
    partners = db_store.load_partners(engine, status=status or "*")

    # Apply pagination
    partners = partners[skip:skip + limit]

    return [
        PartnerRow(
            id=p.get("id", i),
            company_name=p.get("company_name", ""),
            website=p.get("website", ""),
            contact_name=p.get("contact_name"),
            contact_email=p.get("contact_email"),
            status=p.get("status", ""),
            email_confidence=p.get("email_confidence"),
            notes=p.get("notes"),
        )
        for i, p in enumerate(partners)
    ]


@app.put("/api/partners/{partner_id}")
async def update_partner(
    partner_id: int,
    updates: dict,
    user: User = Depends(get_current_user)
):
    """Update a partner record."""
    engine = db_store.get_engine()
    db_store.update_partner(engine, partner_id, updates)
    return {"ok": True}


# ============================================================================
# Lead Management Endpoints
# ============================================================================

@app.get("/api/leads", response_model=List[LeadRow])
async def list_leads(
    status: Optional[str] = Query(None),
    skip: int = Query(0),
    limit: int = Query(50),
    user: User = Depends(get_current_user)
):
    """List leads with optional filtering."""
    engine = db_store.get_engine()
    leads = db_store.load_leads(engine, status=status or "*")

    leads = leads[skip:skip + limit]

    return [
        LeadRow(
            id=l.get("id", i),
            company_name=l.get("company_name", ""),
            website=l.get("website", ""),
            source=l.get("source", ""),
            status=l.get("status", ""),
            date_added=l.get("date_added", ""),
        )
        for i, l in enumerate(leads)
    ]


# ============================================================================
# Audit Log Endpoints
# ============================================================================

@app.get("/api/audit-log", response_model=List[AuditRow])
async def search_audit_log(
    stage: Optional[str] = Query(None),
    decision: Optional[str] = Query(None),
    skip: int = Query(0),
    limit: int = Query(100),
    user: User = Depends(get_current_user)
):
    """Search audit log with filters."""
    engine = db_store.get_engine()
    # TODO: implement filtering in db_store or via SQLAlchemy queries
    audit = db_store.load_review_queue(engine)

    if stage:
        audit = [a for a in audit if a.get("stage") == stage]
    if decision:
        audit = [a for a in audit if a.get("decision") == decision]

    audit = audit[skip:skip + limit]

    return [
        AuditRow(
            id=a.get("id", i),
            stage=a.get("stage", ""),
            company_name=a.get("company_name", ""),
            decision=a.get("decision", ""),
            reasoning=a.get("reasoning"),
            run_id=a.get("run_id", ""),
            created_at=a.get("created_at", ""),
        )
        for i, a in enumerate(audit)
    ]


@app.get("/api/audit-log/export")
async def export_audit_log(user: User = Depends(get_current_user)):
    """Export audit log as CSV."""
    import csv
    import io

    engine = db_store.get_engine()
    audit = db_store.load_review_queue(engine)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["stage", "company_name", "decision", "reasoning", "run_id", "created_at"])
    writer.writeheader()
    writer.writerows(audit)

    return {"csv": output.getvalue()}


# ============================================================================
# Run Management Endpoints
# ============================================================================

@app.post("/api/runs/trigger")
async def trigger_run(user: User = Depends(get_current_user)):
    """Trigger a manual pipeline run via GitHub Actions."""
    if not GITHUB_TOKEN:
        raise HTTPException(status_code=500, detail="GitHub token not configured")

    try:
        resp = requests.post(
            f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/workflows/{WORKFLOW_ID}/dispatches",
            json={"ref": "main"},
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json"
            }
        )
        if resp.status_code not in (200, 204):
            raise Exception(f"GitHub API error: {resp.text}")
        return {"ok": True, "message": "Pipeline triggered"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/runs", response_model=List[PipelineRun])
async def list_runs(
    limit: int = Query(20),
    user: User = Depends(get_current_user)
):
    """List recent pipeline runs from GitHub Actions."""
    if not GITHUB_TOKEN:
        raise HTTPException(status_code=500, detail="GitHub token not configured")

    try:
        resp = requests.get(
            f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/runs",
            params={"per_page": limit},
            headers={"Authorization": f"Bearer {GITHUB_TOKEN}"}
        )
        data = resp.json()

        runs = []
        for run in data.get("workflow_runs", []):
            runs.append(PipelineRun(
                run_id=run["name"],
                status=run["conclusion"] or "running",
                triggered_at=run["created_at"],
                completed_at=run.get("updated_at"),
                github_run_id=run["id"],
                stage_results={}  # TODO: parse from logs
            ))
        return runs
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/runs/{run_id}/logs")
async def get_run_logs(run_id: int, user: User = Depends(get_current_user)):
    """Get logs for a specific run."""
    if not GITHUB_TOKEN:
        raise HTTPException(status_code=500, detail="GitHub token not configured")

    try:
        resp = requests.get(
            f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/runs/{run_id}/logs",
            headers={"Authorization": f"Bearer {GITHUB_TOKEN}"}
        )
        if resp.status_code == 200:
            return {"logs": resp.text}
        return {"logs": ""}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============================================================================
# Config Endpoints
# ============================================================================

@app.get("/api/config")
async def get_config(user: User = Depends(get_current_user)):
    """Get pipeline configuration."""
    config_path = "config.yaml"
    if os.path.exists(config_path):
        config_obj = cfg.load_config(config_path)
        return config_obj.__dict__
    return {}


# ============================================================================
# Entry point
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
