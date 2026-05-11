# HR Scout — AI Candidate Shortlisting Agent

> AI-powered resume screening with a mandatory 5-dimension weighted rubric, transparent justifications, human-in-the-loop override, and multi-format reports.

---

## Table of Contents
1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Tech Stack & Decision Log](#tech-stack--decision-log)
4. [Security Mitigations](#security-mitigations)
5. [Setup](#setup)
6. [Running the Demo](#running-the-demo)
7. [API Reference](#api-reference)
8. [Scoring Rubric](#scoring-rubric)
9. [Human Override](#human-override)
10. [Sample Output](#sample-output)
11. [Testing](#testing)
12. [Prompt Design Notes](#prompt-design-notes)

---

## Overview

HR Scout ingests a Job Description + candidate resumes (PDF/DOCX/LinkedIn JSON), scores each candidate on 5 weighted dimensions, ranks them, and delivers a shortlist report in JSON, HTML, and PDF.

**What it solves:**
- Manual CV screening takes hours; this takes seconds
- Ad-hoc decisions lack transparency; every dimension gets a one-line justification
- Bias creeps into unstructured reviews; the rubric enforces consistency
- LLM outputs can hallucinate; Pydantic validation + heuristic fallback keeps scores grounded

---

## Architecture

```
                  ┌─────────────────────────────────────────────────┐
                  │               HR Scout Pipeline                   │
  JD Text    ───► │  JD Parser  ──► JDProfile (structured)           │
  PDF/DOCX   ───► │  Resume Parser ─► CandidateProfile               │
  LinkedIn JSON ► │  LinkedIn Parser ─► CandidateProfile             │
                  │                                                   │
                  │  Scoring Engine                                   │
                  │  ├── Skills Match (30%) ← embedding overlap      │
                  │  ├── Experience Relevance (25%) ← domain match   │
                  │  ├── Education & Certs (15%) ← level comparison  │
                  │  ├── Project Portfolio (20%) ← semantic sim      │
                  │  └── Communication Quality (10%) ← indicators    │
                  │                                                   │
                  │  Ranking → Shortlist Report (JSON/HTML/PDF)      │
                  │  Audit Log → JSONL append-only trail             │
                  └─────────────────────────────────────────────────┘
                       ▲                              │
                       │                              ▼
              FastAPI REST API              Human Override (HR)
                       ▲                              │
                       │                              ▼
              React Frontend               Override Log + Re-rank
              (single HTML file)
```

---

## Tech Stack & Decision Log

| Component | Choice | Reason |
|-----------|--------|--------|
| **LLM** | Claude claude-sonnet-4-6 (Anthropic) | Best-in-class structured JSON extraction; function calling reliability; low hallucination rate |
| **LLM Fallback** | GPT-4o-mini (OpenAI) | Secondary option when Anthropic key unavailable |
| **Local mode** | Heuristic + embeddings | Zero-API-key demo capability; no cold start |
| **Embeddings** | all-MiniLM-L6-v2 (sentence-transformers) | Local, fast, strong semantic matching; no API cost |
| **Backend** | FastAPI | Async, auto-generated OpenAPI docs, Pydantic-native |
| **Resume PDF** | pdfplumber | Best text extraction quality from PDFs |
| **Resume DOCX** | python-docx | Native DOCX parsing |
| **PDF reports** | ReportLab | Pure-Python, reliable, no system dependencies |
| **HTML reports** | Jinja2 | Clean separation of logic and template |
| **Frontend** | React 18 (CDN, single HTML) | Zero build step, ships in one file; same design language as base UI |
| **Storage** | JSON files | Portable, human-readable, no database setup required |
| **Env secrets** | python-dotenv | Industry standard; .env excluded from git |

**Why Claude over GPT-4?**
Claude's structured output adherence is stronger for schema-constrained prompts. The `claude-sonnet-4-6` model provides excellent HR domain reasoning at a reasonable cost. Claude is also the model being used in this very session (aligned with the user's workflow).

---

## Security Mitigations

### Prompt Injection
- All JD/resume text passes through `app/security/sanitizer.py` before any LLM call
- 12 injection pattern regexes neutralize `ignore previous instructions`, `forget everything`, system tag injections, jailbreak keywords, etc.
- Candidate text is embedded in clearly delimited sections (not interpolated into system instructions)
- All LLM outputs validated by Pydantic models — invalid JSON or out-of-range scores are rejected

### Data Privacy / PII
- `mask_pii()` in `sanitizer.py` masks email, phone, address fields in all audit logs
- Only the minimum profile fields are sent to the LLM (no full raw text after parsing)
- Local heuristic mode sends zero data to any external service
- Logs explicitly exclude raw resume text

### API Key Handling
- All secrets in `.env` (never hardcoded)
- `.env.example` provided with placeholder values
- `.gitignore` excludes `.env` and any `*.env` files
- `get_settings()` uses `lru_cache` to prevent repeated file reads

### Hallucination Control
- Every LLM response is parsed by a Pydantic model — scores must be `float` in `[0, 10]`
- Out-of-range scores are clamped rather than trusted
- Recommendation is always validated against the computed weighted total (LLM can't claim "hire" if score < 65)
- `model_validator` on `DimensionScore` recomputes `weighted_contribution` from the score — LLM can't inflate contributions
- If LLM parse fails, system falls back to heuristics (never crashes with a hallucinated result)

### Unauthorized Access
- Override endpoints accept an `hr_user` field for attribution
- `_verify_admin` dependency is implemented in `routes.py` (currently commented out for local demo — enable with `Depends(_verify_admin)`)
- CORS restricted to `*` in dev — tighten to your domain in production
- All file uploads capped at 10 MB, max 30 files per request

---

## Setup

### Prerequisites
- Python 3.11+
- `pip`

### Installation

```bash
# Clone / navigate to project
cd "HR-Linkedin"

# Create virtual environment
python -m venv venv
venv\Scripts\activate      # Windows
# source venv/bin/activate # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Configure environment
copy .env.example .env     # Windows
# cp .env.example .env     # macOS/Linux

# Edit .env — add your Anthropic API key (optional; works without it)
# LLM_PROVIDER=anthropic
# ANTHROPIC_API_KEY=sk-ant-api03-...
```

### sentence-transformers model
The `all-MiniLM-L6-v2` model downloads automatically (~90 MB) on first run.
To pre-download: `python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"`

---

## Running the Demo

### Start the backend
```bash
python main.py
# → Uvicorn running on http://127.0.0.1:8000
```

### Open the frontend
Navigate to `http://127.0.0.1:8000` — the React frontend is served directly.

Or open `index.html` in a browser (requires backend for live analysis; shows UI immediately).

### Quick API demo with sample data
```bash
# Run the pipeline directly with sample data
python -c "
from pathlib import Path
from app.agents.pipeline import HRPipeline
import json

pipeline = HRPipeline()
jd = json.loads(Path('data/sample_jd.json').read_text())['raw_text']
candidates = [(Path(f).read_bytes(), f.name) for f in Path('data/candidates').glob('*.json')]
session = pipeline.analyze(jd, candidates)
print(session.shortlist_summary)
for r in session.results:
    print(f'  #{r.rank} {r.name}: {r.total_score:.1f}/100 [{r.recommendation.value}]')
print(f'Session saved: outputs/sessions/{session.session_id}.json')
"
```

### Run via API
```bash
# Upload JD + candidates
curl -X POST http://127.0.0.1:8000/api/v1/analyze \
  -F "jd_text=Senior Python engineer needed with React and AWS..." \
  -F "files=@data/candidates/alice_chen.json" \
  -F "files=@data/candidates/bob_kumar.json"

# Get JSON report
curl http://127.0.0.1:8000/api/v1/sessions/{session_id}/report/json

# Get HTML report
curl http://127.0.0.1:8000/api/v1/sessions/{session_id}/report/html > report.html

# Apply override
curl -X POST http://127.0.0.1:8000/api/v1/sessions/{session_id}/candidates/{candidate_id}/override \
  -H "Content-Type: application/json" \
  -d '{"dimension":"skills_match","new_score":8.5,"reason":"GitHub review confirmed additional expertise","hr_user":"HR Manager"}'
```

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/health` | Health check |
| `POST` | `/api/v1/analyze` | Run full analysis (form-data: jd_text + files) |
| `GET` | `/api/v1/sessions` | List all sessions |
| `GET` | `/api/v1/sessions/{id}` | Get session results |
| `POST` | `/api/v1/sessions/{id}/candidates/{cid}/override` | Apply HR override |
| `GET` | `/api/v1/sessions/{id}/report/json` | Download JSON report |
| `GET` | `/api/v1/sessions/{id}/report/html` | View/download HTML report |
| `GET` | `/api/v1/sessions/{id}/report/pdf` | Download PDF report |
| `GET` | `/api/v1/sessions/{id}/audit` | View audit trail |
| `GET` | `/docs` | Interactive Swagger UI |

---

## Scoring Rubric

Each candidate is scored on 5 dimensions. Scores are 0–10; weighted contributions sum to 100.

| Dimension | Weight | 0–3 (Poor) | 4–6 (Average) | 7–10 (Excellent) |
|-----------|--------|------------|----------------|-----------------|
| **Skills Match** | 30% | <30% of required skills | 50–70% match | >85% match |
| **Experience Relevance** | 25% | Unrelated domain | Adjacent domain | Exact domain + seniority |
| **Education & Certs** | 15% | Below minimum degree | Meets requirement | Exceeds + relevant certs |
| **Project Portfolio** | 20% | No projects listed | Generic projects | Strong, relevant portfolio |
| **Communication Quality** | 10% | Poor structure, no summary | Adequate writing | Crisp, structured, quantified |

**Recommendation thresholds:**
- ≥ 65: **Hire**
- 45–64: **Borderline**
- < 45: **No Hire**

---

## Human Override

HR can override any dimension score via the UI or API:

```json
POST /api/v1/sessions/{id}/candidates/{cid}/override
{
  "dimension": "skills_match",
  "new_score": 8.5,
  "reason": "Reviewed GitHub — strong Python OSS contributions confirmed",
  "hr_user": "Jane Smith",
  "flag": false
}
```

Every override:
- Logs `old_score → new_score` with timestamp and HR user
- Recalculates `total_score` and re-ranks all candidates
- Is visible in the UI and in all report formats
- Is appended to the session's `overrides[]` list (never destructive)

---

## Sample Output

With 5 sample candidates against the "Senior Full-Stack Engineer" JD:

```
#1 Alice Chen     — 82.4/100  [HIRE]
#2 Bob Kumar      — 59.1/100  [BORDERLINE]
#3 Carol Smith    — 48.7/100  [BORDERLINE]
#4 Emma Jones     — 38.2/100  [NO HIRE]
#5 David Lee      — 26.5/100  [NO HIRE]
```

Alice's skills_match justification: *"Strong 92% match on required skills (Python, React, TypeScript, PostgreSQL, Docker, Kubernetes) plus AWS and Kafka preferred coverage."*

---

## Testing

```bash
# Install test deps (included in requirements.txt)
pytest tests/ -v

# Run with coverage
pytest tests/ -v --tb=short
```

Tests cover:
- Weight validation (must sum to 1.0)
- Score bounds (0–10 per dimension, 0–100 total)
- Weighted contribution formula
- Strong candidate scores ≥ 65 (hire)
- Unrelated candidate scores < 55
- Justification presence for all dimensions
- LinkedIn JSON parser
- JD heuristic parser
- Prompt injection sanitization
- Override re-scoring

---

## Prompt Design Notes

### JD Parsing Prompt
Uses a strict JSON schema with explicit field descriptions. Rules section prevents skill invention. The prompt is **system-instructed** to return only JSON — candidate content never reaches the system message.

### Scoring Prompt
Provides both the JD summary and candidate profile as **data** (not instructions). The rubric guidance is embedded in the prompt to anchor LLM scoring. Recommendation is always post-validated against computed total score — LLM cannot override thresholds.

### Defense in depth
1. Sanitizer removes injection patterns before prompt construction
2. LLM system message instructs strict JSON compliance
3. Pydantic models validate and clamp all outputs
4. Heuristic fallback if LLM response fails validation
5. `weighted_contribution` is always recomputed from `score × weight × 10` — never trusted from LLM

---

## Project Structure

```
HR-Linkedin/
├── app/
│   ├── agents/pipeline.py       # Main orchestration pipeline
│   ├── parsers/
│   │   ├── jd_parser.py         # JD text → JDProfile
│   │   ├── resume_parser.py     # PDF/DOCX → CandidateProfile
│   │   └── linkedin_parser.py   # LinkedIn JSON → CandidateProfile
│   ├── scoring/
│   │   ├── rubric.py            # 5-dimension weighted scoring
│   │   └── embeddings.py        # Semantic similarity (sentence-transformers)
│   ├── reports/
│   │   ├── generator.py         # JSON/HTML/PDF generation
│   │   └── templates/report.html
│   ├── storage/audit.py         # Append-only JSONL audit log
│   ├── api/routes.py            # FastAPI route handlers
│   ├── security/sanitizer.py    # Prompt injection defense + PII masking
│   ├── config.py                # Settings from .env
│   └── models.py                # All Pydantic data models
├── data/
│   ├── sample_jd.json           # Sample JD (Senior Full-Stack Engineer)
│   └── candidates/              # 5 sample LinkedIn JSON profiles
├── outputs/                     # Generated session data + reports
├── tests/test_pipeline.py       # Pytest test suite
├── main.py                      # FastAPI entrypoint
├── index.html                   # React frontend (single file)
├── requirements.txt
├── .env.example
└── README.md
```
