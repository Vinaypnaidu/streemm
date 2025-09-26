# apps/api/main.py
from __future__ import annotations

import logging
from typing import Callable, Iterable

from fastapi import FastAPI, Depends, Query
from fastapi.middleware.cors import CORSMiddleware

import config
from models import User
from session import get_current_user
from routes_auth import router as auth_router
from routes_uploads import router as uploads_router
from storage import ensure_bucket
from routes_videos import router as videos_router
from routes_history import router as history_router
from routes_search import router as search_router
from routes_homefeed import router as homefeed_router
from search import ensure_indexes, get_client, VIDEOS_INDEX, TRANSCRIPTS_INDEX
from health import collect_health_status


app = FastAPI(title="Streemm API")

log = logging.getLogger("api.main")


StartupTask = tuple[str, Callable[[], None], bool]

STARTUP_TASKS: tuple[StartupTask, ...] = (
    ("object_storage", ensure_bucket, False),
    ("search_indexes", ensure_indexes, True),
)


def _run_startup_tasks(tasks: Iterable[StartupTask]) -> None:
    for name, task, optional in tasks:
        try:
            task()
            log.debug("Startup task '%s' completed", name)
        except Exception as exc:
            if optional:
                log.info("Optional startup task '%s' failed: %s", name, exc)
            else:
                log.warning("Startup task '%s' failed: %s", name, exc)


app.add_middleware(
    CORSMiddleware,
    allow_origins=config.settings.cors_origins or ["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(uploads_router)
app.include_router(videos_router)
app.include_router(history_router)
app.include_router(search_router)
app.include_router(homefeed_router)


@app.on_event("startup")
def _startup() -> None:
    _run_startup_tasks(STARTUP_TASKS)


@app.get("/")
def root():
    return {"message": "hello from api"}


@app.get("/healthz")
def healthz(include_optional: bool = Query(True, description="Include optional checks")):
    return collect_health_status(include_optional=include_optional)


@app.get("/search/debug")
def search_debug():
    client = get_client()
    if not client:
        return {"ok": False, "error": "OpenSearch client unavailable"}
    try:
        cluster = client.cluster.health()
        indices = client.cat.indices(format="json")
        stats = {
            "videos": (
                client.indices.get(VIDEOS_INDEX).get(VIDEOS_INDEX)
                if client.indices.exists(VIDEOS_INDEX)
                else None
            ),
            "transcript_chunks": (
                client.indices.get(TRANSCRIPTS_INDEX).get(TRANSCRIPTS_INDEX)
                if client.indices.exists(TRANSCRIPTS_INDEX)
                else None
            ),
        }
        return {
            "ok": True,
            "cluster": cluster,
            "indices": indices,
            "stats": stats,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/hello")
def hello(name: str = "world"):
    return {"message": f"hello {name}"}


@app.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"id": str(user.id), "email": user.email}


# Run: uvicorn main:app --reload --port 8000
