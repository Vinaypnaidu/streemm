'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

type FeedItem = {
  id: string;
  title: string;
  description: string;
  thumbnail_url?: string;
  duration_seconds?: number;
  progress_percent?: number | null;
};
type FeedResp = { items: FeedItem[]; source: 'keywords' | 'random' };

function ProgressBar({ percent }: { percent?: number | null }) {
  const pct = Math.max(0, Math.min(100, Math.round(percent ?? 0)));
  return (
    <div className="h-1 bg-neutral-800 rounded">
      <div className="h-1 bg-neutral-100 rounded" style={{ width: `${pct}%` }} />
    </div>
  );
}

export default function HomeFeed() {
  const [data, setData] = useState<FeedResp | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    async function run() {
      try {
        const res = await fetch(`${API_BASE}/homefeed`, { credentials: 'include' });
        if (!res.ok) throw new Error(`Request failed (${res.status})`);
        const json = (await res.json()) as FeedResp;
        if (alive) setData(json);
      } catch (e: any) {
        if (alive) setErr(e?.message || 'Failed to load');
      } finally {
        if (alive) setLoading(false);
      }
    }
    run();
    return () => { alive = false; };
  }, []);

  return (
    <div className="px-12 py-8">
      <h1 className="text-3xl font-semibold mb-4">For you</h1>
      {loading && !data ? (
        <p className="text-sm text-neutral-600">Loading…</p>
      ) : err ? null : !data || data.items.length === 0 ? null : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data.items.map(v => {
            const name = (v.title && v.title.trim()) || 'Untitled';
            return (
              <div key={v.id} className="relative rounded-lg overflow-hidden bg-neutral-900">
                <div className="p-4 pb-0">
                  <Link href={`/videos/${v.id}`} className="block">
                    {v.thumbnail_url ? (
                      <img
                        src={v.thumbnail_url}
                        alt=""
                        className="w-full aspect-video object-cover rounded-md"
                      />
                    ) : (
                      <div className="w-full aspect-video grid place-items-center text-neutral-400 bg-neutral-800 rounded-md">
                        No thumbnail
                      </div>
                    )}
                  </Link>
                </div>
                <div className="p-4">
                  <div className="mb-3">
                    <ProgressBar percent={v.progress_percent ?? 0} />
                  </div>
                  <Link href={`/videos/${v.id}`} className="block font-medium text-sm truncate pr-2 hover:underline" title={name}>
                    {name}
                  </Link>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}