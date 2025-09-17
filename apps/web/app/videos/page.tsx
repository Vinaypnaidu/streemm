'use client';

import { useEffect, useMemo, useState } from 'react';
import { useAuth } from '../providers/AuthProvider';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

type VideoItem = {
  id: string;
  status: 'uploaded' | 'processing' | 'ready' | 'failed';
  original_filename: string;
  created_at: string;
};

type PageResp = {
  items: VideoItem[];
  next_offset?: number;
};

function StatusBadge({ status }: { status: VideoItem['status'] }) {
  const cls =
    status === 'ready' ? 'bg-green-100 text-green-800' :
    status === 'processing' ? 'bg-yellow-100 text-yellow-800' :
    status === 'failed' ? 'bg-red-100 text-red-800' :
    'bg-neutral-100 text-neutral-800';
  return <span className={`px-2 py-0.5 rounded text-xs font-medium ${cls}`}>{status}</span>;
}

export default function VideosPage() {
  const { me, loading } = useAuth();
  const [items, setItems] = useState<VideoItem[]>([]);
  const [fetching, setFetching] = useState(false);

  async function load() {
    setFetching(true);
    try {
      const res = await fetch(`${API_BASE}/videos?limit=50`, { credentials: 'include' });
      if (res.ok) {
        const data: PageResp = await res.json();
        setItems(data.items || []);
      }
    } finally {
      setFetching(false);
    }
  }

  useEffect(() => { if (!loading && me) load(); }, [loading, me]);

  // Poll every 7s while anything is not ready/failed
  const shouldPoll = useMemo(() => items.some(i => i.status === 'uploaded' || i.status === 'processing'), [items]);
  useEffect(() => {
    if (!shouldPoll) return;
    const t = setInterval(load, 7000);
    return () => clearInterval(t);
  }, [shouldPoll]);

  if (loading || !me) return null;

  return (
    <div className="px-6 py-6">
      <h1 className="text-xl font-semibold mb-4">Your videos</h1>
      {fetching && items.length === 0 ? (
        <p className="text-sm text-neutral-600">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-neutral-600">No videos yet. Use the “+ Create” button to upload.</p>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {items.map(v => (
            <div key={v.id} className="border border-neutral-200 rounded-xl p-4">
              <div className="flex items-center justify-between mb-2">
                <div className="font-medium text-sm truncate mr-3" title={v.original_filename}>
                  {v.original_filename}
                </div>
                <StatusBadge status={v.status} />
              </div>
              <div className="text-xs text-neutral-500">ID: {v.id}</div>
              <div className="text-xs text-neutral-500">Created: {new Date(v.created_at).toLocaleString()}</div>
              {/* Detail/Player page can be added later */}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}