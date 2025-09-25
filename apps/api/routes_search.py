# apps/api/routes_search.py
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from db import get_db
from models import User, Video
from session import get_current_user
from search import get_client, ensure_indexes, VIDEOS_INDEX, TRANSCRIPTS_INDEX
from storage import build_thumbnail_key, build_public_url

router = APIRouter(prefix="/search", tags=["search"])
log = logging.getLogger("routes_search")

STOPWORDS: Set[str] = {
    "a","an","the","to","is","in","on","of","for","and","or","as","at","be","by","with","from",
    "this","that","it","you","your","are","was","were","will","can","not","we","our","they","them",
    "their","i","me","my","mine","video","videos","watch","watched",
}
_MAX_SPAN_WINDOWS = 8


def _normalize_tokens(text: str) -> List[str]:
    """Lowercase the query and strip punctuation."""
    return [t for t in re.sub(r"[^\w\s']", " ", text.lower()).split() if t]


def _build_meta_query(q: str, limit: int, offset: int) -> Dict[str, Any]:
    return {
        "from": offset,
        "size": limit,
        "query": {
            "multi_match": {
                "query": q,
                "fields": ["title", "description"],
                "type": "best_fields",
            }
        },
        "highlight": {
            "pre_tags": ["<em>"],
            "post_tags": ["</em>"],
            "fields": {"title": {}, "description": {}},
        },
    }


def _iter_span_windows(tokens: List[str]) -> List[Tuple[List[str], float]]:
    """Return a capped list of (window_tokens, base_boost) pairs for span_near boosters."""
    def sliding(seq: List[str], k: int) -> List[List[str]]:
        if len(seq) < k:
            return []
        return [seq[i : i + k] for i in range(0, len(seq) - k + 1)]

    windows: List[Tuple[List[str], float]] = []
    for k, base_boost in ((5, 1.5), (4, 1.2)):
        wins = sliding(tokens, k)
        if wins:
            take = max(1, min(len(wins), _MAX_SPAN_WINDOWS // 2))
            idxs = [round(i * (len(wins) - 1) / (take - 1)) if take > 1 else 0 for i in range(take)]
            for idx in idxs:
                windows.append((wins[idx], base_boost))
    return windows


@router.get("")
def search(
    q: str = Query(..., min_length=1),
    limit_meta: int = 10,
    offset_meta: int = 0,
    limit_transcript: int = 10,
    offset_transcript: int = 0,
    lang: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    client = get_client()
    if not client:
        return {
            "search_ok": False,
            "meta": {"items": [], "estimated_total": 0, "next_offset": None},
            "transcript": {"items": [], "estimated_total": 0, "next_offset": None},
        }

    ensure_indexes()

    tokens = _normalize_tokens(q)
    word_count = len(tokens)
    full_phrase = " ".join(tokens)

    # --------------------
    # Metadata search
    # --------------------
    meta_items: List[Dict] = []
    meta_est_total = 0
    meta_next_offset: Optional[int] = None
    try:
        meta_limit = max(1, min(100, limit_meta))
        meta_offset = max(0, offset_meta)
        body = _build_meta_query(q, meta_limit, meta_offset)
        res_meta = client.search(index=VIDEOS_INDEX, body=body)
        hits = res_meta.get("hits", {}).get("hits", [])
        for h in hits:
            src = h.get("_source", {})
            highlight = h.get("highlight") or {}
            title_html = highlight.get("title", [src.get("title") or ""])
            desc_html = highlight.get("description", [src.get("description") or ""])
            meta_items.append(
                {
                    "video_id": h.get("_id"),
                    "title_html": title_html[0] if title_html else (src.get("title") or ""),
                    "description_html": desc_html[0] if desc_html else (src.get("description") or ""),
                    "thumbnail_url": src.get("thumbnail_url"),
                    "created_at": src.get("created_at"),
                    "duration_seconds": src.get("duration_seconds"),
                    "score": h.get("_score"),
                }
            )
        total_meta = res_meta.get("hits", {}).get("total", {})
        meta_est_total = int(total_meta.get("value", 0))
        meta_next_offset = (meta_offset + meta_limit) if (meta_est_total > meta_offset + meta_limit) else None
    except Exception as e:
        log.error(f"Metadata search failed: {e}")

    # --------------------
    # Transcript search
    # --------------------
    tr_items: List[Dict] = []
    tr_est_total = 0
    tr_next_offset: Optional[int] = None
    first_by_video: Dict[str, Tuple[float, Dict]] = {}

    if word_count >= 3:
        try:
            tr_limit = max(1, min(1000, limit_transcript))
            tr_offset = max(0, offset_transcript)

            if 3 <= word_count <= 5:
                msm = "70%"
            elif word_count >= 6:
                msm = "50%"

            match_query = {
                "query": full_phrase,
                "operator": "or",
                "minimum_should_match": msm,
                "auto_generate_synonyms_phrase_query": False,
            }

            should_clauses: List[Dict[str, Any]] = []
            # Reward long in-order runs (5-grams, then 4-grams) with span_near boosters.
            for i, (window, base_boost) in enumerate(_iter_span_windows(tokens)):
                slop_val = 2 if len(window) >= 5 else 1
                should_clauses.append(
                    {
                        "span_near": {
                            "clauses": [{"span_term": {"text": term}} for term in window],
                            "in_order": True,
                            "slop": slop_val,
                            "boost": round(base_boost * (0.97 ** i), 3),
                        }
                    }
                )

            bool_query: Dict[str, Any] = {
                "must": [
                    {
                        "match": {
                            "text": match_query,
                        }
                    }
                ]
            }
            if should_clauses:
                bool_query["should"] = should_clauses

            content_terms = [t for t in tokens if t not in STOPWORDS and len(t) > 2]
            if content_terms:
                # Soft guard: require at least one non-glue term to match using a dis_max term set.
                bool_query.setdefault("should", []).append(
                    {
                        "dis_max": {
                            "queries": [{"term": {"text": term}} for term in content_terms],
                            "tie_breaker": 0.0,
                        }
                    }
                )
                bool_query["minimum_should_match"] = 1
            if lang:
                bool_query.setdefault("filter", []).append({"term": {"lang": lang}})

            body: Dict[str, Any] = {
                "query": {"bool": bool_query},
                "highlight": {
                    "pre_tags": ["<em>"],
                    "post_tags": ["</em>"],
                    "fields": {
                        "text": {
                            "number_of_fragments": 1,
                            "fragment_size": 180,
                        }
                    },
                },
            }
            if tokens:
                # Final tie-break: rescore top hits with the full phrase to push near-exact matches to the top.
                body["rescore"] = {
                    "window_size": 200,
                    "query": {
                        "rescore_query": {
                            "match_phrase": {
                                "text": {
                                    "query": full_phrase,
                                    "slop": 1,
                                }
                            }
                        },
                        "query_weight": 1.0,
                        "rescore_query_weight": 2.0,
                    },
                }

            res_tr = client.search(
                index=TRANSCRIPTS_INDEX,
                from_=tr_offset,
                size=tr_limit,
                body=body,
            )
            hits_tr = res_tr.get("hits", {}).get("hits", [])
            for h in hits_tr:
                src = h.get("_source", {})
                vid = src.get("video_id")
                if not vid:
                    continue
                start = float(src.get("start_seconds") or 0.0)
                if vid not in first_by_video or start < first_by_video[vid][0]:
                    first_by_video[vid] = (start, h)

            video_ids = list(first_by_video.keys())
            if video_ids:
                rows = db.query(Video).filter(Video.id.in_(video_ids)).all()
                info: Dict[str, Dict] = {}
                for v in rows:
                    thumb_url = build_public_url(build_thumbnail_key(str(v.id)))
                    info[str(v.id)] = {
                        "title": (v.title or "").strip() or v.original_filename,
                        "thumbnail_url": thumb_url,
                    }
                for vid, (start, h) in first_by_video.items():
                    src = h.get("_source", {})
                    highlight = h.get("highlight") or {}
                    snippet = highlight.get("text", [src.get("text") or ""])
                    tr_items.append(
                        {
                            "video_id": vid,
                            "title": info.get(vid, {}).get("title", ""),
                            "thumbnail_url": info.get(vid, {}).get("thumbnail_url"),
                            "progress_seconds": start,
                            "snippet_html": snippet[0] if snippet else src.get("text") or "",
                        }
                    )
            total_tr = res_tr.get("hits", {}).get("total", {})
            tr_est_total = int(total_tr.get("value", 0))
            tr_next_offset = (tr_offset + tr_limit) if (tr_est_total > tr_offset + tr_limit) else None
        except Exception as e:
            log.error(f"Transcript search failed: {e}")

    return {
        "search_ok": True,
        "meta": {"items": meta_items, "estimated_total": meta_est_total, "next_offset": meta_next_offset},
        "transcript": {"items": tr_items, "estimated_total": tr_est_total, "next_offset": tr_next_offset},
    }