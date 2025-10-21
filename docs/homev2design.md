# Video Intelligence – Design Doc

## 1) Data Spec

**Entities –** named things mentioned in the video (people, orgs, products, places, ideas). De-duplicated by `canonical_name`; `importance` expresses how central the entity is to this video.

```json
{ "id": "uuid", "name": "string", "canonical_name": "string", "importance": 0.0 }
```

**Topics –** concrete subjects/skills covered by the video (e.g., "pasta making", "gradient descent"). `prominence` reflects share of focus/time.

```json
{ "id": "uuid", "name": "string", "canonical_name": "string", "prominence": 0.0 }
```

**Tags –** searchable labels derived from topics, entities, and overall content nature; mix domain/field, format/style, and key attributes for discovery.

```json
{ "id": "uuid", "name": "string", "canonical_name": "string", "weight": 0.0 }
```

**Metadata –** minimal coarse descriptors used for filtering and feed rules.

```json
{
  "content_type": "entertainment|educational|review|interview|news|lifestyle|other",
  "language": "en"
}
```

**Summary –** summary of the video (2–4 sentences max) used in UI and as input to embedding.

```json
{ "short_summary": "string" }
```

**Embeddings –** single video-level vector powering semantic recall and similarity-based recommendations.

```json
{ "model": "string", "dim": 0, "video": [0.0] }
```

---

## 2) Embedding Document (what we embed, ~250 tokens)

```
Title: {title}

Description: {source description}

Summary: {short_summary}

Topics: {topic1} | {topic2} | {topic3}
Entities: {name1} | {name2} | {name3}
Tags: {tag1} | {tag2} | {tag3}

Metadata: content_type={one of enum}, language={en}
```

---

## 3) Storage Plan

### 3.1 Postgres (source of truth; normalized & minimal)

* **videos**: `id PK`, `title`, `description`, `duration_s`, `language`, `content_type`, …(existing cols)
* **video_summary**: `video_id PK/FK`, `short_summary TEXT`
* **topics**: `id PK`, `name`, `canonical_name UNIQUE`
* **video_topics**: `video_id FK`, `topic_id FK`, `prominence NUMERIC(3,2)`, `UNIQUE(video_id, topic_id)`
* **entities**: `id PK`, `name`, `canonical_name UNIQUE`
* **video_entities**: `video_id FK`, `entity_id FK`, `importance NUMERIC(3,2)`, `UNIQUE(video_id, entity_id)`
* **tags**: `id PK`, `name`, `canonical_name UNIQUE`
* **video_tags**: `video_id FK`, `tag_id FK`, `weight NUMERIC(3,2)`, `UNIQUE(video_id, tag_id)`

**Indexes (lean, practical)**

* `topics(canonical_name)` **UNIQUE** (btree)
* `entities(canonical_name)` **UNIQUE** (btree)
* `tags(canonical_name)` **UNIQUE** (btree)
* `video_topics(video_id, topic_id)` **UNIQUE** and `video_topics(topic_id, video_id)` (btree)
* `video_entities(video_id, entity_id)` **UNIQUE** and `video_entities(entity_id, video_id)` (btree)
* `video_tags(video_id, tag_id)` **UNIQUE** and `video_tags(tag_id, video_id)` (btree)

### 3.2 OpenSearch (per-video doc; denormalized; BM25 + stored embeddings)

(Include index-only fields + vector; **do not index summary**.)

```json
{
  "id": "uuid",
  "title": "string",
  "description": "string",
  "content_type": "string",
  "duration_s": 0,
  "language": "en",

  "entities": [
    { "name": "string", "canonical_name": "string", "importance": 0.0 }
  ],
  "topics": [
    { "name": "string", "canonical_name": "string", "prominence": 0.0 }
  ],
  "tags": [
    { "name": "string", "canonical_name": "string", "weight": 0.0 }
  ],

  "embedding": [0.0]
}
```

*Mapping hints:*

* `title`, `description` as `text` **with** `.keyword` subfields (for exact filters/aggs).
* `entities`, `topics`, and `tags` as **`nested`** objects; within each, map `name` as `text` + `.keyword`, `canonical_name` as `keyword`, numeric weights as `float`.
* `embedding` as a plain `float` array stored in `_source` (not indexed; used for cosine reranking only).

**BM25 fields (and boosts):**
`title^3, description^2, tags.name^2, entities.name^2, topics.name^1`

### 3.3 Neo4j Graph Layer (bipartite, lean)

*IDs reuse Postgres primary keys; fetch display names from Postgres/OS at render-time.*

**Node labels (properties)**

* `Video { id: UUID }`
* `Topic { id: UUID, canonical_name: String }`
* `Entity { id: UUID, canonical_name: String }`
* `Tag { id: UUID, canonical_name: String }`

**Relationships (properties)**

* `(:Video)-[:HAS_TOPIC { prominence: Float }]->(:Topic)`
* `(:Video)-[:HAS_ENTITY { importance: Float }]->(:Entity)`
* `(:Video)-[:HAS_TAG { weight: Float }]->(:Tag)`

**Constraints / required properties**

* Uniqueness on `Video.id`, `Topic.id`, `Entity.id`, `Tag.id`
* Property existence: `Topic.canonical_name`, `Entity.canonical_name`, `Tag.canonical_name` **required**
* Property existence: `HAS_TOPIC.prominence`, `HAS_ENTITY.importance`, `HAS_TAG.weight` **required**

---

## 4) Extraction & Indexing Flow

1. **Extract (LLM/agents):** entities, topics, **tags**, short_summary, metadata.
2. **Persist to Postgres (upserts):**
   `video_summary.short_summary`;
   `topics` + `video_topics(prominence)`;
   `entities` + `video_entities(importance)`;
   `tags` + `video_tags(weight)`;
   update `videos(content_type|duration_s|language|description)` as needed.
3. **Sync to Neo4j:** upsert `Video/Topic/Entity/Tag` nodes and `HAS_TOPIC/HAS_ENTITY/HAS_TAG` edges.
4. **Build embedding text** using the template (include **description + summary + tags/topics/entities**).
5. **Embed** → single video-level vector.
6. **Index in OpenSearch** (upsert per video): `id`, `title`, `description`, `content_type`, `duration_s`, `language`,
   `entities[]`, `topics[]`, `tags[]`, `embedding`.
   *(Summary is **not** indexed in OS; embedding-only + UI.)*

---

## 5) Recommendations – Two-Lane

**Why two lanes:**
We run **OpenSearch** and **Graph** independently because they optimize *different* objectives. OS excels at **similarity** (semantic + keyword). Graph excels at **adjacency/serendipity** (nearby-but-new). Mixing recall or scores blurs those goals; instead we keep lanes separate, **dedupe in favor of OS** (freeing Graph capacity for novel picks), enforce a **70/30** blend, then do a single global MMR for a pleasant final order.

### 0) Knobs (defaults)

* **Target N:** 100
* **History depth:** last **50** watched videos
* **Lane quotas:** OS = **70**, Graph = **30** (redistribute if a lane under-fills)
* **OS recall caps:** **BM25@500**
* **Graph recall caps:** **Random walks → all unique videos, early dedupe, then filter**
* **Within-lane MMR:** λ = **0.7** (diversify by topics/entities/tags via Jaccard similarity)
* **OS scoring weights:** cosine = **0.5**, BM25 = **0.5**

### 1) Build user signal

* **User vector `u`:** recency-weighted mean of the last **50** `video_vector`s (normalize).
* **OS lane seeds:** top topics, entities, and tags from those videos with weights (`prominence` / `importance` / `weight`), specifically **5 topics**, **15 entities**, and **20 tags**.
* **Graph lane seeds:** top entities and tags only, specifically **15 entities** and **20 tags**.

### 2) OS lane (OpenSearch: BM25 recall + semantic rerank)

1. **Recall (BM25-first):** BM25(500) using seed names over **BM25 fields**:
  `title^3, description^2, tags.name^2, entities.name^2, topics.name^1`.
2. **Semantic reranking:** For the recalled set only, compute cosine similarity between the **user vector `u`** and each candidate's embedding; normalize cosine and BM25 to [0,1] → `cos_norm`, `bm25_norm`.
3. **Lane score:** `OS_score = 0.50·cos_norm + 0.50·bm25_norm`; sort by this score.
4. **Within-lane MMR** (λ = 0.7), similarity = **Jaccard over entities + tags**; keep shortlist ≈ **2× OS lane quota** (default 140).

### 3) Graph lane (Neo4j: Random Walk-based adjacency/serendipity)

1. **Recall (Random Walks):**

   * Run random walks using **`gds.randomWalk.stream`** from seed nodes (entities and tags only).
   * **Walk parameters:** 
     - Seeds: **15 entities** + **20 tags** = **35 seeds**
     - `walkLength`: **7** steps
     - `walksPerNode`: **50** walks per seed
     - `relationshipWeightProperty`: use `importance`/`weight` from edges for biased walks
     - **Total walks:** 35 seeds × 50 = **1,750 walks**
   * Count video visit frequencies across all walks.
   * Collect all unique videos with their visit counts.

2. **Early deduplication:**

   * Remove any videos that appear in the **OS lane's top 140** (2× OS quota).
   * Rationale: OS lane already captured semantically similar content; graph lane's job is to surface adjacent-but-different content.

3. **Cosine similarity filtering:**

   * For each remaining candidate, compute cosine similarity with user vector `u`.
   * **Filter:** keep only candidates with cosine similarity ∈ **[0.1, 0.9]** (lenient bounds as tuning knobs).
     - Lower bound (0.1): exclude completely unrelated content
     - Upper bound (0.9): exclude very similar content

4. **Lane score:** 
   ```
   Graph_score = cosine_norm
   ```
   Rationale: Random walks provide connectivity (visit frequency), early dedupe ensures novelty from OS lane. Among connected and novel candidates, cosine similarity ranks by relevance/quality—take the best matches within the graph-adjacent space.

5. **Within-lane MMR** (λ = 0.7); keep shortlist ≈ **60**.

### 4) Cross-lane dedupe (already handled)

Early deduplication in the graph lane (step 2) removes overlap with OS lane's top 140. No additional cross-lane deduping needed.
*(Optionally tag any OS items that also appeared in graph walks with `graph_support=true` for analytics.)*

### 5) Quota fill (70/30) + backfill

Take **70** from the OS shortlist and **30** from the Graph shortlist. If a lane under-fills, backfill from the other lane's next best.

### 6) Global MMR (final ordering only)

Run one global MMR across the **100** selected videos to interleave and diversify (use lane scores as relevance; λ = 0.7, similarity = **Jaccard over entities + tags**). **Preserve the 70/30 counts**—this step only reorders.

### 7) Explanations

* **OS pick:** "Semantic match to your history; aligns with **{Topic/Entity/Tag}**."
* **Graph pick:** "Discovered through your interests in **{Seed}**—a fresh take you might enjoy."

### 8) Useful counters (to tune later)

Lane CTRs, under-fill rates, early dedupe overlap (how many graph candidates removed by OS), post-MMR diversity by topics/entities/tags, walk parameter sensitivity (walkLength, walksPerNode), cosine bound effectiveness, visit count distribution from walks.