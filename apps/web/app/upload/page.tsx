// apps/web/app/upload/page.tsx
'use client';

import React, { useEffect, useState, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '../providers/AuthProvider';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

type PresignResponse = {
  video_id: string;
  raw_key: string;
  put_url: string;
  headers: Record<string, string>;
};

export default function UploadPage() {
    const router = useRouter();
    const { me, loading } = useAuth();
    const [csrf, setCsrf] = useState<string>('');
    const [csrfHeader, setCsrfHeader] = useState<string>('x-csrf-token');
    const [file, setFile] = useState<File | null>(null);
    const [progress, setProgress] = useState<number>(0);
    const [status, setStatus] = useState<string>('');
    const [result, setResult] = useState<PresignResponse | null>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);


  useEffect(() => {
    if (!loading && !me) {
        router.replace('/');
    }
    }, [loading, me, router]);
    

  useEffect(() => {
    // Fetch CSRF on mount
    (async () => {
        try {
        const res = await fetch(`${API_BASE}/auth/csrf`, {
            credentials: 'include',
        });
        const data = await res.json();
        setCsrf(data.csrf);
        setCsrfHeader(data.header || 'x-csrf-token');
        } catch (e) {
        console.error(e);
        }
    })();
    }, []);

  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] || null;
    setFile(f);
    setProgress(0);
    setStatus('');
    setResult(null);
  };

  const onUpload = async () => {
    if (!file) {
      setStatus('Select a file first.');
      return;
    }
    if (file.type !== 'video/mp4') {
      setStatus('Only video/mp4 is allowed.');
      return;
    }

    setStatus('Requesting presigned URL...');
    try {
      const presignRes = await fetch(`${API_BASE}/uploads/presign`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          [csrfHeader]: csrf,
        },
        body: JSON.stringify({
          filename: file.name,
          content_type: file.type,
          size_bytes: file.size,
        }),
      });
      if (!presignRes.ok) {
        const err = await presignRes.json().catch(() => ({}));
        throw new Error(err.detail || `Presign failed (${presignRes.status})`);
      }
      const presign: PresignResponse = await presignRes.json();
      setResult(presign);

      setStatus('Uploading to object storage...');
      await uploadWithProgress(presign.put_url, file, presign.headers);
      setProgress(100);

      // Auto-finalize after successful upload
      setStatus('Finalizing upload...');
      const originalName = file.name;
      const finRes = await fetch(`${API_BASE}/videos`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          [csrfHeader]: csrf,
        },
        body: JSON.stringify({
          video_id: presign.video_id,
          raw_key: presign.raw_key,
          original_filename: originalName,
        }),
      });
      if (!finRes.ok) {
        const err = await finRes.json().catch(() => ({}));
        throw new Error(err.detail || `Finalize failed (${finRes.status})`);
      }
      const detail: any = await finRes.json();
      setStatus(`Finalized. Status: ${detail.status || 'processing'}. video_id=${presign.video_id}`);

      // Clear selection (keep result visible for reference)
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
    } catch (e: any) {
      setStatus(`Error: ${e.message || String(e)}`);
    }
  };

  const uploadWithProgress = (url: string, blob: Blob, headers: Record<string, string>) => {
    return new Promise<void>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('PUT', url, true);
      // Do not send credentials to MinIO presigned URL
      Object.entries(headers || {}).forEach(([k, v]) => {
        xhr.setRequestHeader(k, v);
      });
      xhr.upload.onprogress = (evt) => {
        if (evt.lengthComputable) {
          const pct = Math.round((evt.loaded / evt.total) * 100);
          setProgress(pct);
        }
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          setProgress(100);
          resolve();
        } else {
          reject(new Error(`PUT failed (${xhr.status})`));
        }
      };
      xhr.onerror = () => reject(new Error('Network error during upload'));
      xhr.send(blob);
    });
  };

  // ... hooks and helpers above ...
  if (loading || !me) return null;

  return (
    <div className="min-h-[calc(100vh-56px)] flex items-center justify-center px-6">
      <div className="w-full max-w-xl mx-auto">
        <div className="border border-neutral-800 rounded-2xl p-6 shadow-sm bg-neutral-900 text-neutral-100">
          <header className="text-center mb-6">
            <h1 className="text-2xl font-semibold tracking-tight">Upload a video</h1>
            <p className="mt-2 text-sm text-neutral-400">
              MP4 only for now. Keep the tab open during upload.
            </p>
          </header>

          {status && <p className="mb-3 text-sm text-center text-neutral-200">{status}</p>}

          <div className="grid gap-5">
            <div>
              <label className="block text-sm font-medium mb-1">Select file</label>

              {/* Hidden input + styled trigger */}
              <input
                id="video-file"
                type="file"
                accept="video/mp4"
                onChange={onFileChange}
                className="sr-only"
                ref={fileInputRef}
              />

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <label
                  htmlFor="video-file"
                  className="w-full text-center rounded-full border border-neutral-700 px-5 py-3 font-medium hover:bg-neutral-800 transition cursor-pointer"
                >
                  Choose file
                </label>

                <button
                  onClick={onUpload}
                  disabled={!file}
                  className="w-full rounded-full bg-neutral-100 text-neutral-900 px-5 py-3 font-medium hover:opacity-90 disabled:opacity-50 transition"
                >
                  {progress > 0 && progress < 100 ? 'Uploading…' : 'Upload'}
                </button>
              </div>

              <p className="mt-2 text-xs text-neutral-400 h-5 truncate text-center sm:text-left">
                {file ? `${file.name} (${Math.round(file.size / 1024 / 1024)} MB)` : ' '}
              </p>
            </div>

            {progress > 0 && (
              <div>
                <div className="h-2 bg-neutral-800 rounded">
                  <div className="h-2 bg-neutral-100 rounded" style={{ width: `${progress}%` }} />
                </div>
                <div className="text-sm text-neutral-300 mt-1 text-center">{progress}%</div>
              </div>
            )}

            {result && (
              <div className="text-sm text-neutral-300">
                <div><span className="font-medium text-neutral-100">video_id:</span> {result.video_id}</div>
                <div><span className="font-medium text-neutral-100">raw_key:</span> {result.raw_key}</div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}