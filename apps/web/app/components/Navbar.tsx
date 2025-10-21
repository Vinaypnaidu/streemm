// apps/web/app/components/Navbar.tsx
"use client";

import Link from "next/link";
import { useAuth } from "../providers/AuthProvider";
import { useEffect, useRef, useState } from "react";
import Sidebar from "./Sidebar";
import { useRouter } from "next/navigation";

export default function Navbar() {
  const { me, loading, logout } = useAuth();
  const [showMenu, setShowMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const [query, setQuery] = useState("");
  const router = useRouter();

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node))
        setShowMenu(false);
    }
    document.addEventListener("click", onDocClick);
    return () => document.removeEventListener("click", onDocClick);
  }, []);

  if (loading || !me) return null;

  function onSearchSubmit(e: React.FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;
    router.push(`/search?q=${encodeURIComponent(q)}`);
  }

  return (
    <>
      <nav className="sticky top-0 z-40 w-full border-b border-neutral-800 bg-neutral-900/95 backdrop-blur">
        <div className="px-4 h-14 flex items-center gap-4 text-neutral-100">
          {/* Left: brand */}
          <div className="flex items-center gap-3">
            <button
              className="p-2 rounded-full hover:bg-neutral-800"
              aria-label="Menu"
            >
              <svg
                width="20"
                height="20"
                viewBox="0 0 24 24"
                className="fill-neutral-200"
              >
                <path d="M3 6h18M3 12h18M3 18h18" />
              </svg>
            </button>
            <Link
              href="/"
              className="flex items-center gap-1 text-2xl font-semibold tracking-tight hover:opacity-80 transition"
            >
              <span className="inline-block w-3 h-3 rounded-sm bg-violet-600 mr-1" />
              Streem
            </Link>
          </div>

          {/* Center: search */}
          <div className="flex-1 flex justify-center">
            <form
              onSubmit={onSearchSubmit}
              className="hidden sm:flex w-full max-w-3xl"
            >
              <input
                placeholder="Search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="w-full rounded-l-full border border-neutral-700 bg-neutral-900 text-neutral-100 px-4 py-2 focus:outline-none focus:ring-1 focus:ring-neutral-400"
              />
              <button
                type="submit"
                className="rounded-r-full border border-neutral-700 border-l-0 px-4 py-2 bg-neutral-800 hover:bg-neutral-700"
                aria-label="Search"
              >
                🔎
              </button>
            </form>
          </div>

          {/* Right: create menu + user */}
          <div
            className="ml-auto flex items-center gap-2 relative"
            ref={menuRef}
          >
            <button
              onClick={() => setShowMenu((v) => !v)}
              className="rounded-full border border-neutral-700 px-4 py-2 text-sm font-medium hover:bg-neutral-800"
              aria-haspopup="menu"
              aria-expanded={showMenu}
            >
              + Create
            </button>
            {showMenu && (
              <div
                role="menu"
                className="absolute right-0 top-12 w-48 rounded-lg border border-neutral-800 bg-neutral-900 shadow-lg"
              >
                <Link
                  href="/upload"
                  className="block px-4 py-2 text-sm hover:bg-neutral-800"
                  onClick={() => setShowMenu(false)}
                >
                  Upload video
                </Link>
                <Link
                  href="/videos"
                  className="block px-4 py-2 text-sm hover:bg-neutral-800"
                  onClick={() => setShowMenu(false)}
                >
                  Your videos
                </Link>
              </div>
            )}
            <button
              onClick={logout}
              className="rounded-full bg-neutral-100 text-neutral-900 px-4 py-2 text-sm font-medium hover:opacity-90"
            >
              Logout
            </button>
          </div>
        </div>
      </nav>

      {/* Sidebar */}
      <Sidebar />
      <div className="hidden md:block w-72" aria-hidden="true" />
    </>
  );
}
