"""Mandatory 5-dimension scoring rubric with weighted contributions."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from app.models import (
    CandidateProfile,
    DimensionScore,
    JDProfile,
    Recommendation,
    RubricScores,
)
from app.scoring.embeddings import compute_similarity, compute_skill_overlap

logger = logging.getLogger(__name__)

# Dimension weights — must sum to 1.0
WEIGHTS = {
    "skills_match": 0.30,
    "experience_relevance": 0.25,
    "education_certs": 0.15,
    "project_portfolio": 0.20,
    "communication_quality": 0.10,
}

# Scoring prompt for LLM path
_SCORE_PROMPT = """You are a strict technical recruiter evaluating a job candidate. Score them on 5 dimensions (0–10) based on the given JD and profile.

JD Summary:
- Title: {title}
- Required skills: {required_skills}
- Preferred skills: {preferred_skills}
- Min experience: {years_min} years
- Education: {education}
- Domain: {domain}
- Key responsibilities: {responsibilities}

Candidate Profile:
- Name: {name}
- Skills: {skills}
- Total experience: {total_years} years
- Domains worked in: {domains}
- Education: {education_candidate}
- Certifications: {certs}
- Projects: {projects}
- Summary: {summary}

Scoring rubric:
- skills_match (30%): required skill coverage. <30% match=0-3, 50-70%=4-7, >85%=8-10
- experience_relevance (25%): domain match + seniority. unrelated=0-3, adjacent=4-6, exact+correct seniority=7-10
- education_certs (15%): degree level vs requirement. below min=0-3, meets=4-7, exceeds=8-10
- project_portfolio (20%): relevance of projects. none=0-2, generic=3-6, strong relevant=7-10
- communication_quality (10%): clarity/structure of resume. poor=0-3, adequate=4-6, crisp/structured=7-10

Return ONLY valid JSON (no markdown fences):
{{
  "skills_match": {{"score": 0-10, "justification": "one sentence"}},
  "experience_relevance": {{"score": 0-10, "justification": "one sentence"}},
  "education_certs": {{"score": 0-10, "justification": "one sentence"}},
  "project_portfolio": {{"score": 0-10, "justification": "one sentence"}},
  "communication_quality": {{"score": 0-10, "justification": "one sentence"}},
  "recommendation": "hire|borderline|no_hire"
}}

Be strict. Only award high scores where clearly justified. The recommendation should match the overall weighted score:
- hire: total >= 65
- borderline: total 45-64
- no_hire: total < 45
"""


def score_candidate(
    candidate: CandidateProfile,
    jd: JDProfile,
    llm_client: Any = None,
) -> tuple[RubricScores, Recommendation]:
    """Score a candidate against a JD. Returns (RubricScores, Recommendation)."""
    if llm_client is not None:
        try:
            return _score_with_llm(candidate, jd, llm_client)
        except Exception as exc:
            logger.warning("LLM scoring failed (%s), using heuristics", exc)

    return _score_heuristic(candidate, jd)


# ── LLM scoring ───────────────────────────────────────────────────────────────

def _score_with_llm(
    candidate: CandidateProfile,
    jd: JDProfile,
    llm_client: Any,
) -> tuple[RubricScores, Recommendation]:
    domains = list({w.domain for w in candidate.work_experience if w.domain})
    edu_str = "; ".join(
        f"{e.degree} in {e.field} ({e.level.value})" for e in candidate.education
    )
    proj_str = "; ".join(
        f"{p.name}: {', '.join(p.technologies[:3])}" for p in candidate.projects[:3]
    )

    prompt = _SCORE_PROMPT.format(
        title=jd.title,
        required_skills=", ".join(jd.required_skills[:15]),
        preferred_skills=", ".join(jd.preferred_skills[:10]),
        years_min=jd.years_experience_min,
        education=jd.education_requirement.value,
        domain=jd.domain,
        responsibilities="; ".join(jd.key_responsibilities[:4]),
        name=candidate.name,
        skills=", ".join(candidate.skills[:20]),
        total_years=candidate.total_years_experience,
        domains=", ".join(domains[:5]),
        education_candidate=edu_str or "Not specified",
        certs=", ".join(candidate.certifications[:5]) or "None",
        projects=proj_str or "None listed",
        summary=candidate.summary[:200] if candidate.summary else "No summary",
    )

    raw = llm_client.complete(prompt, max_tokens=800)
    data = _extract_json(raw)
    return _build_rubric_from_llm(data)


def _build_rubric_from_llm(data: dict) -> tuple[RubricScores, Recommendation]:
    def _dim(key: str, weight: float) -> DimensionScore:
        d = data.get(key, {})
        if isinstance(d, (int, float)):
            score = float(d)
            justification = "LLM score (no justification provided)"
        else:
            score = float(d.get("score", 5.0))
            justification = str(d.get("justification", ""))[:300]
        score = max(0.0, min(10.0, score))
        return DimensionScore(
            score=score,
            weight=weight,
            justification=justification,
        )

    rubric = RubricScores(
        skills_match=_dim("skills_match", WEIGHTS["skills_match"]),
        experience_relevance=_dim("experience_relevance", WEIGHTS["experience_relevance"]),
        education_certs=_dim("education_certs", WEIGHTS["education_certs"]),
        project_portfolio=_dim("project_portfolio", WEIGHTS["project_portfolio"]),
        communication_quality=_dim("communication_quality", WEIGHTS["communication_quality"]),
    )

    rec_str = str(data.get("recommendation", "borderline")).lower()
    rec_map = {
        "hire": Recommendation.HIRE,
        "borderline": Recommendation.BORDERLINE,
        "no_hire": Recommendation.NO_HIRE,
        "no-hire": Recommendation.NO_HIRE,
    }
    rec = rec_map.get(rec_str, Recommendation.BORDERLINE)

    # Validate recommendation against total score
    rec = _validate_recommendation(rec, rubric.total)
    return rubric, rec


# ── Heuristic scoring ─────────────────────────────────────────────────────────

def _score_heuristic(
    candidate: CandidateProfile,
    jd: JDProfile,
) -> tuple[RubricScores, Recommendation]:
    skills_dim = _score_skills(candidate, jd)
    exp_dim = _score_experience(candidate, jd)
    edu_dim = _score_education(candidate, jd)
    proj_dim = _score_projects(candidate, jd)
    comm_dim = _score_communication(candidate)

    rubric = RubricScores(
        skills_match=skills_dim,
        experience_relevance=exp_dim,
        education_certs=edu_dim,
        project_portfolio=proj_dim,
        communication_quality=comm_dim,
    )
    rec = _validate_recommendation(None, rubric.total)
    return rubric, rec


def _score_skills(c: CandidateProfile, jd: JDProfile) -> DimensionScore:
    if not jd.required_skills and not jd.preferred_skills:
        # Use semantic similarity on full text
        jd_text = f"{jd.title} {jd.domain} {' '.join(jd.key_responsibilities)}"
        cand_text = f"{' '.join(c.skills)} {' '.join(w.role for w in c.work_experience)}"
        sim = compute_similarity(jd_text, cand_text)
        score = round(sim * 10, 1)
        just = f"Semantic skill match: {sim*100:.0f}% similarity to JD requirements."
    else:
        req_overlap = compute_skill_overlap(c.skills, jd.required_skills)
        pref_overlap = compute_skill_overlap(c.skills, jd.preferred_skills) if jd.preferred_skills else 0.5
        raw = req_overlap * 0.70 + pref_overlap * 0.30
        score = round(raw * 10, 1)

        req_pct = int(req_overlap * 100)
        if score < 3:
            just = f"Only {req_pct}% of required skills matched — critical gaps in core requirements."
        elif score < 5:
            just = f"{req_pct}% required skills matched; covers some but misses key technical areas."
        elif score < 7:
            just = f"{req_pct}% required skills matched with reasonable coverage of core stack."
        else:
            just = f"Strong {req_pct}% match on required skills plus good preferred skill coverage."

    return DimensionScore(score=score, weight=WEIGHTS["skills_match"], justification=just)


def _score_experience(c: CandidateProfile, jd: JDProfile) -> DimensionScore:
    years = c.total_years_experience
    min_req = jd.years_experience_min

    # Years score (0-5 range contribution)
    if min_req == 0:
        years_score = min(10.0, years * 1.2)
    elif years < min_req * 0.5:
        years_score = 2.0
    elif years < min_req:
        years_score = 4.0 + (years / min_req) * 2
    elif years < min_req * 1.5:
        years_score = 7.0
    else:
        years_score = 9.0

    # Domain relevance (0-5 range contribution)
    candidate_domains = {w.domain.lower() for w in c.work_experience}
    jd_domain_lower = jd.domain.lower()
    jd_keywords = set(re.split(r"[\s/,]+", jd_domain_lower))

    domain_match = 0.0
    for cd in candidate_domains:
        cd_words = set(re.split(r"[\s/,]+", cd))
        overlap = len(jd_keywords & cd_words) / max(len(jd_keywords), 1)
        domain_match = max(domain_match, overlap)

    if domain_match > 0.6:
        domain_score = 9.0
        domain_label = "exact domain match"
    elif domain_match > 0.2:
        domain_score = 6.0
        domain_label = "adjacent domain"
    else:
        # Try semantic similarity
        cand_exp_text = " ".join(
            f"{w.role} at {w.company} ({w.domain})" for w in c.work_experience
        )
        sim = compute_similarity(jd.domain + " " + " ".join(jd.key_responsibilities), cand_exp_text)
        domain_score = round(sim * 10, 1)
        domain_label = "different domain" if sim < 0.3 else "somewhat related domain"

    score = round((years_score * 0.45 + domain_score * 0.55), 1)
    score = max(0.0, min(10.0, score))

    if score < 3:
        just = f"{years:.1f} years exp (need {min_req}+) in {domain_label}."
    elif score < 5:
        just = f"{years:.1f} years in {domain_label}; some relevant experience but gaps remain."
    elif score < 7:
        just = f"{years:.1f} years with {domain_label}; solid background with minor gaps."
    else:
        just = f"{years:.1f} years in {domain_label}; experience closely matches requirements."

    return DimensionScore(score=score, weight=WEIGHTS["experience_relevance"], justification=just)


def _score_education(c: CandidateProfile, jd: JDProfile) -> DimensionScore:
    from app.models import EducationLevel

    level_rank = {
        EducationLevel.ANY: 0,
        EducationLevel.HIGH_SCHOOL: 1,
        EducationLevel.ASSOCIATE: 2,
        EducationLevel.BACHELOR: 3,
        EducationLevel.MASTER: 4,
        EducationLevel.PHD: 5,
    }

    required_rank = level_rank[jd.education_requirement]
    candidate_rank = max(
        (level_rank.get(e.level, 0) for e in c.education),
        default=0,
    )

    if required_rank == 0:
        # No requirement specified — credit whatever they have
        edu_score = min(10.0, candidate_rank * 2.0)
    elif candidate_rank < required_rank:
        edu_score = max(1.0, (candidate_rank / required_rank) * 5)
    elif candidate_rank == required_rank:
        edu_score = 7.0
    else:
        edu_score = 9.5

    # Certifications bonus
    cert_overlap = compute_skill_overlap(c.certifications, jd.certifications) if jd.certifications else 0.0
    cert_bonus = min(2.0, cert_overlap * 4)
    score = round(min(10.0, edu_score + cert_bonus), 1)

    edu_names = [e.level.value for e in c.education] or ["unspecified"]
    if score < 3:
        just = f"Education ({', '.join(edu_names)}) below the {jd.education_requirement.value} requirement."
    elif score < 5:
        just = f"Education partially meets the {jd.education_requirement.value} requirement."
    elif score < 7:
        just = f"{', '.join(edu_names).title()} degree meets requirements; certifications adequate."
    else:
        just = f"{', '.join(edu_names).title()} meets or exceeds {jd.education_requirement.value}; certs add value."

    return DimensionScore(score=score, weight=WEIGHTS["education_certs"], justification=just)


def _score_projects(c: CandidateProfile, jd: JDProfile) -> DimensionScore:
    if not c.projects:
        return DimensionScore(
            score=1.0,
            weight=WEIGHTS["project_portfolio"],
            justification="No projects listed in profile.",
        )

    jd_tech_set = {s.lower() for s in jd.required_skills + jd.preferred_skills}
    project_scores = []
    for proj in c.projects:
        proj_techs = {t.lower() for t in proj.technologies}
        overlap = len(jd_tech_set & proj_techs) / max(len(jd_tech_set), 1) if jd_tech_set else 0.3

        # Semantic similarity of project description to JD
        if proj.description:
            sem = compute_similarity(
                jd.domain + " " + " ".join(jd.key_responsibilities[:3]),
                proj.description,
            )
        else:
            sem = 0.2
        proj_score = (overlap * 0.5 + sem * 0.5) * 10
        project_scores.append(proj_score)

    avg_score = sum(project_scores) / len(project_scores)
    bonus = min(1.5, len(c.projects) * 0.3)  # More projects = small bonus
    score = round(min(10.0, avg_score + bonus), 1)

    if score < 3:
        just = f"{len(c.projects)} project(s) listed but minimal relevance to the role's domain."
    elif score < 5:
        just = f"{len(c.projects)} project(s) show generic work; limited alignment with JD requirements."
    elif score < 7:
        just = f"{len(c.projects)} project(s) demonstrate relevant technical work with partial stack overlap."
    else:
        just = f"{len(c.projects)} strong project(s) with clear relevance to required skills and domain."

    return DimensionScore(score=score, weight=WEIGHTS["project_portfolio"], justification=just)


def _score_communication(c: CandidateProfile) -> DimensionScore:
    comm = c.communication_indicators
    raw_score = (
        comm.grammar_score * 0.25
        + comm.structure_score * 0.25
        + comm.vocabulary_richness * 0.20
        + (0.15 if comm.has_summary else 0.0)
        + (0.10 if comm.bullet_points_used else 0.0)
        + min(0.05, comm.quantified_achievements * 0.01)
    )
    score = round(raw_score * 10, 1)
    score = max(0.0, min(10.0, score))

    if score < 3:
        just = "Resume lacks structure, summary, and quantification — difficult to evaluate."
    elif score < 5:
        just = "Adequate writing with some structure but limited quantified achievements."
    elif score < 7:
        just = "Clearly written with reasonable structure; some quantified results present."
    else:
        just = "Crisp, well-structured resume with strong summary and quantified achievements."

    return DimensionScore(score=score, weight=WEIGHTS["communication_quality"], justification=just)


# ── Recommendation logic ──────────────────────────────────────────────────────

def _validate_recommendation(current: Optional[Recommendation], total: float) -> Recommendation:
    """Enforce recommendation thresholds regardless of LLM suggestion."""
    if total >= 65:
        return Recommendation.HIRE
    elif total >= 45:
        return Recommendation.BORDERLINE
    else:
        return Recommendation.NO_HIRE


# ── JSON helper ───────────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    text = re.sub(r"```(?:json)?", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise ValueError("No valid JSON in LLM scoring response")
