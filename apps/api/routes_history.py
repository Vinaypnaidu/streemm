# apps/api/routes_history.py
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from sqlalchemy import func
import uuid

from csrf import require_csrf
from db import get_db
from session import get_current_user
from models import User, WatchHistory, Video
from schemas import Ok, HeartbeatRequest, PaginatedHistory, HistoryItem
from storage import build_thumbnail_key, build_public_url, object_exists
from config import settings
from sqlalchemy.dialects.postgresql import insert as pg_insert

router = APIRouter(prefix="/history", tags=["history"])


@router.post("/heartbeat", response_model=Ok, status_code=status.HTTP_200_OK)
def heartbeat(
    request: Request,
    body: HeartbeatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_csrf(request)

    print(f"Heartbeat: {body}")

    # Validate video_id
    try:
        vid = uuid.UUID(body.video_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid video_id")

    # Clamp and normalize position (float seconds)
    try:
        pos = max(0.0, float(body.position_seconds))
    except Exception:
        pos = 0.0

    # Ensure video exists (optional, but avoids orphan rows)
    v: Optional[Video] = db.get(Video, vid)
    if not v:
        raise HTTPException(status_code=404, detail="Video not found")

    # Atomic upsert to avoid races
    stmt = (
        pg_insert(WatchHistory)
        .values(
            user_id=user.id,
            video_id=v.id,
            last_position_seconds=pos,
            last_watched_at=func.now(),
        )
        .on_conflict_do_update(
            constraint="pk_watch_history",
            set_={
                "last_position_seconds": pos,
                "last_watched_at": func.now(),
            },
        )
    )
    db.execute(stmt)
    db.commit()

    return Ok(ok=True)


@router.get("", response_model=PaginatedHistory)
def list_history(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
):
    limit = max(1, min(100, limit))

    q = (
        db.query(WatchHistory, Video)
        .join(Video, WatchHistory.video_id == Video.id)
        .filter(WatchHistory.user_id == user.id)
        .order_by(WatchHistory.last_watched_at.desc())
    )
    rows = q.offset(offset).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    items: List[HistoryItem] = []
    for wh, v in rows:
        # Thumbnail
        thumb_key = build_thumbnail_key(str(v.id))
        has_thumb, _ = object_exists(settings.s3_bucket, thumb_key)
        thumb_url = build_public_url(thumb_key) if has_thumb else None

        # Duration and progress
        dur: Optional[float] = (
            v.duration_seconds if v.duration_seconds is not None else None
        )
        progress = None
        if dur and dur > 0:
            progress = max(
                0.0, min(100.0, (float(wh.last_position_seconds) / dur) * 100.0)
            )

        items.append(
            HistoryItem(
                video_id=str(v.id),
                original_filename=v.original_filename,
                title=v.title or "",
                thumbnail_url=thumb_url,
                last_position_seconds=float(wh.last_position_seconds or 0),
                duration_seconds=dur,
                progress_percent=progress,
                last_watched_at=wh.last_watched_at,
            )
        )

    next_offset = offset + len(items) if has_more else None
    return PaginatedHistory(items=items, next_offset=next_offset)
