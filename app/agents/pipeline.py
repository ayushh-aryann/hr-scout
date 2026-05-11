"""Main orchestration pipeline — end-to-end candidate analysis."""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config import get_settings
from app.models import (
    AnalysisSession,
    CandidateProfile,
    CandidateResult,
    JDProfile,
    OverrideAction,
    Recommendation,
)
from app.parsers.jd_parser import parse_jd
from app.parsers.linkedin_parser import parse_linkedin
from app.parsers.resume_parser import parse_resume
from app.scoring.rubric import score_candidate
from app.storage.audit import AuditLog
from app.security.sanitizer import mask_pii

logger = logging.getLogger(__name__)
settings = get_settings()


# ── LLM Client wrapper ────────────────────────────────────────────────────────

class LLMClient:
    """Thin wrapper around Anthropic/OpenAI SDK — unified .complete() interface."""

    def __init__(self):
        self._provider = settings.effective_provider
        self._client = self._init()

    def _init(self) -> Optional[Any]:
        if self._provider == "anthropic":
            try:
                import anthropic
                return anthropic.Anthropic(api_key=settings.anthropic_api_key)
            except Exception as exc:
                logger.error("Anthropic init failed: %s", exc)
        elif self._provider == "openai":
            try:
                import openai
                return openai.OpenAI(api_key=settings.openai_api_key)
            except Exception as exc:
                logger.error("OpenAI init failed: %s", exc)
        logger.info("Running in local/heuristic mode (no LLM)")
        return None

    def complete(self, prompt: str, max_tokens: int = 1024) -> str:
        if self._client is None:
            raise RuntimeError("No LLM client available")

        if self._provider == "anthropic":
            import anthropic
            message = self._client.messages.create(
                model=settings.anthropic_model,
                max_tokens=max_tokens,
                system=(
                    "You are a precise HR analyst. Always return valid JSON exactly as specified. "
                    "Never deviate from the requested schema. Never add explanations outside JSON."
                ),
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text

        elif self._provider == "openai":
            response = self._client.chat.completions.create(
                model=settings.openai_model,
                max_tokens=max_tokens,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a precise HR analyst. Always return valid JSON exactly as "
                            "specified. Never deviate from the requested schema."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
            )
            return response.choices[0].message.content

        raise RuntimeError(f"Unknown provider: {self._provider}")

    @property
    def available(self) -> bool:
        return self._client is not None


# ── Pipeline ──────────────────────────────────────────────────────────────────

class HRPipeline:
    def __init__(self):
        self._llm = LLMClient()
        self._audit = AuditLog(settings.storage_path / "audit.jsonl")
        self._sessions_dir = settings.sessions_path
        logger.info(
            "Pipeline initialized | provider=%s | llm=%s",
            settings.effective_provider,
            "enabled" if self._llm.available else "local-heuristic",
        )

    # ── Public methods ────────────────────────────────────────────────────────

    def analyze(
        self,
        jd_text: str,
        candidate_files: List[Tuple[bytes, str]],  # [(bytes, filename), ...]
        session_id: Optional[str] = None,
    ) -> AnalysisSession:
        """Run full pipeline: parse JD → parse candidates → score → rank."""
        session_id = session_id or str(uuid.uuid4())
        llm = self._llm if self._llm.available else None

        self._audit.log("pipeline_start", session_id, {"candidate_count": len(candidate_files)})

        # Step 1 — parse JD
        logger.info("[%s] Parsing JD (%d chars)", session_id, len(jd_text))
        jd_profile = parse_jd(jd_text, llm_client=llm)
        self._audit.log("jd_parsed", session_id, {
            "title": jd_profile.title,
            "required_skills": jd_profile.required_skills,
        })

        # Step 2 — parse candidates
        candidate_profiles: List[CandidateProfile] = []
        for file_bytes, filename in candidate_files:
            logger.info("[%s] Parsing candidate: %s", session_id, filename)
            try:
                profile = self._parse_candidate(file_bytes, filename, llm)
                candidate_profiles.append(profile)
                self._audit.log("candidate_parsed", session_id, {
                    "name": profile.name,
                    "file": filename,
                    "skills_count": len(profile.skills),
                    "years_exp": profile.total_years_experience,
                })
            except Exception as exc:
                logger.error("[%s] Failed to parse %s: %s", session_id, filename, exc)
                self._audit.log("candidate_parse_error", session_id, {"file": filename, "error": str(exc)})

        # Step 3 — score and rank
        results: List[CandidateResult] = []
        for profile in candidate_profiles:
            logger.info("[%s] Scoring: %s", session_id, profile.name)
            try:
                rubric, recommendation = score_candidate(profile, jd_profile, llm_client=llm)
                total = rubric.total
                result = CandidateResult(
                    candidate_id=profile.candidate_id,
                    name=profile.name,
                    source_file=profile.source_file,
                    profile=profile,
                    scores=rubric,
                    total_score=total,
                    recommendation=recommendation,
                )
                results.append(result)
                self._audit.log("candidate_scored", session_id, {
                    "name": profile.name,
                    "total_score": total,
                    "recommendation": recommendation.value,
                })
            except Exception as exc:
                logger.error("[%s] Scoring failed for %s: %s", session_id, profile.name, exc)

        # Step 4 — rank
        results.sort(key=lambda r: r.total_score, reverse=True)
        for i, r in enumerate(results):
            r.rank = i + 1

        # Step 5 — build summary
        summary = self._build_summary(results, jd_profile)

        session = AnalysisSession(
            session_id=session_id,
            jd_profile=jd_profile,
            results=results,
            shortlist_summary=summary,
            status="completed",
        )
        self._save_session(session)
        self._audit.log("pipeline_complete", session_id, {
            "total_processed": len(results),
            "hire_count": sum(1 for r in results if r.recommendation == Recommendation.HIRE),
        })

        return session

    def apply_override(
        self,
        session_id: str,
        candidate_id: str,
        override: OverrideAction,
    ) -> CandidateResult:
        """Apply a human override to a candidate result and persist."""
        session = self._load_session(session_id)
        result = next((r for r in session.results if r.candidate_id == candidate_id), None)
        if result is None:
            raise ValueError(f"Candidate {candidate_id} not found in session {session_id}")

        # Update the appropriate dimension score
        if override.dimension is not None:
            dim_map = {
                "skills_match": "skills_match",
                "experience_relevance": "experience_relevance",
                "education_certs": "education_certs",
                "project_portfolio": "project_portfolio",
                "communication_quality": "communication_quality",
            }
            if override.dimension in dim_map:
                dim = getattr(result.scores, dim_map[override.dimension])
                override.old_score = dim.score
                dim.score = max(0.0, min(10.0, override.new_score))
                dim.weighted_contribution = round(dim.score * dim.weight * 10, 2)
            else:
                raise ValueError(f"Unknown dimension: {override.dimension}")
        else:
            override.old_score = result.total_score / 10  # normalize for logging
            override.new_score = max(0.0, min(10.0, override.new_score))

        # Recalculate total
        result.total_score = result.scores.total

        # Update recommendation based on new total
        if result.total_score >= 65:
            result.recommendation = Recommendation.HIRE
        elif result.total_score >= 45:
            result.recommendation = Recommendation.BORDERLINE
        else:
            result.recommendation = Recommendation.NO_HIRE

        # Log override
        result.overrides.append(override)
        if override.flagged:
            result.flagged = True
            result.flag_reason = override.reason

        # Re-sort and re-rank
        session.results.sort(key=lambda r: r.total_score, reverse=True)
        for i, r in enumerate(session.results):
            r.rank = i + 1

        self._save_session(session)
        self._audit.log("override_applied", session_id, {
            "candidate_id": candidate_id,
            "dimension": override.dimension,
            "old_score": override.old_score,
            "new_score": override.new_score,
            "reason": override.reason,
            "hr_user": override.hr_user,
        })

        return result

    def get_session(self, session_id: str) -> AnalysisSession:
        return self._load_session(session_id)

    def list_sessions(self) -> List[Dict[str, Any]]:
        summaries = []
        for f in sorted(self._sessions_dir.glob("*.json"), key=os.path.getmtime, reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                summaries.append({
                    "session_id": data.get("session_id"),
                    "status": data.get("status"),
                    "created_at": data.get("created_at"),
                    "jd_title": data.get("jd_profile", {}).get("title"),
                    "candidate_count": len(data.get("results", [])),
                })
            except Exception:
                continue
        return summaries

    # ── Private helpers ───────────────────────────────────────────────────────

    def _parse_candidate(
        self,
        file_bytes: bytes,
        filename: str,
        llm: Optional[Any],
    ) -> CandidateProfile:
        lower = filename.lower()
        if lower.endswith(".json"):
            data = json.loads(file_bytes.decode("utf-8"))
            return parse_linkedin(data, filename)
        else:
            return parse_resume(file_bytes, filename, llm_client=llm)

    def _build_summary(self, results: List[CandidateResult], jd: JDProfile) -> str:
        hire_count = sum(1 for r in results if r.recommendation == Recommendation.HIRE)
        border_count = sum(1 for r in results if r.recommendation == Recommendation.BORDERLINE)
        no_hire_count = sum(1 for r in results if r.recommendation == Recommendation.NO_HIRE)
        top = results[0].name if results else "N/A"
        avg = round(sum(r.total_score for r in results) / max(len(results), 1), 1)

        return (
            f"Analyzed {len(results)} candidates for '{jd.title}'. "
            f"Recommended for hire: {hire_count} | Borderline: {border_count} | No-hire: {no_hire_count}. "
            f"Top candidate: {top} (avg score: {avg}/100). "
            f"Domain focus: {jd.domain}."
        )

    def _save_session(self, session: AnalysisSession) -> None:
        path = self._sessions_dir / f"{session.session_id}.json"
        path.write_text(session.model_dump_json(indent=2), encoding="utf-8")

    def _load_session(self, session_id: str) -> AnalysisSession:
        path = self._sessions_dir / f"{session_id}.json"
        if not path.exists():
            raise ValueError(f"Session not found: {session_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return AnalysisSession(**data)
