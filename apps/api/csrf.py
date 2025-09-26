# apps/api/csrf.py
import secrets
from typing import Tuple
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import HTTPException, Request
from fastapi.responses import Response

from config import settings

COOKIE_NAME = "csrf"
HEADER_NAME = "x-csrf-token"
TTL_SECONDS = 86400  # 24h

_serializer = URLSafeTimedSerializer(settings.session_secret, salt="csrf")


def issue_csrf(response: Response) -> str:
    token = _serializer.dumps(secrets.token_urlsafe(32))
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=False,  # must be readable by JS for double-submit
        samesite="lax",
        secure=(settings.env.lower() == "production"),
        path="/",
        max_age=TTL_SECONDS,
    )
    return token


def require_csrf(request: Request) -> None:
    cookie = request.cookies.get(COOKIE_NAME)
    header = request.headers.get(HEADER_NAME)
    if not cookie or not header:
        raise HTTPException(status_code=403, detail="CSRF token missing")
    if cookie != header:
        raise HTTPException(status_code=403, detail="CSRF token mismatch")
    try:
        _serializer.loads(header, max_age=TTL_SECONDS)
    except SignatureExpired:
        raise HTTPException(status_code=403, detail="CSRF token expired")
    except BadSignature:
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
