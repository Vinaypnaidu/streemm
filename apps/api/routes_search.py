# apps/api/routes_search.py
from __future__ import annotations

import re
import logging
from typing import Dict, List, Optional, Set, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from db import get_db
from models import User, Video
from session import get_current_user
from config import settings
from search import get_meili
from storage import build_thumbnail_key, build_public_url

router = APIRouter(prefix="/search", tags=["search"])
log = logging.getLogger("routes_search")

_word_re = re.compile(r"[A-Za-z0-9_]+")

def _terms(q: str) -> Set[str]:
    return {t.lower() for t in _word_re.findall(q or "") if t.strip()}

def _coverage(text: str, terms: Set[str]) -> float:
    if not terms:
        return 0.0
    txt = (text or "").lower()
    matched = 0
    for t in terms:
        if t and t in txt:
            matched += 1
    return matched / max(1, len(terms))

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
    c = get_meili()
    if not c:
        return {
            "meili_ok": False,
            "meta": {"items": [], "estimated_total": 0, "next_offset": None},
            "transcript": {"items": [], "estimated_total": 0, "next_offset": None},
        }

    terms = _terms(q)

    # --------------------
    # Metadata search
    # --------------------
    meta_items: List[Dict] = []
    meta_est_total = 0
    meta_next_offset: Optional[int] = None
    try:
        res_meta = c.index("videos").search(
            q,
            {
                "limit": max(1, min(100, limit_meta)),
                "offset": max(0, offset_meta),
                "showMatchesPosition": True,
                "attributesToHighlight": ["title", "description"],
                "highlightPreTag": "<em>",
                "highlightPostTag": "</em>",
            },
        )
        hits = res_meta.get("hits", [])
        for h in hits:
            title = h.get("title") or ""
            desc = h.get("description") or ""
            cov = _coverage(f"{title} {desc}", terms)
            if cov >= settings.min_meta_coverage:
                fmt = h.get("_formatted") or {}
                meta_items.append(
                    {
                        "video_id": h.get("id"),
                        "title_html": fmt.get("title", title),
                        "description_html": fmt.get("description", desc),
                        "thumbnail_url": h.get("thumbnail_url"),
                        "created_at": h.get("created_at"),
                        "duration_seconds": h.get("duration_seconds"),
                        "score": h.get("_rankingScore") or h.get("_semanticScore") or None,
                    }
                )
        meta_est_total = res_meta.get("estimatedTotalHits", 0)
        # Pagination hint (approx; filtering may hide some hits)
        meta_next_offset = (offset_meta + limit_meta) if (meta_est_total > offset_meta + limit_meta) else None
    except Exception as e:
        log.error(f"Metadata search failed: {e}")

    # --------------------
    # Transcript search
    # --------------------
    tr_items: List[Dict] = []
    tr_est_total = 0
    tr_next_offset: Optional[int] = None
    first_by_video: Dict[str, Tuple[float, Dict]] = {}
    try:
        params = {
            "limit": max(1, min(1000, limit_transcript)),   # allow enough hits to group
            "offset": max(0, offset_transcript),
            "showMatchesPosition": True,
            "attributesToHighlight": ["text"],
            "highlightPreTag": "<em>",
            "highlightPostTag": "</em>",
        }
        if lang:
            params["filter"] = f'lang = "{lang}"'
        res_tr = c.index("transcript_chunks").search(q, params)
        hits_tr = res_tr.get("hits", [])
        for h in hits_tr:
            vid = h.get("video_id")
            text = h.get("text") or ""
            cov = _coverage(text, terms)
            if cov < settings.min_transcript_coverage:
                continue
            start = float(h.get("start_seconds") or 0.0)
            if vid not in first_by_video or start < first_by_video[vid][0]:
                first_by_video[vid] = (start, h)
        # Hydrate titles/thumbnails from DB
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
                fmt = h.get("_formatted") or {}
                tr_items.append(
                    {
                        "video_id": vid,
                        "title": info.get(vid, {}).get("title", ""),
                        "thumbnail_url": info.get(vid, {}).get("thumbnail_url"),
                        "progress_seconds": start,
                        "snippet_html": fmt.get("text", h.get("text") or ""),
                    }
                )
        tr_est_total = res_tr.get("estimatedTotalHits", 0)
        tr_next_offset = (offset_transcript + limit_transcript) if (tr_est_total > offset_transcript + limit_transcript) else None
    except Exception as e:
        log.error(f"Transcript search failed: {e}")

    return {
        "meili_ok": True,
        "meta": {"items": meta_items, "estimated_total": meta_est_total, "next_offset": meta_next_offset},
        "transcript": {"items": tr_items, "estimated_total": tr_est_total, "next_offset": tr_next_offset},
    }