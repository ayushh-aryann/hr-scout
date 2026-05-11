"""LinkedIn profile JSON parser — converts LinkedIn export/API data to CandidateProfile."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models import (
    CandidateProfile,
    CommunicationIndicators,
    Education,
    EducationLevel,
    Project,
    WorkExperience,
)

logger = logging.getLogger(__name__)

_MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

_EDU_LEVEL_MAP = {
    "bachelor": EducationLevel.BACHELOR,
    "b.s": EducationLevel.BACHELOR,
    "b.sc": EducationLevel.BACHELOR,
    "b.e": EducationLevel.BACHELOR,
    "b.tech": EducationLevel.BACHELOR,
    "b.a": EducationLevel.BACHELOR,
    "master": EducationLevel.MASTER,
    "m.s": EducationLevel.MASTER,
    "m.sc": EducationLevel.MASTER,
    "m.tech": EducationLevel.MASTER,
    "mba": EducationLevel.MASTER,
    "phd": EducationLevel.PHD,
    "ph.d": EducationLevel.PHD,
    "doctorate": EducationLevel.PHD,
    "associate": EducationLevel.ASSOCIATE,
    "diploma": EducationLevel.HIGH_SCHOOL,
}


def parse_linkedin(data: Dict[str, Any], filename: str = "linkedin.json") -> CandidateProfile:
    """
    Parse a LinkedIn profile JSON export (or our internal sample format) into CandidateProfile.

    Supports both the LinkedIn official export schema and a simplified schema used
    by our sample data files.
    """
    # Handle wrapped format
    if "profile" in data:
        data = data["profile"]

    name = _get_name(data)
    email = data.get("email_address") or data.get("email")
    phone = data.get("phone_numbers", [None])[0] if isinstance(data.get("phone_numbers"), list) else data.get("phone")
    summary = data.get("summary") or data.get("about")

    skills = _extract_skills(data)
    work_exp = _extract_work_experience(data)
    education = _extract_education(data)
    certifications = _extract_certifications(data)
    projects = _extract_projects(data)

    total_months = sum(w.duration_months for w in work_exp)
    total_years = round(total_months / 12, 1)

    comm = _assess_communication(data, summary)

    return CandidateProfile(
        candidate_id=str(uuid.uuid4()),
        name=name,
        email=email,
        phone=phone,
        summary=summary,
        skills=skills,
        work_experience=work_exp,
        education=education,
        certifications=certifications,
        projects=projects,
        total_years_experience=total_years,
        source_file=filename,
        source_type="linkedin",
        communication_indicators=comm,
    )


# ── Field extractors ──────────────────────────────────────────────────────────

def _get_name(data: Dict[str, Any]) -> str:
    if "full_name" in data:
        return str(data["full_name"])[:100]
    first = data.get("first_name", "")
    last = data.get("last_name", "")
    if first or last:
        return f"{first} {last}".strip()[:100]
    return data.get("name", "Unknown")[:100]


def _extract_skills(data: Dict[str, Any]) -> List[str]:
    skills: List[str] = []

    # Direct skills list
    raw = data.get("skills", [])
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                skills.append(item.strip())
            elif isinstance(item, dict):
                s = item.get("name") or item.get("skill_name", "")
                if s:
                    skills.append(str(s).strip())

    # Skills from positions
    for pos in data.get("positions", data.get("experience", [])):
        if isinstance(pos, dict):
            for s in pos.get("skills", []):
                if isinstance(s, str) and s not in skills:
                    skills.append(s)

    return [s for s in skills if s][:30]


def _extract_work_experience(data: Dict[str, Any]) -> List[WorkExperience]:
    positions = data.get("positions", data.get("experience", []))
    if not isinstance(positions, list):
        return []

    experiences: List[WorkExperience] = []
    for pos in positions:
        if not isinstance(pos, dict):
            continue

        company = pos.get("company", pos.get("company_name", ""))
        role = pos.get("title", pos.get("role", ""))

        # Duration
        start = pos.get("start_date", pos.get("started_on", {}))
        end = pos.get("end_date", pos.get("finished_on", {}))
        duration = _calc_duration(start, end)

        # Description
        desc = str(pos.get("description", pos.get("summary", "")))[:400]

        # Domain
        industry = pos.get("industry", "") or _infer_domain_from_text(desc + " " + company)

        # Skills used
        skills_used: List[str] = [str(s) for s in pos.get("skills", []) if s]

        experiences.append(WorkExperience(
            company=str(company)[:200],
            role=str(role)[:200],
            duration_months=duration,
            domain=str(industry)[:100],
            skills_used=skills_used[:15],
            description=desc,
            start_date=_format_date(start),
            end_date=_format_date(end) or "Present",
        ))

    return experiences[:6]


def _extract_education(data: Dict[str, Any]) -> List[Education]:
    raw = data.get("education", [])
    if not isinstance(raw, list):
        return []

    educations: List[Education] = []
    for e in raw:
        if not isinstance(e, dict):
            continue

        degree = str(e.get("degree_name", e.get("degree", "")))
        field = str(e.get("field_of_study", e.get("field", "")))
        institution = str(e.get("school_name", e.get("institution", "")))

        end = e.get("end_date", e.get("end_year", {}))
        year = _extract_year(end)

        level = _infer_edu_level(degree)

        educations.append(Education(
            degree=degree[:200],
            level=level,
            field=field[:100],
            institution=institution[:200],
            year=year,
        ))

    return educations[:3]


def _extract_certifications(data: Dict[str, Any]) -> List[str]:
    raw = data.get("certifications", data.get("licenses_and_certifications", []))
    if not isinstance(raw, list):
        return []
    certs: List[str] = []
    for c in raw:
        if isinstance(c, str):
            certs.append(c.strip())
        elif isinstance(c, dict):
            name = c.get("name", c.get("certification_name", ""))
            if name:
                certs.append(str(name).strip())
    return certs[:8]


def _extract_projects(data: Dict[str, Any]) -> List[Project]:
    raw = data.get("projects", [])
    if not isinstance(raw, list):
        return []

    projects: List[Project] = []
    for p in raw:
        if not isinstance(p, dict):
            continue
        name = str(p.get("title", p.get("name", "")))[:100]
        desc = str(p.get("description", ""))[:300]
        techs = [str(t) for t in p.get("technologies", p.get("skills", []))]
        url = p.get("url")
        projects.append(Project(
            name=name,
            description=desc,
            technologies=techs[:8],
            url=url,
        ))
    return projects[:5]


def _assess_communication(data: Dict[str, Any], summary: Optional[str]) -> CommunicationIndicators:
    all_text = summary or ""
    for pos in data.get("positions", data.get("experience", [])):
        if isinstance(pos, dict):
            all_text += " " + str(pos.get("description", ""))

    has_summary = bool(summary and len(summary) > 30)

    # LinkedIn profiles tend to have bullet points in descriptions
    bullets = all_text.count("•") + all_text.count("\n-")
    bullet_used = bullets > 2

    quant = len(re.findall(r"\b\d+%|\b\d+x|\b\$[\d]+|\b\d{4,}\b", all_text))

    words = re.findall(r"[a-z]+", all_text.lower())
    vocab = min(1.0, len(set(words)) / max(len(words), 1) * 3) if words else 0.5

    # LinkedIn profiles are typically well-structured
    has_sections = sum([
        bool(data.get("skills")),
        bool(data.get("positions") or data.get("experience")),
        bool(data.get("education")),
        bool(data.get("certifications")),
        bool(data.get("projects")),
    ])
    structure = min(1.0, has_sections / 4)

    return CommunicationIndicators(
        has_summary=has_summary,
        bullet_points_used=bullet_used,
        quantified_achievements=min(quant, 20),
        grammar_score=0.75,  # LinkedIn profiles are generally well-written
        structure_score=round(structure, 2),
        vocabulary_richness=round(vocab, 2),
    )


# ── Date helpers ──────────────────────────────────────────────────────────────

def _calc_duration(start: Any, end: Any) -> int:
    s_year, s_month = _parse_date(start)
    if end and (not isinstance(end, dict) or end):
        e_year, e_month = _parse_date(end)
    else:
        e_year, e_month = datetime.now().year, datetime.now().month

    months = (e_year - s_year) * 12 + (e_month - s_month)
    return max(1, months)


def _parse_date(d: Any) -> tuple:
    if isinstance(d, dict):
        year = int(d.get("year", datetime.now().year))
        month = int(d.get("month", 1))
        return year, month
    if isinstance(d, int):
        return d, 1
    if isinstance(d, str):
        year_match = re.search(r"\b(19|20)\d{2}\b", d)
        year = int(year_match.group(0)) if year_match else datetime.now().year
        month = 1
        lower_d = d.lower()
        for name, num in _MONTH_MAP.items():
            if name[:3] in lower_d:
                month = num
                break
        return year, month
    return datetime.now().year, 1


def _format_date(d: Any) -> Optional[str]:
    if not d:
        return None
    year, month = _parse_date(d)
    return f"{year}-{month:02d}"


def _extract_year(d: Any) -> Optional[int]:
    if isinstance(d, dict):
        return d.get("year")
    if isinstance(d, int):
        return d
    if isinstance(d, str):
        m = re.search(r"\b(19|20)\d{2}\b", d)
        return int(m.group(0)) if m else None
    return None


def _infer_edu_level(degree: str) -> EducationLevel:
    lower = degree.lower()
    for kw, level in sorted(_EDU_LEVEL_MAP.items(), key=lambda x: -len(x[0])):
        if kw in lower:
            return level
    return EducationLevel.BACHELOR


def _infer_domain_from_text(text: str) -> str:
    lower = text.lower()
    if any(w in lower for w in ["fintech", "banking", "finance", "payments"]):
        return "fintech"
    if any(w in lower for w in ["healthcare", "medical", "health", "pharma"]):
        return "healthcare"
    if any(w in lower for w in ["machine learning", "ai ", "data science"]):
        return "ai/ml"
    if any(w in lower for w in ["devops", "infrastructure", "cloud"]):
        return "devops"
    return "software engineering"
