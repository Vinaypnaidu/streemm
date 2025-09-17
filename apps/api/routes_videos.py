# apps/api/routes_videos.py
import os
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from csrf import require_csrf
from db import get_db
from session import get_current_user
from models import User, Video, VideoAsset
from config import settings
from schemas import (
    FinalizeVideoRequest,
    VideoDetail,
    VideoOut,
    PaginatedVideos,
    VideoAssetOut,
)
from storage import build_raw_key, object_exists, build_public_url
from jobs import enqueue_process_video

router = APIRouter(prefix="/videos", tags=["videos"])

def _video_to_detail(v: Video) -> VideoDetail:
    assets_out: List[VideoAssetOut] = []
    for a in (v.assets or []):
        assets_out.append(
            VideoAssetOut(
                id=str(a.id),
                kind=a.kind,
                label=a.label,
                storage_key=a.storage_key,
                meta=a.meta,
                public_url=build_public_url(a.storage_key),
            )
        )
    return VideoDetail(
        id=str(v.id),
        status=v.status,
        title=v.title or "",
        description=v.description or "",
        original_filename=v.original_filename,
        storage_key_raw=v.storage_key_raw,
        duration_seconds=v.duration_seconds,
        checksum_sha256=v.checksum_sha256,
        probe=v.probe,
        error=v.error,
        created_at=v.created_at,
        assets=assets_out,
    )
    
@router.post("", response_model=VideoDetail, status_code=status.HTTP_202_ACCEPTED)
def finalize_video(
    request: Request,
    body: FinalizeVideoRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_csrf(request)

    # Validate video_id
    try:
        vid = uuid.UUID(body.video_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid video_id")

    # Validate and recompute deterministic raw_key
    _, ext = os.path.splitext(body.original_filename or "")
    ext = ext or ".mp4"
    expected_key = build_raw_key(str(user.id), str(vid), ext)
    if body.raw_key != expected_key:
        raise HTTPException(status_code=400, detail="raw_key does not match expected convention")

    # Ensure object exists in storage
    exists, _meta = object_exists(settings.s3_bucket, body.raw_key)
    if not exists:
        raise HTTPException(status_code=409, detail="Raw object not found in storage. Upload first.")

    # Idempotent: fetch or create
    existing: Optional[Video] = db.get(Video, vid)
    if existing:
        if existing.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")
        if existing.storage_key_raw != body.raw_key:
            raise HTTPException(status_code=409, detail="Video exists with different raw key")
        # Enqueue again is safe (idempotent from worker side later)
        enqueue_process_video(str(existing.id), reason="finalize-idempotent")
        db.flush()
        db.refresh(existing)
        return _video_to_detail(existing)

    v = Video(
        id=vid,
        user_id=user.id,
        original_filename=body.original_filename,
        storage_key_raw=body.raw_key,
        title=(body.title or "").strip(),
        description=(body.description or "").strip(),
        status="uploaded",
        checksum_sha256=body.checksum_sha256,
    )
    db.add(v)
    db.commit()
    db.refresh(v)

    enqueue_process_video(str(v.id), reason="finalize")
    return _video_to_detail(v)

@router.get("", response_model=PaginatedVideos)
def list_videos(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = 20,
    offset: int = 0,
):
    limit = max(1, min(100, limit))
    q = (
        db.query(Video)
        .filter(Video.user_id == user.id)
        .order_by(Video.created_at.desc())
    )
    items = q.offset(offset).limit(limit + 1).all()
    has_more = len(items) > limit
    items = items[:limit]
    out: List[VideoOut] = [
        VideoOut(
            id=str(v.id),
            status=v.status,
            original_filename=v.original_filename,
            title=v.title or "",
            description=v.description or "",
            created_at=v.created_at,
        )
        for v in items
    ]
    next_offset = offset + len(items) if has_more else None
    return PaginatedVideos(items=out, next_offset=next_offset)

@router.get("/{video_id}", response_model=VideoDetail)
def get_video(
    video_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        vid = uuid.UUID(video_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid video_id")

    v: Optional[Video] = db.get(Video, vid)
    if not v:
        raise HTTPException(status_code=404, detail="Not found")
    if v.user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    # Access assets (relationship)
    _ = v.assets
    return _video_to_detail(v)