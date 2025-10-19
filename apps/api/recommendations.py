# apps/api/recommendations.py
from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, TypeVar
from uuid import UUID

from sqlalchemy.orm import Session
from opensearchpy import OpenSearch

from search import VIDEOS_INDEX, ensure_indexes, get_client
from models import (
    Entity,
    Tag,
    Topic,
    Video,
    VideoEntity,
    VideoTag,
    VideoTopic,
    WatchHistory,
)

HISTORY_DEPTH = 25
RECENCY_HALF_LIFE_DAYS = 14.0

MAX_TAG_SEEDS = 15
MAX_ENTITY_SEEDS = 13
MAX_TOPIC_SEEDS = 7

TARGET_TOTAL_RECOMMENDATIONS = 100
OS_LANE_QUOTA = 60
GRAPH_LANE_QUOTA = 40
OS_KNN_RECALL_K = 300
OS_BM25_RECALL_K = 300
GRAPH_ONE_HOP_RECALL_K = 200
GRAPH_TWO_HOP_RECALL_K = 200
MMR_LAMBDA = 0.7
OS_WITHIN_LANE_SHORTLIST = 120
OS_MMR_POOL_MULTIPLIER = 2
OS_COSINE_WEIGHT = 0.5
OS_BM25_WEIGHT = 0.5

BM25_TOP_LEVEL_FIELDS = [
    "title^3",
    "description^2",
]

OS_SOURCE_FIELDS = [
    "title",
    "description",
    "content_type",
    "language",
    "topics",
    "entities",
    "tags",
    "duration_seconds",
    "created_at",
    "updated_at",
    "thumbnail_url",
    "status",
]

# Lean source for recall; embeddings will be hydrated only for the MMR pool
OS_SOURCE_FIELDS_LEAN = [
    "title",
    "description",
    "content_type",
    "language",
    "topics",
    "entities",
    "tags",
    "duration_seconds",
    "created_at",
    "updated_at",
    "thumbnail_url",
    "status",
]


log = logging.getLogger("recommendations")

T = TypeVar("T")

ScoreFn = Callable[[T], float]
SimilarityFn = Callable[[T, T], float]


@dataclass
class HistoryEntry:
    video_id: UUID
    last_watched_at: Optional[datetime]
    recency_weight: float


@dataclass
class Seed:
    canonical_name: str
    name: str
    weight: float


@dataclass
class SeedBundle:
    history: List[HistoryEntry]
    topics: List[Seed]
    entities: List[Seed]
    tags: List[Seed]
    user_embedding: Optional[List[float]]


@dataclass
class OSCandidate:
    video_id: str
    document: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[List[float]] = None
    cosine_score: Optional[float] = None
    bm25_score: Optional[float] = None
    cosine_norm: float = 0.0
    bm25_norm: float = 0.0
    lane_score: float = 0.0
    sources: List[str] = field(default_factory=list)


@dataclass
class OSLaneResult:
    shortlist: List[OSCandidate]
    candidates: List[OSCandidate]
    bm25_terms: List[str] = field(default_factory=list)


def _recency_weight(last_watched_at: Optional[datetime], now: datetime) -> float:
    if last_watched_at is None:
        return 0.0
    if last_watched_at.tzinfo is None:
        last_watched_at = last_watched_at.replace(tzinfo=timezone.utc)
    age_days = max((now - last_watched_at).total_seconds() / 86400.0, 0.0)
    if RECENCY_HALF_LIFE_DAYS <= 0:
        return 0.0
    return math.pow(0.5, age_days / RECENCY_HALF_LIFE_DAYS)


def _normalize_top(
    raw_scores: Dict[UUID, Dict[str, object]], limit: int
) -> List[Seed]:
    if not raw_scores:
        return []
    ranked = sorted(
        raw_scores.values(),
        key=lambda item: item["score"],
        reverse=True,
    )[:limit]
    total = sum(item["score"] for item in ranked if item["score"] > 0)
    if total <= 0:
        return []
    return [
        Seed(
            canonical_name=item["canonical_name"],
            name=item["name"],
            weight=item["score"] / total,
        )
        for item in ranked
        if item["score"] > 0
    ]


def min_max_normalize(values: Sequence[float]) -> List[float]:
    if not values:
        return []
    min_val = min(values)
    max_val = max(values)
    if math.isclose(max_val, min_val):
        return [1.0 if max_val > 0 else 0.0 for _ in values]
    scale = max_val - min_val
    return [(value - min_val) / scale for value in values]


def _safe_get_embedding(doc: Dict[str, Any]) -> Optional[List[float]]:
    vector = doc.get("embedding")
    if not isinstance(vector, (list, tuple)):
        return None
    try:
        return [float(x) for x in vector]
    except Exception:
        return None


def _normalize_scores(values: Sequence[Optional[float]]) -> List[float]:
    raw = [value if value is not None else 0.0 for value in values]
    return min_max_normalize(raw)


def cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
    if not vec_a or not vec_b:
        return 0.0
    if len(vec_a) != len(vec_b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for a, b in zip(vec_a, vec_b):
        dot += a * b
        norm_a += a * a
        norm_b += b * b
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return dot / math.sqrt(norm_a * norm_b)


def max_marginal_relevance(
    items: Sequence[T],
    *,
    score_fn: ScoreFn[T],
    similarity_fn: SimilarityFn[T],
    limit: int,
    lambda_weight: float = MMR_LAMBDA,
) -> List[T]:
    if limit <= 0 or not items:
        return []

    # Precompute relevance scores once
    relevance: List[float] = [score_fn(item) for item in items]
    lam = max(0.0, min(1.0, lambda_weight))

    selected: List[T] = []
    remaining_idx: List[int] = list(range(len(items)))
    max_sim_to_selected: List[float] = [0.0] * len(items)

    while remaining_idx and len(selected) < limit:
        best_idx: Optional[int] = None
        best_score = float("-inf")

        for idx in remaining_idx:
            if not selected:
                mmr_score = relevance[idx]
            else:
                diversity = max_sim_to_selected[idx]
                mmr_score = lam * relevance[idx] - (1.0 - lam) * diversity

            if mmr_score > best_score or (mmr_score == best_score and best_idx is not None and idx < best_idx):
                best_score = mmr_score
                best_idx = idx

        if best_idx is None:
            break

        chosen = items[best_idx]
        selected.append(chosen)
        remaining_idx.remove(best_idx)

        # Update running max similarity once per new selection
        for idx in remaining_idx:
            sim = similarity_fn(items[idx], chosen)
            if sim > max_sim_to_selected[idx]:
                max_sim_to_selected[idx] = sim

    return selected


def _collect_seed_scores(
    rows: Sequence,
    recency_by_video: Dict[UUID, float],
    value_attr: str,
) -> Dict[UUID, Dict[str, object]]:
    scores: Dict[UUID, Dict[str, object]] = {}
    for relation, master in rows:
        base_weight = float(getattr(relation, value_attr) or 0.0)
        if base_weight <= 0:
            continue
        recency = recency_by_video.get(relation.video_id, 0.0)
        if recency <= 0:
            continue
        seed_weight = base_weight * recency
        entry = scores.setdefault(
            master.id,
            {
                "canonical_name": master.canonical_name,
                "name": master.name,
                "score": 0.0,
            },
        )
        entry["score"] += seed_weight
    return scores


def _fetch_video_embeddings(video_ids: Sequence[UUID]) -> Dict[UUID, List[float]]:
    if not video_ids:
        return {}

    client = get_client()
    if not client:
        log.info("recommendations_skip_embeddings: no_opensearch_client")
        return {}

    unique_ids = list({str(video_id) for video_id in video_ids})
    try:
        response = client.mget(index=VIDEOS_INDEX, body={"ids": unique_ids})
    except Exception as exc:
        log.warning("recommendations_mget_failed", exc_info=exc)
        return {}

    docs = response.get("docs", []) if isinstance(response, dict) else []
    embeddings: Dict[UUID, List[float]] = {}
    for doc in docs:
        if not doc or not doc.get("found"):
            continue
        source = doc.get("_source") or {}
        vector = source.get("embedding")
        if not isinstance(vector, (list, tuple)):
            continue
        try:
            video_id = UUID(str(doc.get("_id")))
        except Exception:
            continue
        embeddings[video_id] = [float(x) for x in vector]
    return embeddings


def _compute_user_embedding(
    history_entries: Sequence[HistoryEntry],
    embedding_by_video: Dict[UUID, Sequence[float]],
) -> Optional[List[float]]:
    if not history_entries or not embedding_by_video:
        return None

    accumulator: Optional[List[float]] = None
    weight_sum = 0.0
    expected_dim: Optional[int] = None

    for entry in history_entries:
        weight = float(entry.recency_weight or 0.0)
        if weight <= 0:
            continue
        vector = embedding_by_video.get(entry.video_id)
        if not vector:
            continue

        vec_list = [float(x) for x in vector]
        if expected_dim is None:
            expected_dim = len(vec_list)
            accumulator = [0.0] * expected_dim
        elif len(vec_list) != expected_dim:
            log.debug(
                "recommendations_skip_vector_dim_mismatch",
                extra={
                    "video_id": str(entry.video_id),
                    "expected": expected_dim,
                    "actual": len(vec_list),
                },
            )
            continue

        for idx, value in enumerate(vec_list):
            accumulator[idx] += weight * value
        weight_sum += weight

    if not accumulator or weight_sum <= 0:
        return None

    avg_vector = [value / weight_sum for value in accumulator]
    norm = math.sqrt(sum(value * value for value in avg_vector))
    if norm <= 0:
        return None
    return [value / norm for value in avg_vector]


def build_seed_bundle(
    db: Session,
    user_id: UUID,
    now: Optional[datetime] = None,
    limit: int = HISTORY_DEPTH,
) -> SeedBundle:
    limit = max(1, min(limit, HISTORY_DEPTH))
    now = now or datetime.now(timezone.utc)

    history_rows = (
        db.query(WatchHistory, Video)
        .join(Video, WatchHistory.video_id == Video.id)
        .filter(WatchHistory.user_id == user_id, Video.status == "ready")
        .order_by(WatchHistory.last_watched_at.desc())
        .limit(limit)
        .all()
    )

    history_entries: List[HistoryEntry] = []
    recency_by_video: Dict[UUID, float] = {}
    video_ids: List[UUID] = []

    for wh, _video in history_rows:
        weight = _recency_weight(wh.last_watched_at, now)
        recency_by_video[wh.video_id] = weight
        video_ids.append(wh.video_id)
        history_entries.append(
            HistoryEntry(
                video_id=wh.video_id,
                last_watched_at=wh.last_watched_at,
                recency_weight=weight,
            )
        )

    if not video_ids:
        return SeedBundle(history=[], topics=[], entities=[], tags=[], user_embedding=None)

    embedding_by_video = _fetch_video_embeddings(video_ids)
    user_embedding = _compute_user_embedding(history_entries, embedding_by_video)

    topic_rows = (
        db.query(VideoTopic, Topic)
        .join(Topic, VideoTopic.topic_id == Topic.id)
        .filter(VideoTopic.video_id.in_(video_ids))
        .all()
    )
    entity_rows = (
        db.query(VideoEntity, Entity)
        .join(Entity, VideoEntity.entity_id == Entity.id)
        .filter(VideoEntity.video_id.in_(video_ids))
        .all()
    )
    tag_rows = (
        db.query(VideoTag, Tag)
        .join(Tag, VideoTag.tag_id == Tag.id)
        .filter(VideoTag.video_id.in_(video_ids))
        .all()
    )

    topic_scores = _collect_seed_scores(topic_rows, recency_by_video, "prominence")
    entity_scores = _collect_seed_scores(entity_rows, recency_by_video, "importance")
    tag_scores = _collect_seed_scores(tag_rows, recency_by_video, "weight")

    return SeedBundle(
        history=history_entries,
        topics=_normalize_top(topic_scores, MAX_TOPIC_SEEDS),
        entities=_normalize_top(entity_scores, MAX_ENTITY_SEEDS),
        tags=_normalize_top(tag_scores, MAX_TAG_SEEDS),
        user_embedding=user_embedding,
    )


def _build_bm25_terms(seed_bundle: SeedBundle) -> List[str]:
    terms: List[str] = []
    seen: Set[str] = set()

    def add_from_seeds(seeds: Sequence[Seed], limit: int) -> None:
        ordered = sorted(seeds, key=lambda seed: seed.weight, reverse=True)[:limit]
        for seed in ordered:
            name = (seed.name or "").strip()
            if not name:
                continue
            dedupe_key = name.lower()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            terms.append(name)

    add_from_seeds(seed_bundle.tags, MAX_TAG_SEEDS)
    add_from_seeds(seed_bundle.entities, MAX_ENTITY_SEEDS)
    add_from_seeds(seed_bundle.topics, MAX_TOPIC_SEEDS)

    return terms


def _execute_knn_search(
    client: OpenSearch,
    query_vector: Sequence[float],
    exclude_video_ids: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    if not query_vector:
        return []

    vector = [float(x) for x in query_vector]
    excludes = [str(x) for x in (exclude_video_ids or [])]
    
    must_not_clauses = []
    if excludes:
        must_not_clauses.append({"ids": {"values": excludes}})
    
    body = {
        "size": OS_KNN_RECALL_K,
        "track_total_hits": False,
        "_source": OS_SOURCE_FIELDS_LEAN,
        "query": {
            "bool": {
                "must": [
                    {
                        "knn": {
                            "embedding": {
                                "vector": vector,
                                "k": OS_KNN_RECALL_K,
                            }
                        }
                    }
                ],
                "filter": [
                    {"term": {"status": "ready"}}
                ],
                "must_not": must_not_clauses
            }
        }
    }

    try:
        response = client.search(index=VIDEOS_INDEX, body=body, request_timeout=2.0)
    except Exception as exc:
        log.warning("recommendations_knn_search_failed", exc_info=exc)
        return []

    hits = response.get("hits", {}).get("hits", []) if isinstance(response, dict) else []
    return hits


def _execute_bm25_search(
    client: OpenSearch,
    terms: Sequence[str],
    exclude_video_ids: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    if not terms:
        return []

    query_text = " ".join(value.strip() for value in terms if value.strip())
    if not query_text:
        return []

    excludes = [str(x) for x in (exclude_video_ids or [])]
    body = {
        "size": OS_BM25_RECALL_K,
        "track_total_hits": False,
        "_source": OS_SOURCE_FIELDS_LEAN,
        "query": {
            "bool": {
                "must_not": ([{"ids": {"values": excludes}}] if excludes else []),
                "should": [
                    {
                        "multi_match": {
                            "query": query_text,
                            "fields": BM25_TOP_LEVEL_FIELDS,
                            "type": "best_fields",
                        }
                    },
                    {
                        "nested": {
                            "path": "tags",
                            "score_mode": "max",
                            "query": {
                                "match": {
                                    "tags.name": {
                                        "query": query_text,
                                        "operator": "or",
                                    }
                                }
                            },
                            "boost": 2.0,
                        }
                    },
                    {
                        "nested": {
                            "path": "entities",
                            "score_mode": "max",
                            "query": {
                                "match": {
                                    "entities.name": {
                                        "query": query_text,
                                        "operator": "or",
                                    }
                                }
                            },
                            "boost": 2.0,
                        }
                    },
                    {
                        "nested": {
                            "path": "topics",
                            "score_mode": "max",
                            "query": {
                                "match": {
                                    "topics.name": {
                                        "query": query_text,
                                        "operator": "or",
                                    }
                                }
                            },
                            "boost": 1.0,
                        }
                    },
                ],
                "minimum_should_match": 1,
                "filter": [
                    {
                        "term": {
                            "status": "ready",
                        }
                    }
                ],
            }
        },
    }

    try:
        response = client.search(index=VIDEOS_INDEX, body=body, request_timeout=2.0)
    except Exception as exc:
        log.warning("recommendations_bm25_search_failed", exc_info=exc)
        return []

    hits = response.get("hits", {}).get("hits", []) if isinstance(response, dict) else []
    return hits


def _merge_os_hits(
    knn_hits: Sequence[Dict[str, Any]],
    bm25_hits: Sequence[Dict[str, Any]],
) -> List[OSCandidate]:
    candidates: Dict[str, OSCandidate] = {}

    def upsert(hit: Dict[str, Any], source_label: str) -> OSCandidate:
        raw_id = hit.get("_id")
        if not raw_id:
            raise KeyError
        video_id = str(raw_id)
        candidate = candidates.get(video_id)
        if not candidate:
            source_doc = hit.get("_source") or {}
            candidate = OSCandidate(
                video_id=video_id,
                document=source_doc,
                embedding=None,
                sources=[source_label],
            )
            candidates[video_id] = candidate
        else:
            if source_label not in candidate.sources:
                candidate.sources.append(source_label)
            source_doc = hit.get("_source") or {}
            if source_doc:
                missing_keys = {k: v for k, v in source_doc.items() if k not in candidate.document}
                if missing_keys:
                    candidate.document.update(missing_keys)
        return candidate

    for hit in knn_hits:
        try:
            candidate = upsert(hit, "knn")
        except KeyError:
            continue
        try:
            candidate.cosine_score = float(hit.get("_score") or 0.0)
        except Exception:
            candidate.cosine_score = 0.0

    for hit in bm25_hits:
        try:
            candidate = upsert(hit, "bm25")
        except KeyError:
            continue
        try:
            candidate.bm25_score = float(hit.get("_score") or 0.0)
        except Exception:
            candidate.bm25_score = 0.0

    return list(candidates.values())


def _score_os_candidates(candidates: Sequence[OSCandidate]) -> None:
    cosine_norms = _normalize_scores([candidate.cosine_score for candidate in candidates])
    bm25_norms = _normalize_scores([candidate.bm25_score for candidate in candidates])

    for candidate, cos_norm, bm_norm in zip(candidates, cosine_norms, bm25_norms):
        candidate.cosine_norm = cos_norm
        candidate.bm25_norm = bm_norm
        candidate.lane_score = (
            OS_COSINE_WEIGHT * candidate.cosine_norm
            + OS_BM25_WEIGHT * candidate.bm25_norm
        )


def _hydrate_embeddings_for_pool(client: OpenSearch, pool: List[OSCandidate]) -> None:
    pending: Dict[str, OSCandidate] = {c.video_id: c for c in pool if c.embedding is None}
    if not pending:
        return
    try:
        response = client.mget(
            index=VIDEOS_INDEX,
            body={"ids": list(pending.keys())},
            _source=["embedding"],
            request_timeout=2.0,
        )
    except Exception as exc:
        log.warning("recommendations_pool_mget_failed", exc_info=exc)
        return

    docs = response.get("docs", []) if isinstance(response, dict) else []
    hydrated = 0

    for doc in docs:
        if not doc or not doc.get("found"):
            continue
        vid = str(doc.get("_id"))
        cand = pending.get(vid)
        if not cand or cand.embedding is not None:
            continue

        vec = _safe_get_embedding(doc.get("_source") or {})
        if vec is None or any(not math.isfinite(x) for x in vec):
            continue

        cand.embedding = vec
        hydrated += 1

    if hydrated and hydrated < len(pending):
        log.debug(
            "recommendations_pool_mget_partial",
            extra={"requested": len(pending), "hydrated": hydrated},
        )


def _candidate_similarity(a: OSCandidate, b: OSCandidate) -> float:
    if a.embedding and b.embedding:
        similarity = cosine_similarity(a.embedding, b.embedding)
        if similarity < 0:
            return 0.0
        return min(similarity, 1.0)
    return 0.0


def run_opensearch_lane(seed_bundle: SeedBundle) -> OSLaneResult:
    client = get_client()
    if not client:
        log.info("recommendations_skip_os_lane: missing_opensearch_client")
        return OSLaneResult(shortlist=[], candidates=[], bm25_terms=[])

    ensure_indexes()

    bm25_terms = _build_bm25_terms(seed_bundle)
    exclude_ids = [str(h.video_id) for h in seed_bundle.history]

    knn_hits: List[Dict[str, Any]] = []
    if seed_bundle.user_embedding:
        knn_hits = _execute_knn_search(client, seed_bundle.user_embedding, exclude_ids)

    bm25_hits: List[Dict[str, Any]] = []
    bm25_hits = _execute_bm25_search(client, bm25_terms, exclude_ids)

    if not knn_hits and not bm25_hits:
        log.info("recommendations_os_lane_empty_results")
        return OSLaneResult(shortlist=[], candidates=[], bm25_terms=bm25_terms)

    candidates = _merge_os_hits(knn_hits, bm25_hits)
    if not candidates:
        return OSLaneResult(shortlist=[], candidates=[], bm25_terms=bm25_terms)

    _score_os_candidates(candidates)

    candidates_sorted = sorted(candidates, key=lambda item: item.lane_score, reverse=True)

    shortlist_limit = min(OS_WITHIN_LANE_SHORTLIST, len(candidates_sorted))
    if shortlist_limit == 0:
        return OSLaneResult(shortlist=[], candidates=candidates_sorted, bm25_terms=bm25_terms)

    pool_size = min(
        len(candidates_sorted),
        max(shortlist_limit, OS_MMR_POOL_MULTIPLIER * shortlist_limit),
    )
    pool = candidates_sorted[:pool_size]

    _hydrate_embeddings_for_pool(client, pool)

    shortlist = max_marginal_relevance(
        pool,
        score_fn=lambda candidate: candidate.lane_score,
        similarity_fn=_candidate_similarity,
        limit=shortlist_limit,
        lambda_weight=MMR_LAMBDA,
    )

    return OSLaneResult(shortlist=shortlist, candidates=candidates_sorted, bm25_terms=bm25_terms)