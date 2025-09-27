# Implementation details

## 1. Authentication

### Overview
- Email/password auth with server-side sessions in Redis.
- HttpOnly cookie `sid` identifies the session; session data lives only in Redis.
- Double-submit CSRF token for all mutating routes.

### Data model
- Table: `users`
  - `id UUID PK`
  - `email TEXT UNIQUE NOT NULL` (always lowercased)
  - `password_hash TEXT NOT NULL` (Argon2id)
  - `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
  - `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()` (auto-updated)
  - `last_login_at TIMESTAMPTZ NULL`

### Sessions
- Key: `sess:{sid}` → `{"user_id": "<uuid>", "issued_at": "<iso8601>"}`
- TTL: 7 days; rolling in Redis (on access) and rolling in browser (cookie refreshed on access).
- Cookie: `sid`
  - HttpOnly, `SameSite=Lax`, `Secure=true` in production, `max-age=604800`.
- Creation:
  - On successful register/login, generate `sid`, `SETEX` in Redis, set cookie.
- Validation:
  - Read `sid` cookie → fetch session in Redis → extend TTL → load user.
- Logout:
  - Delete Redis key and clear cookie.

### CSRF
- Double-submit cookie pattern using `itsdangerous`-signed token.
- GET `/auth/csrf`:
  - Sets cookie `csrf=<signed>` (not HttpOnly), returns `{ csrf }`.
- Mutating requests:
  - Must send `x-csrf-token: <same signed value>` and include cookies.
- Verification:
  - Require cookie and header to match and verify signature + max-age (24h).

### API
- `POST /auth/register`:
  - Body: `{ email, password }` (email normalized to lowercase; password ≥ 8).
  - Effects: create user → create session → set cookie → return `{ id, email }`.
- `POST /auth/login`:
  - Body: `{ email, password }`.
  - Rate limit: 20/min per `(ip,email)` via Redis `INCR` + TTL.
  - Effects: issue new session cookie; return `{ id, email }`.
- `POST /auth/logout`:
  - Effects: delete Redis session and clear cookie; return `{ ok: true }`.
- `GET /me`:
  - Returns `{ id, email }` if authenticated; 401 otherwise.
- `GET /auth/csrf`:
  - Returns `{ csrf, header: "x-csrf-token" }` and sets `csrf` cookie.

### Flows
- Register
  1. Client GET `/auth/csrf` → receives `csrf` cookie and token.
  2. Client POST `/auth/register` with `x-csrf-token` and `{ email, password }`.
  3. API validates CSRF → validates inputs → creates user → issues session → sets `sid` cookie → 201 with `{ id, email }`.
- Login
  1. Client GET `/auth/csrf` → token.
  2. Client POST `/auth/login` with `x-csrf-token`, `{ email, password }`.
  3. API validates CSRF → checks rate limit → verifies password → issues session → sets `sid` cookie → 200 with `{ id, email }`.
- Authenticated request
  1. Client requests API with cookies.
  2. API reads `sid` → loads session from Redis → refreshes Redis TTL and re-sets cookie → loads user → proceeds.
- Logout
  1. Client GET `/auth/csrf` → token.
  2. Client POST `/auth/logout` with `x-csrf-token`.
  3. API deletes `sess:{sid}` and clears cookie → `{ ok: true }`.

### Security & errors
- Password hashing: Argon2id (`argon2-cffi`).
- CORS: allow-list `http://localhost:3000` (and `http://127.0.0.1:3000` if used), `allow_credentials=true`, headers include `x-csrf-token`.
- Sessions: server-side only; cookie contains opaque `sid`, never user data.
- Rolling expiry: Redis TTL and cookie `max-age` refreshed on access.
- Rate limiting (dev): 20/min per `(ip,email)`; can delete counter on success.
- Error responses: 400 invalid input, 401 invalid creds or missing session, 403 CSRF failure, 409 email exists, 429 rate limit.


## 2. Object storage & presigned upload

### Overview
- **MinIO** as S3-compatible object storage.
- Store raw browser uploads under deterministic keys; processed assets will live alongside later.

### Configuration
- Environment (API):
  - `S3_ENDPOINT=http://localhost:9000`
  - `S3_ACCESS_KEY=minioadmin`, `S3_SECRET_KEY=minioadmin`
  - `S3_REGION=us-east-1`, `S3_BUCKET=media`, `S3_USE_SSL=false`
  - `PRESIGN_EXPIRES_SECONDS=900`
  - `UPLOAD_MAX_BYTES=1073741824` (1 GB), `UPLOAD_ALLOWED_MIME=video/mp4`
- MinIO free tier CORS:
  - Use global setting:
    - `mc admin config set local api cors_allow_origin="http://localhost:3000"`
    - `mc admin service restart local`

### Storage keys
- Raw upload: `raw/{user_id}/{video_id}.mp4`
- (Later) HLS: `hls/{video_id}/{label}/...`
- (Later) Thumbnail: `thumbs/{video_id}/poster.jpg`
- (New) Captions: `captions/{video_id}/en.vtt`

### API
- `POST /uploads/presign`:
  - Auth required (session cookie), CSRF required (double-submit).
  - Request: `{ filename, content_type, size_bytes }`
  - Validates MIME and size against config.
  - Rate limit: 5/min per user via Redis `INCR` + TTL.
  - Response: `{ video_id, raw_key, put_url, headers }`
  - `put_url` is a presigned `PUT` to MinIO with `headers: { "Content-Type": content_type }`

### Flow
1. GET `/auth/csrf` to obtain CSRF token; cookie set.
2. POST `/uploads/presign` with `x-csrf-token` and request body.
3. PUT the file to `put_url` with returned headers; show progress.
4. On success, show `video_id`/`raw_key` for confirmation.
5. (Later) call finalize to persist metadata and enqueue processing.

### Security & constraints
- Server-side sessions; no credentials on presigned PUTs.
- CSRF enforced for presign; CORS on API allows only known origins.
- Size + MIME validation on the server; client enforces `video/mp4`.
- Keys are deterministic and safe to log; no PII embedded.


## 3. Video model & finalize/enqueue

### Overview
- Persist raw upload metadata as a `video` owned by a user.
- Finalize verifies the raw object exists under deterministic key rules, creates (or returns) the `video` record, then enqueues background processing.
- Listing and detail endpoints let the user browse their videos.

### Data model
- Table: `videos`
  - `id UUID PK`
  - `user_id UUID NOT NULL` FK → `users(id)` ON DELETE CASCADE
  - `title TEXT NOT NULL DEFAULT ''`
  - `description TEXT NOT NULL DEFAULT ''`
  - `original_filename TEXT NOT NULL`
  - `storage_key_raw TEXT NOT NULL` (e.g., `raw/{user_id}/{video_id}.mp4`)
  - `status TEXT NOT NULL DEFAULT 'uploaded'` (uploaded|processing|ready|failed)
  - `probe JSONB NULL`
  - `duration_seconds FLOAT NULL`
  - `checksum_sha256 TEXT NULL`
  - `error TEXT NULL`
  - `notified_at TIMESTAMPTZ NULL` (set when "video ready" email sent)
  - `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
  - `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`
  - Index: `(user_id, created_at DESC)` for listing
  
- Table: `video_assets`
  - `id UUID PK`
  - `video_id UUID NOT NULL` FK → `videos(id)` ON DELETE CASCADE
  - `kind TEXT NOT NULL` (hls|thumbnail)
  - `label TEXT NOT NULL` (e.g., 720p|480p|poster)
  - `storage_key TEXT NOT NULL`
  - `meta JSONB NULL`
  - `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
  - `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`
  - Unique: `(video_id, kind, label)`
  - Index: `(video_id)`

### Storage keys
- Raw: `raw/{user_id}/{video_id}.mp4`
- HLS (later): `hls/{video_id}/{label}/...`
- Thumbnail (later): `thumbs/{video_id}/poster.jpg`

Helpers exist to build keys and to verify object existence:
- `build_raw_key(user_id, video_id, ext)`
- `build_hls_key(video_id, label, filename)`
- `build_thumbnail_key(video_id)`
- `object_exists(bucket, key) -> (bool, meta)`

### API
- POST `/videos` (Finalize)
  - Auth + CSRF required.
  - Request:
    - `video_id: string (uuid)`
    - `raw_key: string`
    - `original_filename: string`
    - `checksum_sha256?: string`
    - `title?: string` (optional, defaults to empty string)
    - `description?: string` (optional, defaults to empty string)
  - Behavior:
    - Recompute expected raw key from `user_id`, `video_id`, and `original_filename` extension; must match provided `raw_key`.
    - Verify object exists in `S3_BUCKET` at `raw_key`. If missing → 409.
    - Idempotent upsert:
      - If `videos.id` exists and belongs to user with same `storage_key_raw` → return 202.
      - If different owner or raw key mismatch → 403/409.
      - Else create new record with `status='uploaded'` (and provided `title`, `description`).
    - Enqueue background processing stub.
  - Response: 202 with `VideoDetail`.
- GET `/videos/my` (List own videos)
  - Auth required.
  - Query: `limit` (1–100, default 20), `offset` (default 0).
  - Returns: `{ items: VideoOut[], next_offset?: number }` newest first.
  - Each `VideoOut` includes `thumbnail_public_url` if a poster exists in storage.
- GET `/videos/{id}` (Detail for playback and resume)
  - Auth required; any authenticated user can view.
  - Returns: `PublicVideoDetail` including `assets`, `resume_from_seconds`, `progress_percent`.
- DELETE `/videos/{id}`
  - Auth + CSRF required; owner-only.
  - Deletes raw, HLS, thumbnail, and captions objects (best-effort) then the DB rows.
  - Response: `{ ok: true }`.

### Response shapes
- `VideoOut`: `{ id, status, original_filename, title, description, created_at, thumbnail_public_url? }`
- `VideoDetail`: `{ id, status, original_filename, title, description, storage_key_raw, duration_seconds?, checksum_sha256?, probe?, error?, created_at, assets: VideoAssetOut[] }`
- `VideoAssetOut`: `{ id, kind, label, storage_key, meta?, public_url? }`
- `PublicVideoDetail`: `{ id, status, original_filename, title, description, duration_seconds?, error?, created_at, assets: VideoAssetOut[], resume_from_seconds?, progress_percent? }`

### Flows
- Finalize
  1. Client uploads the file to MinIO using presigned PUT from `/uploads/presign`.
  2. Client calls `POST /videos` with `{ video_id, raw_key, original_filename, title?, description? }`.
  3. API validates CSRF/session, validates key convention and object existence, creates or returns `videos` row with `status='uploaded'`, and enqueues processing.
  4. Client can fetch `GET /videos/my` and `GET /videos/{id}` to see status.

### Idempotency & permissions
- Finalize is idempotent per `(user_id, video_id, storage_key_raw)`.
- Repeated finalize enqueues are safe; the worker implements idempotent processing in M4.
- Only the owner can finalize or delete a video. Any authenticated user can view details.
- Error cases: 400 invalid `video_id` or key mismatch; 403 cross-user access; 409 finalize before upload or raw key mismatch with existing record.

### Enqueue
- Minimal stub pushes a JSON payload to Redis list `q:videos`: `{ "video_id": "<uuid>", "reason": "finalize" }`.


## 4. Worker & transcoding pipeline

### Responsibilities
- Dequeue `{"video_id"}` from Redis `q:videos`.
- Acquire per-video lock `lock:video:{id}` (SET NX PX), refresh TTL.
- Steps (idempotent): ffprobe → HLS 720p → HLS 480p → thumbnail → transcription (captions) → finalize status.
- Upload assets to MinIO under deterministic keys and UPSERT `video_assets`.
- Push to `dlq:videos` for failed videos.

### State model
- `uploaded` → worker sets `processing` → when required assets present → `ready` (else `failed` with `error`).
- Safe to re-enqueue at any time; steps skip if target already exists.

### Locking
- Redis `SET lock:video:{id} worker_id NX PX=WORKER_LOCK_TTL_MS` (default 15m).
- Background refresher thread updates TTL periodically.
- On exit/failure the lock expires; another worker can proceed.

### Retries/backoff
- `attempts:video:{id}` tracks tries; backoff sequence `30,120,300` seconds.
- On terminal failure: set `videos.status='failed'` + `error`.

### Timeouts (configurable)
- `FFPROBE_TIMEOUT_SECONDS=30`
- `FFMPEG_TIMEOUT_720P_SECONDS=1200`
- `FFMPEG_TIMEOUT_480P_SECONDS=900`
- `THUMBNAIL_TIMEOUT_SECONDS=30`

### Transcoding choices
- HLS VOD with 4s segments; GOP/keyint computed ~2s based on probe FPS (clamped [24,240]).
- 720p: h264 main, CRF 20, preset veryfast, aac 128k.
- 480p: h264 main, CRF 22, preset veryfast, aac 96k.
- Keys:
  - Raw: `raw/{user_id}/{video_id}.mp4`
  - HLS: `hls/{video_id}/{label}/index.m3u8`
  - Thumbnail: `thumbs/{video_id}/poster.jpg`
- Captions: `captions/{video_id}/en.vtt`

### Idempotency
- Before each step: check object exists in MinIO; if exists, skip.
- UPSERT `video_assets(video_id, kind, label)` to avoid duplicates.
- Finalize sets `ready` only if 720p + 480p + poster exist.

### Observability
- JSON logs per step `{ video_id, step, duration_ms?, skip?, error? }`.
- `/ready` checks DB + Redis.
- Inspect Redis:
  - `redis-cli LLEN q:videos`
  - `redis-cli GET lock:video:{id}`
  - `redis-cli GET attempts:video:{id}`

### Ops
- Re-enqueue: re-call finalize (idempotent) or `redis-cli LPUSH q:videos '{"video_id":"..."}'`.
- Clear stuck lock: delete `lock:video:{id}` if worker is dead (rare).
- Scale: run multiple workers; lock ensures one-at-a-time per video.

### Security/dev
- Dev uses public GET from MinIO; in prod switch to private and use `presign_get()` or CDN.
- Public URLs are derived via `S3_PUBLIC_ENDPOINT/S3_BUCKET/{key}`.

### Transcription (captions)
- Goal
  - Generate English captions and searchable transcript chunks for each video.
- Storage
  - Write WebVTT to `captions/{video_id}/en.vtt` in MinIO (public in dev; private/presign in prod).
- Implementation
  - Primary: `faster-whisper` (`WHISPER_ENABLED=true`, `WHISPER_MODEL=base.en`, `WHISPER_LANG=en`).
  - The worker extracts mono 16kHz WAV with FFmpeg for transcription.
  - Merge segments into ~80–200 char chunks (≈5–12s) for indexing.
- Indexing
  - After captions are produced, the worker replaces transcript docs for the video in OpenSearch:
    - `transcript_chunks` docs: `{ id: "{video_id}_{seq}_{start_ms}", video_id, text, start_seconds, end_seconds, lang, created_at }`.
    - Note: the id combines `video_id`, a sequence index, and the start time in milliseconds.
  - Video metadata (title/description/duration/thumbnail/status) is indexed in `videos` on finalize and after probe/thumbnail.
- Idempotency & failures
  - Skip captioning if `captions/{video_id}/en.vtt` already exists.
  - If faster-whisper fails and fallback is disabled/unavailable, continue pipeline without captions.
  - Transcript indexing uses delete-by-filter then add-documents to be idempotent.
- Tuning
  - Adjust CRF or preset based on quality/CPU budget.
  - Segment length and GOP affect seek latency and encoder efficiency.
  - Consider a master playlist later to unify variants.


## 5. Watch history & resume

### Behavior
- Any authenticated user can watch any video.
- As soon as a user opens `/videos/{id}`, we add it to their history (position defaults to 0).
- We remember only the latest position (last write wins). If the user scrubs backwards then leaves, we resume from that last heartbeat.
- On read: if progress ≥ 95% of duration, we reset to 0 for the next session (95% rule applies only when the player asks where to start).
- History shows the last 50 videos a user watched, newest first.

### Data model
- Table: `watch_history` (one row per user/video)
  - `user_id UUID NOT NULL` → FK `users(id)` ON DELETE CASCADE
  - `video_id UUID NOT NULL` → FK `videos(id)` ON DELETE CASCADE
  - `last_position_seconds FLOAT NOT NULL DEFAULT 0`
  - `last_watched_at TIMESTAMPTZ NOT NULL DEFAULT now()`
  - Primary Key: `(user_id, video_id)`
  - Index: `(user_id, last_watched_at DESC)` for fast “last 50” retrieval
  - Cascade deletes ensure rows vanish if the user or video is removed.

### API
- GET `/videos/{id}` (Detail + resume)
  - Auth: required (any user).
  - Behavior:
    - Upsert `watch_history` row for `(user_id, video_id)` if it doesn’t exist (position=0).
    - Load `last_position_seconds` and `videos.duration_seconds`.
    - If `duration` is present and `position/duration ≥ 0.95`, atomically reset `last_position_seconds=0` and return `resume_from_seconds=0`.
    - Otherwise return `resume_from_seconds = last_position_seconds`.
    - Compute `progress_percent` if duration is known.
  - Response (extends `PublicVideoDetail`): `resume_from_seconds: number | null`, `progress_percent: number | null`.
- POST `/history/heartbeat`
  - Auth + CSRF required.
  - Body: `{ "video_id": "UUID", "position_seconds": number }`
  - Behavior:
    - Clamp `position_seconds >= 0`.
    - UPSERT `(user_id, video_id)` with `last_position_seconds = position_seconds` and `last_watched_at = now()`.
    - Do NOT apply the 95% rule here (only on read).
  - Response: `{ "ok": true }`
- GET `/history?limit=50&offset=0`
  - Auth required.
  - Behavior: join `watch_history` with `videos`, newest first. Include thumbnail URL (if exists) and computed `progress_percent` (if duration known).
  - Response item example:
    ```json
    {
      "video_id": "UUID",
      "original_filename": "clip.mp4",
      "title": "Optional Title",
      "thumbnail_url": "http://.../thumbs/{id}/poster.jpg",
      "last_position_seconds": 137,
      "duration_seconds": 220.1,
      "progress_percent": 62.3,
      "last_watched_at": "2025-09-18T16:20:00Z"
    }
    ```

### Frontend
- Video detail `/videos/{id}`:
  - Fetch `GET /videos/{id}` and set player `currentTime = resume_from_seconds`.
  - Deep-link support: `?t=<seconds>` takes precedence over `resume_from_seconds` on first load.
  - Autoplay on first load; on quality switches, preserve current position and keep playing if it was already playing.
  - Send heartbeats:
    - On `playing`, `pause`, `ended`, `visibilitychange (hidden)`, `beforeunload`
    - Throttled via `timeupdate` (~10s) while playing
    - CSRF centralized via `AuthProvider.getCsrf()`, standard `x-csrf-token`, with a single 403 retry
    - Use `keepalive: true` so the final heartbeat can complete on unload
- History page `/history`:
  - Fetch `GET /history?limit=50` and render a single-column list with thumbnail, title, last watched time, and a progress bar using `progress_percent`.
  - Clicking a history item links to `/videos/{id}?t=last_position_seconds` so playback resumes immediately.

### Ownership & permissions
- `GET /videos/{id}`: any authenticated user can view.
- Mutations (finalize, delete) and `GET /videos/my` remain owner-scoped.
- `watch_history` rows are per-user and cascade on user/video deletion.

### Edge cases & idempotency
- “Last write wins”: only the latest `last_position_seconds` is stored.
- The 95% reset is applied only when reading detail.
- If `videos.duration_seconds` is missing, return the saved position and omit `progress_percent`.
- Repeated calls are safe; upserts avoid duplicates.
- Deleting a video cascades to its history entries.


## 6. Video search

### Overview
- Two panels returned side-by-side by the API and rendered in the web app:
  - Metadata search: matches against each video's title + description.
  - Transcript search: matches across transcript chunks; one result per video at the earliest occurrence.

### Search service
- OpenSearch (dev via Docker).
- Config (API/Worker): `OPENSEARCH_URL`, `OPENSEARCH_USERNAME`, `OPENSEARCH_PASSWORD`.
- Transcript coverage thresholds: `minimum_should_match` is set dynamically (70% for 3–5 tokens, 50% for 6+).

### Indexes & document shapes
- Index `videos` (document `_id` = `id`): `{ id, title, description, user_id, created_at, duration_seconds, thumbnail_url, status }`
- Index `transcript_chunks` (document `_id` combines `video_id`, a sequential index, and the segment start time in ms): `{ id: "{video_id}_{seq}_{start_ms}", video_id, text, start_seconds, end_seconds, lang, created_at }`

### Query strategy
- Metadata panel
  - `multi_match` across `title` and `description` with highlighting.
  - Results include `score`, `thumbnail_url`, `created_at`, `duration_seconds`.
- Transcript panel
  - Primary `match` on `text` using the normalized query string and dynamic `minimum_should_match`.
  - Span-near boosters reward long in-order runs (5-gram, 4-gram windows capped at eight per query).
  - A dis_max guard requires at least one non-glue term to match.
  - Rescoring emphasizes the full phrase (slop 1) inside the top window.
  - Highlights return a single 180-character fragment.

### Indexing lifecycle
- On finalize (`POST /videos`) and after probe/thumbnail in the worker: upsert `videos` doc via `index_video_metadata(video)`.
- After transcription in the worker: replace-by-query all `transcript_chunks` for that `video_id` via `index_transcript_chunks(video_id, chunks)`.
- On delete (`DELETE /videos/{id}`): remove from `videos` and delete all `transcript_chunks` by `video_id`.

### API
- `GET /search?q=...&limit_meta=10&offset_meta=0&limit_transcript=10&offset_transcript=0&lang=en`
  - Executes the metadata OpenSearch query and the transcript OpenSearch query described above.
  - Transcript results collapse to the earliest chunk per video and hydrate titles/thumbnails from Postgres.
  - Response: `{ search_ok, meta: { items, estimated_total, next_offset }, transcript: { items, estimated_total, next_offset } }`.

### Frontend
- Navbar search navigates to `/search?q=...`.
- `/search` page renders two columns:
  - Metadata: card with thumbnail, highlighted title/description.
  - Transcript: card with thumbnail, a snippet, a mini progress bar seeded by `progress_seconds/duration`, and deep link to `/videos/{id}?t=progress_seconds`.
- Video page honors `?t=` and seeks on first load (with hls.js, applied after manifest parsed).


## 7. Home feed

### Overview
- “For You” feed using a keyword profile built from a user’s recent watch history.
- Single OpenSearch query against the `videos` index; fallback to random if no signal.
- Only `status="ready"` videos are eligible.

### Data sources
- `watch_history`: last 15 rows for the current user, newest first.
- `videos`: titles, descriptions, duration, thumbnail presence.
- OpenSearch `videos` index (must include `status` field and allow filtering by it).

### Keyword profile
- Concatenate `title + description` for each of the last 15 watched videos into one blob.
- Normalize: lowercase, strip punctuation, collapse whitespace.
- Tokenize and drop short/stop words; retain top ~50 by frequency.

### Querying
- Build a `bool` query:
  - `must`: `multi_match` across `title`, `description` with the keyword blob.
  - `filter`: `term` on `status="ready"` (additional language filter may be applied later).
  - Highlighting disabled (reuse DB metadata instead).
- Backend hydrates titles/thumbnails from Postgres and computes progress percentages from `watch_history`.
- Fallback to `ORDER BY random()` if we have no keywords or the search returns no hits.

### Frontend
- Page `/` (when authenticated) fetches `GET /homefeed`.
- Renders a multi-column card grid (same as “Your videos”): poster/thumbnail, progress bar (from `progress_percent`), title (no status chip).
- Clicking a card navigates to `/videos/{id}`.

### Edge cases & behavior
- If no history or no usable tokens → fallback to random ready videos.
- If duration is missing, `progress_percent` is omitted (or 0) and the bar shows empty.
- OpenSearch outage returns random ready videos; feed remains functional.
- Search results are validated against DB and filtered to `status="ready"`.

### Security & performance
- Auth required; no PII leaves the service.
- Tokenization and counting happen in-process; single OpenSearch query.
- DB fallback uses `ORDER BY random() LIMIT 25` (acceptable for dev; tune later if needed).


## 8. Email notifications

### Overview
- When a video first becomes `ready`, enqueue a notification job.
- A dedicated notifier worker consumes `q:emails`, sends an email, and marks `videos.notified_at`.
- Retries with backoff; terminal failures go to `dlq:emails`.

### Data model
- `videos.notified_at TIMESTAMPTZ NULL` — set when an email is successfully sent (once-per-video semantics).

### Queues
- Email queue: `q:emails`
- Email DLQ: `dlq:emails`
- Per-video email lock: `lock:email:{video_id}`
- Attempts key: `attempts:email:{video_id}`

### Flow
1. Video worker finalizes assets; when all required assets exist → status transitions to `ready`.
2. On first transition to `ready` and `notified_at IS NULL`, enqueue `{ "video_id": "...", "reason": "video_ready" }` to `q:emails`.
3. Notifier worker acquires `lock:email:{video_id}`, loads `Video` and owner `User`, verifies `status == "ready" AND notified_at IS NULL`, sends email, sets `notified_at = now()` on success, or retries/backoffs and pushes to DLQ on terminal failure.

### Idempotency
- Once-per-video: enforced by both the Redis lock and `videos.notified_at`.
- Re-enqueue-safe: notifier re-checks `notified_at` before sending.

### Dev SMTP
- Mailpit (multi-arch): SMTP on `localhost:1025`, web UI at `http://localhost:8025`.
- Compose service: `axllent/mailpit:latest`.

### Configuration
- `EMAIL_ENABLED` (default true in dev)
- `EMAIL_FROM`
- `SMTP_HOST`, `SMTP_PORT`
- `SMTP_STARTTLS` (bool), `SMTP_SSL` (bool)


## 9. Health & diagnostics

### API
- `GET /healthz?include_optional=true`:
  - Runs checks for database, cache (Redis), object storage bucket, and optionally OpenSearch.
  - Response: `{ ok, checks: { database, cache, object_storage, search } }` with per-check details and skip flags.
- `GET /search/debug`:
  - Returns OpenSearch cluster health, index list, and basic index stats for `videos` and `transcript_chunks`.
  - Response: `{ ok, cluster, indices, stats }` or `{ ok: false, error }` if unavailable.