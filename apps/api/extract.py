# apps/api/extract.py
from __future__ import annotations

import logging
import uuid
import re
import json as _json
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator

from config import settings
from prompt import _build_prompt

from openai import OpenAI

from models import (
    Video, VideoSummary,
    Topic, Entity, Tag,
    VideoTopic, VideoEntity, VideoTag,
)

log = logging.getLogger("extract")

class TopicItem(BaseModel):
    name: str
    canonical_name: str
    prominence: float = Field(ge=0.0, le=1.0)

    @validator("canonical_name", pre=True)
    def _canon(cls, v: str) -> str:
        return (v or "").strip().lower()


class EntityItem(BaseModel):
    name: str
    canonical_name: str
    importance: float = Field(ge=0.0, le=1.0)

    @validator("canonical_name", pre=True)
    def _canon(cls, v: str) -> str:
        return (v or "").strip().lower()


class TagItem(BaseModel):
    tag: str
    weight: float = Field(ge=0.0, le=1.0)

    @validator("tag", pre=True)
    def _canon(cls, v: str) -> str:
        return (v or "").strip().lower()


class ContentAnalysis(BaseModel):
    primary_type: Optional[str] = None
    secondary_type: Optional[str] = None
    reasoning: Optional[str] = None


class ExtractResult(BaseModel):
    short_summary: Optional[str] = None
    topics: List[TopicItem] = []
    entities: List[EntityItem] = []
    tags: List[TagItem] = []
    content_type: Optional[str] = None
    language: Optional[str] = None
    content_analysis: Optional[ContentAnalysis] = None  # not persisted


def _client() -> Optional[OpenAI]:
    if not settings.openai_api_key:
        log.info("OPENAI_API_KEY missing; skipping extraction")
        return None
    if OpenAI is None:
        log.warning("OpenAI SDK not available; skipping extraction")
        return None
    return OpenAI(api_key=settings.openai_api_key)


def _clip(s: str, max_chars: int) -> str:
    s = s.strip()
    return s[:max_chars]


def _build_transcript_text(chunks: List[Dict[str, Any]], max_chars: int) -> str:
    buf: List[str] = []
    total = 0
    for ch in chunks or []:
        t = (ch.get("text") or "").strip()
        if not t:
            continue
        need = len(t) + (1 if buf else 0)
        if total + need > max_chars:
            break
        if buf:
            buf.append(" ")
        buf.append(t)
        total += need
    return "".join(buf)


def _call_openai_json(prompt: str) -> Optional[Dict[str, Any]]:
    client = _client()
    if not client:
        return None
    try:
        resp = client.chat.completions.create(
            model=(settings.openai_chat_model or "gpt-5-mini"),
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or "{}"
        # Log raw JSON string for debugging
        try:
            log.info("openai_extract_raw_json: %s", content)
        except Exception:
            pass

        try:
            return _json.loads(content)
        except Exception:
            m = re.search(r"\{[\s\S]*\}", content)
            if m:
                try:
                    return _json.loads(m.group(0))
                except Exception:
                    pass
            return None
    except Exception as e:
        log.warning("openai_call_failed: %s", e)
        return None


def _normalize_result(raw: Dict[str, Any]) -> ExtractResult:
    items_topics = []
    for it in (raw.get("topics") or []):
        try:
            items_topics.append(TopicItem(**it).dict())
        except Exception:
            pass
    seen = set()
    topics_norm = []
    for it in items_topics:
        cn = it["canonical_name"]
        if cn in seen:
            continue
        seen.add(cn)
        topics_norm.append(it)

    items_entities = []
    for it in (raw.get("entities") or []):
        try:
            items_entities.append(EntityItem(**it).dict())
        except Exception:
            pass
    seen = set()
    entities_norm = []
    for it in items_entities:
        cn = it["canonical_name"]
        if cn in seen:
            continue
        seen.add(cn)
        entities_norm.append(it)

    # Tags: normalize and dedupe by canonical tag string
    items_tags = []
    for it in (raw.get("tags") or []):
        try:
            items_tags.append(TagItem(**it).dict())
        except Exception:
            pass
    seen = set()
    tags_norm = []
    for it in items_tags:
        tg = it["tag"]
        if tg in seen:
            continue
        seen.add(tg)
        tags_norm.append(it)

    meta = raw.get("metadata") or {}
    ca_raw = raw.get("content_analysis") or {}
    ca_obj = None
    try:
        ca_obj = ContentAnalysis(**ca_raw)
    except Exception:
        ca_obj = None

    return ExtractResult(
        short_summary=(raw.get("short_summary") or None),
        topics=[TopicItem(**t) for t in topics_norm],
        entities=[EntityItem(**e) for e in entities_norm],
        tags=[TagItem(**t) for t in tags_norm],
        content_type=(meta.get("content_type") or None),
        language=(meta.get("language") or None),
        content_analysis=ca_obj,
    )


def extract_from_transcript(
    video_id: str,
    title: str,
    description: str,
    transcript_chunks: List[Dict[str, Any]] | None,
    *,
    max_transcript_chars: int = 60000,
) -> Optional[ExtractResult]:
    """
    Main entrypoint: takes chunked transcript from worker, builds prompt, returns normalized result.
    """
    title = (title or "").strip()
    description = (description or "").strip()
    transcript_text = _build_transcript_text(transcript_chunks or [], max_transcript_chars)
    prompt = _build_prompt(title, description, transcript_text)
    raw = _call_openai_json(prompt)
    if not raw:
        return None
    return _normalize_result(raw)


def persist_result(db, video_id: str, res: ExtractResult) -> None:
    """
    Upsert into Postgres (idempotent):
      - video_summary
      - topics + video_topics
      - entities + video_entities
      - tags + video_tags
      - videos(content_type, language) when provided (no duration from LLM)
    """
    vid = uuid.UUID(video_id)

    # 1) Video summary
    ss = (res.short_summary or "").strip()
    existing_sum = db.get(VideoSummary, vid)
    if existing_sum:
        if existing_sum.short_summary != ss:
            existing_sum.short_summary = ss
    else:
        db.add(VideoSummary(video_id=vid, short_summary=ss))

    # 2) Topics
    existing_vt = db.query(VideoTopic).filter(VideoTopic.video_id == vid).all()
    have_topic_ids = {row.topic_id for row in existing_vt}
    want_topic_ids = set()

    for t in res.topics or []:
        cn = (t.canonical_name or "").strip().lower()
        if not cn:
            continue
        topic = db.query(Topic).filter(Topic.canonical_name == cn).first()
        if not topic:
            topic = Topic(name=t.name or cn, canonical_name=cn)
            db.add(topic)
            db.flush()
        want_topic_ids.add(topic.id)

        link = (
            db.query(VideoTopic)
            .filter(VideoTopic.video_id == vid, VideoTopic.topic_id == topic.id)
            .first()
        )
        if link:
            link.prominence = float(t.prominence)
        else:
            db.add(VideoTopic(video_id=vid, topic_id=topic.id, prominence=float(t.prominence)))

    to_drop = have_topic_ids - want_topic_ids
    if to_drop:
        db.query(VideoTopic).filter(
            VideoTopic.video_id == vid,
            VideoTopic.topic_id.in_(list(to_drop)),
        ).delete(synchronize_session=False)

    # 3) Entities
    existing_ve = db.query(VideoEntity).filter(VideoEntity.video_id == vid).all()
    have_entity_ids = {row.entity_id for row in existing_ve}
    want_entity_ids = set()

    for e in res.entities or []:
        cn = (e.canonical_name or "").strip().lower()
        if not cn:
            continue
        ent = db.query(Entity).filter(Entity.canonical_name == cn).first()
        if not ent:
            ent = Entity(name=e.name or cn, canonical_name=cn)
            db.add(ent)
            db.flush()
        want_entity_ids.add(ent.id)

        link = (
            db.query(VideoEntity)
            .filter(VideoEntity.video_id == vid, VideoEntity.entity_id == ent.id)
            .first()
        )
        if link:
            link.importance = float(e.importance)
        else:
            db.add(VideoEntity(video_id=vid, entity_id=ent.id, importance=float(e.importance)))

    to_drop_e = have_entity_ids - want_entity_ids
    if to_drop_e:
        db.query(VideoEntity).filter(
            VideoEntity.video_id == vid,
            VideoEntity.entity_id.in_(list(to_drop_e)),
        ).delete(synchronize_session=False)

    # 4) Tags
    existing_vtags = db.query(VideoTag).filter(VideoTag.video_id == vid).all()
    have_tag_ids = {row.tag_id for row in existing_vtags}
    want_tag_ids = set()

    for t in res.tags or []:
        tg = (t.tag or "").strip().lower()
        if not tg:
            continue
        tag = db.query(Tag).filter(Tag.canonical_name == tg).first()
        if not tag:
            tag = Tag(name=tg, canonical_name=tg)
            db.add(tag)
            db.flush()
        want_tag_ids.add(tag.id)

        link = (
            db.query(VideoTag)
            .filter(VideoTag.video_id == vid, VideoTag.tag_id == tag.id)
            .first()
        )
        if link:
            link.weight = float(t.weight)
        else:
            db.add(VideoTag(video_id=vid, tag_id=tag.id, weight=float(t.weight)))

    to_drop_t = have_tag_ids - want_tag_ids
    if to_drop_t:
        db.query(VideoTag).filter(
            VideoTag.video_id == vid,
            VideoTag.tag_id.in_(list(to_drop_t)),
        ).delete(synchronize_session=False)

    # 5) Update videos(content_type, language)
    v = db.get(Video, vid)
    if v:
        if res.content_type and (v.content_type or "").strip() != res.content_type.strip():
            v.content_type = res.content_type.strip()
        if res.language and (v.language or "").strip().lower() != res.language.strip().lower():
            v.language = res.language.strip()

    db.commit()