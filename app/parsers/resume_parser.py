"""Resume parser — handles PDF and DOCX files into CandidateProfile."""

from __future__ import annotations

import io
import json
import logging
import math
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.models import (
    CandidateProfile,
    CommunicationIndicators,
    Education,
    EducationLevel,
    Project,
    WorkExperience,
)
from app.security.sanitizer import sanitize_resume_text

logger = logging.getLogger(__name__)


# ── Public API ────────────────────────────────────────────────────────────────

def parse_resume(
    file_bytes: bytes,
    filename: str,
    llm_client: Any = None,
) -> CandidateProfile:
    """Parse a PDF or DOCX resume into a CandidateProfile."""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        text = _extract_pdf(file_bytes)
    elif ext in (".docx", ".doc"):
        text = _extract_docx(file_bytes)
    else:
        raise ValueError(f"Unsupported file type: {ext}")

    clean = sanitize_resume_text(text)

    if llm_client is not None:
        try:
            return _parse_with_llm(clean, filename, llm_client)
        except Exception as exc:
            logger.warning("LLM resume parse failed (%s), using heuristics", exc)

    return _parse_heuristic(clean, filename)


# ── Text extraction ───────────────────────────────────────────────────────────

def _extract_pdf(data: bytes) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = []
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    pages.append(t)
            return "\n".join(pages)
    except Exception as exc:
        logger.error("PDF extraction failed: %s", exc)
        return ""


def _extract_docx(data: bytes) -> str:
    try:
        from docx import Document
        doc = Document(io.BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as exc:
        logger.error("DOCX extraction failed: %s", exc)
        return ""


# ── LLM parse path ────────────────────────────────────────────────────────────

_RESUME_PROMPT = """You are an expert recruiter. Extract structured information from the resume below.

Resume Text:
---
{resume_text}
---

Return ONLY valid JSON (no markdown fences):
{{
  "name": "full name",
  "email": "email or null",
  "phone": "phone or null",
  "summary": "professional summary or null",
  "skills": ["list of technical/soft skills"],
  "work_experience": [
    {{
      "company": "company name",
      "role": "job title",
      "duration_months": 12,
      "domain": "domain/industry",
      "skills_used": ["skills used in this role"],
      "description": "brief description",
      "start_date": "YYYY-MM or null",
      "end_date": "YYYY-MM or null (use Present for current)"
    }}
  ],
  "education": [
    {{
      "degree": "degree name",
      "level": "high_school|associate|bachelor|master|phd",
      "field": "field of study",
      "institution": "school name",
      "year": 2020
    }}
  ],
  "certifications": ["list of certifications"],
  "projects": [
    {{
      "name": "project name",
      "description": "brief description",
      "technologies": ["tech stack"],
      "domain": "domain or null"
    }}
  ]
}}

Rules:
- Only extract what is explicitly stated; never invent.
- duration_months: estimate from dates if not stated.
- skills: include both technical and domain skills.
"""


def _parse_with_llm(text: str, filename: str, llm_client: Any) -> CandidateProfile:
    prompt = _RESUME_PROMPT.format(resume_text=text[:8000])
    raw = llm_client.complete(prompt, max_tokens=2048)
    data = _extract_json(raw)
    return _build_profile(data, filename, "pdf" if filename.endswith(".pdf") else "docx")


# ── Heuristic parse ───────────────────────────────────────────────────────────

_SKILL_VOCAB = {
    "python", "javascript", "typescript", "java", "go", "rust", "c++", "c#",
    "ruby", "php", "swift", "kotlin", "scala", "r",
    "react", "vue", "angular", "next.js", "svelte", "node.js", "express",
    "django", "flask", "fastapi", "spring", "rails",
    "postgresql", "mysql", "mongodb", "redis", "elasticsearch", "sqlite",
    "aws", "gcp", "azure", "docker", "kubernetes", "terraform", "ansible",
    "git", "github", "gitlab", "ci/cd", "jenkins",
    "machine learning", "deep learning", "tensorflow", "pytorch", "scikit-learn",
    "sql", "graphql", "rest api", "grpc", "kafka", "rabbitmq",
    "linux", "bash", "microservices", "agile", "scrum",
    "html", "css", "tailwind", "bootstrap", "figma",
    "spark", "hadoop", "airflow", "dbt",
}

_EDU_LEVEL_MAP = {
    "ph.d": EducationLevel.PHD, "phd": EducationLevel.PHD,
    "doctorate": EducationLevel.PHD,
    "master": EducationLevel.MASTER, "m.s": EducationLevel.MASTER,
    "m.sc": EducationLevel.MASTER, "mba": EducationLevel.MASTER,
    "m.eng": EducationLevel.MASTER, "m.tech": EducationLevel.MASTER,
    "bachelor": EducationLevel.BACHELOR, "b.s": EducationLevel.BACHELOR,
    "b.sc": EducationLevel.BACHELOR, "b.e": EducationLevel.BACHELOR,
    "b.tech": EducationLevel.BACHELOR, "b.a": EducationLevel.BACHELOR,
    "associate": EducationLevel.ASSOCIATE,
    "high school": EducationLevel.HIGH_SCHOOL, "diploma": EducationLevel.HIGH_SCHOOL,
}


def _parse_heuristic(text: str, filename: str) -> CandidateProfile:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    lower = text.lower()

    # Name — first non-empty line that looks like a name
    name = _extract_name(lines)

    # Email
    email_match = re.search(r"[\w.+%-]+@[\w.-]+\.\w{2,}", text)
    email = email_match.group(0) if email_match else None

    # Phone
    phone_match = re.search(r"[\+]?[\d\s\-\(\)]{10,16}", text)
    phone = phone_match.group(0).strip() if phone_match else None

    # Skills
    skills = sorted(s for s in _SKILL_VOCAB if re.search(r"\b" + re.escape(s) + r"\b", lower))

    # Work experience blocks
    work_exp = _extract_work_experience(text)
    total_months = sum(w.duration_months for w in work_exp)
    total_years = round(total_months / 12, 1)

    # Education
    education = _extract_education(text)

    # Certifications
    certs = _extract_certifications(text)

    # Projects
    projects = _extract_projects(text)

    # Summary — paragraph after name/contact block
    summary = _extract_summary(lines)

    # Communication indicators
    comm = _assess_communication(text, lines)

    src_type = "pdf" if filename.lower().endswith(".pdf") else "docx"

    return CandidateProfile(
        candidate_id=str(uuid.uuid4()),
        name=name,
        email=email,
        phone=phone,
        summary=summary,
        skills=skills,
        work_experience=work_exp,
        education=education,
        certifications=certs,
        projects=projects,
        total_years_experience=total_years,
        source_file=filename,
        source_type=src_type,
        communication_indicators=comm,
    )


# ── Heuristic helpers ─────────────────────────────────────────────────────────

def _extract_name(lines: List[str]) -> str:
    for line in lines[:5]:
        # Name lines: typically 2-4 words, no special chars
        words = line.split()
        if 2 <= len(words) <= 4 and all(re.match(r"[A-Za-z'\-\.]+$", w) for w in words):
            return line
    return "Unknown Candidate"


def _extract_work_experience(text: str) -> List[WorkExperience]:
    """Extract work experience entries using section pattern matching."""
    experiences: List[WorkExperience] = []

    # Look for date patterns like "Jan 2020 – Dec 2022" or "2019 - Present"
    date_pattern = re.compile(
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|"
        r"April|June|July|August|September|October|November|December)\s+\d{4}|\d{4})"
        r"\s*[–\-—to]+\s*"
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|"
        r"April|June|July|August|September|October|November|December)\s+\d{4}|\d{4}|Present|Current|Now)",
        re.IGNORECASE,
    )

    blocks = re.split(r"\n{2,}", text)
    for block in blocks:
        dates = date_pattern.findall(block)
        if not dates:
            continue
        start_str, end_str = dates[0]
        duration = _calc_duration_months(start_str, end_str)

        lines = [l.strip() for l in block.splitlines() if l.strip()]
        role = lines[0] if lines else "Unknown Role"
        company = lines[1] if len(lines) > 1 else "Unknown Company"
        description = " ".join(lines[2:5]) if len(lines) > 2 else ""

        lower_block = block.lower()
        skills_used = [
            s for s in _SKILL_VOCAB
            if re.search(r"\b" + re.escape(s) + r"\b", lower_block)
        ]

        exp = WorkExperience(
            company=company[:200],
            role=role[:200],
            duration_months=duration,
            domain=_infer_domain(block),
            skills_used=skills_used[:15],
            description=description[:400],
            start_date=start_str,
            end_date=end_str,
        )
        experiences.append(exp)
        if len(experiences) >= 6:
            break

    return experiences


def _calc_duration_months(start: str, end: str) -> int:
    """Estimate duration in months from date strings."""
    def extract_year_month(s: str) -> Tuple[int, int]:
        if re.match(r"^\d{4}$", s.strip()):
            return int(s.strip()), 6  # assume mid-year
        month_map = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        }
        parts = s.lower().split()
        year = next((int(p) for p in parts if p.isdigit() and len(p) == 4), datetime.now().year)
        month = next((month_map[p[:3]] for p in parts if p[:3] in month_map), 1)
        return year, month

    try:
        if end.lower() in ("present", "current", "now"):
            end_year, end_month = datetime.now().year, datetime.now().month
        else:
            end_year, end_month = extract_year_month(end)
        start_year, start_month = extract_year_month(start)
        months = (end_year - start_year) * 12 + (end_month - start_month)
        return max(1, months)
    except Exception:
        return 12  # default 1 year


def _infer_domain(text: str) -> str:
    lower = text.lower()
    if any(w in lower for w in ["fintech", "banking", "finance", "payments", "trading"]):
        return "fintech"
    if any(w in lower for w in ["healthcare", "medical", "health", "pharma", "clinical"]):
        return "healthcare"
    if any(w in lower for w in ["e-commerce", "ecommerce", "retail", "marketplace"]):
        return "e-commerce"
    if any(w in lower for w in ["ml", "machine learning", "ai ", "data science", "nlp"]):
        return "ai/ml"
    if any(w in lower for w in ["devops", "sre", "infrastructure", "cloud"]):
        return "devops"
    return "software engineering"


def _extract_education(text: str) -> List[Education]:
    educations: List[Education] = []
    lower = text.lower()
    for kw, level in sorted(_EDU_LEVEL_MAP.items(), key=lambda x: -len(x[0])):
        if kw in lower:
            # Find the line containing this keyword
            for line in text.splitlines():
                if kw in line.lower():
                    year_match = re.search(r"\b(19|20)\d{2}\b", line)
                    year = int(year_match.group(0)) if year_match else None
                    educations.append(Education(
                        degree=line.strip()[:200],
                        level=level,
                        field=_extract_field(line),
                        institution=_extract_institution(line),
                        year=year,
                    ))
                    break
    return educations[:3]


def _extract_field(line: str) -> str:
    fields = ["computer science", "software engineering", "information technology",
              "data science", "electrical engineering", "mathematics", "physics",
              "business", "economics", "finance"]
    lower = line.lower()
    for f in fields:
        if f in lower:
            return f.title()
    return "Unknown"


def _extract_institution(line: str) -> str:
    inst_keywords = ["university", "college", "institute", "school", "academy"]
    lower = line.lower()
    for kw in inst_keywords:
        if kw in lower:
            idx = lower.index(kw)
            start = max(0, idx - 30)
            end = min(len(line), idx + 30)
            return line[start:end].strip()
    return "Unknown Institution"


def _extract_certifications(text: str) -> List[str]:
    patterns = [
        r"AWS\s+(?:Certified|Solutions Architect|Developer|DevOps Engineer)[^\n]*",
        r"Google\s+(?:Certified|Cloud)[^\n]*",
        r"Azure\s+(?:Administrator|Developer|Architect|Certified)[^\n]*",
        r"CKA(?:D|S)?\b[^\n]*",
        r"PMP\b[^\n]*",
        r"(?:Oracle|Sun)\s+Certified[^\n]*",
        r"(?:Cisco\s+)?CCNA?\b[^\n]*",
        r"(?:Certified\s+)?(?:Scrum\s+Master|Product\s+Owner)[^\n]*",
        r"TensorFlow\s+Developer[^\n]*",
        r"(?:SHRM|PHR|SPHR)\b[^\n]*",
    ]
    certs: List[str] = []
    for pat in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            c = m.group(0).strip()[:100]
            if c not in certs:
                certs.append(c)
    return certs[:6]


def _extract_projects(text: str) -> List[Project]:
    projects: List[Project] = []
    # Look for "Projects" section
    section_match = re.search(
        r"(?:projects?|portfolio|open.?source)\s*\n(.*?)(?:\n\n|\Z)",
        text, re.IGNORECASE | re.DOTALL
    )
    if not section_match:
        return projects

    section = section_match.group(1)
    entries = re.split(r"\n(?=[A-Z•\-])", section)
    for entry in entries[:5]:
        entry = entry.strip()
        if len(entry) < 10:
            continue
        lines = entry.splitlines()
        name = lines[0].lstrip("•-").strip()[:100]
        desc = " ".join(lines[1:3]).strip()[:300] if len(lines) > 1 else ""
        lower_e = entry.lower()
        techs = [s for s in _SKILL_VOCAB if re.search(r"\b" + re.escape(s) + r"\b", lower_e)]
        projects.append(Project(
            name=name,
            description=desc,
            technologies=techs[:8],
            domain=_infer_domain(entry),
        ))
    return projects


def _extract_summary(lines: List[str]) -> Optional[str]:
    # Summary is usually a multi-word paragraph in the first 15 lines
    for i, line in enumerate(lines[:15]):
        words = line.split()
        if len(words) > 10 and not re.match(r"^[\w.]+@", line):
            return line[:500]
    return None


def _assess_communication(text: str, lines: List[str]) -> CommunicationIndicators:
    has_summary = any(
        w in text.lower() for w in ["summary", "objective", "profile", "about me"]
    )
    bullets = sum(1 for l in lines if l.startswith(("•", "-", "–", "*")))
    bullet_used = bullets > 3

    # Count quantified achievements (numbers in achievement lines)
    quant = len(re.findall(r"\b\d+%|\b\d+x|\b\$[\d]+|\b\d{4,}\b", text))

    # Vocabulary richness (unique words / total words ratio approximation)
    words = re.findall(r"[a-z]+", text.lower())
    vocab_richness = min(1.0, len(set(words)) / max(len(words), 1) * 3) if words else 0.5

    # Structure score based on section headers
    section_headers = len(re.findall(
        r"^(experience|education|skills?|projects?|certifications?|summary|objective)\s*$",
        text, re.MULTILINE | re.IGNORECASE
    ))
    structure = min(1.0, section_headers / 4)

    # Grammar proxy: avg sentence length (very long or very short = issues)
    sentences = re.split(r"[.!?]+", text)
    avg_len = sum(len(s.split()) for s in sentences) / max(len(sentences), 1)
    grammar = 0.6 if avg_len < 3 or avg_len > 40 else 0.8

    return CommunicationIndicators(
        has_summary=has_summary,
        bullet_points_used=bullet_used,
        quantified_achievements=min(quant, 20),
        grammar_score=round(grammar, 2),
        structure_score=round(structure, 2),
        vocabulary_richness=round(vocab_richness, 2),
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_json(text: str) -> Dict[str, Any]:
    text = re.sub(r"```(?:json)?", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise ValueError("No valid JSON in LLM response")


def _build_profile(data: Dict[str, Any], filename: str, src_type: str) -> CandidateProfile:
    def _list(k: str) -> List[str]:
        v = data.get(k, [])
        return [str(x).strip() for x in (v if isinstance(v, list) else [])]

    work_exp: List[WorkExperience] = []
    for w in data.get("work_experience", []):
        work_exp.append(WorkExperience(
            company=str(w.get("company", ""))[:200],
            role=str(w.get("role", ""))[:200],
            duration_months=int(w.get("duration_months", 12)),
            domain=str(w.get("domain", "general"))[:100],
            skills_used=_list("skills_used") if "skills_used" in w else [],
            description=str(w.get("description", ""))[:400],
            start_date=w.get("start_date"),
            end_date=w.get("end_date"),
        ))

    educations: List[Education] = []
    for e in data.get("education", []):
        level_str = str(e.get("level", "bachelor")).lower()
        level = EducationLevel.BACHELOR
        for k, v in EducationLevel.__members__.items():
            if v.value == level_str:
                level = v
                break
        educations.append(Education(
            degree=str(e.get("degree", ""))[:200],
            level=level,
            field=str(e.get("field", ""))[:100],
            institution=str(e.get("institution", ""))[:200],
            year=e.get("year"),
        ))

    projects: List[Project] = []
    for p in data.get("projects", []):
        projects.append(Project(
            name=str(p.get("name", ""))[:100],
            description=str(p.get("description", ""))[:300],
            technologies=_list("technologies") if "technologies" in p else [],
            domain=p.get("domain"),
        ))

    total_months = sum(w.duration_months for w in work_exp)
    total_years = round(total_months / 12, 1)

    return CandidateProfile(
        candidate_id=str(uuid.uuid4()),
        name=str(data.get("name", "Unknown"))[:100],
        email=data.get("email"),
        phone=data.get("phone"),
        summary=data.get("summary"),
        skills=_list("skills"),
        work_experience=work_exp,
        education=educations,
        certifications=_list("certifications"),
        projects=projects,
        total_years_experience=total_years,
        source_file=filename,
        source_type=src_type,
    )
