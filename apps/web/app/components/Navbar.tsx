'use client';

import Link from 'next/link';
import { useAuth } from '../providers/AuthProvider';

export default function Navbar() {
  const { me, loading, logout } = useAuth();
  if (loading || !me) return null;

  return (
    <nav className="sticky top-0 z-40 w-full border-b border-neutral-200 bg-white/90 backdrop-blur">
      <div className="max-w-6xl mx-auto px-4 h-14 flex items-center">
        <div className="flex items-center gap-8">
          <Link href="/" className="text-lg font-semibold tracking-tight hover:opacity-80 transition">
            Reelay
          </Link>
          <Link
            href="/upload"
            className="text-sm font-medium text-neutral-900 hover:opacity-70 transition"
          >
            Upload
          </Link>
        </div>
        <div className="ml-auto flex items-center gap-3">
          <span className="hidden sm:inline text-sm text-neutral-600">{me.email}</span>
          <button
            onClick={logout}
            className="rounded-full bg-neutral-900 text-white px-4 py-2 text-sm font-medium hover:opacity-90 transition"
          >
            Logout
          </button>
        </div>
      </div>
    </nav>
  );
}