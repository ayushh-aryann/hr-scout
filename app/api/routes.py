"""FastAPI route definitions."""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets

from app.agents.pipeline import HRPipeline
from app.config import get_settings
from app.models import AnalysisSession, CandidateResult, OverrideRequest, ShortlistSummary
from app.reports.generator import generate_html, generate_json, generate_pdf

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/api/v1")
security = HTTPBasic()

# Singleton pipeline instance
_pipeline: Optional[HRPipeline] = None


def get_pipeline() -> HRPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = HRPipeline()
    return _pipeline


def _verify_admin(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    """Protect override endpoints with basic auth."""
    correct_password = secrets.compare_digest(
        credentials.password.encode(),
        settings.api_secret_key.encode(),
    )
    if not correct_password:
        raise HTTPException(
            status_code=401,
            detail="Incorrect credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health")
async def health():
    return {"status": "ok", "provider": settings.effective_provider}


# ── Analysis ──────────────────────────────────────────────────────────────────

@router.post("/analyze", response_model=AnalysisSession)
async def analyze(
    jd_text: str = Form(..., description="Raw job description text"),
    files: List[UploadFile] = File(..., description="Resume files (PDF/DOCX) or LinkedIn JSON"),
    pipeline: HRPipeline = Depends(get_pipeline),
):
    """
    Run the full candidate analysis pipeline.

    Upload a JD text + one or more resume files. Returns a ranked shortlist
    with rubric scores for each candidate.
    """
    if not jd_text.strip():
        raise HTTPException(400, "jd_text is required")
    if not files:
        raise HTTPException(400, "At least one candidate file is required")
    if len(files) > 30:
        raise HTTPException(400, "Maximum 30 files per request")

    # Read file bytes
    candidate_files = []
    for upload in files:
        if not upload.filename:
            continue
        ext = upload.filename.lower().rsplit(".", 1)[-1]
        if ext not in ("pdf", "docx", "doc", "json"):
            raise HTTPException(400, f"Unsupported file type: {upload.filename}")
        data = await upload.read()
        if len(data) > 10 * 1024 * 1024:  # 10 MB cap
            raise HTTPException(400, f"File too large: {upload.filename}")
        candidate_files.append((data, upload.filename))

    if not candidate_files:
        raise HTTPException(400, "No valid candidate files found")

    try:
        session = pipeline.analyze(jd_text, candidate_files)
        return session
    except Exception as exc:
        logger.exception("Pipeline error")
        raise HTTPException(500, f"Analysis failed: {exc}")


# ── Session management ────────────────────────────────────────────────────────

@router.get("/sessions", response_model=list)
async def list_sessions(pipeline: HRPipeline = Depends(get_pipeline)):
    return pipeline.list_sessions()


@router.get("/sessions/{session_id}", response_model=AnalysisSession)
async def get_session(session_id: str, pipeline: HRPipeline = Depends(get_pipeline)):
    try:
        return pipeline.get_session(session_id)
    except ValueError:
        raise HTTPException(404, f"Session not found: {session_id}")


# ── Override ──────────────────────────────────────────────────────────────────

@router.post(
    "/sessions/{session_id}/candidates/{candidate_id}/override",
    response_model=CandidateResult,
)
async def override_candidate(
    session_id: str,
    candidate_id: str,
    request: OverrideRequest,
    pipeline: HRPipeline = Depends(get_pipeline),
    # No auth dependency — kept simple for local prototype
    # To add auth: hr_user: str = Depends(_verify_admin)
):
    """
    Apply a human override to a candidate's dimension score.

    dimension: one of skills_match | experience_relevance | education_certs |
               project_portfolio | communication_quality | null (for flagging only)
    new_score: 0–10
    reason: explanation (required)
    """
    from app.models import OverrideAction
    from datetime import datetime

    override_action = OverrideAction(
        timestamp=datetime.utcnow(),
        hr_user=request.hr_user,
        dimension=request.dimension,
        old_score=0.0,  # will be filled by pipeline
        new_score=request.new_score,
        reason=request.reason,
        flagged=request.flag,
    )

    try:
        result = pipeline.apply_override(session_id, candidate_id, override_action)
        return result
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    except Exception as exc:
        logger.exception("Override error")
        raise HTTPException(500, f"Override failed: {exc}")


# ── Reports ───────────────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/report/json")
async def report_json(session_id: str, pipeline: HRPipeline = Depends(get_pipeline)):
    try:
        session = pipeline.get_session(session_id)
    except ValueError:
        raise HTTPException(404, "Session not found")
    content = generate_json(session)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="report_{session_id[:8]}.json"'},
    )


@router.get("/sessions/{session_id}/report/html", response_class=HTMLResponse)
async def report_html(session_id: str, pipeline: HRPipeline = Depends(get_pipeline)):
    try:
        session = pipeline.get_session(session_id)
    except ValueError:
        raise HTTPException(404, "Session not found")
    html = generate_html(session)
    return HTMLResponse(content=html)


@router.get("/sessions/{session_id}/report/pdf")
async def report_pdf(session_id: str, pipeline: HRPipeline = Depends(get_pipeline)):
    try:
        session = pipeline.get_session(session_id)
    except ValueError:
        raise HTTPException(404, "Session not found")
    try:
        pdf_bytes = generate_pdf(session)
    except Exception as exc:
        logger.exception("PDF generation failed")
        raise HTTPException(500, f"PDF generation failed: {exc}")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="shortlist_{session_id[:8]}.pdf"'},
    )


# ── Audit ─────────────────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/audit")
async def get_audit(session_id: str, pipeline: HRPipeline = Depends(get_pipeline)):
    try:
        pipeline.get_session(session_id)  # verify session exists
    except ValueError:
        raise HTTPException(404, "Session not found")
    entries = pipeline._audit.read_all(session_id=session_id)
    return {"session_id": session_id, "entries": entries}
