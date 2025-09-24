from __future__ import annotations

import re
from collections import Counter
from typing import List, Optional, Set

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from db import get_db
from session import get_current_user
from models import User, Video, WatchHistory
from schemas import HomeFeedItem, HomeFeedResponse
from search import get_meili
from storage import build_thumbnail_key, build_public_url

router = APIRouter(prefix="/homefeed", tags=["homefeed"])

_word_re = re.compile(r"[a-z0-9]+")
STOPWORDS: Set[str] = {
    "a","an","the","to","is","in","on","of","for","and","or","as","at","be","by","with","from",
    "this","that","it","you","your","are","was","were","will","can","not","we","our","they","them",
    "their","i","me","my","mine","video","videos","watch","watched"
}

def _tokens_from_text(text: str) -> List[str]:
    low = (text or "").lower()
    toks = _word_re.findall(low)
    out = []
    for t in toks:
        if not t or t in STOPWORDS: 
            continue
        if t.isdigit():
            continue
        if len(t) < 2:
            continue
        out.append(t)
    return out

@router.get("", response_model=HomeFeedResponse)
def homefeed(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Last 15 watched, newest first
    rows = (
        db.query(WatchHistory, Video)
        .join(Video, WatchHistory.video_id == Video.id)
        .filter(WatchHistory.user_id == user.id)
        .order_by(WatchHistory.last_watched_at.desc())
        .limit(15)
        .all()
    )

    # Build keyword profile
    blob_parts: List[str] = []
    for _wh, v in rows:
        blob_parts.append((v.title or "").strip())
        blob_parts.append((v.description or "").strip())
    blob = " ".join([p for p in blob_parts if p])

    toks = _tokens_from_text(blob)
    if toks:
        freq = Counter(toks)
        top_words = [w for w, _ in freq.most_common(50)]
    else:
        top_words = []

    c = get_meili()

    def _compute_progress_map(video_ids: List[str]) -> dict:
        if not video_ids:
            return {}
        wh_rows = (
            db.query(WatchHistory, Video.duration_seconds)
            .join(Video, WatchHistory.video_id == Video.id)
            .filter(WatchHistory.user_id == user.id, WatchHistory.video_id.in_(video_ids))
            .all()
        )
        m = {}
        for wh, dur in wh_rows:
            try:
                d = float(dur) if dur is not None else None
                pos = float(wh.last_position_seconds or 0)
                pct = None
                if d and d > 0:
                    pct = max(0.0, min(100.0, (pos / d) * 100.0))
                m[str(wh.video_id)] = pct
            except Exception:
                m[str(wh.video_id)] = None
        return m

    def _make_items_from_videos(vids: List[Video], source: str) -> HomeFeedResponse:
        ids = [str(v.id) for v in vids]
        prog = _compute_progress_map(ids)
        out: List[HomeFeedItem] = []
        for v in vids:
            thumb_url = build_public_url(build_thumbnail_key(str(v.id)))
            out.append(
                HomeFeedItem(
                    id=str(v.id),
                    title=(v.title or "").strip() or v.original_filename,
                    description=(v.description or "").strip(),
                    thumbnail_url=thumb_url,
                    duration_seconds=float(v.duration_seconds) if v.duration_seconds is not None else None,
                    progress_percent=prog.get(str(v.id)),
                )
            )
        return HomeFeedResponse(items=out, source=source)

    def _fallback_random() -> HomeFeedResponse:
        vids = (
            db.query(Video)
            .filter(Video.status == "ready")
            .order_by(func.random())
            .limit(25)
            .all()
        )
        return _make_items_from_videos(vids, "random")

    if not c or not top_words:
        return _fallback_random()

    q = " ".join(top_words)
    try:
        # Try server-side filter first (requires index settings + status in docs)
        res = c.index("videos").search(q, {
            "limit": 25,
            "filter": 'status = "ready"',
            "attributesToRetrieve": ["id","title","description","thumbnail_url","duration_seconds","status"],
        })
        hits = res.get("hits", [])
    except Exception:
        # Fallback: no filter; we'll filter via DB
        try:
            res = c.index("videos").search(q, {"limit": 50})
            hits = res.get("hits", [])
        except Exception:
            hits = []

    if not hits:
        return _fallback_random()

    ids = [h.get("id") for h in hits if h.get("id")]
    if not ids:
        return _fallback_random()

    # Filter to ready via DB and maintain hit order
    db_vids = db.query(Video).filter(Video.id.in_(ids), Video.status == "ready").all()
    by_id = {str(v.id): v for v in db_vids}
    ordered_vids: List[Video] = [by_id[i] for i in ids if i in by_id]

    if not ordered_vids:
        return _fallback_random()

    return _make_items_from_videos(ordered_vids, "keywords")