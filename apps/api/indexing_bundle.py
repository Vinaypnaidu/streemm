# apps/api/indexing_bundle.py
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy.orm import Session

from config import settings
from models import (
    Video,
    VideoSummary,
    VideoTopic,
    Topic,
    VideoEntity,
    Entity,
    VideoTag,
    Tag,
)

from embedding_utils import TopicSnippet, EntitySnippet, TagSnippet


@dataclass(frozen=True)
class VideoIndexBundle:
    video_id: str
    user_id: str
    title: str
    description: str
    status: str
    duration_seconds: Optional[float]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    content_type: Optional[str]
    language: Optional[str]
    summary: Optional[str]
    topics: List[TopicSnippet]
    entities: List[EntitySnippet]
    tags: List[TagSnippet]


def _decimal_to_float(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)


def load_video_index_bundle(db: Session, video_id: str) -> Optional[VideoIndexBundle]:
    """
    Fetch all data needed for embedding + OpenSearch indexing in one query bundle.
    Returns None if the video is missing.
    """
    vid = uuid.UUID(str(video_id))
    video = db.get(Video, vid)
    if not video:
        return None

    summary_row = db.get(VideoSummary, vid)
    summary_text = (summary_row.short_summary or "").strip() if summary_row else None

    topic_rows = (
        db.query(VideoTopic, Topic)
        .join(Topic, Topic.id == VideoTopic.topic_id)
        .filter(VideoTopic.video_id == vid)
        .all()
    )
    topic_th = settings.opensearch_topic_prominence_th
    topics = [
        TopicSnippet(
            id=str(topic.id),
            name=(topic.name or "").strip(),
            canonical_name=(topic.canonical_name or "").strip().lower(),
            prominence=float(vt.prominence or 0),
        )
        for vt, topic in topic_rows
        if float(vt.prominence or 0) >= topic_th
    ]

    entity_rows = (
        db.query(VideoEntity, Entity)
        .join(Entity, Entity.id == VideoEntity.entity_id)
        .filter(VideoEntity.video_id == vid)
        .all()
    )
    entity_th = settings.opensearch_entity_importance_th
    entities = [
        EntitySnippet(
            id=str(entity.id),
            name=(entity.name or "").strip(),
            canonical_name=(entity.canonical_name or "").strip().lower(),
            importance=float(ve.importance or 0),
        )
        for ve, entity in entity_rows
        if float(ve.importance or 0) >= entity_th
    ]

    tag_rows = (
        db.query(VideoTag, Tag)
        .join(Tag, Tag.id == VideoTag.tag_id)
        .filter(VideoTag.video_id == vid)
        .all()
    )
    tag_th = settings.opensearch_tag_weight_th
    tags = [
        TagSnippet(
            id=str(tag.id),
            name=(tag.name or "").strip(),
            canonical_name=(tag.canonical_name or "").strip().lower(),
            weight=float(vt.weight or 0),
        )
        for vt, tag in tag_rows
        if float(vt.weight or 0) >= tag_th
    ]

    return VideoIndexBundle(
        video_id=str(video.id),
        user_id=str(video.user_id),
        title=(video.title or "").strip(),
        description=(video.description or "").strip(),
        status=(video.status or "uploaded").strip(),
        duration_seconds=_decimal_to_float(video.duration_seconds),
        created_at=video.created_at,
        updated_at=video.updated_at,
        content_type=(video.content_type or "").strip() or None,
        language=(video.language or "").strip() or None,
        summary=summary_text,
        topics=topics,
        entities=entities,
        tags=tags,
    )