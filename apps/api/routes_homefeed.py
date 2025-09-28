# apps/api/routes_homefeed.py
import logging
import re
from collections import Counter
from typing import Dict, List, Optional, Set

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from db import get_db
from session import get_current_user
from models import User, Video, WatchHistory
from schemas import HomeFeedItem, HomeFeedResponse
from search import get_client, ensure_indexes, VIDEOS_INDEX
from storage import build_thumbnail_key, build_public_url

router = APIRouter(prefix="/homefeed", tags=["homefeed"])

log = logging.getLogger("routes_homefeed")

_WORD_RE = re.compile(r"[a-z0-9]+")
STOPWORDS: Set[str] = {
    "a",
    "an",
    "the",
    "to",
    "is",
    "in",
    "on",
    "of",
    "for",
    "and",
    "or",
    "as",
    "at",
    "be",
    "by",
    "with",
    "from",
    "this",
    "that",
    "it",
    "you",
    "your",
    "are",
    "was",
    "were",
    "will",
    "can",
    "not",
    "we",
    "our",
    "they",
    "them",
    "their",
    "i",
    "me",
    "my",
    "mine",
    "video",
    "videos",
    "watch",
    "watched",
}


def _tokens_from_text(text: str) -> List[str]:
    low = (text or "").lower()
    toks = _WORD_RE.findall(low)
    out: List[str] = []
    for t in toks:
        if not t or t in STOPWORDS:
            continue
        if t.isdigit():
            continue
        if len(t) < 2:
            continue
        out.append(t)
    return out


def _compute_progress_map(
    db: Session, user: User, video_ids: List[str]
) -> Dict[str, Optional[float]]:
    if not video_ids:
        return {}
    rows = (
        db.query(WatchHistory, Video.duration_seconds)
        .join(Video, WatchHistory.video_id == Video.id)
        .filter(WatchHistory.user_id == user.id, WatchHistory.video_id.in_(video_ids))
        .all()
    )
    progress: Dict[str, Optional[float]] = {}
    for wh, dur in rows:
        try:
            duration = float(dur) if dur is not None else None
        except Exception:
            duration = None
        try:
            position = float(wh.last_position_seconds or 0.0)
        except Exception:
            position = 0.0
        pct: Optional[float] = None
        if duration and duration > 0:
            pct = max(0.0, min(100.0, (position / duration) * 100.0))
        progress[str(wh.video_id)] = pct
    return progress


def _make_items_from_videos(
    vids: List[Video], progress: Dict[str, Optional[float]], source: str
) -> HomeFeedResponse:
    items: List[HomeFeedItem] = []
    for v in vids:
        thumb_url = build_public_url(build_thumbnail_key(str(v.id)))
        items.append(
            HomeFeedItem(
                id=str(v.id),
                title=(v.title or "").strip() or v.original_filename,
                description=(v.description or "").strip(),
                thumbnail_url=thumb_url,
                duration_seconds=(
                    float(v.duration_seconds)
                    if v.duration_seconds is not None
                    else None
                ),
                progress_percent=progress.get(str(v.id)),
            )
        )
    return HomeFeedResponse(items=items, source=source)


def _fallback_random(db: Session, user: User) -> HomeFeedResponse:
    vids = (
        db.query(Video)
        .filter(Video.status == "ready")
        .order_by(func.random())
        .limit(25)
        .all()
    )
    progress = _compute_progress_map(db, user, [str(v.id) for v in vids])
    return _make_items_from_videos(vids, progress, "random")


@router.get("", response_model=HomeFeedResponse)
def homefeed(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ensure_indexes()

    rows = (
        db.query(WatchHistory, Video)
        .join(Video, WatchHistory.video_id == Video.id)
        .filter(WatchHistory.user_id == user.id)
        .order_by(WatchHistory.last_watched_at.desc())
        .limit(15)
        .all()
    )

    blob_parts: List[str] = []
    for _wh, v in rows:
        blob_parts.append((v.title or "").strip())
        blob_parts.append((v.description or "").strip())
    blob = " ".join([p for p in blob_parts if p])

    tokens = _tokens_from_text(blob)
    if tokens:
        freq = Counter(tokens)
        top_words = [w for w, _ in freq.most_common(50)]
    else:
        top_words = []

    client = get_client()
    if not client or not top_words:
        return _fallback_random(db, user)

    query = " ".join(top_words)
    body = {
        "size": 25,
        "query": {
            "bool": {
                "must": [
                    {
                        "multi_match": {
                            "query": query,
                            "fields": ["title", "description"],
                            "type": "best_fields",
                        }
                    }
                ],
                "filter": [{"term": {"status": "ready"}}],
            }
        },
    }

    try:
        res = client.search(index=VIDEOS_INDEX, body=body)
        hits = res.get("hits", {}).get("hits", [])
    except Exception as exc:
        log.warning("homefeed_opensearch_failed", exc_info=exc)
        return _fallback_random(db, user)

    ids = [h.get("_id") for h in hits if h.get("_id")]
    if not ids:
        return _fallback_random(db, user)

    db_vids = db.query(Video).filter(Video.id.in_(ids), Video.status == "ready").all()
    by_id = {str(v.id): v for v in db_vids}
    ordered_vids: List[Video] = [by_id[i] for i in ids if i in by_id]

    if not ordered_vids:
        return _fallback_random(db, user)

    progress = _compute_progress_map(db, user, [str(v.id) for v in ordered_vids])
    return _make_items_from_videos(ordered_vids, progress, "keywords")
