'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useAuth } from '../providers/AuthProvider';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

type VideoItem = {
  id: string;
  status: 'uploaded' | 'processing' | 'ready' | 'failed';
  original_filename: string;
  title: string;
  description: string;
  created_at: string;
  thumbnail_public_url?: string | null;
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
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  async function deleteVideo(id: string) {
    try {
      setDeletingId(id);
      // Get CSRF token
      const resCsrf = await fetch(`${API_BASE}/auth/csrf`, { credentials: 'include' });
      const dataCsrf = await resCsrf.json();
      const csrf = dataCsrf.csrf;
      const headerName = dataCsrf.header || 'x-csrf-token';

      const res = await fetch(`${API_BASE}/videos/${id}`, {
        method: 'DELETE',
        credentials: 'include',
        headers: {
          [headerName]: csrf,
        },
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Delete failed (${res.status})`);
      }
      // Remove from local list
      setItems(prev => prev.filter(v => v.id !== id));
    } catch (e: any) {
      alert(e.message || 'Failed to delete');
    } finally {
      setDeletingId(null);
      setMenuFor(null);
    }
  }

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

  const shouldPoll = useMemo(
    () => items.some(i => i.status === 'uploaded' || i.status === 'processing'),
    [items]
  );
  useEffect(() => {
    if (!shouldPoll) return;
    const t = setInterval(load, 7000);
    return () => clearInterval(t);
  }, [shouldPoll]);

  if (loading || !me) return null;

  return (
    <div className="px-10 py-8">
      <h1 className="text-2xl font-semibold mb-4">Your videos</h1>
      {fetching && items.length === 0 ? (
        <p className="text-sm text-neutral-600">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-neutral-600">No videos yet. Use the “+ Create” button to upload.</p>
      ) : (
        // <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        //   {items.map(v => {
        //     const name = (v.title && v.title.trim()) || v.original_filename;
        //     return (
        //       <div key={v.id} className="rounded-lg overflow-hidden bg-neutral-900">
        //         <Link href={`/videos/${v.id}`} className="block">
        //           {v.thumbnail_public_url ? (
        //             <img
        //               src={v.thumbnail_public_url}
        //               alt=""
        //               className="w-full aspect-video object-cover"
        //             />
        //           ) : (
        //             <div className="w-full aspect-video grid place-items-center text-neutral-400 bg-neutral-800">
        //               No thumbnail
        //             </div>
        //           )}
        //         </Link>
        //         <div className="p-4">
        //           <div className="flex items-center justify-between mb-2">
        //             <Link href={`/videos/${v.id}`} className="font-medium text-sm truncate mr-3 hover:underline" title={name}>
        //               {name}
        //             </Link>
        //             <StatusBadge status={v.status} />
        //           </div>
        //           <div className="text-xs text-neutral-500">Created: {new Date(v.created_at).toLocaleString()}</div>
        //         </div>
        //       </div>
        //     );
        //   })}
        // </div>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {items.map(v => {
            const name = (v.title && v.title.trim()) || v.original_filename;
            const open = menuFor === v.id;
            return (
              <div key={v.id} className="relative rounded-lg overflow-hidden bg-neutral-900">
                <Link href={`/videos/${v.id}`} className="block">
                  {v.thumbnail_public_url ? (
                    <img
                      src={v.thumbnail_public_url}
                      alt=""
                      className="w-full aspect-video object-cover"
                    />
                  ) : (
                    <div className="w-full aspect-video grid place-items-center text-neutral-400 bg-neutral-800">
                      No thumbnail
                    </div>
                  )}
                </Link>

                {/* 3-dots menu trigger */}
                <button
                  className="absolute top-2 right-2 p-2 rounded-md bg-neutral-900/70 hover:bg-neutral-800"
                  onClick={() => setMenuFor(open ? null : v.id)}
                  aria-haspopup="menu"
                  aria-expanded={open}
                >
                  ⋯
                </button>

                {/* Menu */}
                {open && (
                  <div className="absolute top-10 right-2 z-10 w-36 rounded-md border border-neutral-800 bg-neutral-900 shadow-lg">
                    <button
                      className="w-full text-left px-3 py-2 text-sm hover:bg-neutral-800 disabled:opacity-50"
                      onClick={() => {
                        if (confirm('Delete this video? This cannot be undone.')) {
                          deleteVideo(v.id);
                        } else {
                          setMenuFor(null);
                        }
                      }}
                      disabled={!!deletingId}
                    >
                      {deletingId === v.id ? 'Deleting…' : 'Delete'}
                    </button>
                  </div>
                )}

                <div className="p-4">
                  <div className="flex items-center justify-between mb-2">
                    <Link href={`/videos/${v.id}`} className="font-medium text-sm truncate mr-3 hover:underline" title={name}>
                      {name}
                    </Link>
                    <StatusBadge status={v.status} />
                  </div>
                  <div className="text-xs text-neutral-500">Created: {new Date(v.created_at).toLocaleString()}</div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}