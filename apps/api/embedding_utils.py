# apps/api/embedding_utils.py
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Iterable, Optional, Sequence

from openai import OpenAI

from config import settings

log = logging.getLogger("embeddings")


@dataclass(frozen=True)
class TopicSnippet:
    id: str
    name: str
    canonical_name: str
    prominence: float


@dataclass(frozen=True)
class EntitySnippet:
    id: str
    name: str
    canonical_name: str
    importance: float


@dataclass(frozen=True)
class TagSnippet:
    id: str
    name: str
    canonical_name: str
    weight: float


def _format_pipe_list(items: Iterable[str]) -> str:
    values = [value.strip() for value in items if value and value.strip()]
    return " | ".join(values) if values else "n/a"


def build_video_embedding_text(
    *,
    title: str,
    description: str,
    summary: Optional[str],
    topics: Iterable[TopicSnippet],
    entities: Iterable[EntitySnippet],
    tags: Iterable[TagSnippet],
    content_type: Optional[str],
    language: Optional[str],
) -> str:
    """Assemble the embedding string following docs/homev2design.md."""

    topic_names = _format_pipe_list(topic.name for topic in topics)
    entity_names = _format_pipe_list(entity.name for entity in entities)
    tag_names = _format_pipe_list(tag.name for tag in tags)

    lines = [
        f"Title: {title.strip() if title else ''}",
        "",
        f"Description: {description.strip() if description else ''}",
        "",
        f"Summary: {(summary or '').strip()}",
        "",
        f"Topics: {topic_names}",
        f"Entities: {entity_names}",
        f"Tags: {tag_names}",
        "",
        "Metadata: "
        f"content_type={(content_type or 'other')}, "
        f"language={(language or 'en')}",
    ]
    return "\n".join(lines)


def _get_client() -> Optional[OpenAI]:
    api_key = (settings.openai_api_key or "").strip()
    if not api_key:
        log.info("openai_embeddings_disabled: missing OPENAI_API_KEY")
        return None
    try:
        return OpenAI(api_key=api_key)
    except Exception as exc:
        log.warning("openai_client_error: %s", exc)
        return None


def generate_embedding(text: str) -> Optional[Sequence[float]]:
    text = (text or "").strip()
    if not text:
        log.info("openai_embeddings_skipped: empty text")
        return None

    client = _get_client()
    if not client:
        return None

    model = settings.openai_embedding_model or "text-embedding-3-small"
    try:
        response = client.embeddings.create(model=model, input=text)
    except Exception as exc:
        log.warning("openai_embeddings_failed: %s", exc)
        return None

    data = response.data[0]
    vector = getattr(data, "embedding", None)
    if not vector:
        log.warning("openai_embeddings_missing_vector: data=%s", data)
        return None
    return vector