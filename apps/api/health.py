# apps/api/health.py
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import Response

from cache import healthcheck as cache_healthcheck
from config import settings
from db import healthcheck as db_healthcheck
from search import get_client
from storage import client as storage_client
from neo4j import GraphDatabase

log = logging.getLogger("health")


def check_database() -> Dict[str, Any]:
    """Check if database connection is working."""
    try:
        db_healthcheck()
        return {"ok": True}
    except Exception as e:
        log.warning("Database health check failed: %s", e)
        return {"ok": False, "error": str(e)}


def check_cache() -> Dict[str, Any]:
    """Check if Redis cache is working."""
    try:
        if not cache_healthcheck():
            raise RuntimeError("Redis ping returned falsy response")
        return {"ok": True}
    except Exception as e:
        log.warning("Cache health check failed: %s", e)
        return {"ok": False, "error": str(e)}


def check_object_storage() -> Dict[str, Any]:
    """Check if S3/MinIO object storage is working."""
    bucket = settings.s3_bucket
    if not bucket:
        return {"ok": True, "skipped": True, "reason": "S3 bucket not configured"}
    
    try:
        client = storage_client()
        if not client.bucket_exists(bucket):
            raise RuntimeError(f"Bucket '{bucket}' does not exist")
        return {"ok": True, "bucket": bucket}
    except Exception as e:
        log.warning("Object storage health check failed: %s", e)
        return {"ok": False, "error": str(e)}


def check_search(skip_if_disabled: bool = False) -> Dict[str, Any]:
    """Check if OpenSearch is working (optional service)."""
    url = (settings.opensearch_url or "").strip()
    if not url:
        return {"ok": True, "skipped": True, "reason": "OpenSearch URL not configured"}
    
    if skip_if_disabled:
        return {"ok": True, "skipped": True, "reason": "optional check skipped"}
    
    try:
        client = get_client()
        if not client:
            raise RuntimeError("OpenSearch client unavailable")
        
        if not client.ping():
            raise RuntimeError("OpenSearch ping failed")
        
        cluster = client.cluster.health()
        status = cluster.get("status") if isinstance(cluster, dict) else "unknown"
        return {"ok": True, "status": status}
    except Exception as e:
        log.warning("Search health check failed: %s", e)
        return {"ok": True, "error": str(e), "optional": True}


def check_neo4j(skip_if_disabled: bool = False) -> Dict[str, Any]:
    """Check if Neo4j is working (optional service)."""
    uri = (settings.neo4j_uri or "").strip()
    if not uri:
        return {"ok": True, "skipped": True, "reason": "Neo4j URI not configured"}
    
    if skip_if_disabled:
        return {"ok": True, "skipped": True, "reason": "optional check skipped"}
    
    try:
        driver = GraphDatabase.driver(
            uri,
            auth=(settings.neo4j_username or "", settings.neo4j_password or "")
        )
        driver.verify_connectivity()
        with driver.session(database=settings.neo4j_database or "neo4j") as session:
            rec = session.run("RETURN 1 AS ok").single()
            ok_val = bool(rec and rec.get("ok", 0))
        driver.close()
        return {"ok": ok_val}
    except Exception as e:
        log.warning("Neo4j health check failed: %s", e)
        return {"ok": True, "error": str(e), "optional": True}


def collect_health_status(include_optional: bool = True) -> Dict[str, Any]:
    """
    Run all health checks and return overall status.
    
    Required services: database, cache, object_storage
    Optional services: search (OpenSearch)
    
    Returns overall "ok": True only if all required services are healthy.
    """
    # Run required checks
    database = check_database()
    cache = check_cache()
    storage = check_object_storage()
    
    # Run optional checks
    search = check_search(skip_if_disabled=not include_optional)
    neo4j = check_neo4j(skip_if_disabled=not include_optional)
    
    # Determine overall health - only required services affect this
    overall_ok = all([
        database.get("ok", False),
        cache.get("ok", False),
        storage.get("ok", False),
    ])
    
    return {
        "ok": overall_ok,
        "checks": {
            "database": database,
            "cache": cache,
            "object_storage": storage,
            "search": search,
            "neo4j": neo4j
        }
    }


def liveness_check() -> Dict[str, Any]:
    """
    Kubernetes liveness probe - checks if app is alive.
    Should only fail if app needs to be restarted.
    """
    # For API: just check if the app is running (always True unless crashed)
    return {"status": "alive"}


def readiness_check() -> Dict[str, Any]:
    """
    Kubernetes readiness probe - checks if app is ready to serve traffic.
    Should check critical dependencies (DB, Redis).
    """
    # Check only critical services for readiness
    database = check_database()
    cache = check_cache()
    
    is_ready = database.get("ok", False) and cache.get("ok", False)
    
    if not is_ready:
        return {
            "status": "not_ready",
            "database": database,
            "cache": cache,
        }
    
    return {"status": "ready"}