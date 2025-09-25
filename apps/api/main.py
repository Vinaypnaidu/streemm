from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

import config
from db import healthcheck as db_health
from cache import healthcheck as cache_health
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


app = FastAPI(title="Streemm API")

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
def _startup():
    try:
        ensure_bucket()
    except Exception:
        pass
    try:
        ensure_indexes()
    except Exception:
        pass

@app.get("/")
def root():
    return {"message": "hello from api"}

@app.get("/healthz")
def healthz():
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
    return {"ok": ok_db and ok_cache, "db": ok_db, "cache": ok_cache}

@app.get("/search/debug")
def search_debug():
    client = get_client()
    if not client:
        return {"ok": False, "error": "OpenSearch client unavailable"}
    try:
        cluster = client.cluster.health()
        indices = client.cat.indices(format="json")
        stats = {
            "videos": client.indices.get(VIDEOS_INDEX).get(VIDEOS_INDEX) if client.indices.exists(VIDEOS_INDEX) else None,
            "transcript_chunks": client.indices.get(TRANSCRIPTS_INDEX).get(TRANSCRIPTS_INDEX) if client.indices.exists(TRANSCRIPTS_INDEX) else None,
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