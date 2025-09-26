# apps/api/jobs.py
import json
from typing import Optional
from cache import redis_client

QUEUE_KEY = "q:videos"
DLQ_KEY = "dlq:videos"
EMAIL_QUEUE_KEY = "q:emails"
EMAIL_DLQ_KEY = "dlq:emails"


def enqueue_process_video(video_id: str, *, reason: Optional[str] = None) -> None:
    payload = {"video_id": video_id, "reason": reason or "finalize"}
    redis_client.lpush(QUEUE_KEY, json.dumps(payload))


def enqueue_notify_video_ready(video_id: str) -> None:
    payload = {"video_id": video_id, "reason": "video_ready"}
    redis_client.lpush(EMAIL_QUEUE_KEY, json.dumps(payload))
