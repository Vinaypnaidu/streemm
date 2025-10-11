# Video Intelligence MVP — Final Design Doc

## 1) Frozen Data Spec (lean, with 1–2 line descriptions)

**Entities —** named things mentioned in the video (people, orgs, products, places, ideas). De-duplicated by `canonical_name`; `importance` expresses how central the entity is to this video.

```json
{ "id": "uuid", "name": "string", "canonical_name": "string", "importance": 0.0 }
```

*Note:* `type` is **index-only** (LLM-generated) → used in embedding + OpenSearch, **not** in DB.

**Topics —** concrete subjects/skills covered by the video (e.g., “pasta making”, “gradient descent”). `prominence` reflects share of focus/time.

```json
{ "id": "uuid", "name": "string", "canonical_name": "string", "prominence": 0.0 }
```

*Note:* `category` is **index-only** (LLM-generated) → embedding + OpenSearch only.

**Chapters —** ultra-light, ordered outline of the video’s flow (one-liners; no timestamps). Stored per video as an array (embedding-only; not indexed in OS).

```json
{ "chapters": ["string", "string", "string"] }
```

**Tags —** searchable labels derived from topics/entities/attributes; user-facing indexing sugar. `weight` is confidence/usefulness.

```json
{ "tag": "string", "weight": 0.0 }
```

**Metadata —** minimal coarse descriptors used for filtering and feed rules (no long text).

```json
{
  "content_type": "tutorial|review|interview|vlog|documentary|news|discussion|educational|presentation|entertainment|sports|other",
  "duration_s": 0.0,
  "language": "en"
}
```

**Summary —** summary of the video (2–4 sentences max) used in UI and as input to embedding.

```json
{ "short_summary": "string" }
```

**Embeddings —** single video-level vector powering semantic recall and similarity-based recommendations.

```json
{ "model": "string", "dim": 0, "video": [0.0] }
```

---

## 2) Embedding Document (what we embed, ≤ ~600 tokens)

```
Title: {title}

Description: {source description}

Summary: {short_summary}

Chapters:
- {chapter 1}
- {chapter 2}
- {chapter 3}

Topics: {topic1} | {topic2} | {topic3}           // may include category inline, e.g., "Pasta making [cooking_food]"
Entities: {name1 (person)} | {name2 (product)}   // include entity type inline

Tags: {tag1}, {tag2}, {tag3}

Metadata: content_type={tutorial|...}, language={en}
```

---

## 3) Storage Plan

### 3.1 Postgres (source of truth; normalized & minimal)

* **videos**: `id PK`, `title`, `description`, `duration_s`, `language`, `content_type`, …(existing cols)
* **video_summary**: `video_id PK/FK`, `short_summary TEXT`
* **video_chapters**: `video_id PK/FK`, `chapters TEXT[]`  ← one row per video (embedding-only)
* **topics**: `id PK`, `name`, `canonical_name UNIQUE`
* **video_topics**: `video_id FK`, `topic_id FK`, `prominence NUMERIC(3,2)`, `UNIQUE(video_id, topic_id)`
* **entities**: `id PK`, `name`, `canonical_name UNIQUE`
* **video_entities**: `video_id FK`, `entity_id FK`, `importance NUMERIC(3,2)`, `UNIQUE(video_id, entity_id)`
* **video_tags**: `video_id FK`, `tag TEXT`, `weight NUMERIC(3,2)`, `UNIQUE(video_id, tag)`

**Indexes (lean, practical)**

* `topics(canonical_name)` **UNIQUE** (btree)
* `entities(canonical_name)` **UNIQUE** (btree)
* `video_topics(video_id, topic_id)` **UNIQUE** and `video_topics(topic_id, video_id)` (btree)
* `video_entities(video_id, entity_id)` **UNIQUE** and `video_entities(entity_id, video_id)` (btree)
* `video_tags(video_id, tag)` **UNIQUE** and `video_tags(tag)` (btree)
* *(No index needed on `video_chapters` beyond the PK; reads are by `video_id`.)*
* Optional: `video_topics(topic_id, prominence)`, `video_entities(entity_id, importance)`, `videos(content_type)`, `videos(language)`, and case-insensitive tags via `CITEXT` or `UNIQUE (video_id, lower(tag))`

### 3.2 OpenSearch (per-video doc; denormalized; kNN enabled)

(Include index-only fields + vector; **do not index summary or chapters**.)

```json
{
  "id": "uuid",
  "title": "string",
  "description": "string",              // from source description (videos.description)
  "content_type": "string",
  "duration_s": 0,
  "language": "en",

  "entities": [
    { "name": "string", "canonical_name": "string", "type": "string", "importance": 0.0 }
  ],
  "topics": [
    { "name": "string", "canonical_name": "string", "prominence": 0.0, "category": "string" }
  ],

  "tags": ["string", "string"],

  "embedding": [0.0]
}
```

*Mapping hints:* text fields with `keyword` subfields for aggs; `entities`/`topics` as `nested`; `embedding` as `knn_vector`.
*BM25 fields (no summary/chapters):* `title^4`, `topics.name^3`, `entities.name^3`, `description^2`, `tags^1`.

### 3.3 Neo4j Graph Layer (bipartite, lean)

*IDs reuse Postgres primary keys; fetch display names from Postgres/OS at render-time.*

**Node labels (properties)**

* `Video { id: UUID }`
* `Topic { id: UUID, canonical_name: String }`
* `Entity { id: UUID, canonical_name: String }`

**Relationships (properties)**

* `(:Video)-[:HAS_TOPIC { prominence: Float }]->(:Topic)`
* `(:Video)-[:HAS_ENTITY { importance: Float }]->(:Entity)`

**Constraints / required properties**

* Uniqueness on `Video.id`, `Topic.id`, `Entity.id`
* Property existence: `Topic.canonical_name` **required**, `Entity.canonical_name` **required**
* Property existence: `HAS_TOPIC.prominence` **required**, `HAS_ENTITY.importance` **required**
* *(No extra indexes on `canonical_name`.)*

---

## 4) Extraction & Indexing Flow

1. **Extract (LLM/agents):** entities (**plus index-only `type`**), topics (**plus index-only `category`**), chapters (one-liners), tags, short_summary, metadata.
2. **Persist to Postgres (upserts):**
   `video_summary.short_summary`; `video_chapters.chapters` (array);
   `topics` + `video_topics(prominence)` *(no `category`)*;
   `entities` + `video_entities(importance)` *(no `type`)*;
   `video_tags(tag,weight)`; update `videos(content_type|duration_s|language)` as needed.
3. **Sync to Neo4j:** upsert `Video/Topic/Entity` nodes and `HAS_TOPIC/HAS_ENTITY` edges (weights mandatory).
4. **Build embedding text** using the template (include **description + summary + chapters**, and index-only `type`/`category`).
5. **Embed** → single video-level vector.
6. **Index in OpenSearch** (upsert per video): `id`, `title`, `description`, `content_type`, `duration_s`, `language`,
   `entities[]` *(incl. type)*, `topics[]` *(incl. category)*, `tags[]`, `embedding`.
   *(Summary & chapters are **not** indexed in OS; they’re embedding-only + UI.)*

---

## 5) Recommendations — Two-Lane (Lean, OS ≠ Graph)

**Why two lanes (don’t mix):**
We run **OpenSearch** and **Graph** independently because they optimize *different* objectives. OS excels at **similarity** (semantic + keyword). Graph excels at **adjacency/serendipity** (nearby-but-new). Mixing recall or scores blurs those goals; instead we keep lanes separate, **dedupe in favor of OS** (freeing Graph capacity for novel picks), enforce a **60/40** blend, then do a single global MMR for a pleasant final order.

### 0) Knobs (defaults)

* **Target N:** 100
* **History depth:** last **25** watched videos
* **Lane quotas:** OS = **60**, Graph = **40** (redistribute if a lane under-fills)
* **OS recall caps:** **kNN@300**, **BM25@300**
* **Graph recall caps:** **1-hop@200**, **2-hop@200** (both mandatory)
* **Within-lane MMR:** λ≈0.7 (diversify by `topics.category` / `entities.type`)
* **No uploader rules** (diversity via MMR only)

### 1) Build user signal

* **User vector `u`:** recency-weighted mean of the last **25** `video_vector`s (normalize).
* **User seeds:** top topics + entities from those videos with weights (from `prominence`/`importance`), e.g., ≤10 of each.

### 2) OS lane (OpenSearch: similarity + keywords)

1. **Recall (parallel):** kNN(300) on `embedding` with `u`, and BM25(300) using seed names over `title, description, topics.name, entities.name, tags`; **union & dedupe**.
2. **Normalize** to [0,1]: `cos_norm`, `bm25_norm`, `freshness = exp(-age_days/30)`.
3. **Lane score:** `OS_score = 0.60·cos_norm + 0.30·bm25_norm + 0.10·freshness`.
4. **Within-lane MMR** (λ≈0.7); keep shortlist ≈ **120**.

### 3) Graph lane (Neo4j: adjacency/serendipity; **1-hop & 2-hop mandatory**)

1. **Recall:**

   * **1-hop (200):** seeds → videos via `HAS_TOPIC`/`HAS_ENTITY` (direct membership).
   * **2-hop (200):** seeds → **neighbors** (via co-occurrence over videos) → videos with those neighbors.
   * **Union & dedupe** inside lane.
2. **Features (all ∈[0,1]):**

   * **NeighborNovelty** *(see below)* — how much the candidate contains **neighbors of the seeds** (not the seeds).
   * **MultiSeedSupport** *(see below)* — fraction of distinct seeds with **≥1 neighbor** present in the candidate.
   * **Freshness** — `exp(-age_days/30)`.
3. **Lane score:** `Graph_score = 0.60·NeighborNovelty + 0.30·MultiSeedSupport + 0.10·Freshness`.
4. **Within-lane MMR** (λ≈0.7); keep shortlist ≈ **80**.

### 4) Cross-lane dedupe (deterministic, OS-wins)

If a `video_id` appears in both shortlists, **keep it in OS** and **remove it from Graph**.
*(Optionally tag the OS item with `graph_support=true` for analytics/explanations.)*

### 5) Quota fill (60/40) + backfill

Take **60** from the OS shortlist and **40** from the Graph shortlist. If a lane under-fills, backfill from the other lane’s next best.

### 6) Global MMR (final ordering only)

Run one global MMR across the **100** selected videos to interleave and diversify (use lane scores as relevance; similarity from embeddings + category/type). **Preserve the 60/40 counts**—this step only reorders.

### 7) Explanations

* **OS pick:** “Semantic match to your history; aligns with **{Topic/Entity}**.”
* **Graph pick:** “Related via your interests (adjacent to **{Seed → Neighbor}**).”

### 8) Useful counters (to tune later)

Lane CTRs, under-fill rates, cross-lane overlap removed, post-MMR diversity by category/type.

---

## Graph features, definitions & examples

### What inputs we actually have

* **User history:** the last **25** watched videos with their **timestamps** (no dwell/likes needed).
* **Per video:** `topics[{topic_id, canonical_name, prominence}]`, `entities[{entity_id, canonical_name, importance}]`.
* **Graph:** `Video -[:HAS_TOPIC {prominence}]-> Topic`, `Video -[:HAS_ENTITY {importance}]-> Entity`.

### A) Seed weights — how we weight the user’s interests

1. For each watched video `i`, compute recency weight `w_i = exp(-age_days_i / 14)`.
2. Topic scores: `score_t = Σ_i (w_i * prominence_{i,t})`; Entity scores: `score_e = Σ_i (w_i * importance_{i,e})`.
3. Normalize per modality: `s_t = score_t / Σ_t score_t`, `s_e = score_e / Σ_e score_e`.
4. Keep top ~10 topics and ~10 entities as **seeds**.

**Output**

```
Topic seeds:  [{topic_id, canonical_name, weight = s_t}, ...]
Entity seeds: [{entity_id, canonical_name, weight = s_e}, ...]
```

### B) Neighbor strengths (per seed) — how we find adjacency

For each seed:

1. Traverse 2 hops: Seed → Video → Neighbor (same modality).
2. Accumulate `raw_strength += (membership_on_video_of_seed) * (membership_on_video_of_neighbor)`.
3. Drop self, keep top ~20 neighbors by `raw_strength`.
4. Normalize per seed so neighbor strengths sum to 1.

**Output (examples)**

```
Sourdough → [{Autolyse: 0.50}, {Whole-wheat: 0.30}, {High-hydration: 0.20}]
Ken Forkish → [{Preferment: 0.60}, {"Flour Water Salt Yeast": 0.40}]
```

### C) NeighborNovelty — related-but-new

1. Merge neighbors across seeds: each neighbor gets contributions `seed_weight * neighbor_strength(seed)`.
2. Sum by neighbor → `W[n]`, normalize so ΣW = 1.
3. Candidate score = Σ (W[n] * candidate_membership_for_n).
   **Effect:** rewards **adjacent** concepts tied to your interests, without repeating the seeds.

### D) MultiSeedSupport — convergent novelty

1. Keep **seed → neighbors** maps.
2. A seed is “supported” if the candidate has **any** of that seed’s neighbors with membership ≥ 0.15.
3. `MultiSeedSupport = (# supported seeds) / (total seeds)`.
   **Effect:** prefers videos that **bridge multiple** interests via different adjacencies.

### E) Freshness — newness nudge

`Freshness = exp(- age_days / 30)` (bounded [0,1]). Small temporal boost so adjacent picks aren’t stale.

### F) Tiny worked example

Seeds (weights):

```
Topics:  Sourdough (0.40), Fermentation (0.25)
Entities: Ken Forkish (0.20), Dutch oven (0.15)
```

Neighbors (per seed):

```
Sourdough → {Autolyse: 0.50, Whole-wheat: 0.30}
Ken Forkish → {Preferment: 0.60, "Flour Water Salt Yeast": 0.40}
Fermentation → {Kimchi: 0.55, Pickling: 0.45}
Dutch oven → {Banneton: 0.65, Preheated pot: 0.35}
```

Merged neighbor weights (pre-normalization):

```
Autolyse: 0.40*0.50=0.20, Preferment: 0.20*0.60=0.12, Whole-wheat: 0.12, Banneton: 0.0975, ...
```

Candidate has `{Autolyse (0.7), Preferment (0.5)}` → good **NeighborNovelty**;
supports seeds **Sourdough** and **Ken Forkish** → **MultiSeedSupport = 2/4 = 0.50**;
Freshness from publish age.