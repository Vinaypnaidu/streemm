# apps/api/routes_auth.py
from fastapi import APIRouter, Depends, HTTPException, Response, Request, status
from sqlalchemy.orm import Session

from db import get_db
from models import User
from auth import hash_password, verify_password, normalize_email
from session import (
    create_session,
    set_session_cookie,
    clear_session_cookie,
    delete_session,
)
from schemas import RegisterRequest, LoginRequest, UserOut, Ok
from csrf import issue_csrf, require_csrf, HEADER_NAME
from cache import redis_client

router = APIRouter(prefix="/auth", tags=["auth"])

# dev rate limit: 20/min per (ip,email)
LOGIN_LIMIT = 20
LOGIN_WINDOW_SEC = 60


def _login_key(ip: str, email: str) -> str:
    return f"rl:login:{ip}:{email}"


def check_login_rate_limit(ip: str, email: str) -> None:
    k = _login_key(ip, email)
    count = redis_client.incr(k)
    if count == 1:
        redis_client.expire(k, LOGIN_WINDOW_SEC)
    if count > LOGIN_LIMIT:
        raise HTTPException(
            status_code=429, detail="Too many login attempts, try again soon."
        )


@router.get("/csrf")
def get_csrf(response: Response):
    token = issue_csrf(response)
    return {"csrf": token, "header": HEADER_NAME}


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(
    request: Request,
    body: RegisterRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    # CSRF
    require_csrf(request)

    email = normalize_email(body.email or "")
    if not email:
        raise HTTPException(status_code=400, detail="Invalid email")
    if not body.password or len(body.password) < 8:
        raise HTTPException(
            status_code=400, detail="Password must be at least 8 characters"
        )

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(email=email, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)

    sid = create_session(str(user.id))
    set_session_cookie(response, sid)

    return UserOut(id=str(user.id), email=user.email)


@router.post("/login", response_model=UserOut)
def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    # CSRF
    require_csrf(request)

    email = normalize_email(body.email or "")
    if not email or not body.password:
        raise HTTPException(status_code=400, detail="Invalid credentials")

    # Rate limit (per ip+email)
    ip = request.client.host if request.client else "unknown"
    check_login_rate_limit(ip, email)

    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(user.password_hash, body.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    sid = create_session(str(user.id))
    set_session_cookie(response, sid)

    return UserOut(id=str(user.id), email=user.email)


@router.post("/logout", response_model=Ok, status_code=status.HTTP_200_OK)
def logout(request: Request, response: Response):
    # CSRF
    require_csrf(request)

    from config import settings

    sid = request.cookies.get(settings.session_cookie_name)
    if sid:
        delete_session(sid)  # server-side revoke
    clear_session_cookie(response)  # client-side remove
    return Ok(ok=True)
