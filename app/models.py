"""Core Pydantic models — single source of truth for all data structures."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


# ── Enums ────────────────────────────────────────────────────────────────────

class EducationLevel(str, Enum):
    HIGH_SCHOOL = "high_school"
    ASSOCIATE = "associate"
    BACHELOR = "bachelor"
    MASTER = "master"
    PHD = "phd"
    ANY = "any"


class SeniorityLevel(str, Enum):
    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    STAFF = "staff"
    ANY = "any"


class Recommendation(str, Enum):
    HIRE = "hire"
    BORDERLINE = "borderline"
    NO_HIRE = "no_hire"


# ── JD Models ────────────────────────────────────────────────────────────────

class JDProfile(BaseModel):
    title: str = "Unknown Role"
    company: Optional[str] = None
    required_skills: List[str] = Field(default_factory=list)
    preferred_skills: List[str] = Field(default_factory=list)
    years_experience_min: int = 0
    years_experience_max: Optional[int] = None
    education_requirement: EducationLevel = EducationLevel.ANY
    certifications: List[str] = Field(default_factory=list)
    domain: str = "general"
    industry: Optional[str] = None
    key_responsibilities: List[str] = Field(default_factory=list)
    seniority_level: SeniorityLevel = SeniorityLevel.ANY
    raw_text: str = ""


# ── Candidate Profile Models ──────────────────────────────────────────────────

class WorkExperience(BaseModel):
    company: str = ""
    role: str = ""
    duration_months: int = 0
    domain: str = "general"
    skills_used: List[str] = Field(default_factory=list)
    description: str = ""
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class Education(BaseModel):
    degree: str = ""
    level: EducationLevel = EducationLevel.BACHELOR
    field: str = ""
    institution: str = ""
    year: Optional[int] = None


class Project(BaseModel):
    name: str = ""
    description: str = ""
    technologies: List[str] = Field(default_factory=list)
    domain: Optional[str] = None
    url: Optional[str] = None


class CommunicationIndicators(BaseModel):
    has_summary: bool = False
    bullet_points_used: bool = False
    quantified_achievements: int = 0
    grammar_score: float = Field(default=0.7, ge=0.0, le=1.0)
    structure_score: float = Field(default=0.7, ge=0.0, le=1.0)
    vocabulary_richness: float = Field(default=0.7, ge=0.0, le=1.0)


class CandidateProfile(BaseModel):
    candidate_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Unknown"
    email: Optional[str] = None
    phone: Optional[str] = None
    summary: Optional[str] = None
    skills: List[str] = Field(default_factory=list)
    work_experience: List[WorkExperience] = Field(default_factory=list)
    education: List[Education] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)
    projects: List[Project] = Field(default_factory=list)
    total_years_experience: float = 0.0
    source_file: str = ""
    source_type: str = "pdf"  # pdf | docx | linkedin
    communication_indicators: CommunicationIndicators = Field(
        default_factory=CommunicationIndicators
    )


# ── Scoring Models ────────────────────────────────────────────────────────────

class DimensionScore(BaseModel):
    """Score for a single rubric dimension."""
    score: float = Field(..., ge=0.0, le=10.0)
    weight: float = Field(..., ge=0.0, le=1.0)
    weighted_contribution: float = Field(default=0.0)
    justification: str = ""
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def compute_contribution(self) -> "DimensionScore":
        self.weighted_contribution = round(self.score * self.weight * 10, 2)
        return self


class RubricScores(BaseModel):
    """All 5 rubric dimensions with mandatory weights."""
    skills_match: DimensionScore           # 30%
    experience_relevance: DimensionScore   # 25%
    education_certs: DimensionScore        # 15%
    project_portfolio: DimensionScore      # 20%
    communication_quality: DimensionScore  # 10%

    @property
    def total(self) -> float:
        return round(
            self.skills_match.weighted_contribution
            + self.experience_relevance.weighted_contribution
            + self.education_certs.weighted_contribution
            + self.project_portfolio.weighted_contribution
            + self.communication_quality.weighted_contribution,
            2,
        )


# ── Override / Audit ──────────────────────────────────────────────────────────

class OverrideAction(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    hr_user: str = "HR"
    dimension: Optional[str] = None  # None = total-level flag/note
    old_score: float
    new_score: float
    reason: str
    flagged: bool = False


# ── Result Models ─────────────────────────────────────────────────────────────

class CandidateResult(BaseModel):
    candidate_id: str
    name: str
    source_file: str
    profile: CandidateProfile
    scores: RubricScores
    total_score: float  # 0–100
    recommendation: Recommendation
    rank: Optional[int] = None
    overrides: List[OverrideAction] = Field(default_factory=list)
    flagged: bool = False
    flag_reason: Optional[str] = None
    processed_at: datetime = Field(default_factory=datetime.utcnow)


class AnalysisSession(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    jd_profile: JDProfile
    results: List[CandidateResult] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    shortlist_summary: str = ""
    status: str = "processing"  # processing | completed | failed
    error: Optional[str] = None


# ── API Request/Response Models ───────────────────────────────────────────────

class OverrideRequest(BaseModel):
    dimension: Optional[str] = None
    new_score: float = Field(..., ge=0.0, le=10.0)
    reason: str = Field(..., min_length=1, max_length=1000)
    hr_user: str = Field(default="HR", max_length=100)
    flag: bool = False
    flag_reason: Optional[str] = None


class ShortlistSummary(BaseModel):
    session_id: str
    total_candidates: int
    hire_recommended: int
    borderline: int
    no_hire: int
    top_candidate: Optional[str] = None
    avg_score: float
    generated_at: datetime = Field(default_factory=datetime.utcnow)
