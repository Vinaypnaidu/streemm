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
from recommendations import get_recommendations
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


def _empty_response() -> HomeFeedResponse:
    return HomeFeedResponse(items=[], source="empty")


@router.get("", response_model=HomeFeedResponse)
def homefeed(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ensure_indexes()

    # Use the orchestrator to blend both lanes
    result = get_recommendations(db, user.id)

    if not result.video_ids:
        return _empty_response()

    # Fetch videos from database
    vids = db.query(Video).filter(
        Video.id.in_(result.video_ids),
        Video.status == "ready"
    ).all()
    
    # Build lookup and preserve order from recommendation result
    by_id = {str(v.id): v for v in vids}
    ordered: List[Video] = [by_id[vid] for vid in result.video_ids if vid in by_id]
    
    if not ordered:
        return _empty_response()

    # Compute progress for all videos
    progress = _compute_progress_map(db, user, [str(v.id) for v in ordered])
    
    # Build response items with source metadata
    items: List[HomeFeedItem] = []
    for v in ordered:
        vid_str = str(v.id)
        thumb_url = build_public_url(build_thumbnail_key(vid_str))
        
        # Determine source for this video
        source = result.sources.get(vid_str, "unknown")
        
        items.append(
            HomeFeedItem(
                id=vid_str,
                title=(v.title or "").strip() or v.original_filename,
                description=(v.description or "").strip(),
                thumbnail_url=thumb_url,
                duration_seconds=(
                    float(v.duration_seconds)
                    if v.duration_seconds is not None
                    else None
                ),
                progress_percent=progress.get(vid_str),
            )
        )
    
    # Use blended source with lane counts
    source_label = f"blended(os={result.os_count},graph={result.graph_count})"
    return HomeFeedResponse(items=items, source=source_label)
