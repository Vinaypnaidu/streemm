// apps/web/app/providers/AuthProvider.tsx
"use client";

import React, { createContext, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type Me = { id: string; email: string } | null;

type AuthContextType = {
  me: Me;
  loading: boolean;
  setMe: (me: Me) => void;
  logout: () => Promise<void>;
  getCsrf: () => Promise<string>;
};

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/me`, { credentials: "include" });
        if (mounted && res.ok) setMe(await res.json());
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  async function getCsrf(): Promise<string> {
    const res = await fetch(`${API_BASE}/auth/csrf`, {
      credentials: "include",
    });
    const data = await res.json();
    return data.csrf as string;
  }

  async function logout() {
    try {
      const csrf = await getCsrf();
      await fetch(`${API_BASE}/auth/logout`, {
        method: "POST",
        credentials: "include",
        headers: { "x-csrf-token": csrf },
      });
    } catch {}
    setMe(null);
    router.replace("/");
  }

  return (
    <AuthContext.Provider value={{ me, loading, setMe, logout, getCsrf }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
