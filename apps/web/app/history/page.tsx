// apps/web/app/history/page.tsx
"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useAuth } from "../providers/AuthProvider";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type HistoryItem = {
  video_id: string;
  original_filename: string;
  title: string;
  thumbnail_url?: string | null;
  last_position_seconds: number;
  duration_seconds?: number | null;
  progress_percent?: number | null;
  last_watched_at: string;
};

type PageResp = {
  items: HistoryItem[];
  next_offset?: number;
};

function ProgressBar({ percent }: { percent: number }) {
  const pct = Math.max(0, Math.min(100, Math.round(percent)));
  return (
    <div className="h-1 bg-neutral-800 rounded">
      <div
        className="h-1 bg-neutral-100 rounded"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

export default function HistoryPage() {
  const { me, loading } = useAuth();
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [fetching, setFetching] = useState(false);

  async function load() {
    setFetching(true);
    try {
      const res = await fetch(`${API_BASE}/history?limit=50`, {
        credentials: "include",
      });
      if (res.ok) {
        const data: PageResp = await res.json();
        setItems(data.items || []);
      }
    } finally {
      setFetching(false);
    }
  }

  useEffect(() => {
    if (!loading && me) load();
  }, [loading, me]);

  if (loading || !me) return null;

  return (
    <div className="px-8 py-6">
      <h1 className="text-2xl font-semibold mb-4">History</h1>

      {fetching && items.length === 0 ? (
        <p className="text-sm text-neutral-600">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-neutral-600">No watch history yet.</p>
      ) : (
        <div className="space-y-4">
          {items.map((it) => {
            const name = (it.title && it.title.trim()) || it.original_filename;
            const pct =
              it.progress_percent ??
              (it.duration_seconds && it.duration_seconds > 0
                ? (it.last_position_seconds / it.duration_seconds) * 100
                : 0);
            return (
              <div
                key={it.video_id}
                className="w-full rounded-lg border border-neutral-800 bg-neutral-900"
              >
                <div className="flex gap-4 p-4">
                  <Link
                    href={`/videos/${it.video_id}?t=${Math.max(0, Math.floor(it.last_position_seconds || 0))}`}
                    className="shrink-0"
                  >
                    {it.thumbnail_url ? (
                      <img
                        src={it.thumbnail_url}
                        alt=""
                        className="w-80 aspect-video object-cover rounded-md"
                      />
                    ) : (
                      <div className="w-80 aspect-video grid place-items-center text-neutral-400 bg-neutral-800 rounded-md">
                        No thumbnail
                      </div>
                    )}
                  </Link>
                  <div className="min-w-0 flex-1">
                    <Link
                      href={`/videos/${it.video_id}?t=${Math.max(0, Math.floor(it.last_position_seconds || 0))}`}
                      className="font-medium text-sm truncate mr-3 hover:underline"
                      title={name}
                    >
                      {name}
                    </Link>
                    <div className="mt-3">
                      <ProgressBar percent={pct} />
                    </div>
                    <div className="text-xs text-neutral-500 mt-2">
                      Last watched:{" "}
                      {new Date(it.last_watched_at).toLocaleString()}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
