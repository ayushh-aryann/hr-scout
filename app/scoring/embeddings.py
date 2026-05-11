"""Semantic similarity via sentence-transformers (local) or TF-IDF fallback."""

from __future__ import annotations

import logging
from typing import List, Optional

import numpy as np

logger = logging.getLogger(__name__)

_model = None
_tfidf = None
_tfidf_vectorizer = None


def _load_model() -> Optional[object]:
    global _model
    if _model is not None:
        return _model
    try:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
        logger.info("sentence-transformers model loaded")
        return _model
    except Exception as exc:
        logger.warning("sentence-transformers unavailable (%s); using TF-IDF fallback", exc)
        return None


def compute_similarity(text_a: str, text_b: str) -> float:
    """Cosine similarity between two text blocks. Returns 0.0–1.0."""
    if not text_a or not text_b:
        return 0.0

    model = _load_model()
    if model is not None:
        return _embed_similarity(model, text_a, text_b)
    return _tfidf_similarity(text_a, text_b)


def compute_skill_overlap(candidate_skills: List[str], jd_skills: List[str]) -> float:
    """Jaccard-like overlap with semantic broadening via embeddings if available."""
    if not jd_skills:
        return 0.0
    if not candidate_skills:
        return 0.0

    # Exact/substring matching
    cand_lower = {s.lower() for s in candidate_skills}
    jd_lower = {s.lower() for s in jd_skills}

    exact_matched = cand_lower & jd_lower
    exact_count = len(exact_matched)

    # Partial / substring matches for unmatched JD skills
    partial = 0
    for jd_s in jd_lower:
        if jd_s in exact_matched:
            continue
        for cand_s in cand_lower:
            if jd_s in cand_s or cand_s in jd_s:
                partial += 0.7
                break

    model = _load_model()
    semantic_bonus = 0.0
    if model is not None and len(jd_skills) <= 20:
        semantic_bonus = _semantic_skill_overlap(
            model, candidate_skills, jd_skills, already_matched=exact_count + partial
        )

    total_matched = exact_count + partial + semantic_bonus
    return min(1.0, total_matched / len(jd_skills))


def _embed_similarity(model: object, a: str, b: str) -> float:
    from sentence_transformers import util
    emb_a = model.encode(a[:512], convert_to_tensor=True)
    emb_b = model.encode(b[:512], convert_to_tensor=True)
    score = float(util.cos_sim(emb_a, emb_b))
    return max(0.0, min(1.0, score))


def _semantic_skill_overlap(
    model: object,
    candidate_skills: List[str],
    jd_skills: List[str],
    already_matched: float,
) -> float:
    """Use embeddings to find semantically similar skills not caught by exact match."""
    from sentence_transformers import util
    remaining_jd = [s for s in jd_skills if s.lower() not in {cs.lower() for cs in candidate_skills}]
    if not remaining_jd:
        return 0.0

    try:
        cand_embs = model.encode(candidate_skills, convert_to_tensor=True)
        jd_embs = model.encode(remaining_jd, convert_to_tensor=True)
        similarity_matrix = util.cos_sim(jd_embs, cand_embs).numpy()
        bonus = sum(
            0.5 for row in similarity_matrix if row.max() > 0.65
        )
        return bonus
    except Exception:
        return 0.0


def _tfidf_similarity(a: str, b: str) -> float:
    global _tfidf_vectorizer
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        if _tfidf_vectorizer is None:
            _tfidf_vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))

        tfidf = _tfidf_vectorizer.fit_transform([a, b])
        sim = cosine_similarity(tfidf[0:1], tfidf[1:2])[0][0]
        return float(sim)
    except Exception as exc:
        logger.debug("TF-IDF similarity failed: %s", exc)
        return 0.3  # neutral fallback
