"""Report generator — outputs JSON, HTML, and PDF shortlist reports."""

from __future__ import annotations

import io
import logging
from datetime import datetime
from pathlib import Path
from typing import List

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.models import AnalysisSession, CandidateResult, Recommendation

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def generate_json(session: AnalysisSession) -> str:
    """Return the session as a pretty-printed JSON string."""
    return session.model_dump_json(indent=2)


def generate_html(session: AnalysisSession) -> str:
    """Render the HTML report using the Jinja2 template."""
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    # Register custom filter
    env.filters["rec_color"] = _rec_color
    env.filters["rec_label"] = _rec_label
    env.filters["score_bar_width"] = lambda s: f"{min(100, s * 10):.0f}%"

    template = env.get_template("report.html")
    return template.render(
        session=session,
        generated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        hire_count=sum(1 for r in session.results if r.recommendation == Recommendation.HIRE),
        borderline_count=sum(
            1 for r in session.results if r.recommendation == Recommendation.BORDERLINE
        ),
        no_hire_count=sum(
            1 for r in session.results if r.recommendation == Recommendation.NO_HIRE
        ),
    )


def generate_pdf(session: AnalysisSession) -> bytes:
    """Generate a PDF report using ReportLab."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm, mm
    from reportlab.platypus import (
        HRFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    _add_custom_styles(styles)

    story = []

    # ── Title block ───────────────────────────────────────────────────────────
    story.append(Paragraph("HR Scout — Candidate Shortlist Report", styles["Title"]))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        f"<b>Role:</b> {session.jd_profile.title} | "
        f"<b>Generated:</b> {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        styles["SubTitle"],
    ))
    story.append(Spacer(1, 8 * mm))

    # ── Summary row ───────────────────────────────────────────────────────────
    hire_c = sum(1 for r in session.results if r.recommendation == Recommendation.HIRE)
    border_c = sum(1 for r in session.results if r.recommendation == Recommendation.BORDERLINE)
    no_hire_c = sum(1 for r in session.results if r.recommendation == Recommendation.NO_HIRE)

    summary_data = [
        ["Total Candidates", "Hire", "Borderline", "No-Hire"],
        [str(len(session.results)), str(hire_c), str(border_c), str(no_hire_c)],
    ]
    summary_table = Table(summary_data, colWidths=[4 * cm] * 4)
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a1d")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f5f5f5"), colors.white]),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 8 * mm))

    # ── Summary text ──────────────────────────────────────────────────────────
    story.append(Paragraph(session.shortlist_summary, styles["BodyText"]))
    story.append(Spacer(1, 10 * mm))

    # ── Rankings table ────────────────────────────────────────────────────────
    story.append(Paragraph("Candidate Rankings", styles["Heading1"]))
    story.append(Spacer(1, 3 * mm))

    rank_headers = ["Rank", "Candidate", "Skills", "Exp", "Edu", "Projects", "Comm", "Total", "Decision"]
    rank_data = [rank_headers]
    for r in session.results:
        rec_label = _rec_label_plain(r.recommendation)
        rank_data.append([
            str(r.rank),
            r.name[:20],
            f"{r.scores.skills_match.score:.1f}",
            f"{r.scores.experience_relevance.score:.1f}",
            f"{r.scores.education_certs.score:.1f}",
            f"{r.scores.project_portfolio.score:.1f}",
            f"{r.scores.communication_quality.score:.1f}",
            f"{r.total_score:.1f}",
            rec_label,
        ])

    col_widths = [1.2 * cm, 4.5 * cm, 1.5 * cm, 1.5 * cm, 1.5 * cm, 2.0 * cm, 1.5 * cm, 1.8 * cm, 2.5 * cm]
    rank_table = Table(rank_data, colWidths=col_widths, repeatRows=1)
    rank_table.setStyle(_build_rank_table_style(session.results))
    story.append(rank_table)
    story.append(Spacer(1, 10 * mm))

    # ── Individual breakdowns ─────────────────────────────────────────────────
    story.append(Paragraph("Detailed Score Breakdowns", styles["Heading1"]))
    story.append(Spacer(1, 4 * mm))

    for result in session.results:
        story.extend(_candidate_detail_section(result, styles))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
        story.append(Spacer(1, 6 * mm))

    doc.build(story)
    return buf.getvalue()


# ── PDF helpers ───────────────────────────────────────────────────────────────

def _add_custom_styles(styles):
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    styles.add(ParagraphStyle(
        "SubTitle",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.grey,
        spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        "JustificationText",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#444444"),
        leftIndent=8,
        spaceAfter=4,
    ))


def _build_rank_table_style(results: List[CandidateResult]):
    from reportlab.lib import colors
    from reportlab.platypus import TableStyle

    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a1d")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ALIGN", (1, 1), (1, -1), "LEFT"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9f9f9")]),
    ]

    for i, r in enumerate(results, start=1):
        if r.recommendation == Recommendation.HIRE:
            style.append(("TEXTCOLOR", (8, i), (8, i), colors.HexColor("#16a34a")))
        elif r.recommendation == Recommendation.BORDERLINE:
            style.append(("TEXTCOLOR", (8, i), (8, i), colors.HexColor("#d97706")))
        else:
            style.append(("TEXTCOLOR", (8, i), (8, i), colors.HexColor("#dc2626")))

    return TableStyle(style)


def _candidate_detail_section(result: CandidateResult, styles) -> list:
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    items = []
    rec_color_map = {
        Recommendation.HIRE: "#16a34a",
        Recommendation.BORDERLINE: "#d97706",
        Recommendation.NO_HIRE: "#dc2626",
    }
    rec_color = rec_color_map[result.recommendation]

    items.append(Paragraph(
        f"<b>#{result.rank} {result.name}</b> — "
        f"<font color='{rec_color}'>{_rec_label_plain(result.recommendation).upper()}</font> "
        f"| Total: <b>{result.total_score:.1f}/100</b>",
        styles["Heading2"],
    ))
    items.append(Spacer(1, 2 * mm))

    # Scores table
    dim_names = ["Skills Match (30%)", "Experience (25%)", "Education & Certs (15%)", "Projects (20%)", "Communication (10%)"]
    dims = [
        result.scores.skills_match,
        result.scores.experience_relevance,
        result.scores.education_certs,
        result.scores.project_portfolio,
        result.scores.communication_quality,
    ]

    score_data = [["Dimension", "Score", "Contribution", "Justification"]]
    for name, dim in zip(dim_names, dims):
        score_data.append([
            name,
            f"{dim.score:.1f}/10",
            f"{dim.weighted_contribution:.1f}",
            Paragraph(dim.justification[:100], styles["JustificationText"]),
        ])
    score_data.append(["", "", f"TOTAL: {result.total_score:.1f}/100", ""])

    from reportlab.lib.units import cm
    score_table = Table(
        score_data,
        colWidths=[4.5 * cm, 2 * cm, 3 * cm, 8 * cm],
        repeatRows=1,
    )
    score_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (1, 0), (2, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e5e7eb")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f9fafb")),
    ]))
    items.append(score_table)
    items.append(Spacer(1, 3 * mm))

    # Overrides
    if result.overrides:
        items.append(Paragraph(f"Human Overrides ({len(result.overrides)})", styles["Heading3"] if "Heading3" in styles.byName else styles["Heading2"]))
        for ov in result.overrides:
            items.append(Paragraph(
                f"• [{ov.timestamp.strftime('%Y-%m-%d %H:%M')}] {ov.hr_user}: "
                f"{ov.dimension or 'flag'} score {ov.old_score:.1f}→{ov.new_score:.1f} — {ov.reason}",
                styles["JustificationText"],
            ))

    return items


# ── Template filters ──────────────────────────────────────────────────────────

def _rec_color(rec: Recommendation) -> str:
    return {"hire": "#16a34a", "borderline": "#d97706", "no_hire": "#dc2626"}.get(
        rec.value if hasattr(rec, "value") else str(rec), "#888"
    )


def _rec_label(rec: Recommendation) -> str:
    return {"hire": "Hire", "borderline": "Borderline", "no_hire": "No Hire"}.get(
        rec.value if hasattr(rec, "value") else str(rec), str(rec)
    )


def _rec_label_plain(rec: Recommendation) -> str:
    return _rec_label(rec)
