# apps/api/search.py
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

from opensearchpy import OpenSearch
from opensearchpy.exceptions import NotFoundError
from opensearchpy.helpers import bulk

from sqlalchemy.orm import Session

from config import settings
from storage import build_public_url, build_thumbnail_key
from embedding_utils import build_video_embedding_text, generate_embedding
from indexing_bundle import load_video_index_bundle
from indexing_payload import build_video_search_document

log = logging.getLogger("search")
if not log.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    log.addHandler(handler)
log.setLevel(logging.INFO)

_client: Optional[OpenSearch] = None
_indexes_ready = False

VIDEOS_INDEX = "videos"
TRANSCRIPTS_INDEX = "transcript_chunks"


def _build_client() -> Optional[OpenSearch]:
    url = settings.opensearch_url
    if not url:
        log.warning("No OPENSEARCH_URL configured")
        return None

    parsed = urlparse(url)
    scheme = parsed.scheme or "http"
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if scheme == "https" else 9200)
    use_ssl = scheme == "https"

    http_auth = None
    if settings.opensearch_username:
        http_auth = (
            settings.opensearch_username,
            settings.opensearch_password or "",
        )

    try:
        client = OpenSearch(
            hosts=[{"host": host, "port": port, "scheme": scheme}],
            http_auth=http_auth,
            use_ssl=use_ssl,
            verify_certs=use_ssl,
            ssl_show_warn=False,
            retry_on_timeout=True,
            max_retries=3,
        )
        if not client.ping():
            log.error("Failed to ping OpenSearch at %s", url)
            return None
        log.info("OpenSearch connected: %s", url)
        return client
    except Exception as exc:
        log.error("Failed to connect to OpenSearch at %s: %s", url, exc)
        return None


def get_client() -> Optional[OpenSearch]:
    global _client
    if _client is None:
        _client = _build_client()
    return _client


def ensure_indexes() -> None:
    client = get_client()
    if not client:
        log.warning("OpenSearch not available, skipping index setup")
        return
    _ensure_indexes_once(client)


def _ensure_indexes_once(client: OpenSearch) -> None:
    global _indexes_ready
    if _indexes_ready:
        return
    try:
        _ensure_videos_index(client)
        _ensure_transcripts_index(client)
        _indexes_ready = True
    except Exception as exc:
        log.error("Failed to ensure OpenSearch indexes: %s", exc)


def _ensure_videos_index(client: OpenSearch) -> None:
    if client.indices.exists(index=VIDEOS_INDEX):
        return
    body = {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "refresh_interval": "1s",
            "index": {
                "knn": False,
            },
        },
        "mappings": {
            "properties": {
                "title": {
                    "type": "text",
                    "fields": {"raw": {"type": "keyword", "ignore_above": 256}},
                },
                "description": {
                    "type": "text",
                    "fields": {"raw": {"type": "keyword", "ignore_above": 512}},
                },
                "short_summary": {
                    "type": "text",
                    "index": False,
                },
                "content_type": {"type": "keyword"},
                "language": {"type": "keyword"},
                "duration_seconds": {"type": "float"},
                "created_at": {"type": "date"},
                "updated_at": {"type": "date"},
                "user_id": {"type": "keyword"},
                "status": {"type": "keyword"},
                "embedding": {
                    "type": "float",
                    "index": False,
                    "doc_values": False
                },
                "topics": {
                    "type": "nested",
                    "properties": {
                        "id": {"type": "keyword"},
                        "name": {
                            "type": "text",
                            "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                        },
                        "canonical_name": {"type": "keyword"},
                        "prominence": {"type": "float"},
                    },
                },
                "entities": {
                    "type": "nested",
                    "properties": {
                        "id": {"type": "keyword"},
                        "name": {
                            "type": "text",
                            "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                        },
                        "canonical_name": {"type": "keyword"},
                        "importance": {"type": "float"},
                    },
                },
                "tags": {
                    "type": "nested",
                    "properties": {
                        "id": {"type": "keyword"},
                        "name": {
                            "type": "text",
                            "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                        },
                        "canonical_name": {"type": "keyword"},
                        "weight": {"type": "float"},
                    },
                },
            }
        },
    }
    try:
        client.indices.create(index=VIDEOS_INDEX, body=body)
        log.info("Created OpenSearch index %s", VIDEOS_INDEX)
    except Exception as exc:
        if client.indices.exists(index=VIDEOS_INDEX):
            return
        raise exc


def _ensure_transcripts_index(client: OpenSearch) -> None:
    if client.indices.exists(index=TRANSCRIPTS_INDEX):
        return
    body = {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "refresh_interval": "1s",
        },
        "mappings": {
            "properties": {
                "video_id": {"type": "keyword"},
                "text": {"type": "text"},
                "start_seconds": {"type": "float"},
                "end_seconds": {"type": "float"},
                "lang": {"type": "keyword"},
                "created_at": {"type": "date"},
            }
        },
    }
    try:
        client.indices.create(index=TRANSCRIPTS_INDEX, body=body)
        log.info("Created OpenSearch index %s", TRANSCRIPTS_INDEX)
    except Exception as exc:
        if client.indices.exists(index=TRANSCRIPTS_INDEX):
            return
        raise exc


def index_video_metadata(video) -> None:
    client = get_client()
    if not client:
        log.debug("OpenSearch not available, skipping video metadata indexing")
        return

    _ensure_indexes_once(client)

    video_id = str(video.id)
    thumb_url = build_public_url(build_thumbnail_key(video_id))
    doc = {
        "title": (video.title or "").strip(),
        "description": (video.description or "").strip(),
        "user_id": str(video.user_id),
        "created_at": (
            video.created_at.isoformat() if getattr(video, "created_at", None) else None
        ),
        "duration_seconds": (
            float(video.duration_seconds)
            if getattr(video, "duration_seconds", None) is not None
            else 0.0
        ),
        "thumbnail_url": thumb_url,
        "status": (video.status or "uploaded"),
    }

    try:
        doc_clean = {k: v for k, v in doc.items() if v is not None}
        client.update(
            index=VIDEOS_INDEX,
            id=video_id,
            body={"doc": doc_clean, "doc_as_upsert": True},
            refresh="wait_for",
        )
        log.info("Upserted video metadata for %s", video_id)
    except Exception as exc:
        log.error("Failed to index video metadata for %s: %s", video_id, exc)


def index_video_content(db: Session, video_id: str) -> None:
    client = get_client()
    if not client:
        log.debug("OpenSearch not available, skipping video content indexing")
        return

    _ensure_indexes_once(client)

    bundle = load_video_index_bundle(db, video_id)
    if not bundle:
        log.warning("index_video_content_missing_bundle video_id=%s", video_id)
        return

    embed_topics = [
        t for t in bundle.topics if t.prominence >= settings.opensearch_topic_prominence_th
    ]
    embed_entities = [
        e for e in bundle.entities if e.importance >= settings.opensearch_entity_importance_th
    ]
    embed_tags = [
        g for g in bundle.tags if g.weight >= settings.opensearch_tag_weight_th
    ]

    embed_text = build_video_embedding_text(
        title=bundle.title,
        description=bundle.description,
        summary=bundle.summary,
        topics=embed_topics,
        entities=embed_entities,
        tags=embed_tags,
        content_type=bundle.content_type,
        language=bundle.language,
    )

    embedding = generate_embedding(embed_text)
    if embedding is None:
        log.info("index_video_content_no_embedding video_id=%s", video_id)

    thumb_url = build_public_url(build_thumbnail_key(bundle.video_id))

    doc = build_video_search_document(bundle, embedding=embedding, thumbnail_url=thumb_url)

    try:
        client.index(index=VIDEOS_INDEX, id=bundle.video_id, body=doc, refresh="wait_for")
        log.info("Indexed video content for %s", video_id)
    except Exception as exc:
        log.error("Failed to index video content for %s: %s", video_id, exc)


def index_transcript_chunks(video_id: str, chunks: Iterable[Dict[str, Any]]) -> None:
    client = get_client()
    if not client:
        log.debug("OpenSearch not available, skipping transcript chunk indexing")
        return

    _ensure_indexes_once(client)

    chunk_list: List[Dict[str, Any]] = list(chunks)
    log.info("Indexing %d transcript chunks for video %s", len(chunk_list), video_id)

    try:
        client.delete_by_query(
            index=TRANSCRIPTS_INDEX,
            body={"query": {"term": {"video_id": video_id}}},
            refresh=True,
            conflicts="proceed",
        )
    except NotFoundError:
        pass
    except Exception as exc:
        log.warning("Failed to purge transcript chunks for %s: %s", video_id, exc)

    if not chunk_list:
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    actions = []
    for idx, chunk in enumerate(chunk_list):
        text = (chunk.get("text") or "").strip()
        if not text:
            continue
        start_sec = float(chunk.get("start_seconds", 0.0))
        end_sec = float(chunk.get("end_seconds", start_sec))
        created_at = chunk.get("created_at") or now_iso
        lang = chunk.get("lang") or settings.whisper_lang
        doc_id = f"{video_id}_{idx}_{int(round(start_sec * 1000))}"

        actions.append(
            {
                "_op_type": "index",
                "_index": TRANSCRIPTS_INDEX,
                "_id": doc_id,
                "_source": {
                    "video_id": video_id,
                    "text": text,
                    "start_seconds": start_sec,
                    "end_seconds": end_sec,
                    "lang": lang,
                    "created_at": created_at,
                },
            }
        )

    if not actions:
        log.warning("No non-empty transcript chunks to index for %s", video_id)
        return

    success, errors = bulk(client, actions, refresh="wait_for")
    if errors:
        log.error("Bulk indexing errors for %s: %s", video_id, errors)
    else:
        log.info("Indexed %d transcript chunks for %s", success, video_id)


def delete_video_from_search(video_id: str) -> None:
    client = get_client()
    if not client:
        log.debug("OpenSearch not available, skipping video deletion from search")
        return

    try:
        resp = client.delete(index=VIDEOS_INDEX, id=video_id, refresh="wait_for")
        result = resp.get("result", "unknown") if isinstance(resp, dict) else resp
        log.info(
            "Deleted video %s from %s index (result=%s)", video_id, VIDEOS_INDEX, result
        )
    except NotFoundError:
        log.debug("Video %s already absent from %s index", video_id, VIDEOS_INDEX)
    except Exception as exc:
        log.error(
            "Failed to delete video %s from %s index: %s", video_id, VIDEOS_INDEX, exc
        )

    try:
        resp = client.delete_by_query(
            index=TRANSCRIPTS_INDEX,
            body={"query": {"term": {"video_id": video_id}}},
            refresh=True,
            conflicts="proceed",
        )
        deleted = resp.get("deleted", 0) if isinstance(resp, dict) else resp
        log.info("Deleted transcript chunks for %s (deleted=%s)", video_id, deleted)
    except NotFoundError:
        log.debug("Transcript index missing for video %s", video_id)
    except Exception as exc:
        log.error("Failed to delete transcript chunks for %s: %s", video_id, exc)
