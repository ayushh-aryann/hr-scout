"""Generate 5 realistic PDF resumes + 1 JD PDF for testing."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
)

OUT = Path(__file__).parent.parent / "sample_data" / "resumes"
OUT.mkdir(parents=True, exist_ok=True)

W, H = A4

# ── Style helpers ─────────────────────────────────────────────────────────────

def make_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("Name",    fontSize=22, fontName="Helvetica-Bold",
                               textColor=colors.HexColor("#1a1a1d"), spaceAfter=2))
    styles.add(ParagraphStyle("Contact", fontSize=9,  textColor=colors.grey, spaceAfter=8))
    styles.add(ParagraphStyle("Section", fontSize=11, fontName="Helvetica-Bold",
                               textColor=colors.HexColor("#1a1a1d"), spaceBefore=10, spaceAfter=3))
    styles.add(ParagraphStyle("Body",    fontSize=9.5, leading=14, spaceAfter=4))
    styles.add(ParagraphStyle("BulletItem",  fontSize=9,  leading=13, leftIndent=12,
                               bulletIndent=4, spaceAfter=2))
    styles.add(ParagraphStyle("JobTitle",fontSize=10, fontName="Helvetica-Bold", spaceAfter=1))
    styles.add(ParagraphStyle("SubGrey", fontSize=9,  textColor=colors.grey, spaceAfter=4))
    return styles

def divider():
    return HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#e5e7eb"), spaceAfter=4)

def section(title, styles):
    return [Paragraph(title.upper(), styles["Section"]), divider()]

def bullet(text, styles):
    return Paragraph(f"• {text}", styles["BulletItem"])

def build_pdf(filename, story):
    doc = SimpleDocTemplate(str(OUT / filename), pagesize=A4,
                             rightMargin=2*cm, leftMargin=2*cm,
                             topMargin=1.8*cm, bottomMargin=1.8*cm)
    doc.build(story)
    print(f"  OK {filename}")


# ── Resume 1: Alice Chen — Strong Match ───────────────────────────────────────
def alice_chen(styles):
    s = []
    s.append(Paragraph("Alice Chen", styles["Name"]))
    s.append(Paragraph("alice.chen@email.com  |  +1-415-555-0101  |  San Francisco, CA  |  github.com/alicechen", styles["Contact"]))
    s.append(Paragraph(
        "Senior full-stack engineer with 7+ years building high-throughput fintech systems. "
        "Led migration of payments platform from monolith to microservices at Stripe, cutting latency by 40%. "
        "Expert in Python/FastAPI, React/TypeScript, and AWS. AWS Solutions Architect certified.", styles["Body"]))
    s += section("Experience", styles)
    s.append(Paragraph("Senior Software Engineer — Stripe", styles["JobTitle"]))
    s.append(Paragraph("March 2021 – Present  |  San Francisco, CA", styles["SubGrey"]))
    for b in [
        "Led migration of payments processing service from monolith to microservices using Python/FastAPI + Kubernetes",
        "Reduced p99 API latency by 40% through Redis caching and PostgreSQL query optimisation",
        "Built real-time webhook delivery system handling 100k events/day using Apache Kafka",
        "Mentored 3 junior engineers; led weekly architecture reviews and code standards sessions",
        "Stack: Python, FastAPI, TypeScript, React, Kafka, Kubernetes, AWS, PostgreSQL, Redis, Docker"
    ]: s.append(bullet(b, styles))
    s.append(Spacer(1, 4*mm))
    s.append(Paragraph("Full-Stack Engineer — Plaid", styles["JobTitle"]))
    s.append(Paragraph("June 2018 – February 2021  |  San Francisco, CA", styles["SubGrey"]))
    for b in [
        "Built financial data aggregation APIs serving 3M daily active users",
        "Developed React/TypeScript dashboard for financial analytics with real-time charts",
        "Implemented OAuth2 flows and bank-grade AES-256 encryption for sensitive data",
        "Reduced CI/CD pipeline from 45 min to 8 min using GitHub Actions + caching",
        "Stack: Python, Django, React, TypeScript, GraphQL, PostgreSQL, AWS RDS, Docker"
    ]: s.append(bullet(b, styles))
    s += section("Skills", styles)
    s.append(Paragraph("<b>Languages:</b> Python, TypeScript, JavaScript, Go, SQL", styles["Body"]))
    s.append(Paragraph("<b>Backend:</b> FastAPI, Django, Flask, Node.js, GraphQL, REST APIs, gRPC", styles["Body"]))
    s.append(Paragraph("<b>Frontend:</b> React, Next.js, TailwindCSS", styles["Body"]))
    s.append(Paragraph("<b>Infrastructure:</b> AWS (EC2, RDS, Lambda, S3, EKS), Docker, Kubernetes, Terraform, CI/CD", styles["Body"]))
    s.append(Paragraph("<b>Data:</b> PostgreSQL, Redis, MongoDB, Kafka, RabbitMQ, Elasticsearch", styles["Body"]))
    s += section("Education", styles)
    s.append(Paragraph("B.S. Computer Science — UC Berkeley  |  2016", styles["Body"]))
    s += section("Certifications", styles)
    s.append(Paragraph("AWS Certified Solutions Architect – Associate  |  AWS Certified Developer – Associate", styles["Body"]))
    s += section("Projects", styles)
    s.append(Paragraph("<b>PayFlow</b> — Open-source payment orchestration layer (1.2k GitHub ⭐)", styles["JobTitle"]))
    s.append(Paragraph("Python/FastAPI, PostgreSQL, Redis, Docker — used by 15 startups in production", styles["SubGrey"]))
    return s

# ── Resume 2: Bob Kumar — Partial Match (Healthcare background) ───────────────
def bob_kumar(styles):
    s = []
    s.append(Paragraph("Bob Kumar", styles["Name"]))
    s.append(Paragraph("bob.kumar@email.com  |  +1-212-555-0202  |  New York, NY", styles["Contact"]))
    s.append(Paragraph(
        "Software engineer with 6 years building Python/Django backends and React frontends. "
        "Primary experience in healthcare SaaS. Proficient with AWS and Docker. "
        "Looking to transition into fintech engineering.", styles["Body"]))
    s += section("Experience", styles)
    s.append(Paragraph("Software Engineer — HealthTech Inc", styles["JobTitle"]))
    s.append(Paragraph("January 2020 – Present  |  New York, NY", styles["SubGrey"]))
    for b in [
        "Built patient scheduling and billing modules using Python/Django and React (15k daily users)",
        "Integrated HL7/FHIR APIs for electronic health records interoperability",
        "Deployed Docker containers on AWS EC2 with RDS PostgreSQL backend",
        "Reduced API response time by 25% through N+1 query elimination and Redis caching",
        "Stack: Python, Django, React, JavaScript, PostgreSQL, Redis, AWS, Docker, REST"
    ]: s.append(bullet(b, styles))
    s.append(Spacer(1, 4*mm))
    s.append(Paragraph("Junior Python Developer — MediSoft Solutions", styles["JobTitle"]))
    s.append(Paragraph("July 2018 – December 2019  |  Boston, MA", styles["SubGrey"]))
    for b in [
        "Migrated legacy Python 2 codebase to Python 3; improved test coverage to 80% with pytest",
        "Built internal reporting dashboards using React and Chart.js",
    ]: s.append(bullet(b, styles))
    s += section("Skills", styles)
    s.append(Paragraph("<b>Languages:</b> Python, JavaScript, SQL", styles["Body"]))
    s.append(Paragraph("<b>Backend:</b> Django, Flask, REST APIs, Celery, pytest", styles["Body"]))
    s.append(Paragraph("<b>Frontend:</b> React, HTML/CSS, Chart.js", styles["Body"]))
    s.append(Paragraph("<b>Infrastructure:</b> AWS (EC2, RDS, S3), Docker, Git, GitHub", styles["Body"]))
    s.append(Paragraph("<b>Data:</b> PostgreSQL, Redis, MySQL", styles["Body"]))
    s += section("Education", styles)
    s.append(Paragraph("B.E. Computer Science — University of Michigan  |  2018", styles["Body"]))
    s += section("Certifications", styles)
    s.append(Paragraph("AWS Certified Cloud Practitioner", styles["Body"]))
    return s

# ── Resume 3: Carol Smith — Borderline (Python backend only) ─────────────────
def carol_smith(styles):
    s = []
    s.append(Paragraph("Carol Smith", styles["Name"]))
    s.append(Paragraph("carol.smith@email.com  |  +1-617-555-0303  |  Boston, MA", styles["Contact"]))
    s.append(Paragraph(
        "Backend Python developer with 5 years building data pipelines and REST APIs "
        "for financial risk analytics. Strong in Python and SQL. "
        "Limited frontend experience. No cloud certifications.", styles["Body"]))
    s += section("Experience", styles)
    s.append(Paragraph("Backend Developer — RiskMetrics Corp", styles["JobTitle"]))
    s.append(Paragraph("April 2020 – Present  |  Boston, MA", styles["SubGrey"]))
    for b in [
        "Built Python/Flask APIs for risk calculation models processing $2B+ in daily transactions",
        "Optimised complex SQL queries for large financial datasets, reducing run-time by 60%",
        "Managed Celery workers for async Monte Carlo simulation processing",
        "On-premise deployments only — no cloud/Kubernetes experience",
        "Stack: Python, Flask, PostgreSQL, Celery, Linux, bash, pandas, numpy"
    ]: s.append(bullet(b, styles))
    s.append(Spacer(1, 4*mm))
    s.append(Paragraph("Python Developer — DataBridge Analytics", styles["JobTitle"]))
    s.append(Paragraph("January 2019 – March 2020  |  Cambridge, MA", styles["SubGrey"]))
    for b in [
        "Developed ETL pipelines aggregating financial data from 12 broker APIs",
        "Built one simple internal React dashboard (limited frontend exposure)",
    ]: s.append(bullet(b, styles))
    s += section("Skills", styles)
    s.append(Paragraph("<b>Languages:</b> Python, SQL, bash", styles["Body"]))
    s.append(Paragraph("<b>Backend:</b> Flask, Celery, REST APIs, pandas, numpy, SQLAlchemy", styles["Body"]))
    s.append(Paragraph("<b>Data:</b> PostgreSQL, MySQL, ETL pipelines", styles["Body"]))
    s.append(Paragraph("<b>Other:</b> Git, Linux, basic React (limited)", styles["Body"]))
    s += section("Education", styles)
    s.append(Paragraph("B.S. Mathematics — Boston University  |  2018", styles["Body"]))
    return s

# ── Resume 4: David Lee — Unrelated (Java Enterprise) ────────────────────────
def david_lee(styles):
    s = []
    s.append(Paragraph("David Lee", styles["Name"]))
    s.append(Paragraph("david.lee@email.com  |  +1-312-555-0404  |  Chicago, IL", styles["Contact"]))
    s.append(Paragraph(
        "Senior Java developer with 8+ years building enterprise Spring Boot applications "
        "for insurance and logistics. Expert in Java ecosystem. "
        "No Python, TypeScript, or Kubernetes experience. Considering pivoting stacks.", styles["Body"]))
    s += section("Experience", styles)
    s.append(Paragraph("Senior Java Developer — InsureCorp", styles["JobTitle"]))
    s.append(Paragraph("March 2018 – Present  |  Chicago, IL", styles["SubGrey"]))
    for b in [
        "Architected claims processing system using Java Spring Boot microservices (50k claims/day)",
        "Led team of 5 developers; designed Oracle DB schemas for complex insurance models",
        "Integrated SOAP web services for legacy mainframe communication",
        "Deployed on IBM WebSphere application server — no cloud infrastructure",
        "Stack: Java, Spring Boot, Oracle DB, Hibernate, SOAP, IBM WebSphere, Maven, JUnit"
    ]: s.append(bullet(b, styles))
    s.append(Spacer(1, 4*mm))
    s.append(Paragraph("Java Developer — Logistics Pro", styles["JobTitle"]))
    s.append(Paragraph("January 2016 – February 2018  |  Chicago, IL", styles["SubGrey"]))
    for b in [
        "Built route optimisation APIs in Java for supply chain management",
        "Managed Oracle database schemas and Hibernate ORM mappings",
    ]: s.append(bullet(b, styles))
    s += section("Skills", styles)
    s.append(Paragraph("<b>Languages:</b> Java, XML, SQL (Oracle)", styles["Body"]))
    s.append(Paragraph("<b>Frameworks:</b> Spring Boot, Spring MVC, Hibernate, JUnit, TestNG", styles["Body"]))
    s.append(Paragraph("<b>Infrastructure:</b> IBM WebSphere, Apache Tomcat, Maven, Jenkins, Jira", styles["Body"]))
    s.append(Paragraph("<b>Data:</b> Oracle DB, IBM DB2", styles["Body"]))
    s += section("Education", styles)
    s.append(Paragraph("B.Tech Computer Engineering — Illinois Institute of Technology  |  2015", styles["Body"]))
    s += section("Certifications", styles)
    s.append(Paragraph("Oracle Certified Professional Java SE 11 Developer", styles["Body"]))
    return s

# ── Resume 5: Emma Jones — Weak Match (Junior) ────────────────────────────────
def emma_jones(styles):
    s = []
    s.append(Paragraph("Emma Jones", styles["Name"]))
    s.append(Paragraph("emma.jones@email.com  |  +1-206-555-0505  |  Seattle, WA", styles["Contact"]))
    s.append(Paragraph(
        "Recent CS graduate with 1.5 years full-stack experience. "
        "Familiar with Python and React from coursework and a startup internship. "
        "Eager to learn cloud infrastructure and production-scale systems.", styles["Body"]))
    s += section("Experience", styles)
    s.append(Paragraph("Junior Full-Stack Developer — StartupXYZ", styles["JobTitle"]))
    s.append(Paragraph("June 2023 – Present  |  Seattle, WA (Remote)", styles["SubGrey"]))
    for b in [
        "Building e-commerce features using Python/Flask backend and React frontend (team of 3)",
        "Maintaining PostgreSQL database schemas and writing unit tests with pytest",
        "Using Docker for local development — no production Kubernetes experience",
        "Stack: Python, Flask, React, JavaScript, PostgreSQL, Docker, Git"
    ]: s.append(bullet(b, styles))
    s.append(Spacer(1, 4*mm))
    s.append(Paragraph("Software Engineering Intern — TechCorp", styles["JobTitle"]))
    s.append(Paragraph("May 2022 – August 2022  |  Seattle, WA", styles["SubGrey"]))
    for b in [
        "3-month internship: built Python reporting scripts and one React component for internal tooling",
    ]: s.append(bullet(b, styles))
    s += section("Skills", styles)
    s.append(Paragraph("<b>Languages:</b> Python, JavaScript, SQL, HTML/CSS", styles["Body"]))
    s.append(Paragraph("<b>Backend:</b> Flask, Django (basic), REST APIs, pytest", styles["Body"]))
    s.append(Paragraph("<b>Frontend:</b> React, Tailwind CSS", styles["Body"]))
    s.append(Paragraph("<b>Other:</b> Docker (local only), Git, GitHub", styles["Body"]))
    s += section("Education", styles)
    s.append(Paragraph("B.S. Computer Science — University of Washington  |  2023  |  GPA: 3.7", styles["Body"]))
    s += section("Projects", styles)
    s.append(Paragraph("<b>Study Buddy App</b> — Group matching app (Python/Flask + React, deployed on Heroku)", styles["Body"]))
    s.append(Paragraph("<b>Budget Tracker</b> — Personal finance tracker (Django + SQLite, university project)", styles["Body"]))
    return s

# ── JD PDF ────────────────────────────────────────────────────────────────────
def job_description(styles):
    s = []
    s.append(Paragraph("Job Description", styles["Name"]))
    s.append(Paragraph("FinPay Technologies  |  San Francisco, CA  |  Full-Time  |  Remote-Friendly", styles["Contact"]))
    s.append(Paragraph("Senior Full-Stack Engineer — Payments Platform", styles["Section"]))
    s += [divider()]
    s.append(Paragraph(
        "We are a fast-growing fintech startup building next-generation payments infrastructure. "
        "We are looking for a Senior Full-Stack Engineer to join our platform team "
        "and help scale our core product to millions of users.", styles["Body"]))
    s += section("Responsibilities", styles)
    for b in [
        "Design, build, and maintain high-performance APIs using Python (FastAPI/Django)",
        "Lead frontend development with React + TypeScript, building polished user interfaces",
        "Own the full SDLC from architecture design to Kubernetes deployment",
        "Conduct thorough code reviews and mentor junior engineers",
        "Drive technical architecture decisions and advocate for engineering best practices",
        "Collaborate with product and design teams to ship features quickly",
        "Maintain CI/CD pipelines using GitHub Actions",
    ]: s.append(bullet(b, styles))
    s += section("Required Skills", styles)
    for b in [
        "Python (5+ years) — FastAPI or Django",
        "React + TypeScript (3+ years)",
        "PostgreSQL and Redis",
        "Docker and Kubernetes",
        "RESTful API design and implementation",
        "CI/CD pipelines (GitHub Actions, Jenkins)",
    ]: s.append(bullet(b, styles))
    s += section("Preferred Skills", styles)
    for b in [
        "Go or Rust",
        "GraphQL",
        "AWS (EC2, RDS, Lambda, S3)",
        "Apache Kafka or RabbitMQ",
        "Microservices architecture",
        "Prior fintech / payments domain experience",
    ]: s.append(bullet(b, styles))
    s += section("Requirements", styles)
    for b in [
        "5+ years professional software engineering experience",
        "Bachelor's degree in Computer Science, Software Engineering, or equivalent",
        "AWS Certified Developer or Solutions Architect certification is a plus",
        "Excellent written and verbal communication skills — remote-first team",
    ]: s.append(bullet(b, styles))
    return s

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    styles = make_styles()
    print("Generating PDF resumes...")
    build_pdf("alice_chen_resume.pdf", alice_chen(styles))
    build_pdf("bob_kumar_resume.pdf", bob_kumar(styles))
    build_pdf("carol_smith_resume.pdf", carol_smith(styles))
    build_pdf("david_lee_resume.pdf", david_lee(styles))
    build_pdf("emma_jones_resume.pdf", emma_jones(styles))

    # JD PDF in sample_data root
    jd_out = Path(__file__).parent.parent / "sample_data" / "job_description.pdf"
    doc = SimpleDocTemplate(str(jd_out), pagesize=A4,
                             rightMargin=2*cm, leftMargin=2*cm,
                             topMargin=1.8*cm, bottomMargin=1.8*cm)
    doc.build(job_description(styles))
    print("  OK job_description.pdf")
    print(f"\nAll files saved to: sample_data/")
