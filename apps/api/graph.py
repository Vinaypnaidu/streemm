# apps/api/graph.py
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, Optional

from neo4j import GraphDatabase, Driver
from config import settings

# silence verbose driver logs/notifications
logging.getLogger("neo4j").setLevel(logging.WARNING)
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

log = logging.getLogger("graph")

_driver: Optional[Driver] = None
_constraints_ready = False


def get_driver() -> Optional[Driver]:
    global _driver
    if _driver:
        return _driver
    uri = (settings.neo4j_uri or "").strip()
    if not uri:
        log.info("Neo4j disabled (NEO4J_URI empty)")
        return None
    try:
        _driver = GraphDatabase.driver(
            uri,
            auth=(settings.neo4j_username or "", settings.neo4j_password or ""),
        )
        _driver.verify_connectivity()
        log.info("Neo4j connected: %s", uri)
        return _driver
    except Exception as e:
        log.warning("Neo4j connection failed: %s", e)
        _driver = None
        return None


def ensure_constraints() -> None:
    global _constraints_ready
    if _constraints_ready:
        return
    drv = get_driver()
    if not drv:
        return
    cypher = [
        # Uniqueness on IDs
        "CREATE CONSTRAINT video_id_unique IF NOT EXISTS FOR (v:Video) REQUIRE v.id IS UNIQUE",
        "CREATE CONSTRAINT topic_id_unique IF NOT EXISTS FOR (t:Topic) REQUIRE t.id IS UNIQUE",
        "CREATE CONSTRAINT entity_id_unique IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE",
        # # Required canonical_name properties; disabled for now as they need enterprise version
        # "CREATE CONSTRAINT topic_canonical_required IF NOT EXISTS FOR (t:Topic) REQUIRE t.canonical_name IS NOT NULL",
        # "CREATE CONSTRAINT entity_canonical_required IF NOT EXISTS FOR (e:Entity) REQUIRE e.canonical_name IS NOT NULL",
    ]
    try:
        with drv.session(database=settings.neo4j_database or "neo4j") as sess:
            for stmt in cypher:
                sess.run(stmt)
        _constraints_ready = True
        log.info("Neo4j constraints ensured")
    except Exception as e:
        log.warning("Failed to ensure constraints: %s", e)


def _merge_video(sess, video_id: str) -> None:
    sess.run("MERGE (:Video {id: $id})", id=video_id)


def _merge_topic(sess, topic_id: str, canonical_name: str) -> None:
    # Keep canonical_name if present; set on create or if missing
    sess.run(
        """
        MERGE (t:Topic {id: $id})
        ON CREATE SET t.canonical_name = $cn
        SET t.canonical_name = coalesce(t.canonical_name, $cn)
        """,
        id=topic_id,
        cn=canonical_name,
    )


def _merge_entity(sess, entity_id: str, canonical_name: str) -> None:
    # Keep canonical_name if present; set on create or if missing
    sess.run(
        """
        MERGE (e:Entity {id: $id})
        ON CREATE SET e.canonical_name = $cn
        SET e.canonical_name = coalesce(e.canonical_name, $cn)
        """,
        id=entity_id,
        cn=canonical_name,
    )


def _merge_has_topic(sess, video_id: str, topic_id: str, prominence: float) -> None:
    sess.run(
        """
        MATCH (v:Video {id: $vid})
        MATCH (t:Topic {id: $tid})
        MERGE (v)-[r:HAS_TOPIC]->(t)
        SET r.prominence = $p
        """,
        vid=video_id,
        tid=topic_id,
        p=float(prominence),
    )


def _merge_has_entity(sess, video_id: str, entity_id: str, importance: float) -> None:
    sess.run(
        """
        MATCH (v:Video {id: $vid})
        MATCH (e:Entity {id: $eid})
        MERGE (v)-[r:HAS_ENTITY]->(e)
        SET r.importance = $w
        """,
        vid=video_id,
        eid=entity_id,
        w=float(importance),
    )


def sync_video(
    video_id: str,
    topics: Iterable[Dict[str, Any]],
    entities: Iterable[Dict[str, Any]],
) -> None:
    """
    topics: items with {id, canonical_name, prominence}
    entities: items with {id, canonical_name, importance}
    Applies thresholds; best-effort logging; no exceptions on failure.
    """
    drv = get_driver()
    if not drv:
        log.info("Neo4j unavailable; skipping graph sync")
        return

    ensure_constraints()

    p_th = float(getattr(settings, "neo4j_prominence_insert_th", 0.50))
    w_th = float(getattr(settings, "neo4j_importance_insert_th", 0.50))

    topics = list(topics or [])
    entities = list(entities or [])

    # Filter by confidence thresholds
    t_keep = [
        t for t in topics
        if float(t.get("prominence", 0.0)) >= p_th
           and t.get("id") and (t.get("canonical_name") or "").strip()
    ]
    e_keep = [
        e for e in entities
        if float(e.get("importance", 0.0)) >= w_th
           and e.get("id") and (e.get("canonical_name") or "").strip()
    ]

    try:
        with drv.session(database=settings.neo4j_database or "neo4j") as sess:
            _merge_video(sess, video_id)

            for t in t_keep:
                _merge_topic(sess, t["id"], (t["canonical_name"] or "").strip().lower())
                _merge_has_topic(sess, video_id, t["id"], float(t["prominence"]))

            for e in e_keep:
                _merge_entity(sess, e["id"], (e["canonical_name"] or "").strip().lower())
                _merge_has_entity(sess, video_id, e["id"], float(e["importance"]))

        log.info(
            "graph_sync_ok video=%s topics=%d entities=%d skipped_topics=%d skipped_entities=%d",
            video_id, len(t_keep), len(e_keep),
            len(topics) - len(t_keep),
            len(entities) - len(e_keep),
        )
    except Exception as exc:
        log.warning("graph_sync_failed video=%s error=%s", video_id, exc)


def delete_video(video_id: str, *, prune_orphans: bool = True) -> None:
    drv = get_driver()
    if not drv:
        return
    try:
        with drv.session(database=settings.neo4j_database or "neo4j") as sess:
            # Delete the video node and its relationships
            sess.run(
                """
                MATCH (v:Video {id: $vid})
                DETACH DELETE v
                """,
                vid=video_id,
            )
            if prune_orphans:
                # Remove Topics with no incoming HAS_TOPIC from any Video
                sess.run(
                    """
                    MATCH (t:Topic)
                    WHERE NOT EXISTS( ()-[:HAS_TOPIC]->(t) )
                    DETACH DELETE t
                    """
                )
                # Remove Entities with no incoming HAS_ENTITY from any Video
                sess.run(
                    """
                    MATCH (e:Entity)
                    WHERE NOT EXISTS( ()-[:HAS_ENTITY]->(e) )
                    DETACH DELETE e
                    """
                )
        log.info("graph_delete_ok video=%s", video_id)
    except Exception as exc:
        log.warning("graph_delete_failed video=%s error=%s", video_id, exc)