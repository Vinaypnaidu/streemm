# apps/api/search.py
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional
from datetime import datetime, timezone

import meilisearch
from meilisearch.errors import MeilisearchApiError, MeilisearchError

from config import settings
from storage import build_thumbnail_key, build_public_url

log = logging.getLogger("search")

_meili: Optional[meilisearch.Client] = None

def get_meili() -> Optional[meilisearch.Client]:
    global _meili
    if _meili is not None:
        return _meili
    if not settings.meili_url:
        log.warning("No MEILI_URL configured")
        return None
    try:
        _meili = meilisearch.Client(settings.meili_url, settings.meili_master_key or None)
        # Test connection
        _meili.health()
        log.info(f"Meilisearch connected: {settings.meili_url}")
        return _meili
    except Exception as e:
        log.error(f"Failed to connect to Meilisearch at {settings.meili_url}: {e}")
        return None

def ensure_indexes() -> None:
    c = get_meili()
    if not c:
        log.warning("Meilisearch not available, skipping index setup")
        return
    
    log.info("Setting up Meilisearch indexes...")
    
    # videos
    try:
        videos_index = c.index("videos")
        info = videos_index.get_stats()
        log.info(f"Videos index exists: {info.get('numberOfDocuments', 0)} docs")
    except MeilisearchApiError as e:
        log.info(f"Creating videos index: {e}")
        try:
            task = c.create_index("videos", {"primaryKey": "id"})
            log.info(f"Created videos index, task: {task.task_uid}")
        except Exception as e:
            log.error(f"Failed to create videos index: {e}")
            return
    
    # transcript_chunks
    try:
        chunks_index = c.index("transcript_chunks")
        info = chunks_index.get_stats()
        log.info(f"Transcript chunks index exists: {info.get('numberOfDocuments', 0)} docs")
    except MeilisearchApiError as e:
        log.info(f"Creating transcript_chunks index: {e}")
        try:
            task = c.create_index("transcript_chunks", {"primaryKey": "id"})
            log.info(f"Created transcript_chunks index, task: {task.task_uid}")
        except Exception as e:
            log.error(f"Failed to create transcript_chunks index: {e}")
            return

    try:
        task = c.index("videos").update_settings({
            "searchableAttributes": ["title", "description"],
            "filterableAttributes": ["created_at", "user_id"],
            "sortableAttributes": ["created_at", "duration_seconds"],
            "typoTolerance": { "enabled": True },
        })
        log.info(f"Updated videos index settings, task: {task.task_uid}")
    except Exception as e:
        log.error(f"Failed to update videos settings: {e}")
    
    try:
        task = c.index("transcript_chunks").update_settings({
            "searchableAttributes": ["text"],
            "filterableAttributes": ["lang", "created_at", "video_id"], 
            "sortableAttributes": ["created_at", "start_seconds"],
            "typoTolerance": { "enabled": True },
        })
        log.info(f"Updated transcript_chunks index settings, task: {task.task_uid}")
    except Exception as e:
        log.error(f"Failed to update transcript_chunks settings: {e}")

def index_video_metadata(video) -> None:
    """Upsert a single video's metadata document."""
    c = get_meili()
    if not c:
        log.debug("Meilisearch not available, skipping video metadata indexing")
        return
    
    video_id = str(video.id)
    log.debug(f"Indexing video metadata for {video_id}")
    
    thumb_url = build_public_url(build_thumbnail_key(str(video.id)))
    doc = {
        "id": str(video.id),
        "title": (video.title or "").strip(),
        "description": (video.description or "").strip(),
        "user_id": str(video.user_id),
        "created_at": video.created_at.isoformat() if getattr(video, "created_at", None) else None,
        "duration_seconds": float(video.duration_seconds) if video.duration_seconds is not None else 0,
        "thumbnail_url": thumb_url,
    }
    
    try:
        task = c.index("videos").add_documents([doc])
        log.info(f"Indexed video metadata for {video_id}, task: {task.task_uid}")
    except Exception as e:
        log.error(f"Failed to index video metadata for {video_id}: {e}")

def index_transcript_chunks(video_id: str, chunks: Iterable[Dict[str, Any]]) -> None:
    """Replace transcript chunks for a video (idempotent)."""
    c = get_meili()
    if not c:
        log.debug("Meilisearch not available, skipping transcript chunk indexing")
        return
    
    log.info(f"Indexing transcript chunks for video {video_id}")
    
    idx = c.index("transcript_chunks")
    
    # Idempotent replace: delete any existing docs for this video first
    try:
        del_task = idx.delete_documents(filter=f'video_id = "{video_id}"')
        log.info(f"Enqueued deletion of existing transcript chunks for {video_id}, task: {del_task.task_uid}")
    except Exception as e:
        log.warning(f"Failed to enqueue deletion for {video_id}: {e}")
    
    # Add new docs
    docs: List[Dict[str, Any]] = []
    for ch in chunks:
        start_sec = float(ch["start_seconds"])
        end_sec = float(ch["end_seconds"])
        start_int = int(round(start_sec))
        created_at = ch.get("created_at")
        if not created_at:
            created_at = datetime.now(timezone.utc).isoformat()
        docs.append({
            "id": f"{video_id}_{start_int}",
            "video_id": video_id,
            "text": ch["text"],
            "start_seconds": start_sec,
            "end_seconds": end_sec,
            "lang": ch.get("lang", "en"),
            "created_at": created_at,
        })
    
    log.info(f"Prepared {len(docs)} transcript chunks for {video_id}")
    
    if docs:
        try:
            task = idx.add_documents(docs)
            log.info(f"Indexed {len(docs)} transcript chunks for {video_id}, task: {task.task_uid}")
        except Exception as e:
            log.error(f"Failed to index transcript chunks for {video_id}: {e}")
    else:
        log.warning(f"No transcript chunks to index for {video_id}")

def delete_video_from_search(video_id: str) -> None:
    c = get_meili()
    if not c:
        log.debug("Meilisearch not available, skipping video deletion from search")
        return
    
    log.info(f"Deleting video {video_id} from search indexes")
    
    try:
        task = c.index("videos").delete_document(video_id)
        log.info(f"Deleted video {video_id} from videos index, task: {task.task_uid}")
    except MeilisearchApiError as e:
        log.warning(f"Failed to delete video {video_id} from videos index: {e}")
    except Exception as e:
        log.error(f"Unexpected error deleting video {video_id} from videos index: {e}")
    
    try:
        task = c.index("transcript_chunks").delete_documents(filter=f'video_id = "{video_id}"')
        log.info(f"Deleted transcript chunks for {video_id}, task: {task.task_uid}")
    except MeilisearchApiError as e:
        log.warning(f"Failed to delete transcript chunks for {video_id}: {e}")
    except Exception as e:
        log.error(f"Unexpected error deleting transcript chunks for {video_id}: {e}")