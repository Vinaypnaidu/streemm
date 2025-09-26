# apps/api/routes_uploads.py
import os
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, status

from csrf import require_csrf
from session import get_current_user
from models import User
from config import settings
from schemas import PresignRequest, PresignResponse
from storage import build_raw_key, presign_put
from cache import redis_client

router = APIRouter(tags=["uploads"])

UPLOAD_LIMIT = 5
UPLOAD_WINDOW_SEC = 60


def _upload_key(user_id: str) -> str:
    return f"rl:upload:{user_id}"


def check_upload_rate_limit(user_id: str) -> None:
    key = _upload_key(user_id)
    count = redis_client.incr(key)
    if count == 1:
        redis_client.expire(key, UPLOAD_WINDOW_SEC)
    if count > UPLOAD_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="Too many uploads, try again soon.",
        )

@router.post("/uploads/presign", response_model=PresignResponse, status_code=status.HTTP_200_OK)
def presign_upload(request: Request, body: PresignRequest, user: User = Depends(get_current_user)):
    require_csrf(request)

    check_upload_rate_limit(str(user.id))

    # Validate inputs
    if not body.filename or not body.content_type:
        raise HTTPException(status_code=400, detail="Missing filename or content type")
    if body.content_type != settings.upload_allowed_mime:
        raise HTTPException(status_code=400, detail="Unsupported content type")
    if body.size_bytes <= 0 or body.size_bytes > settings.upload_max_bytes:
        raise HTTPException(status_code=400, detail="File too large")

    video_id = str(uuid.uuid4())
    _, ext = os.path.splitext(body.filename)
    ext = ext or ".mp4"
    raw_key = build_raw_key(str(user.id), video_id, ext)

    put_url = presign_put(settings.s3_bucket, raw_key, settings.presign_expires_seconds)

    # Client should set these headers on the PUT
    headers = {"Content-Type": body.content_type}
    return PresignResponse(video_id=video_id, raw_key=raw_key, put_url=put_url, headers=headers)