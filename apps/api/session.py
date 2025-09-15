# apps/api/session.py
import json
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict
from fastapi import Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from config import settings
from cache import redis_client
from db import get_db
from models import User

SESSION_PREFIX = "sess:"
TTL = settings.session_ttl_seconds

def _key(sid: str) -> str:
    return f"{SESSION_PREFIX}{sid}"

def create_session(user_id: str) -> str:
    sid = secrets.token_urlsafe(32)
    payload = {
        "user_id": user_id,
        "issued_at": datetime.now(timezone.utc).isoformat(),
    }
    redis_client.set(_key(sid), json.dumps(payload), ex=TTL)
    return sid

def get_session(sid: str) -> Optional[Dict]:
    raw = redis_client.get(_key(sid))
    if not raw:
        return None
    # Rolling TTL: extend on each access
    redis_client.expire(_key(sid), TTL)
    return json.loads(raw)

def delete_session(sid: str) -> None:
    redis_client.delete(_key(sid))

def set_session_cookie(response: Response, sid: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=sid,
        httponly=True,
        samesite="lax",
        secure=(settings.env.lower() == "production"),
        path="/",
        max_age=TTL,
    )

def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        samesite="lax",
    )

def get_current_user(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> User:
    sid = request.cookies.get(settings.session_cookie_name)
    if not sid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    sess = get_session(sid)  # already refreshes Redis TTL
    if not sess:
        raise HTTPException(status_code=401, detail="Session expired")
    # Refresh browser cookie TTL as well (rolling cookie expiry)
    set_session_cookie(response, sid)
    user = db.get(User, sess["user_id"])
    if not user:
        delete_session(sid)
        raise HTTPException(status_code=401, detail="User not found")
    return user