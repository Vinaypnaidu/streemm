# apps/api/worker.py
import os
import json
import uuid
import time
import threading
import logging
import tempfile
import subprocess
from typing import Optional

from fastapi import FastAPI, Response
from cache import redis_client, healthcheck as cache_health
from db import SessionLocal, healthcheck as db_health
from models import Video, VideoAsset
from jobs import QUEUE_KEY, DLQ_KEY, enqueue_notify_video_ready
from config import settings
from storage import (
    download_object,
    object_exists,
    build_hls_key,
    build_thumbnail_key,
    upload_dir,
    build_caption_key,
)
from search import index_video_metadata
from extract import extract_from_transcript, persist_result

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("worker")

app = FastAPI(title="Streem Worker")

_stop_event = threading.Event()


def _lock_key(video_id: str) -> str:
    return f"lock:video:{video_id}"


def _attempts_key(video_id: str) -> str:
    return f"attempts:video:{video_id}"


def acquire_lock(video_id: str, worker_id: str, ttl_ms: int) -> bool:
    try:
        ok = redis_client.set(_lock_key(video_id), worker_id, nx=True, px=ttl_ms)
        return bool(ok)
    except Exception:
        return False


def refresh_lock(video_id: str, ttl_ms: int) -> None:
    try:
        redis_client.pexpire(_lock_key(video_id), ttl_ms)
    except Exception:
        pass


def release_lock(video_id: str, worker_id: str) -> None:
    try:
        val = redis_client.get(_lock_key(video_id))
        if val == worker_id:
            redis_client.delete(_lock_key(video_id))
    except Exception:
        pass


def _backoff_for_attempt(attempt: int) -> Optional[int]:
    arr = settings.worker_backoff_seconds
    return arr[attempt - 1] if 1 <= attempt <= len(arr) else None


def _lock_refresher(video_id: str, worker_id: str, stop: threading.Event):
    # TODO: verify worker_id matches current worker
    interval = max(5, min(60, settings.worker_lock_ttl_ms // 3000))
    while not stop.is_set():
        time.sleep(interval)
        refresh_lock(video_id, settings.worker_lock_ttl_ms)


def _run_ffprobe(path: str) -> dict:
    t0 = time.time()
    cmd = [
        settings.ffprobe_bin,
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        path,
    ]
    res = subprocess.run(
        cmd, capture_output=True, text=True, timeout=settings.ffprobe_timeout_seconds
    )
    dt = int((time.time() - t0) * 1000)
    if res.returncode != 0:
        raise RuntimeError(
            f"ffprobe failed: code={res.returncode} err={res.stderr.strip()}"
        )
    log.info(json.dumps({"step": "ffprobe", "duration_ms": dt}))
    return json.loads(res.stdout)


def _parse_fps_from_probe(probe: dict) -> float:
    # Look for the first video stream
    for s in probe.get("streams", []):
        if s.get("codec_type") == "video":
            for k in ("avg_frame_rate", "r_frame_rate"):
                fr = s.get(k)
                if isinstance(fr, str) and "/" in fr:
                    num, den = fr.split("/")
                    try:
                        num, den = float(num), float(den)
                        if den > 0:
                            return num / den
                    except Exception:
                        pass
    return 30.0  # fallback


def _derive_gop_2s(fps: float) -> int:
    try:
        g = int(round(fps * 2.0))
        return max(24, min(240, g))  # clamp to [24, 240]
    except Exception:
        return 60


def _transcode_hls_720p(src_path: str, out_dir: str, gop: int) -> None:
    os.makedirs(out_dir, exist_ok=True)
    playlist = os.path.join(out_dir, "index.m3u8")
    seg_pat = os.path.join(out_dir, "seg_%03d.ts")
    t0 = time.time()
    cmd = [
        settings.ffmpeg_bin,
        "-y",
        "-i",
        src_path,
        "-vf",
        "scale=-2:720",
        "-c:v",
        "h264",
        "-profile:v",
        "main",
        "-crf",
        "20",
        "-preset",
        "veryfast",
        "-g",
        str(gop),
        "-keyint_min",
        str(gop),
        "-sc_threshold",
        "0",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-hls_time",
        "4",
        "-hls_playlist_type",
        "vod",
        "-hls_segment_filename",
        seg_pat,
        playlist,
    ]
    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=settings.ffmpeg_timeout_720p_seconds,
    )
    dt = int((time.time() - t0) * 1000)
    if res.returncode != 0:
        raise RuntimeError(
            f"ffmpeg(720p) failed: code={res.returncode} err={res.stderr.strip()}"
        )
    log.info(json.dumps({"step": "hls_720p", "duration_ms": dt}))


def _transcode_hls_480p(src_path: str, out_dir: str, gop: int) -> None:
    os.makedirs(out_dir, exist_ok=True)
    playlist = os.path.join(out_dir, "index.m3u8")
    seg_pat = os.path.join(out_dir, "seg_%03d.ts")
    t0 = time.time()
    cmd = [
        settings.ffmpeg_bin,
        "-y",
        "-i",
        src_path,
        "-vf",
        "scale=-2:480",
        "-c:v",
        "h264",
        "-profile:v",
        "main",
        "-crf",
        "22",
        "-preset",
        "veryfast",
        "-g",
        str(gop),
        "-keyint_min",
        str(gop),
        "-sc_threshold",
        "0",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        "-hls_time",
        "4",
        "-hls_playlist_type",
        "vod",
        "-hls_segment_filename",
        seg_pat,
        playlist,
    ]
    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=settings.ffmpeg_timeout_480p_seconds,
    )
    dt = int((time.time() - t0) * 1000)
    if res.returncode != 0:
        raise RuntimeError(
            f"ffmpeg(480p) failed: code={res.returncode} err={res.stderr.strip()}"
        )
    log.info(json.dumps({"step": "hls_480p", "duration_ms": dt}))


def _generate_thumbnail(src_path: str, out_path: str, offset_seconds: float = 0.0) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    t0 = time.time()

    # format offset as HH:MM:SS.mmm
    try:
        ts = max(0.0, float(offset_seconds))
    except Exception:
        ts = 0.0
    h = int(ts // 3600)
    m = int((ts % 3600) // 60)
    s = ts - (h * 3600 + m * 60)
    ts_str = f"{h:02d}:{m:02d}:{s:06.3f}"

    cmd = [
        settings.ffmpeg_bin,
        "-y",
        "-ss",
        ts_str,
        "-i",
        src_path,
        "-frames:v",
        "1",
        "-q:v",
        "2",
        out_path,
    ]
    res = subprocess.run(
        cmd, capture_output=True, text=True, timeout=settings.thumbnail_timeout_seconds
    )
    dt = int((time.time() - t0) * 1000)
    if res.returncode != 0:
        raise RuntimeError(
            f"ffmpeg(thumbnail) failed: code={res.returncode} err={res.stderr.strip()}"
        )
    log.info(json.dumps({"step": "thumbnail", "duration_ms": dt, "seek": ts_str}))


def _write_vtt(segments, out_path: str) -> None:
    # segments: iterable of {"start": float, "end": float, "text": str}
    def _fmt(t: float) -> str:
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = t % 60
        return f"{h:02d}:{m:02d}:{s:06.3f}"  

    lines = ["WEBVTT", ""]
    for i, seg in enumerate(segments, 1):
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", 0.0))
        text = (seg.get("text") or "").strip()
        lines.append(str(i))
        lines.append(f"{_fmt(start)} --> {_fmt(end)}")
        lines.append(text)
        lines.append("")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _read_vtt(vtt_path: str):
    def _parse_ts(s: str) -> float:
        s = s.replace(",", ".").strip()
        h, m, rest = s.split(":")
        sec = float(rest)
        return int(h) * 3600 + int(m) * 60 + sec

    segments = []
    with open(vtt_path, "r", encoding="utf-8") as f:
        lines = [l.rstrip("\n") for l in f]

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if "-->" in line:
            try:
                start_s, end_s = [p.strip() for p in line.split("-->")]
                i += 1
                text_lines = []
                while i < len(lines) and lines[i].strip():
                    text_lines.append(lines[i].strip())
                    i += 1
                if text_lines:
                    segments.append({
                        "start": _parse_ts(start_s),
                        "end": _parse_ts(end_s),
                        "text": " ".join(text_lines),
                    })
            except Exception:
                pass
        i += 1
    return segments


def _transcribe_with_faster_whisper(audio_path: str, model_name: str, language: str):
    try:
        from faster_whisper import WhisperModel
    except Exception:
        return None
    try:
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        segments, _info = model.transcribe(audio_path, language=language)
        out = []
        for s in segments:
            out.append(
                {
                    "start": float(s.start),
                    "end": float(s.end),
                    "text": (s.text or "").strip(),
                    "lang": language,
                }
            )
        return out
    except Exception:
        return None


def _chunk_segments(segments, min_len: int = 80, max_len: int = 200):
    chunks = []
    cur_text = ""
    cur_start = None
    cur_end = None
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        s = float(seg.get("start", 0.0))
        e = float(seg.get("end", s))
        if cur_start is None:
            cur_start = s
        candidate = (cur_text + " " + text).strip() if cur_text else text
        if len(candidate) <= max_len:
            cur_text = candidate
            cur_end = e
            if len(cur_text) >= min_len:
                chunks.append(
                    {
                        "start_seconds": cur_start,
                        "end_seconds": cur_end,
                        "text": cur_text,
                        "lang": settings.whisper_lang,
                    }
                )
                cur_text = ""
                cur_start = None
                cur_end = None
        else:
            if cur_text:
                chunks.append(
                    {
                        "start_seconds": cur_start,
                        "end_seconds": cur_end or s,
                        "text": cur_text,
                        "lang": settings.whisper_lang,
                    }
                )
            cur_text = text
            cur_start = s
            cur_end = e
    if cur_text:
        chunks.append(
            {
                "start_seconds": cur_start or 0.0,
                "end_seconds": cur_end or (cur_start or 0.0),
                "text": cur_text,
                "lang": settings.whisper_lang,
            }
        )
    return chunks


def _upsert_asset_720p(db, video_id: uuid.UUID, playlist_key: str) -> None:
    existing = (
        db.query(VideoAsset)
        .filter(
            VideoAsset.video_id == video_id,
            VideoAsset.kind == "hls",
            VideoAsset.label == "720p",
        )
        .first()
    )
    if existing:
        if existing.storage_key != playlist_key:
            existing.storage_key = playlist_key
        db.commit()
    else:
        a = VideoAsset(
            video_id=video_id,
            kind="hls",
            label="720p",
            storage_key=playlist_key,
            meta=None,
        )
        db.add(a)
        db.commit()


def _upsert_asset_480p(db, video_id: uuid.UUID, playlist_key: str) -> None:
    existing = (
        db.query(VideoAsset)
        .filter(
            VideoAsset.video_id == video_id,
            VideoAsset.kind == "hls",
            VideoAsset.label == "480p",
        )
        .first()
    )
    if existing:
        if existing.storage_key != playlist_key:
            existing.storage_key = playlist_key
        db.commit()
    else:
        a = VideoAsset(
            video_id=video_id,
            kind="hls",
            label="480p",
            storage_key=playlist_key,
            meta=None,
        )
        db.add(a)
        db.commit()


def _upsert_thumbnail(db, video_id: uuid.UUID, key: str) -> None:
    existing = (
        db.query(VideoAsset)
        .filter(
            VideoAsset.video_id == video_id,
            VideoAsset.kind == "thumbnail",
            VideoAsset.label == "poster",
        )
        .first()
    )
    if existing:
        if existing.storage_key != key:
            existing.storage_key = key
        db.commit()
    else:
        a = VideoAsset(
            video_id=video_id,
            kind="thumbnail",
            label="poster",
            storage_key=key,
            meta=None,
        )
        db.add(a)
        db.commit()


def process_video(video_id: str, reason: str) -> None:
    worker_id = f"pid:{os.getpid()}-thr:{threading.get_ident()}"
    got = acquire_lock(video_id, worker_id, settings.worker_lock_ttl_ms)
    if not got:
        log.info(
            json.dumps(
                {"video_id": video_id, "step": "lock_skip", "reason": "already_locked"}
            )
        )
        return

    refresher_stop = threading.Event()
    refresher = threading.Thread(
        target=_lock_refresher, args=(video_id, worker_id, refresher_stop), daemon=True
    )
    refresher.start()

    try:
        with SessionLocal() as db:
            v = db.get(Video, uuid.UUID(video_id))
            if not v:
                log.warning(
                    json.dumps(
                        {"video_id": video_id, "step": "load", "error": "missing_video"}
                    )
                )
                return
            if v.status == "uploaded":
                v.status = "processing"
                v.error = None
                db.commit()

        log.info(
            json.dumps(
                {"video_id": video_id, "step": "pipeline_start", "reason": reason}
            )
        )

        # Pull raw locally
        with SessionLocal() as db:
            v = db.get(Video, uuid.UUID(video_id))
            if not v:
                return
            raw_key = v.storage_key_raw

        with tempfile.TemporaryDirectory() as tmpd:
            local_raw = os.path.join(tmpd, "raw.mp4")
            download_object(settings.s3_bucket, raw_key, local_raw)

            # FFPROBE (idempotent-safe; overwrites)
            probe = _run_ffprobe(local_raw)
            fps = _parse_fps_from_probe(probe)
            gop = _derive_gop_2s(fps)
            duration = None
            try:
                duration = probe.get("format", {}).get("duration")
            except Exception:
                duration = None
            with SessionLocal() as db:
                v = db.get(Video, uuid.UUID(video_id))
                if v:
                    v.probe = probe
                    try:
                        v.duration_seconds = (
                            float(duration) if duration is not None else None
                        )
                    except Exception:
                        v.duration_seconds = None
                    v.error = None
                    db.commit()
                    try:
                        index_video_metadata(v)
                    except Exception:
                        log.exception("index_video_metadata_failed")

            # HLS 720p: skip if playlist exists
            playlist_key = build_hls_key(video_id, "720p", "index.m3u8")
            exists, _ = object_exists(settings.s3_bucket, playlist_key)
            if not exists:
                out_dir = os.path.join(tmpd, "hls_720p")
                _transcode_hls_720p(local_raw, out_dir, gop)
                upload_dir(settings.s3_bucket, f"hls/{video_id}/720p", out_dir)
            else:
                log.info(
                    json.dumps(
                        {"video_id": video_id, "step": "hls_720p", "skip": "exists"}
                    )
                )

            # HLS 480p
            playlist_key_480 = build_hls_key(video_id, "480p", "index.m3u8")
            exists480, _ = object_exists(settings.s3_bucket, playlist_key_480)
            if not exists480:
                out_dir_480 = os.path.join(tmpd, "hls_480p")
                _transcode_hls_480p(local_raw, out_dir_480, gop)
                upload_dir(settings.s3_bucket, f"hls/{video_id}/480p", out_dir_480)
            else:
                log.info(
                    json.dumps(
                        {"video_id": video_id, "step": "hls_480p", "skip": "exists"}
                    )
                )

            # Thumbnail
            thumb_key = build_thumbnail_key(video_id)
            exists_thumb, _ = object_exists(settings.s3_bucket, thumb_key)
            if not exists_thumb:
                thumb_local = os.path.join(tmpd, "poster.jpg")
                # seek to 10% of duration; fallback to 0 if unknown
                offset_sec = 0.0
                try:
                    offset_sec = max(0.0, float(duration) * 0.10) if (duration is not None) else 0.0
                except Exception:
                    offset_sec = 0.0
                _generate_thumbnail(local_raw, thumb_local, offset_sec)
                # Reuse upload_dir would add directory; upload single file instead:
                from storage import (
                    client,
                    _guess_content_type,
                )  # reuse content-type helper

                c = client()
                c.fput_object(
                    settings.s3_bucket,
                    thumb_key,
                    thumb_local,
                    content_type=_guess_content_type(thumb_local),
                )
            else:
                log.info(
                    json.dumps(
                        {"video_id": video_id, "step": "thumbnail", "skip": "exists"}
                    )
                )

            chunks = None
            
            # Transcription
            caption_key = build_caption_key(video_id, settings.whisper_lang)
            has_vtt, _ = object_exists(settings.s3_bucket, caption_key)
            if settings.whisper_enabled and not has_vtt:
                # Extract audio (wav) for better compatibility
                audio_path = os.path.join(tmpd, "audio.wav")
                try:
                    cmd = [
                        settings.ffmpeg_bin,
                        "-y",
                        "-i",
                        local_raw,
                        "-ac",
                        "1",
                        "-ar",
                        "16000",
                        audio_path,
                    ]
                    res = subprocess.run(
                        cmd, capture_output=True, text=True, timeout=600
                    )
                    if res.returncode != 0:
                        raise RuntimeError(
                            f"ffmpeg(audio) failed: code={res.returncode} err={res.stderr.strip()}"
                        )

                    segments = _transcribe_with_faster_whisper(
                        audio_path, settings.whisper_model, settings.whisper_lang
                    )
                    if not segments or not any((s.get("text") or "").strip() for s in segments):
                        log.info(json.dumps({"video_id": video_id, "step": "transcription", "skip": "no_speech"}))
                        segments = []
                    else:
                        # Write VTT
                        vtt_local = os.path.join(tmpd, "captions.vtt")
                        _write_vtt(segments, vtt_local)
                        from storage import client, _guess_content_type

                        c = client()
                        c.fput_object(
                            settings.s3_bucket,
                            caption_key,
                            vtt_local,
                            content_type=_guess_content_type(vtt_local),
                        )

                        # Index transcript chunks in OpenSearch
                        from search import index_transcript_chunks

                        chunks = _chunk_segments(segments)
                        try:
                            index_transcript_chunks(video_id, chunks)
                        except Exception:
                            log.exception("index_transcript_chunks_failed")
                except Exception:
                    log.exception("transcription_failed")
            elif has_vtt:
                # VTT already present; rebuild chunks and (re)index in OpenSearch
                try:
                    vtt_local = os.path.join(tmpd, "captions.vtt")
                    download_object(settings.s3_bucket, caption_key, vtt_local)
                    segments = _read_vtt(vtt_local)
                    if segments:
                        from search import index_transcript_chunks
                        chunks = _chunk_segments(segments)
                        try:
                            index_transcript_chunks(video_id, chunks)
                            log.info(json.dumps({"video_id": video_id, "step": "transcript_index", "source": "vtt", "chunks": len(chunks)}))
                        except Exception:
                            log.exception("index_transcript_chunks_failed_from_vtt")
                    else:
                        log.info(json.dumps({"video_id": video_id, "step": "transcript_index", "source": "vtt", "skip": "no_segments"}))
                except Exception:
                    log.exception("download_or_parse_vtt_failed")

        # Extraction (LLM): use transcript chunks if available; otherwise degrade to title/description
        try:
            with SessionLocal() as db:
                v = db.get(Video, uuid.UUID(video_id))
                if v:
                    res = extract_from_transcript(
                        video_id,
                        v.title or "",
                        v.description or "",
                        chunks,  # may be None
                    )
                    if res is None:
                        # OpenAI call or JSON parse failed; best-effort, do not block finalization
                        log.info(json.dumps({"video_id": video_id, "step": "extract", "skip": "llm_no_result"}))
                    else:
                        # JSON returned; persist (idempotent), even if arrays are empty
                        try:
                            persist_result(db, video_id, res)
                            log.info(json.dumps({"video_id": video_id, "step": "extract", "status": "persisted"}))
                        except Exception:
                            log.exception("extract_persist_failed")
        except Exception:
            # Any unexpected error during extraction should not block readiness
            log.exception("extract_failed")

        # Upsert asset records
        with SessionLocal() as db:
            _upsert_asset_720p(db, uuid.UUID(video_id), playlist_key)
            _upsert_asset_480p(db, uuid.UUID(video_id), playlist_key_480)
            _upsert_thumbnail(db, uuid.UUID(video_id), thumb_key)

        # Finalize status if all required assets exist
        ok720, _ = object_exists(settings.s3_bucket, playlist_key)
        ok480, _ = object_exists(settings.s3_bucket, playlist_key_480)
        okthumb, _ = object_exists(settings.s3_bucket, thumb_key)
        with SessionLocal() as db:
            v = db.get(Video, uuid.UUID(video_id))
            if v:
                will_be_ready = ok720 and ok480 and okthumb
                prev_status = v.status
                if will_be_ready:
                    v.status = "ready"
                    v.error = None
                else:
                    v.status = "processing"
                db.commit()

                # Enqueue notification exactly once on transition to ready
                if will_be_ready and prev_status != "ready" and (v.notified_at is None):
                    try:
                        enqueue_notify_video_ready(str(v.id))
                    except Exception:
                        pass

                try:
                    index_video_metadata(v)
                except Exception:
                    log.exception("index_video_metadata_failed_finalize")

        redis_client.delete(_attempts_key(video_id))
        log.info(
            json.dumps(
                {
                    "video_id": video_id,
                    "step": "finalize",
                    "ready": ok720 and ok480 and okthumb,
                }
            )
        )

    except Exception as e:
        log.exception("process_video_failed")
        attempts = int(redis_client.incr(_attempts_key(video_id)))
        delay = _backoff_for_attempt(attempts)
        if delay is not None:
            log.info(
                json.dumps(
                    {
                        "video_id": video_id,
                        "step": "retry",
                        "attempts": attempts,
                        "delay_sec": delay,
                    }
                )
            )
            time.sleep(delay)
            redis_client.lpush(
                QUEUE_KEY, json.dumps({"video_id": video_id, "reason": "retry"})
            )
        else:
            with SessionLocal() as db:
                v = db.get(Video, uuid.UUID(video_id))
                if v:
                    v.status = "failed"
                    v.error = str(e)
                    db.commit()
                    try:
                        print(f"Pushing to DLQ: {video_id}")
                        redis_client.lpush(
                            DLQ_KEY,
                            json.dumps(
                                {
                                    "video_id": video_id,
                                    "error": str(e),
                                    "attempts": attempts,
                                    "reason": reason,
                                    "ts": int(time.time()),
                                }
                            ),
                        )
                        redis_client.ltrim(DLQ_KEY, 0, 9999)
                    except Exception:
                        pass
            log.error(
                json.dumps(
                    {"video_id": video_id, "step": "failed_terminal", "error": str(e)}
                )
            )
    finally:
        refresher_stop.set()
        release_lock(video_id, worker_id)


def _consumer_loop():
    log.info("Worker consumer started")
    while not _stop_event.is_set():
        try:
            item = redis_client.brpop(QUEUE_KEY, timeout=5)
            if not item:
                continue
            _q, payload = item
            data = json.loads(payload)
            video_id = data.get("video_id")
            reason = data.get("reason", "unknown")
            if not video_id:
                continue
            process_video(video_id, reason)
        except Exception:
            log.exception("worker_loop_error")
            time.sleep(1)


@app.on_event("startup")
def on_startup():
    t = threading.Thread(target=_consumer_loop, daemon=True)
    t.start()


@app.on_event("shutdown")
def on_shutdown():
    _stop_event.set()


@app.get("/ready")
def ready(response: Response):
    """
    Kubernetes readiness/liveness probe.
    Returns 200 if healthy, 503 if not.
    """
    ok_db = True
    ok_cache = True
    try:
        db_health()
    except Exception:
        ok_db = False
    try:
        cache_health()
    except Exception:
        ok_cache = False
    
    is_ok = ok_db and ok_cache
    
    # Set HTTP status code for Kubernetes
    if not is_ok:
        response.status_code = 503
    
    return {"ok": is_ok, "db": ok_db, "cache": ok_cache}
