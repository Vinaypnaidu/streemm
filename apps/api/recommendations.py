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
from graph import get_driver as get_neo4j_driver, ensure_constraints as ensure_graph_constraints
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

# Recommendation configuration
HISTORY_DEPTH = 50
RECENCY_HALF_LIFE_DAYS = 21

MAX_TAG_SEEDS = 20
MAX_ENTITY_SEEDS = 15
MAX_TOPIC_SEEDS = 5

TARGET_TOTAL_RECOMMENDATIONS = 100
OS_LANE_QUOTA = 70
GRAPH_LANE_QUOTA = 30
MMR_LAMBDA = 0.7

# OpenSearch lane tuning
OS_BM25_RECALL_K = 500
OS_COSINE_WEIGHT = 0.5
OS_BM25_WEIGHT = 0.5

# Graph lane tuning
GRAPH_WALK_LENGTH = 7
GRAPH_WALKS_PER_NODE = 50
GRAPH_COSINE_MIN = 0.1
GRAPH_COSINE_MAX = 0.9

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
    "embedding",
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
    id: Optional[UUID] = None


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


@dataclass
class GraphCandidate:
    video_id: str
    visit_count: int = 0
    document: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[List[float]] = None
    cosine_score: Optional[float] = None
    cosine_norm: float = 0.0
    lane_score: float = 0.0
    sources: List[str] = field(default_factory=list)


@dataclass
class GraphLaneResult:
    shortlist: List[GraphCandidate]
    candidates: List[GraphCandidate]


@dataclass
class UnifiedCandidate:
    video_id: str
    lane_score: float
    document: Dict[str, Any]
    lane_source: str


@dataclass
class RecommendationResult:
    video_ids: List[str]
    sources: Dict[str, str]
    os_count: int
    graph_count: int


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
            id=item.get("id"),
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
                "id": master.id,
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
        "_source": OS_SOURCE_FIELDS,
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


def _build_candidates_from_bm25(bm25_hits: Sequence[Dict[str, Any]]) -> List[OSCandidate]:
    candidates: List[OSCandidate] = []
    seen: Set[str] = set()
    for hit in bm25_hits:
        raw_id = hit.get("_id")
        if not raw_id:
            continue
        video_id = str(raw_id)
        if video_id in seen:
            continue
        seen.add(video_id)
        source_doc = hit.get("_source") or {}
        cand = OSCandidate(
            video_id=video_id,
            document=source_doc,
            embedding=_safe_get_embedding(source_doc),
            sources=["bm25"],
        )
        try:
            cand.bm25_score = float(hit.get("_score") or 0.0)
        except Exception:
            cand.bm25_score = 0.0
        candidates.append(cand)
    return candidates


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


def _candidate_similarity(a: OSCandidate, b: OSCandidate) -> float:
    """
    Jaccard similarity based on entities and tags.
    Faster than embedding-based similarity.
    """
    def to_tokens(doc: Dict[str, Any]) -> Set[str]:
        tokens: Set[str] = set()
        # Entities are stored as list[dict]
        for e in doc.get("entities", []) or []:
            if isinstance(e, dict):
                val = (e.get("canonical_name") or e.get("name") or "").strip()
                if val:
                    tokens.add(val.lower())
        # Tags are stored as list[dict]
        for t in doc.get("tags", []) or []:
            if isinstance(t, dict):
                val = (t.get("canonical_name") or t.get("name") or "").strip()
                if val:
                    tokens.add(val.lower())
        return tokens

    a_tokens = to_tokens(a.document)
    b_tokens = to_tokens(b.document)

    if not a_tokens or not b_tokens:
        return 0.0

    inter = len(a_tokens & b_tokens)
    union = len(a_tokens | b_tokens)
    if union <= 0:
        return 0.0
    return inter / union


def run_opensearch_lane(seed_bundle: SeedBundle) -> OSLaneResult:
    client = get_client()
    if not client:
        log.info("recommendations_skip_os_lane: missing_opensearch_client")
        return OSLaneResult(shortlist=[], candidates=[], bm25_terms=[])

    ensure_indexes()

    bm25_terms = _build_bm25_terms(seed_bundle)
    exclude_ids = [str(h.video_id) for h in seed_bundle.history]

    bm25_hits: List[Dict[str, Any]] = []
    bm25_hits = _execute_bm25_search(client, bm25_terms, exclude_ids)

    # BM25-first recall: if nothing is recalled, return early
    if not bm25_hits:
        log.info("recommendations_os_lane_empty_results")
        return OSLaneResult(shortlist=[], candidates=[], bm25_terms=bm25_terms)

    # Build candidate set from BM25 recall only
    candidates = _build_candidates_from_bm25(bm25_hits)
    if not candidates:
        return OSLaneResult(shortlist=[], candidates=[], bm25_terms=bm25_terms)

    # Compute cosine similarity against the user profile embedding when available
    # TODO: Consider vectorizing this step with numpy
    if seed_bundle.user_embedding:
        user_vec = [float(x) for x in seed_bundle.user_embedding]
        for cand in candidates:
            if cand.embedding:
                cand.cosine_score = cosine_similarity(user_vec, cand.embedding)
            else:
                cand.cosine_score = 0.0
    else:
        # No user embedding -> cosine contributes 0
        for cand in candidates:
            cand.cosine_score = 0.0

    _score_os_candidates(candidates)

    candidates_sorted = sorted(candidates, key=lambda item: item.lane_score, reverse=True)

    # Feed MMR with up to 4x lane quota candidates 
    pool_size = min(4 * OS_LANE_QUOTA, len(candidates_sorted))
    pool = candidates_sorted[:pool_size]

    # Select up to 2x lane quota via MMR 
    shortlist_limit = min(2 * OS_LANE_QUOTA, len(candidates_sorted))
    if shortlist_limit == 0:
        return OSLaneResult(shortlist=[], candidates=candidates_sorted, bm25_terms=bm25_terms)

    shortlist = max_marginal_relevance(
        pool,
        score_fn=lambda candidate: candidate.lane_score,
        similarity_fn=_candidate_similarity,
        limit=shortlist_limit,
        lambda_weight=MMR_LAMBDA,
    )

    return OSLaneResult(shortlist=shortlist, candidates=candidates_sorted, bm25_terms=bm25_terms)


def _graph_random_walk_stream(seed_bundle: SeedBundle) -> List[Dict[str, Any]]:
    """
    Runs random walks on a Cypher-projected graph using Entity+Tag seeds.
    Returns aggregated visit counts of visited Video nodes only.

    Output rows: { "id": str, "count": int }
    """
    drv = get_neo4j_driver()
    if not drv:
        log.info("graph_lane_skip: neo4j_unavailable")
        return []

    # Collect seed node ids (Entity + Tag) as strings
    seed_ids: List[str] = []
    for s in (seed_bundle.entities or []):
        if s.id:
            try:
                seed_ids.append(str(s.id))
            except Exception:
                pass
    for s in (seed_bundle.tags or []):
        if s.id:
            try:
                seed_ids.append(str(s.id))
            except Exception:
                pass

    # Deduplicate and enforce limits similar to OS usage (top-K already applied in seed bundle)
    seed_ids = list(dict.fromkeys(seed_ids))
    if not seed_ids:
        log.info("graph_lane_skip: empty_seeds")
        return []

    ensure_graph_constraints()

    graph_name = f"rec_walk_{int(datetime.now(timezone.utc).timestamp()*1000)}"

    visited: List[Dict[str, Any]] = []

    try:
        with drv.session() as sess:
            # TODO: Consider an hourly/daily precomputed projection to speed this up 
            # Build projection using native projection API
            sess.run(
                """
                CALL gds.graph.project(
                  $graphName,
                  ['Video', 'Tag', 'Entity'],
                  {
                    HAS_TAG: {
                      type: 'HAS_TAG',
                      orientation: 'UNDIRECTED',
                      properties: {
                        weight: {
                          property: 'weight',
                          defaultValue: 1.0
                        }
                      }
                    },
                    HAS_ENTITY: {
                      type: 'HAS_ENTITY',
                      orientation: 'UNDIRECTED',
                      properties: {
                        weight: {
                          property: 'importance',
                          defaultValue: 1.0
                        }
                      }
                    }
                  }
                )
                """,
                graphName=graph_name,
            )

            # Stream random walks, map nodeIds back, filter to Video, and aggregate counts in Cypher
            result = sess.run(
                """
                MATCH (s)
                WHERE (s:Entity OR s:Tag) AND s.id IN $seedIds
                WITH collect(id(s)) AS startNodes
                CALL gds.randomWalk.stream($graphName, {
                  sourceNodes: startNodes,
                  walkLength: $walkLength,
                  walksPerNode: $walksPerNode,
                  relationshipWeightProperty: 'weight'
                })
                YIELD nodeIds
                UNWIND nodeIds AS nodeId
                MATCH (v:Video)
                WHERE id(v) = nodeId AND v.id IS NOT NULL
                RETURN v.id AS id, count(*) AS count
                ORDER BY count DESC
                """,
                graphName=graph_name,
                seedIds=seed_ids,
                walkLength=GRAPH_WALK_LENGTH,
                walksPerNode=GRAPH_WALKS_PER_NODE,
            )
            for rec in result:
                try:
                    visited.append({
                        "id": rec["id"],
                        "count": int(rec["count"] or 0),
                    })
                except Exception:
                    continue
    except Exception as exc:
        log.warning("graph_lane_random_walk_failed", exc_info=exc)
    finally:
        try:
            with drv.session() as sess:
                sess.run("CALL gds.graph.drop($graphName)", graphName=graph_name)
        except Exception:
            pass

    return visited


def _graph_build_candidates_from_walks(
    walk_rows: Sequence[Dict[str, Any]],
    *,
    exclude_video_ids: Optional[Sequence[str]] = None,
) -> List[GraphCandidate]:
    """
    Convert aggregated walk rows {id, count} into GraphCandidate list.
    Excludes any videos present in exclude_video_ids.
    """
    if not walk_rows:
        return []

    excludes = set(str(x) for x in (exclude_video_ids or []))
    candidates: List[GraphCandidate] = []
    seen: Set[str] = set()
    for row in walk_rows:
        vid = str(row.get("id")) if row.get("id") is not None else ""
        if not vid or vid in seen or vid in excludes:
            continue
        seen.add(vid)
        try:
            cnt = int(row.get("count") or 0)
        except Exception:
            cnt = 0
        candidates.append(
            GraphCandidate(
                video_id=vid,
                visit_count=cnt,
                sources=["graph_walk"],
            )
        )
    return candidates


def run_graph_lane(
    seed_bundle: SeedBundle,
    os_top_ids: Optional[Sequence[str]] = None,
) -> GraphLaneResult:
    """
    Graph lane orchestrator (early phase):
    - Random walks from Entity+Tag seeds
    - Early exclusions: user history and OS top-140
    - Returns GraphLaneResult with candidates populated; scoring and MMR will follow
    """
    # Random walks and aggregation (already aggregated in Cypher)
    walk_rows = _graph_random_walk_stream(seed_bundle)

    # Build exclude list: user history + OS top-140
    exclude_history = [str(h.video_id) for h in (seed_bundle.history or [])]
    exclude_os = [str(x) for x in (os_top_ids or [])]
    exclude_ids = list({*exclude_history, *exclude_os})

    candidates = _graph_build_candidates_from_walks(walk_rows, exclude_video_ids=exclude_ids)

    log.info(
        "graph_lane_stage early_dedupe walk_rows=%d candidates_after_exclude=%d history_excludes=%d os_excludes=%d",
        len(walk_rows), len(candidates), len(exclude_history), len(exclude_os)
    )

    # Hydrate candidates with OS docs and embeddings
    _graph_hydrate_candidates_from_os(candidates)

    # Compute cosine similarity against user embedding when available
    filtered: List[GraphCandidate] = list(candidates)
    if seed_bundle.user_embedding:
        user_vec = [float(x) for x in seed_bundle.user_embedding]
        for cand in filtered:
            if cand.embedding:
                cand.cosine_score = cosine_similarity(user_vec, cand.embedding)
            else:
                cand.cosine_score = 0.0
        filtered = [c for c in filtered if GRAPH_COSINE_MIN <= float(c.cosine_score or 0.0) <= GRAPH_COSINE_MAX]
    else:
        # No user embedding -> skip cosine filtering
        for cand in filtered:
            cand.cosine_score = 0.0

    # Score lane using cosine similarity directly (higher is better)
    cosine_norms = _normalize_scores([c.cosine_score for c in filtered])
    for cand, cos_norm in zip(filtered, cosine_norms):
        cand.cosine_norm = cos_norm
        cand.lane_score = cos_norm

    # Sort by lane_score desc for deterministic pool
    filtered_sorted = sorted(filtered, key=lambda c: (c.lane_score, c.visit_count), reverse=True)

    # MMR shortlist ≈ 2x lane quota
    shortlist_limit = min(2 * GRAPH_LANE_QUOTA, len(filtered_sorted))
    if shortlist_limit <= 0:
        return GraphLaneResult(shortlist=[], candidates=filtered_sorted)

    shortlist = max_marginal_relevance(
        filtered_sorted,
        score_fn=lambda c: c.lane_score,
        similarity_fn=_candidate_similarity,
        limit=shortlist_limit,
        lambda_weight=MMR_LAMBDA,
    )

    return GraphLaneResult(shortlist=shortlist, candidates=filtered_sorted)


def _os_fetch_sources(video_ids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    if not video_ids:
        return {}
    client = get_client()
    if not client:
        return {}
    ensure_indexes()
    unique_ids = list(dict.fromkeys(str(x) for x in video_ids))
    try:
        response = client.mget(index=VIDEOS_INDEX, body={"ids": unique_ids})
    except Exception as exc:
        log.warning("graph_lane_os_mget_failed", exc_info=exc)
        return {}
    docs = response.get("docs", []) if isinstance(response, dict) else []
    out: Dict[str, Dict[str, Any]] = {}
    for doc in docs:
        if not doc or not doc.get("found"):
            continue
        vid = str(doc.get("_id"))
        source = doc.get("_source") or {}
        out[vid] = source
    return out


def _graph_hydrate_candidates_from_os(candidates: Sequence[GraphCandidate]) -> None:
    ids = [c.video_id for c in candidates]
    by_id = _os_fetch_sources(ids)
    for c in candidates:
        src = by_id.get(c.video_id) or {}
        c.document = src
        c.embedding = _safe_get_embedding(src)


def get_recommendations(
    db: Session,
    user_id: UUID,
    target_count: int = TARGET_TOTAL_RECOMMENDATIONS,
) -> RecommendationResult:
    """
    Orchestrate the two-lane recommendation system:
    - Run OS lane (70%) and Graph lane (30%)
    - Handle backfill if either lane under-delivers
    - Apply global MMR for final ordering while preserving lane counts
    - Attach lane-based source metadata
    """
    # Build user signal 
    seed_bundle = build_seed_bundle(db, user_id)

    # Run OS lane
    os_result = run_opensearch_lane(seed_bundle)
    os_shortlist = os_result.shortlist

    # Extract top IDs from OS lane for graph exclusion (top 2x quota = 140)
    os_top_ids = [c.video_id for c in os_shortlist[: 2 * OS_LANE_QUOTA]]

    # Run Graph lane with OS exclusions
    graph_result = run_graph_lane(seed_bundle, os_top_ids=os_top_ids)
    graph_shortlist = graph_result.shortlist

    # Determine lane quotas with backfill
    os_available = len(os_shortlist)
    graph_available = len(graph_shortlist)

    os_quota = OS_LANE_QUOTA
    graph_quota = GRAPH_LANE_QUOTA

    # Handle under-delivery and backfill
    if os_available < os_quota:
        shortfall = os_quota - os_available
        graph_quota = min(graph_quota + shortfall, graph_available)
        os_quota = os_available
    elif graph_available < graph_quota:
        shortfall = graph_quota - graph_available
        os_quota = min(os_quota + shortfall, os_available)
        graph_quota = graph_available

    # Select items from each lane
    os_selected = os_shortlist[:os_quota]
    graph_selected = graph_shortlist[:graph_quota]

    log.info(
        "recommendations_lane_selection os_quota=%d graph_quota=%d os_available=%d graph_available=%d",
        os_quota, graph_quota, os_available, graph_available,
    )

    # Build unified candidate pool for global MMR
    unified_pool: List[UnifiedCandidate] = []
    
    for c in os_selected:
        unified_pool.append(
            UnifiedCandidate(
                video_id=c.video_id,
                lane_score=c.lane_score,
                document=c.document,
                lane_source="os",
            )
        )
    
    for c in graph_selected:
        unified_pool.append(
            UnifiedCandidate(
                video_id=c.video_id,
                lane_score=c.lane_score,
                document=c.document,
                lane_source="graph",
            )
        )

    # Apply global MMR for final ordering using existing similarity function
    final_ordered = max_marginal_relevance(
        unified_pool,
        score_fn=lambda c: c.lane_score,
        similarity_fn=_candidate_similarity,
        limit=target_count,
        lambda_weight=MMR_LAMBDA,
    )

    # Build result with source tracking
    video_ids: List[str] = []
    sources: Dict[str, str] = {}

    for c in final_ordered:
        video_ids.append(c.video_id)
        sources[c.video_id] = c.lane_source

    # Count actual lane representation in final results
    final_os_count = sum(1 for s in sources.values() if s == "os")
    final_graph_count = sum(1 for s in sources.values() if s == "graph")

    log.info(
        "recommendations_final_blend total=%d os=%d graph=%d",
        len(video_ids), final_os_count, final_graph_count,
    )

    return RecommendationResult(
        video_ids=video_ids,
        sources=sources,
        os_count=final_os_count,
        graph_count=final_graph_count,
    )