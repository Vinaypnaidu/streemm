'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useParams } from 'next/navigation';
import Hls from 'hls.js';
import { useAuth } from '../../providers/AuthProvider';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

type Asset = { kind: string; label: string; storage_key: string; public_url?: string | null };
type Detail = {
  id: string;
  status: 'uploaded' | 'processing' | 'ready' | 'failed';
  original_filename: string;
  title: string;
  description: string;
  created_at: string;
  assets: Asset[];
  resume_from_seconds?: number | null;
  progress_percent?: number | null;
  duration_seconds?: number | null;
};

export default function VideoDetailPage() {
  const params = useParams<{ id: string }>();
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const hlsRef = useRef<Hls | null>(null);

  const [detail, setDetail] = useState<Detail | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [quality, setQuality] = useState<'720p' | '480p' | null>(null);

  const { getCsrf } = useAuth();

  // Desired resume time
  const resumeRef = useRef<number>(0);
  const resumeAppliedRef = useRef<boolean>(false);

  async function load() {
    setLoading(true);
    setErr(null);
    try {
      const res = await fetch(`${API_BASE}/videos/${params.id}`, { credentials: 'include' });
      if (!res.ok) throw new Error(`Failed (${res.status})`);
      const data: Detail = await res.json();
      setDetail(data);
    } catch (e: any) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [params.id]);

  // CSRF is fetched lazily via getCsrf() when sending heartbeats

  // Track resume time from detail
  useEffect(() => {
    if (!detail) return;
    const t = typeof detail.resume_from_seconds === 'number' ? detail.resume_from_seconds || 0 : 0;
    resumeRef.current = Math.max(0, Math.floor(t));
    // allow first attach after new detail to apply resume time
    resumeAppliedRef.current = false;
  }, [detail]);

  const poster = useMemo(
    () => detail?.assets.find(a => a.kind === 'thumbnail' && a.label === 'poster')?.public_url || undefined,
    [detail]
  );

  const hls720 = useMemo(
    () => detail?.assets.find(a => a.kind === 'hls' && a.label === '720p')?.public_url || null,
    [detail]
  );
  const hls480 = useMemo(
    () => detail?.assets.find(a => a.kind === 'hls' && a.label === '480p')?.public_url || null,
    [detail]
  );

  // Default quality: 720p if available, else 480p
  useEffect(() => {
    if (!detail) return;
    if (hls720) setQuality(q => q ?? '720p');
    else if (hls480) setQuality(q => q ?? '480p');
    else setQuality(null);
  }, [detail, hls720, hls480]);

  const hlsSrc = useMemo(() => {
    if (quality === '720p') return hls720;
    if (quality === '480p') return hls480;
    return null;
  }, [quality, hls720, hls480]);

  // Initialize/refresh playback when source changes; preserve current time on quality switch.
  // On the very first attach after load(), use resumeRef.current as the starting time.
  useEffect(() => {
    const video = videoRef.current;
    const src = hlsSrc;
    if (!video || !src) return;

    const prevTime = video.currentTime || 0;
    const wasPaused = video.paused;

    if (hlsRef.current) {
      hlsRef.current.destroy();
      hlsRef.current = null;
    }

    if (video.canPlayType('application/vnd.apple.mpegurl')) {
      const onLoaded = () => {
        try {
          const start = resumeAppliedRef.current ? prevTime : resumeRef.current;
          const isFirst = !resumeAppliedRef.current;
          video.currentTime = start;
          resumeAppliedRef.current = true;
          // Autoplay: on first attach always try; on quality switch, only if previously playing
          if (!wasPaused || isFirst) {
            void video.play().catch(() => {});
          }
        } catch {}
      };
      video.addEventListener('loadedmetadata', onLoaded);
      video.src = src;
      video.load();
      return () => {
        video.removeEventListener('loadedmetadata', onLoaded);
      };
    } else if (Hls.isSupported()) {
      const hls = new Hls({ maxMaxBufferLength: 60 });
      hlsRef.current = hls;
      hls.loadSource(src);
      hls.attachMedia(video);
      const onAttached = () => {
        try {
          const start = resumeAppliedRef.current ? prevTime : resumeRef.current;
          const isFirst = !resumeAppliedRef.current;
          video.currentTime = start;
          resumeAppliedRef.current = true;
          if (!wasPaused || isFirst) {
            void video.play().catch(() => {});
          }
        } catch {}
      };
      hls.on(Hls.Events.MEDIA_ATTACHED, onAttached);
      return () => {
        hls.off(Hls.Events.MEDIA_ATTACHED, onAttached);
        hls.destroy();
        hlsRef.current = null;
      };
    }
  }, [hlsSrc]);

  async function sendHeartbeat(pos: number) {
    const payload = {
      video_id: params.id,
      position_seconds: Math.max(0, Math.floor(pos)),
    } as const;
    async function postOnce(token: string) {
      return fetch(`${API_BASE}/history/heartbeat`, {
        method: 'POST',
        credentials: 'include',
        keepalive: true,
        headers: { 'content-type': 'application/json', 'x-csrf-token': token },
        body: JSON.stringify(payload),
      });
    }
    try {
      let token = await getCsrf();
      let res = await postOnce(token);
      if (res.status === 403) {
        token = await getCsrf();
        await postOnce(token);
      }
    } catch {}
  }

// Heartbeats: throttle via timeupdate (~10s), plus on playing/pause/ended/tab hide/unload
useEffect(() => {
  const video = videoRef.current;
  if (!video) return;

  let lastSentMs = 0;
  const THROTTLE_MS = 10000;

  const sendNow = () => sendHeartbeat(video.currentTime || 0);

  const onPlaying = () => sendNow();
  const onPause = () => sendNow();
  const onEnded = () => sendNow();
  const onTimeUpdate = () => {
    const now = Date.now();
    if (now - lastSentMs >= THROTTLE_MS && !video.paused && !video.ended) {
      lastSentMs = now;
      sendNow();
    }
  };
  const onBeforeUnload = () => sendNow();
  const onVisibilityChange = () => {
    if (document.visibilityState === 'hidden') sendNow();
  };

  video.addEventListener('playing', onPlaying);
  video.addEventListener('pause', onPause);
  video.addEventListener('ended', onEnded);
  video.addEventListener('timeupdate', onTimeUpdate);
  window.addEventListener('beforeunload', onBeforeUnload);
  document.addEventListener('visibilitychange', onVisibilityChange);

  return () => {
    video.removeEventListener('playing', onPlaying);
    video.removeEventListener('pause', onPause);
    video.removeEventListener('ended', onEnded);
    video.removeEventListener('timeupdate', onTimeUpdate);
    window.removeEventListener('beforeunload', onBeforeUnload);
    document.removeEventListener('visibilitychange', onVisibilityChange);
  };
}, [hlsSrc, params.id]);

  if (loading) return <div className="px-6 py-6 text-sm text-neutral-400">Loading…</div>;
  if (err) return <div className="px-6 py-6 text-sm text-red-400">Error: {err}</div>;
  if (!detail) return null;

  const name = (detail.title && detail.title.trim()) || detail.original_filename;

  return (
    <div className="px-10 py-6">
      <div className="mx-auto w-full grid gap-3">
        <h1 className="text-3xl font-semibold">{name}</h1>

        <div className="flex items-center gap-2">
          <span className="text-sm text-neutral-400">Quality:</span>
          <button
            onClick={() => setQuality('720p')}
            disabled={!hls720}
            className={`text-sm px-3 py-1 rounded-md border ${
              quality === '720p' ? 'border-neutral-500 text-neutral-100' : 'border-neutral-700 text-neutral-300'
            } disabled:opacity-50`}
          >
            720p
          </button>
          <button
            onClick={() => setQuality('480p')}
            disabled={!hls480}
            className={`text-sm px-3 py-1 rounded-md border ${
              quality === '480p' ? 'border-neutral-500 text-neutral-100' : 'border-neutral-700 text-neutral-300'
            } disabled:opacity-50`}
          >
            480p
          </button>
        </div>

        <div className="w-full">
          <video
            ref={videoRef}
            controls
            poster={poster}
            autoPlay
            playsInline
            className="w-full rounded-md bg-black"
          />
        </div>
      </div>
    </div>
  );
}