# apps/api/storage.py
from __future__ import annotations

import os
from datetime import timedelta
from typing import Optional
from urllib.parse import urlparse

from minio import Minio
from config import settings

_client: Optional[Minio] = None

def client() -> Minio:
    global _client
    if _client is None:
        u = urlparse(settings.s3_endpoint)
        host = u.netloc or u.path  # supports "http://localhost:9000" or "localhost:9000"
        secure = (u.scheme == "https") if u.scheme else settings.s3_use_ssl
        _client = Minio(
            host,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            secure=secure,
            region=settings.s3_region,
        )
    return _client

def ensure_bucket(bucket: Optional[str] = None) -> None:
    b = bucket or settings.s3_bucket
    c = client()
    if not c.bucket_exists(b):
        c.make_bucket(b)

def build_raw_key(user_id: str, video_id: str, ext: str) -> str:
    if not ext.startswith("."):
        ext = "." + ext
    return f"raw/{user_id}/{video_id}{ext}"

def presign_put(bucket: str, key: str, expires_seconds: int) -> str:
    c = client()
    # Try convenience method if present; otherwise fallback to generic signer
    try:
        return c.presigned_put_object(bucket, key, expires=timedelta(seconds=expires_seconds))
    except AttributeError:
        return c.get_presigned_url("PUT", bucket, key, expires=timedelta(seconds=expires_seconds))