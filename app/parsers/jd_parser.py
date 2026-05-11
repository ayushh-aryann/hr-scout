"""JD Parser — extracts structured requirements from raw job description text."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.models import EducationLevel, JDProfile, SeniorityLevel
from app.security.sanitizer import sanitize_jd

logger = logging.getLogger(__name__)

# ── LLM prompt ────────────────────────────────────────────────────────────────

_JD_PARSE_PROMPT = """You are an expert HR analyst. Parse the job description below into structured JSON.

Job Description:
---
{jd_text}
---

Return ONLY valid JSON (no markdown fences) with this exact schema:
{{
  "title": "string — job title",
  "company": "string or null",
  "required_skills": ["list of must-have technical skills"],
  "preferred_skills": ["list of nice-to-have skills"],
  "years_experience_min": 0,
  "years_experience_max": null,
  "education_requirement": "any|high_school|associate|bachelor|master|phd",
  "certifications": ["list of required/preferred certifications"],
  "domain": "brief domain label e.g. full-stack development",
  "industry": "industry sector or null",
  "key_responsibilities": ["top 5 responsibilities as short phrases"],
  "seniority_level": "any|intern|junior|mid|senior|staff"
}}

Rules:
- Only include skills explicitly mentioned; never invent.
- required_skills = must-have; preferred_skills = nice-to-have / bonus.
- years_experience_min = minimum years stated (0 if not stated).
- All string values must be plain text, not markdown.
"""


def parse_jd(jd_text: str, llm_client: Any = None) -> JDProfile:
    """Parse a job description into a structured JDProfile."""
    clean_text = sanitize_jd(jd_text)

    if llm_client is not None:
        try:
            return _parse_with_llm(clean_text, llm_client)
        except Exception as exc:
            logger.warning("LLM JD parse failed (%s), falling back to heuristics", exc)

    return _parse_heuristic(clean_text)


# ── LLM path ─────────────────────────────────────────────────────────────────

def _parse_with_llm(clean_text: str, llm_client: Any) -> JDProfile:
    prompt = _JD_PARSE_PROMPT.format(jd_text=clean_text)
    raw = llm_client.complete(prompt, max_tokens=1024)
    data = _extract_json(raw)
    return _build_profile(data, clean_text)


# ── Heuristic fallback ────────────────────────────────────────────────────────

_SKILL_KEYWORDS = {
    "python", "javascript", "typescript", "java", "go", "rust", "c++", "c#",
    "ruby", "php", "swift", "kotlin", "scala", "r", "matlab",
    "react", "vue", "angular", "next.js", "svelte", "node.js", "express",
    "django", "flask", "fastapi", "spring", "rails", "laravel",
    "postgresql", "mysql", "mongodb", "redis", "elasticsearch", "sqlite",
    "aws", "gcp", "azure", "docker", "kubernetes", "terraform", "ansible",
    "git", "ci/cd", "jenkins", "github actions", "circleci",
    "machine learning", "deep learning", "tensorflow", "pytorch", "scikit-learn",
    "sql", "graphql", "rest", "grpc", "kafka", "rabbitmq",
    "linux", "bash", "powershell", "microservices", "devops",
}

_CERT_PATTERNS = [
    r"\bAWS\s+(?:Certified|Solutions Architect|Developer|DevOps)\b",
    r"\bGCP\s+(?:Associate|Professional|Certified)\b",
    r"\bAzure\s+(?:Administrator|Developer|Architect)\b",
    r"\bCKA\b", r"\bCKAD\b", r"\bCKS\b",
    r"\bPMP\b", r"\bCSM\b", r"\bCPHR\b",
    r"\bCPA\b", r"\bCFA\b",
    r"\bOCP\b", r"\bOCA\b",
]

_EDU_MAP = {
    "phd": EducationLevel.PHD,
    "doctorate": EducationLevel.PHD,
    "master": EducationLevel.MASTER,
    "mba": EducationLevel.MASTER,
    "bachelor": EducationLevel.BACHELOR,
    "b.s": EducationLevel.BACHELOR,
    "b.e": EducationLevel.BACHELOR,
    "b.tech": EducationLevel.BACHELOR,
    "associate": EducationLevel.ASSOCIATE,
    "high school": EducationLevel.HIGH_SCHOOL,
}

_SENIORITY_MAP = {
    "intern": SeniorityLevel.INTERN,
    "junior": SeniorityLevel.JUNIOR,
    "entry": SeniorityLevel.JUNIOR,
    "mid-level": SeniorityLevel.MID,
    "mid level": SeniorityLevel.MID,
    "senior": SeniorityLevel.SENIOR,
    "sr.": SeniorityLevel.SENIOR,
    "staff": SeniorityLevel.STAFF,
    "principal": SeniorityLevel.STAFF,
    "lead": SeniorityLevel.SENIOR,
}


def _parse_heuristic(text: str) -> JDProfile:
    lower = text.lower()

    # Title — first line or heading-like sentence
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    title = lines[0] if lines else "Unknown Role"
    if len(title) > 120:
        title = title[:120]

    # Skills — keyword scan
    found_skills = sorted(
        s for s in _SKILL_KEYWORDS if re.search(r"\b" + re.escape(s) + r"\b", lower)
    )
    required = found_skills[:max(1, len(found_skills) // 2 + 1)]
    preferred = found_skills[len(required):]

    # Certifications
    certs: List[str] = []
    for pat in _CERT_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            c = m.group(0).strip()
            if c not in certs:
                certs.append(c)

    # Years of experience
    exp_match = re.search(
        r"(\d+)\+?\s*(?:to|-)\s*(\d+)\s*years?|(\d+)\+?\s*years?", lower
    )
    exp_min = 0
    exp_max: Optional[int] = None
    if exp_match:
        if exp_match.group(1):
            exp_min = int(exp_match.group(1))
            exp_max = int(exp_match.group(2))
        elif exp_match.group(3):
            exp_min = int(exp_match.group(3))

    # Education
    edu = EducationLevel.ANY
    for kw, level in sorted(_EDU_MAP.items(), key=lambda x: -len(x[0])):
        if kw in lower:
            edu = level
            break

    # Seniority
    seniority = SeniorityLevel.ANY
    for kw, level in sorted(_SENIORITY_MAP.items(), key=lambda x: -len(x[0])):
        if kw in lower:
            seniority = level
            break

    # Domain — simple heuristic
    domain = "software engineering"
    if any(w in lower for w in ["data science", "machine learning", "ml engineer"]):
        domain = "data science / ml"
    elif any(w in lower for w in ["devops", "sre", "infrastructure", "platform"]):
        domain = "devops / infrastructure"
    elif any(w in lower for w in ["frontend", "front-end", "ui engineer"]):
        domain = "frontend development"
    elif any(w in lower for w in ["full-stack", "full stack"]):
        domain = "full-stack development"
    elif any(w in lower for w in ["backend", "back-end", "api engineer"]):
        domain = "backend development"

    # Responsibilities — sentences containing action verbs
    action_verbs = ["design", "build", "develop", "lead", "maintain", "implement",
                    "collaborate", "own", "drive", "architect"]
    responsibilities: List[str] = []
    for sent in re.split(r"[.\n]", text):
        s = sent.strip()
        if any(v in s.lower() for v in action_verbs) and 10 < len(s) < 200:
            responsibilities.append(s)
            if len(responsibilities) >= 5:
                break

    return JDProfile(
        title=title,
        required_skills=required,
        preferred_skills=preferred,
        years_experience_min=exp_min,
        years_experience_max=exp_max,
        education_requirement=edu,
        certifications=certs,
        domain=domain,
        seniority_level=seniority,
        key_responsibilities=responsibilities,
        raw_text=text,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_json(text: str) -> Dict[str, Any]:
    """Strip markdown fences and parse JSON."""
    text = re.sub(r"```(?:json)?", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object via regex
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise ValueError("No valid JSON found in LLM response")


def _build_profile(data: Dict[str, Any], raw_text: str) -> JDProfile:
    def _list(key: str) -> List[str]:
        v = data.get(key, [])
        return [str(x).strip() for x in v if x] if isinstance(v, list) else []

    edu_str = str(data.get("education_requirement", "any")).lower()
    edu = EducationLevel.ANY
    for k, v in EducationLevel.__members__.items():
        if v.value == edu_str:
            edu = v
            break

    sen_str = str(data.get("seniority_level", "any")).lower()
    sen = SeniorityLevel.ANY
    for k, v in SeniorityLevel.__members__.items():
        if v.value == sen_str:
            sen = v
            break

    return JDProfile(
        title=str(data.get("title", "Unknown Role"))[:200],
        company=data.get("company"),
        required_skills=_list("required_skills"),
        preferred_skills=_list("preferred_skills"),
        years_experience_min=int(data.get("years_experience_min", 0)),
        years_experience_max=data.get("years_experience_max"),
        education_requirement=edu,
        certifications=_list("certifications"),
        domain=str(data.get("domain", "general"))[:100],
        industry=data.get("industry"),
        key_responsibilities=_list("key_responsibilities"),
        seniority_level=sen,
        raw_text=raw_text,
    )
