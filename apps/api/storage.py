# apps/api/storage.py
from __future__ import annotations

import os
from datetime import timedelta
from typing import Optional, Tuple, Dict, Any
from urllib.parse import urlparse, urlunparse

from minio import Minio
from config import settings

_client: Optional[Minio] = None
_pub_client: Optional[Minio] = None

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

def public_client() -> Minio:
    global _pub_client
    if _pub_client is None:
        u = urlparse(settings.s3_public_endpoint)
        host = u.netloc or u.path
        secure = (u.scheme == "https") if u.scheme else settings.s3_use_ssl
        _pub_client = Minio(
            host,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            secure=secure,
            region=settings.s3_region,
        )
    return _pub_client

def ensure_bucket(bucket: Optional[str] = None) -> None:
    b = bucket or settings.s3_bucket
    c = client()
    if not c.bucket_exists(b):
        c.make_bucket(b)

def build_raw_key(user_id: str, video_id: str, ext: str) -> str:
    if not ext.startswith("."):
        ext = "." + ext
    return f"raw/{user_id}/{video_id}{ext}"

def build_hls_key(video_id: str, label: str, filename: str) -> str:
    return f"hls/{video_id}/{label}/{filename}"

def build_thumbnail_key(video_id: str) -> str:
    return f"thumbs/{video_id}/poster.jpg"

def presign_put(bucket: str, key: str, expires_seconds: int) -> str:
    c = public_client() if settings.s3_public_endpoint else client()
    try:
        return c.presigned_put_object(bucket, key, expires=timedelta(seconds=expires_seconds))
    except AttributeError:
        return c.get_presigned_url("PUT", bucket, key, expires=timedelta(seconds=expires_seconds))

def object_exists(bucket: str, key: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
    c = client()
    try:
        st = c.stat_object(bucket, key)
        meta: Dict[str, Any] = {
            "size": getattr(st, "size", None),
            "etag": getattr(st, "etag", None),
            "content_type": getattr(st, "content_type", None),
            "last_modified": getattr(st, "last_modified", None).isoformat() if getattr(st, "last_modified", None) else None,
            "metadata": getattr(st, "metadata", None),
            "version_id": getattr(st, "version_id", None),
        }
        return True, meta
    except Exception:
        return False, None