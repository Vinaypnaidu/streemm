// apps/web/app/components/Sidebar.tsx
"use client";

import Link from "next/link";
import { useAuth } from "../providers/AuthProvider";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";

function Item({
  href,
  label,
  icon,
  active,
}: {
  href: string;
  label: string;
  icon: React.ReactNode;
  active?: boolean;
}) {
  return (
    <Link
      href={href}
      className={`flex items-center gap-4 px-3 py-2 rounded-xl ${active ? "bg-neutral-800 text-neutral-100" : "hover:bg-neutral-800 text-neutral-200"}`}
    >
      <span className="w-5 h-5 flex items-center justify-center">{icon}</span>
      <span className="text-sm">{label}</span>
    </Link>
  );
}

export default function Sidebar() {
  const { me, loading } = useAuth();
  const pathname = usePathname();
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);
  if (!mounted || loading || !me) return null;

  return (
    <aside className="fixed top-14 left-0 w-56 h-[calc(100vh-56px)] border-r border-neutral-900 bg-neutral-900 text-neutral-100 px-2">
      <nav className="py-3 space-y-2">
        <Item
          href="/"
          label="Home"
          icon={<span>🏠</span>}
          active={pathname === "/"}
        />
        <Item
          href="/history"
          label="History"
          icon={<span>🕘</span>}
          active={pathname?.startsWith("/history")}
        />
        <Item
          href="/videos"
          label="Your videos"
          icon={<span>🎞️</span>}
          active={pathname?.startsWith("/videos")}
        />
      </nav>
      <div className="absolute bottom-0 left-0 right-0 border-t border-neutral-900 bg-neutral-900 p-2">
        <div className="flex items-center gap-4 px-3 py-2 rounded-xl text-sm text-neutral-300">
          <span className="w-5 h-5 flex items-center justify-center">
            <span className="text-[14px]">👤</span>
          </span>
          <span className="truncate" title={me.email}>
            {me.email}
          </span>
        </div>
      </div>
    </aside>
  );
}
