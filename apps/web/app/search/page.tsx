// apps/web/app/search/page.tsx
"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type MetaItem = {
  video_id: string;
  title_html: string;
  description_html: string;
  short_summary?: string | null;
  thumbnail_url?: string | null;
  created_at?: string | null;
  duration_seconds?: number | null;
  score?: number | null;
};

type TranscriptItem = {
  video_id: string;
  title: string;
  thumbnail_url?: string | null;
  progress_seconds: number;
  snippet_html: string;
};

type SearchResponse = {
  search_ok: boolean;
  meta: {
    items: MetaItem[];
    estimated_total: number;
    next_offset?: number | null;
  };
  transcript: {
    items: TranscriptItem[];
    estimated_total: number;
    next_offset?: number | null;
  };
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

function fmtTime(s: number) {
  const sec = Math.max(0, Math.floor(s || 0));
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const r = sec % 60;
  if (h > 0) {
    return `${h}:${m.toString().padStart(2, "0")}:${r.toString().padStart(2, "0")}`;
  }
  return `${m}:${r.toString().padStart(2, "0")}`;
}

export default function SearchPage() {
  const sp = useSearchParams();
  const q = (sp.get("q") || "").trim();

  const [data, setData] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // durations for transcript items
  const [durations, setDurations] = useState<Record<string, number | null>>({});

  async function fetchDurations(ids: string[]) {
    // fetch /videos/{id} to get duration_seconds
    const entries = await Promise.all(
      ids.map(async (id) => {
        try {
          const res = await fetch(`${API_BASE}/videos/${id}`, {
            credentials: "include",
          });
          if (!res.ok) return [id, null] as const;
          const d = await res.json();
          return [
            id,
            typeof d?.duration_seconds === "number" ? d.duration_seconds : null,
          ] as const;
        } catch {
          return [id, null] as const;
        }
      }),
    );
    const m: Record<string, number | null> = {};
    for (const [id, dur] of entries) m[id] = dur;
    setDurations((prev) => ({ ...prev, ...m }));
  }

  useEffect(() => {
    if (!q) {
      setData(null);
      setErr(null);
      return;
    }
    setLoading(true);
    setErr(null);
    (async () => {
      try {
        const res = await fetch(
          `${API_BASE}/search?q=${encodeURIComponent(q)}`,
          { credentials: "include" },
        );
        if (!res.ok) throw new Error(`Search failed (${res.status})`);
        const json: SearchResponse = await res.json();
        setData(json);
        // After transcript results arrive, fetch durations to compute percent bars
        const ids = Array.from(
          new Set((json.transcript?.items || []).map((i) => i.video_id)),
        );
        if (ids.length) fetchDurations(ids);
      } catch (e: any) {
        setErr(e.message || "Search failed");
        setData(null);
      } finally {
        setLoading(false);
      }
    })();
  }, [q]);

  if (!q)
    return (
      <div className="px-12 py-8 text-sm text-neutral-400">
        Type a query to search.
      </div>
    );
  if (loading && !data)
    return (
      <div className="px-12 py-8 text-sm text-neutral-400">Searching…</div>
    );
  if (err)
    return <div className="px-12 py-8 text-sm text-red-400">Error: {err}</div>;

  const meta = data?.meta?.items || [];
  const tx = data?.transcript?.items || [];

  return (
    <div className="px-8 py-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 items-start">
        {/* Left: metadata results */}
        <section>
          <h2 className="text-xl font-semibold mb-3">Videos</h2>
          {meta.length === 0 ? (
            <div className="text-sm text-neutral-500">No metadata matches.</div>
          ) : (
            <div className="space-y-4">
              {meta.map((it) => (
                <div
                  key={it.video_id}
                  className="w-full rounded-lg border border-neutral-800 bg-neutral-900"
                >
                  <div className="flex gap-4 p-4 pr-6">
                    <Link href={`/videos/${it.video_id}`} className="shrink-0">
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
                    <div className="min-w-0 flex-1 pr-4">
                      <Link
                        href={`/videos/${it.video_id}`}
                        className="block font-medium text-sm hover:underline line-clamp-2 mb-1.5"
                        dangerouslySetInnerHTML={{
                          __html: it.title_html || "",
                        }}
                      />
                      {it.duration_seconds && (
                        <p className="text-xs text-neutral-500 mt-1">
                          {fmtTime(it.duration_seconds)}
                        </p>
                      )}
                      {it.short_summary && (
                        <p className="text-xs text-neutral-400 mt-2 line-clamp-6">
                          {it.short_summary}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Right: transcript results */}
        <section>
          <h2 className="text-xl font-semibold mb-3">Jump To Moments</h2>
          {tx.length === 0 ? (
            <div className="text-sm text-neutral-500">
              No transcript matches.
            </div>
          ) : (
            <div className="space-y-4">
              {tx.map((it) => {
                const dur = durations[it.video_id] ?? null;
                const pct =
                  dur && dur > 0 ? (it.progress_seconds / dur) * 100 : 0;
                return (
                  <div
                    key={it.video_id}
                    className="w-full rounded-lg border border-neutral-800 bg-neutral-900"
                  >
                    <div className="flex gap-4 p-4">
                      <Link
                        href={`/videos/${it.video_id}?t=${Math.max(0, Math.floor(it.progress_seconds))}`}
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
                          href={`/videos/${it.video_id}?t=${Math.max(0, Math.floor(it.progress_seconds))}`}
                          className="font-medium text-sm mr-3 hover:underline line-clamp-2"
                          title={it.title}
                        >
                          {it.title}
                        </Link>
                        <div
                          className="text-xs text-neutral-400 mt-1"
                          dangerouslySetInnerHTML={{
                            __html: it.snippet_html || "",
                          }}
                        />
                        <div className="text-xs text-neutral-500 mt-2">
                          Starts at {fmtTime(it.progress_seconds)}
                        </div>
                        <div className="mt-2">
                          <ProgressBar percent={pct} />
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
