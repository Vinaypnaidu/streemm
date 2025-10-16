from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from indexing_bundle import VideoIndexBundle


def _serialize_topics(bundle: VideoIndexBundle) -> List[Dict[str, Any]]:
    items = []
    for topic in bundle.topics:
        if not topic.canonical_name:
            continue
        items.append(
            {
                "id": topic.id,
                "name": topic.name,
                "canonical_name": topic.canonical_name,
                "prominence": float(topic.prominence),
            }
        )
    return items


def _serialize_entities(bundle: VideoIndexBundle) -> List[Dict[str, Any]]:
    items = []
    for entity in bundle.entities:
        if not entity.canonical_name:
            continue
        items.append(
            {
                "id": entity.id,
                "name": entity.name,
                "canonical_name": entity.canonical_name,
                "importance": float(entity.importance),
            }
        )
    return items


def _serialize_tags(bundle: VideoIndexBundle) -> List[Dict[str, Any]]:
    items = []
    for tag in bundle.tags:
        if not tag.canonical_name:
            continue
        items.append(
            {
                "id": tag.id,
                "name": tag.name,
                "canonical_name": tag.canonical_name,
                "weight": float(tag.weight),
            }
        )
    return items


def build_video_search_document(
    bundle: VideoIndexBundle,
    *,
    embedding: Optional[Sequence[float]] = None,
    thumbnail_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Construct the OpenSearch document for a video."""

    duration = bundle.duration_seconds
    if duration is None:
        duration = 0.0

    doc: Dict[str, Any] = {
        "title": bundle.title,
        "description": bundle.description,
        "content_type": bundle.content_type,
        "language": bundle.language,
        "duration_seconds": duration,
        "created_at": bundle.created_at.isoformat() if bundle.created_at else None,
        "updated_at": bundle.updated_at.isoformat() if bundle.updated_at else None,
        "user_id": bundle.user_id,
        "status": bundle.status,
        "thumbnail_url": thumbnail_url,
        "topics": _serialize_topics(bundle),
        "entities": _serialize_entities(bundle),
        "tags": _serialize_tags(bundle),
    }

    # Drop None values to avoid mapping issues
    doc = {k: v for k, v in doc.items() if v is not None}

    if embedding is not None:
        doc["embedding"] = list(embedding)

    return doc

