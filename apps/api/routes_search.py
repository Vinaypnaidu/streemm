# apps/api/routes_search.py
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from db import get_db
from models import User, Video
from session import get_current_user
from search import get_client, ensure_indexes, VIDEOS_INDEX, TRANSCRIPTS_INDEX
from storage import build_thumbnail_key, build_public_url

router = APIRouter(prefix="/search", tags=["search"])
log = logging.getLogger("routes_search")


def _normalize_tokens(text: str) -> List[str]:
    """Lowercase the query and strip punctuation."""
    return [t for t in re.sub(r"[^\w\s']", " ", text.lower()).split() if t]


def _build_meta_query(q: str, limit: int, offset: int) -> Dict[str, Any]:
    """
    Build BM25 query for metadata search across title, description, entities, tags, and topics.
    Uses nested queries for structured fields with appropriate boost values.
    """
    return {
        "from": offset,
        "size": limit,
        "query": {
            "bool": {
                "should": [
                    {
                        "multi_match": {
                            "query": q,
                            "fields": ["title^2", "description^1"],
                            "type": "best_fields",
                        }
                    },
                    {
                        "nested": {
                            "path": "entities",
                            "score_mode": "max",
                            "query": {
                                "match": {
                                    "entities.name": {
                                        "query": q,
                                        "operator": "or",
                                    }
                                }
                            },
                            "boost": 2.0,
                        }
                    },
                    {
                        "nested": {
                            "path": "tags",
                            "score_mode": "max",
                            "query": {
                                "match": {
                                    "tags.name": {
                                        "query": q,
                                        "operator": "or",
                                    }
                                }
                            },
                            "boost": 1.0,
                        }
                    },
                    {
                        "nested": {
                            "path": "topics",
                            "score_mode": "max",
                            "query": {
                                "match": {
                                    "topics.name": {
                                        "query": q,
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
        "highlight": {
            "pre_tags": ["<em>"],
            "post_tags": ["</em>"],
            "fields": {
                "title": {},
                "description": {},
                "entities.name": {},
                "tags.name": {},
                "topics.name": {},
            },
        },
    }


@router.get("")
def search(
    q: str = Query(..., min_length=1),
    limit_meta: int = 10,
    offset_meta: int = 0,
    limit_transcript: int = 10,
    offset_transcript: int = 0,
    lang: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    client = get_client()
    if not client:
        return {
            "search_ok": False,
            "meta": {"items": [], "estimated_total": 0, "next_offset": None},
            "transcript": {"items": [], "estimated_total": 0, "next_offset": None},
        }

    ensure_indexes()

    tokens = _normalize_tokens(q)
    word_count = len(tokens)
    full_phrase = " ".join(tokens)

    # --------------------
    # Metadata search
    # --------------------
    meta_items: List[Dict] = []
    meta_est_total = 0
    meta_next_offset: Optional[int] = None
    try:
        meta_limit = max(1, min(100, limit_meta))
        meta_offset = max(0, offset_meta)
        body = _build_meta_query(q, meta_limit, meta_offset)
        res_meta = client.search(index=VIDEOS_INDEX, body=body)
        hits = res_meta.get("hits", {}).get("hits", [])
        for h in hits:
            src = h.get("_source", {})
            highlight = h.get("highlight") or {}
            title_html = highlight.get("title", [src.get("title") or ""])
            desc_html = highlight.get("description", [src.get("description") or ""])
            meta_items.append(
                {
                    "video_id": h.get("_id"),
                    "title_html": (
                        title_html[0] if title_html else (src.get("title") or "")
                    ),
                    "description_html": (
                        desc_html[0] if desc_html else (src.get("description") or "")
                    ),
                    "short_summary": src.get("short_summary"),
                    "thumbnail_url": src.get("thumbnail_url"),
                    "created_at": src.get("created_at"),
                    "duration_seconds": src.get("duration_seconds"),
                    "score": h.get("_score"),
                }
            )
        total_meta = res_meta.get("hits", {}).get("total", {})
        meta_est_total = int(total_meta.get("value", 0))
        meta_next_offset = (
            (meta_offset + meta_limit)
            if (meta_est_total > meta_offset + meta_limit)
            else None
        )
    except Exception as e:
        log.error(f"Metadata search failed: {e}")

    # --------------------
    # Transcript search
    # --------------------
    tr_items: List[Dict] = []
    tr_est_total = 0
    tr_next_offset: Optional[int] = None
    first_by_video: Dict[str, Tuple[float, Dict]] = {}

    # Only search transcripts if we have at least 3 words
    if word_count >= 3:
        try:
            tr_limit = max(1, min(1000, limit_transcript))
            tr_offset = max(0, offset_transcript)

            # Step 1: Try exact phrase match first (with minimal slop for word order tolerance)
            exact_body: Dict[str, Any] = {
                "query": {
                    "bool": {
                        "must": [
                            {
                                "match_phrase": {
                                    "text": {
                                        "query": full_phrase,
                                        "slop": 0,  # Exact phrase match
                                    }
                                }
                            }
                        ]
                    }
                },
                "highlight": {
                    "pre_tags": ["<em>"],
                    "post_tags": ["</em>"],
                    "fields": {
                        "text": {
                            "number_of_fragments": 1,
                            "fragment_size": 180,
                        }
                    },
                },
            }
            if lang:
                exact_body["query"]["bool"].setdefault("filter", []).append(
                    {"term": {"lang": lang}}
                )

            res_tr = client.search(
                index=TRANSCRIPTS_INDEX,
                from_=tr_offset,
                size=tr_limit,
                body=exact_body,
            )

            total_tr = res_tr.get("hits", {}).get("total", {})
            exact_hits_count = int(total_tr.get("value", 0))

            # Step 2: If no exact matches, fall back to fuzzy matching
            if exact_hits_count == 0:
                log.info(
                    f"No exact matches for '{full_phrase}', falling back to fuzzy match"
                )

                # Calculate allowed mismatches based on word count
                # 4-5 words: allow 1 word wrong/missing/extra (atleast 70% match)
                # 6+ words: allow 2 words wrong/missing/extra (atleast 65% match)
                if word_count == 4:
                    minimum_should_match = "75%"
                elif word_count >= 5:
                    minimum_should_match = "60%"
                else:  # word_count == 3
                    minimum_should_match = "100%"

                fuzzy_body: Dict[str, Any] = {
                    "query": {
                        "bool": {
                            "must": [
                                {
                                    "match": {
                                        "text": {
                                            "query": full_phrase,
                                            "operator": "or",
                                            "minimum_should_match": minimum_should_match,
                                        }
                                    }
                                }
                            ]
                        }
                    },
                    "highlight": {
                        "pre_tags": ["<em>"],
                        "post_tags": ["</em>"],
                        "fields": {
                            "text": {
                                "number_of_fragments": 1,
                                "fragment_size": 180,
                            }
                        },
                    },
                }
                if lang:
                    fuzzy_body["query"]["bool"].setdefault("filter", []).append(
                        {"term": {"lang": lang}}
                    )

                res_tr = client.search(
                    index=TRANSCRIPTS_INDEX,
                    from_=tr_offset,
                    size=tr_limit,
                    body=fuzzy_body,
                )

            # Process hits and group by video (keep earliest match per video)
            hits_tr = res_tr.get("hits", {}).get("hits", [])
            for h in hits_tr:
                src = h.get("_source", {})
                vid = src.get("video_id")
                if not vid:
                    continue
                start = float(src.get("start_seconds") or 0.0)
                if vid not in first_by_video or start < first_by_video[vid][0]:
                    first_by_video[vid] = (start, h)

            # Fetch video metadata for matched videos
            video_ids = list(first_by_video.keys())
            if video_ids:
                rows = db.query(Video).filter(Video.id.in_(video_ids)).all()
                info: Dict[str, Dict] = {}
                for v in rows:
                    thumb_url = build_public_url(build_thumbnail_key(str(v.id)))
                    info[str(v.id)] = {
                        "title": (v.title or "").strip() or v.original_filename,
                        "thumbnail_url": thumb_url,
                    }
                for vid, (start, h) in first_by_video.items():
                    src = h.get("_source", {})
                    highlight = h.get("highlight") or {}
                    snippet = highlight.get("text", [src.get("text") or ""])
                    tr_items.append(
                        {
                            "video_id": vid,
                            "title": info.get(vid, {}).get("title", ""),
                            "thumbnail_url": info.get(vid, {}).get("thumbnail_url"),
                            "progress_seconds": start,
                            "snippet_html": (
                                snippet[0] if snippet else src.get("text") or ""
                            ),
                        }
                    )

            total_tr = res_tr.get("hits", {}).get("total", {})
            tr_est_total = int(total_tr.get("value", 0))
            tr_next_offset = (
                (tr_offset + tr_limit)
                if (tr_est_total > tr_offset + tr_limit)
                else None
            )
        except Exception as e:
            log.error(f"Transcript search failed: {e}")

    return {
        "search_ok": True,
        "meta": {
            "items": meta_items,
            "estimated_total": meta_est_total,
            "next_offset": meta_next_offset,
        },
        "transcript": {
            "items": tr_items,
            "estimated_total": tr_est_total,
            "next_offset": tr_next_offset,
        },
    }
