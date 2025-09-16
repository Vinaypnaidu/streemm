# apps/api/jobs.py
import json
from typing import Optional
from cache import redis_client

QUEUE_KEY = "q:videos"

def enqueue_process_video(video_id: str, *, reason: Optional[str] = None) -> None:
    payload = {"video_id": video_id, "reason": reason or "finalize"}
    redis_client.lpush(QUEUE_KEY, json.dumps(payload))