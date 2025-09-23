'use client';

import { useEffect, useMemo, useState } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

type VideoItem = { id: string; status: 'uploaded'|'processing'|'ready'|'failed'; original_filename: string; created_at: string; };
type PageResp = { items: VideoItem[]; next_offset?: number };
type Asset = { kind: string; label: string; storage_key: string; public_url?: string };
type Detail = { id: string; status: string; assets: Asset[]; };

function Card({ v, poster }: { v: VideoItem; poster?: string }) {
  return (
    <div className="text-neutral-100">
      <div className="relative rounded-xl overflow-hidden bg-neutral-800">
        {poster ? (
          <img src={poster} alt="" className="w-full aspect-video object-cover" />
        ) : (
          <div className="w-full aspect-video grid place-items-center text-neutral-400">No thumbnail</div>
        )}
        <div className="absolute bottom-1 right-1 bg-neutral-900/80 text-neutral-100 text-xs px-1.5 py-0.5 rounded">
          {v.status === 'ready' ? '12:34' : v.status}
        </div>
      </div>
      <div className="mt-2 flex gap-3">
        <div className="w-9 h-9 rounded-full bg-neutral-700 shrink-0 grid place-items-center text-xs">R</div>
        <div className="min-w-0">
          <div className="font-medium leading-snug line-clamp-2">{v.original_filename}</div>
          <div className="text-xs text-neutral-400 mt-1">Streemm • {new Date(v.created_at).toLocaleDateString()}</div>
        </div>
        <button className="ml-auto self-start p-1.5 rounded-full hover:bg-neutral-800" aria-label="More">⋯</button>
      </div>
    </div>
  );
}

export default function HomeFeed() {
  return (
    <div className="px-4 md:pl-6">
      <div className="py-6 text-sm text-neutral-400">Home feed coming soon.</div>
    </div>
  );
}