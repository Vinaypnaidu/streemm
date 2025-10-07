# apps/api/notifier.py
import os
import json
import time
import threading
import logging
import uuid

from fastapi import FastAPI, Response
from sqlalchemy import func

from cache import redis_client, healthcheck as cache_health
from db import SessionLocal, healthcheck as db_health
from models import Video, User
from jobs import EMAIL_QUEUE_KEY, EMAIL_DLQ_KEY
from config import settings
from mailer import send_email

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("notifier")

app = FastAPI(title="Streem Notifier")
_stop_event = threading.Event()


def _lock_key(video_id: str) -> str:
    return f"lock:email:{video_id}"


def _attempts_key(video_id: str) -> str:
    return f"attempts:email:{video_id}"


def acquire_lock(video_id: str, worker_id: str, ttl_ms: int) -> bool:
    try:
        ok = redis_client.set(_lock_key(video_id), worker_id, nx=True, px=ttl_ms)
        return bool(ok)
    except Exception:
        return False


def release_lock(video_id: str, worker_id: str) -> None:
    try:
        val = redis_client.get(_lock_key(video_id))
        if val == worker_id:
            redis_client.delete(_lock_key(video_id))
    except Exception:
        pass


def _backoff_for_attempt(attempt: int):
    arr = settings.worker_backoff_seconds
    return arr[attempt - 1] if 1 <= attempt <= len(arr) else None


def notify_video_ready(video_id: str, reason: str) -> None:
    worker_id = f"pid:{os.getpid()}-thr:{threading.get_ident()}"
    if not acquire_lock(video_id, worker_id, settings.worker_lock_ttl_ms):
        log.info(json.dumps({"video_id": video_id, "step": "lock_skip"}))
        return

    try:
        with SessionLocal() as db:
            v = db.get(Video, uuid.UUID(video_id))
            if not v:
                log.warning(
                    json.dumps(
                        {"video_id": video_id, "step": "load", "error": "missing_video"}
                    )
                )
                return

            if v.status != "ready" or v.notified_at is not None:
                log.info(
                    json.dumps(
                        {
                            "video_id": video_id,
                            "step": "skip",
                            "status": v.status,
                            "notified_at": str(v.notified_at),
                        }
                    )
                )
                return

            # Load user email
            u = db.get(User, v.user_id)
            if not u or not (u.email or "").strip():
                log.warning(
                    json.dumps({"video_id": video_id, "step": "load_user_email_failed"})
                )
                return

            title = (
                v.title or v.original_filename or "your video"
            ).strip() or "your video"
            link = f"{settings.public_web_base_url}/videos/{video_id}"
            subject = f"Your video “{title}” is ready"
            text = f'Hi,\n\nYour video "{title}" is ready to watch.\n\nOpen: {link}\n\n— Streem'

            send_email(u.email, subject, text)

            # Mark as notified (once)
            v.notified_at = func.now()
            db.commit()
            redis_client.delete(_attempts_key(video_id))
            log.info(json.dumps({"video_id": video_id, "step": "sent"}))

    except Exception as e:
        log.exception("notify_failed")
        attempts = int(redis_client.incr(_attempts_key(video_id)))
        delay = _backoff_for_attempt(attempts)
        if delay is not None:
            log.info(
                json.dumps(
                    {
                        "video_id": video_id,
                        "step": "retry",
                        "attempts": attempts,
                        "delay_sec": delay,
                    }
                )
            )
            time.sleep(delay)
            redis_client.lpush(
                EMAIL_QUEUE_KEY, json.dumps({"video_id": video_id, "reason": "retry"})
            )
        else:
            try:
                redis_client.lpush(
                    EMAIL_DLQ_KEY,
                    json.dumps(
                        {
                            "video_id": video_id,
                            "error": str(e),
                            "attempts": attempts,
                            "reason": reason,
                            "ts": int(time.time()),
                        }
                    ),
                )
                redis_client.ltrim(EMAIL_DLQ_KEY, 0, 9999)
            except Exception:
                pass
            log.error(
                json.dumps(
                    {"video_id": video_id, "step": "failed_terminal", "error": str(e)}
                )
            )
    finally:
        release_lock(video_id, worker_id)


def _consumer_loop():
    log.info("Notifier consumer started")
    while not _stop_event.is_set():
        try:
            item = redis_client.brpop(EMAIL_QUEUE_KEY, timeout=5)
            if not item:
                continue
            _q, payload = item
            data = json.loads(payload)
            video_id = data.get("video_id")
            reason = data.get("reason", "unknown")
            if not video_id:
                continue
            notify_video_ready(video_id, reason)
        except Exception:
            log.exception("notifier_loop_error")
            time.sleep(1)


@app.on_event("startup")
def on_startup():
    t = threading.Thread(target=_consumer_loop, daemon=True)
    t.start()


@app.on_event("shutdown")
def on_shutdown():
    _stop_event.set()


@app.get("/ready")
def ready(response: Response):
    """
    Kubernetes readiness/liveness probe.
    Returns 200 if healthy, 503 if not.
    """
    ok_db = True
    ok_cache = True
    try:
        db_health()
    except Exception:
        ok_db = False
    try:
        cache_health()
    except Exception:
        ok_cache = False
    
    is_ok = ok_db and ok_cache
    
    # Set HTTP status code for Kubernetes
    if not is_ok:
        response.status_code = 503
    
    return {"ok": is_ok, "db": ok_db, "cache": ok_cache}
