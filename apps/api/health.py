# apps/api/health.py
from __future__ import annotations

import logging
from typing import Any, Dict, Callable, Optional, Tuple

from cache import healthcheck as cache_healthcheck
from config import settings
from db import healthcheck as db_healthcheck
from search import get_client
from storage import client as storage_client


log = logging.getLogger("health")


class HealthCheckSkipped(Exception):
    """Raised when a health check is intentionally skipped."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


HealthCheck = Tuple[str, Callable[[], Optional[Dict[str, Any]]], bool]


def _check_database() -> Optional[Dict[str, Any]]:
    db_healthcheck()
    return None


def _check_cache() -> Optional[Dict[str, Any]]:
    cache_ok = cache_healthcheck()
    if not cache_ok:
        raise RuntimeError("Redis ping returned falsy response")
    return None


def _check_object_storage() -> Optional[Dict[str, Any]]:
    bucket = settings.s3_bucket
    if not bucket:
        raise HealthCheckSkipped("S3 bucket not configured")

    client = storage_client()
    exists = client.bucket_exists(bucket)
    if not exists:
        raise RuntimeError(f"Bucket '{bucket}' does not exist")
    return {"bucket": bucket}


def _check_search() -> Optional[Dict[str, Any]]:
    url = (settings.opensearch_url or "").strip()
    if not url:
        raise HealthCheckSkipped("OpenSearch URL not configured")

    client = get_client()
    if not client:
        raise RuntimeError("OpenSearch client unavailable")

    if not client.ping():
        raise RuntimeError("OpenSearch ping failed")

    cluster = client.cluster.health()
    status = cluster.get("status") if isinstance(cluster, dict) else None
    return {"status": status or "unknown"}


CHECKS: Tuple[HealthCheck, ...] = (
    ("database", _check_database, False),
    ("cache", _check_cache, False),
    ("object_storage", _check_object_storage, False),
    ("search", _check_search, True),
)


def collect_health_status(include_optional: bool = True) -> Dict[str, Any]:
    checks: Dict[str, Dict[str, Any]] = {}
    overall_ok = True

    for name, func, optional in CHECKS:
        if optional and not include_optional:
            checks[name] = {
                "ok": True,
                "skipped": True,
                "reason": "optional check skipped",
            }
            continue

        try:
            details = func() or {}
            checks[name] = {"ok": True, **details}
        except HealthCheckSkipped as skipped:
            checks[name] = {"ok": True, "skipped": True, "reason": skipped.reason}
        except Exception as exc:
            checks[name] = {"ok": False, "error": str(exc)}
            if not optional:
                overall_ok = False
            log.warning("Health check '%s' failed: %s", name, exc)

    return {"ok": overall_ok, "checks": checks}

