import os
import json
import uuid
import time
import threading
import logging
import tempfile
import subprocess
from typing import Optional

from fastapi import FastAPI
from cache import redis_client, healthcheck as cache_health
from db import SessionLocal, healthcheck as db_health
from models import Video, VideoAsset
from jobs import QUEUE_KEY
from config import settings
from storage import download_object, object_exists, build_hls_key, build_thumbnail_key, upload_dir

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("worker")

app = FastAPI(title="Reelay Worker")

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
    interval = max(5, min(60, settings.worker_lock_ttl_ms // 3000))
    while not stop.is_set():
        time.sleep(interval)
        refresh_lock(video_id, settings.worker_lock_ttl_ms)

def _run_ffprobe(path: str) -> dict:
    t0 = time.time()
    cmd = [
        settings.ffprobe_bin,
        "-v", "error",
        "-show_format",
        "-show_streams",
        "-of", "json",
        path,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=settings.ffprobe_timeout_seconds)
    dt = int((time.time() - t0) * 1000)
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe failed: code={res.returncode} err={res.stderr.strip()}")
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
        settings.ffmpeg_bin, "-y",
        "-i", src_path,
        "-vf", "scale=-2:720",
        "-c:v", "h264",
        "-profile:v", "main",
        "-crf", "20",
        "-preset", "veryfast",
        "-g", str(gop),
        "-keyint_min", str(gop),
        "-sc_threshold", "0",
        "-c:a", "aac",
        "-b:a", "128k",
        "-hls_time", "4",
        "-hls_playlist_type", "vod",
        "-hls_segment_filename", seg_pat,
        playlist,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=settings.ffmpeg_timeout_720p_seconds)
    dt = int((time.time() - t0) * 1000)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg(720p) failed: code={res.returncode} err={res.stderr.strip()}")
    log.info(json.dumps({"step": "hls_720p", "duration_ms": dt}))

def _transcode_hls_480p(src_path: str, out_dir: str, gop: int) -> None:
    os.makedirs(out_dir, exist_ok=True)
    playlist = os.path.join(out_dir, "index.m3u8")
    seg_pat = os.path.join(out_dir, "seg_%03d.ts")
    t0 = time.time()
    cmd = [
        settings.ffmpeg_bin, "-y",
        "-i", src_path,
        "-vf", "scale=-2:480",
        "-c:v", "h264",
        "-profile:v", "main",
        "-crf", "22",
        "-preset", "veryfast",
        "-g", str(gop),
        "-keyint_min", str(gop),
        "-sc_threshold", "0",
        "-c:a", "aac",
        "-b:a", "96k",
        "-hls_time", "4",
        "-hls_playlist_type", "vod",
        "-hls_segment_filename", seg_pat,
        playlist,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=settings.ffmpeg_timeout_480p_seconds)
    dt = int((time.time() - t0) * 1000)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg(480p) failed: code={res.returncode} err={res.stderr.strip()}")
    log.info(json.dumps({"step": "hls_480p", "duration_ms": dt}))

def _generate_thumbnail(src_path: str, out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    t0 = time.time()
    cmd = [
        settings.ffmpeg_bin, "-y",
        "-ss", "00:00:00.000",
        "-i", src_path,
        "-frames:v", "1",
        "-q:v", "2",
        out_path,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=settings.thumbnail_timeout_seconds)
    dt = int((time.time() - t0) * 1000)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg(thumbnail) failed: code={res.returncode} err={res.stderr.strip()}")
    log.info(json.dumps({"step": "thumbnail", "duration_ms": dt}))

def _upsert_asset_720p(db, video_id: uuid.UUID, playlist_key: str) -> None:
    existing = db.query(VideoAsset).filter(
        VideoAsset.video_id == video_id,
        VideoAsset.kind == "hls",
        VideoAsset.label == "720p",
    ).first()
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
    existing = db.query(VideoAsset).filter(
        VideoAsset.video_id == video_id,
        VideoAsset.kind == "hls",
        VideoAsset.label == "480p",
    ).first()
    if existing:
        if existing.storage_key != playlist_key:
            existing.storage_key = playlist_key
        db.commit()
    else:
        a = VideoAsset(video_id=video_id, kind="hls", label="480p", storage_key=playlist_key, meta=None)
        db.add(a)
        db.commit()

def _upsert_thumbnail(db, video_id: uuid.UUID, key: str) -> None:
    existing = db.query(VideoAsset).filter(
        VideoAsset.video_id == video_id,
        VideoAsset.kind == "thumbnail",
        VideoAsset.label == "poster",
    ).first()
    if existing:
        if existing.storage_key != key:
            existing.storage_key = key
        db.commit()
    else:
        a = VideoAsset(video_id=video_id, kind="thumbnail", label="poster", storage_key=key, meta=None)
        db.add(a)
        db.commit()

def process_video(video_id: str, reason: str) -> None:
    worker_id = f"pid:{os.getpid()}-thr:{threading.get_ident()}"
    got = acquire_lock(video_id, worker_id, settings.worker_lock_ttl_ms)
    if not got:
        log.info(json.dumps({"video_id": video_id, "step": "lock_skip", "reason": "already_locked"}))
        return

    refresher_stop = threading.Event()
    refresher = threading.Thread(target=_lock_refresher, args=(video_id, worker_id, refresher_stop), daemon=True)
    refresher.start()

    try:
        with SessionLocal() as db:
            v = db.get(Video, uuid.UUID(video_id))
            if not v:
                log.warning(json.dumps({"video_id": video_id, "step": "load", "error": "missing_video"}))
                return
            if v.status == "uploaded":
                v.status = "processing"
                v.error = None
                db.commit()

        log.info(json.dumps({"video_id": video_id, "step": "pipeline_start", "reason": reason}))

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
                    v.duration_seconds = str(duration) if duration is not None else None
                    v.error = None
                    db.commit()

            # HLS 720p: skip if playlist exists
            playlist_key = build_hls_key(video_id, "720p", "index.m3u8")
            exists, _ = object_exists(settings.s3_bucket, playlist_key)
            if not exists:
                out_dir = os.path.join(tmpd, "hls_720p")
                _transcode_hls_720p(local_raw, out_dir, gop)
                upload_dir(settings.s3_bucket, f"hls/{video_id}/720p", out_dir)
            else:
                log.info(json.dumps({"video_id": video_id, "step": "hls_720p", "skip": "exists"}))

            # HLS 480p
            playlist_key_480 = build_hls_key(video_id, "480p", "index.m3u8")
            exists480, _ = object_exists(settings.s3_bucket, playlist_key_480)
            if not exists480:
                out_dir_480 = os.path.join(tmpd, "hls_480p")
                _transcode_hls_480p(local_raw, out_dir_480, gop)
                upload_dir(settings.s3_bucket, f"hls/{video_id}/480p", out_dir_480)
            else:
                log.info(json.dumps({"video_id": video_id, "step": "hls_480p", "skip": "exists"}))

            # Thumbnail
            thumb_key = build_thumbnail_key(video_id)
            exists_thumb, _ = object_exists(settings.s3_bucket, thumb_key)
            if not exists_thumb:
                thumb_local = os.path.join(tmpd, "poster.jpg")
                _generate_thumbnail(local_raw, thumb_local)
                # Reuse upload_dir would add directory; upload single file instead:
                from storage import client, _guess_content_type  # reuse content-type helper
                c = client()
                c.fput_object(settings.s3_bucket, thumb_key, thumb_local, content_type=_guess_content_type(thumb_local))
            else:
                log.info(json.dumps({"video_id": video_id, "step": "thumbnail", "skip": "exists"}))

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
                if ok720 and ok480 and okthumb:
                    v.status = "ready"
                    v.error = None
                else:
                    # Keep processing if partial; retries/idempotency will fill in
                    v.status = "processing"
                db.commit()

        redis_client.delete(_attempts_key(video_id))
        log.info(json.dumps({"video_id": video_id, "step": "finalize", "ready": ok720 and ok480 and okthumb}))

    except Exception as e:
        log.exception("process_video_failed")
        attempts = int(redis_client.incr(_attempts_key(video_id)))
        delay = _backoff_for_attempt(attempts)
        if delay is not None:
            log.info(json.dumps({"video_id": video_id, "step": "retry", "attempts": attempts, "delay_sec": delay}))
            time.sleep(delay)
            redis_client.lpush(QUEUE_KEY, json.dumps({"video_id": video_id, "reason": "retry"}))
        else:
            with SessionLocal() as db:
                v = db.get(Video, uuid.UUID(video_id))
                if v:
                    v.status = "failed"
                    v.error = str(e)
                    db.commit()
            log.error(json.dumps({"video_id": video_id, "step": "failed_terminal", "error": str(e)}))
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
def ready():
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
    return {"ok": ok_db and ok_cache, "db": ok_db, "cache": ok_cache}