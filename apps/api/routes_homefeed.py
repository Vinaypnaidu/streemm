# apps/api/routes_homefeed.py
import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from db import get_db
from session import get_current_user
from models import User, Video, WatchHistory
from schemas import HomeFeedItem, HomeFeedResponse
from recommendations import build_seed_bundle, run_opensearch_lane
from search import ensure_indexes
from storage import build_thumbnail_key, build_public_url

router = APIRouter(prefix="/homefeed", tags=["homefeed"])

log = logging.getLogger("routes_homefeed")



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


def _empty_response() -> HomeFeedResponse:
    return HomeFeedResponse(items=[], source="empty")


@router.get("", response_model=HomeFeedResponse)
def homefeed(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ensure_indexes()

    seeds = build_seed_bundle(db, user.id)
    lane = run_opensearch_lane(seeds)

    ids = [c.video_id for c in lane.shortlist]
    if not ids:
        return _empty_response()

    vids = db.query(Video).filter(Video.id.in_(ids), Video.status == "ready").all()
    by_id = {str(v.id): v for v in vids}
    ordered: List[Video] = [by_id[i] for i in ids if i in by_id]
    if not ordered:
        return _empty_response()

    progress = _compute_progress_map(db, user, [str(v.id) for v in ordered])
    return _make_items_from_videos(ordered, progress, "os_lane")
