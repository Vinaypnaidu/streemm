'use client';

import { useEffect, useState } from 'react';
import { useAuth } from './providers/AuthProvider';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

type Mode = 'login' | 'register';

export default function Home() {
  const { me, loading, setMe, getCsrf } = useAuth();
  const [mode, setMode] = useState<Mode>('login');

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setSubmitting(true);
    try {
      const csrf = await getCsrf();
      const url = mode === 'login' ? '/auth/login' : '/auth/register';
      const res = await fetch(`${API_BASE}${url}`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'content-type': 'application/json', 'x-csrf-token': csrf },
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || 'Request failed');
      }
      const user = await res.json();
      setMe(user);           // instantly reveals Navbar
      setPassword('');
    } catch (e: any) {
      setErr(e.message || 'Request failed');
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return null;

  return (
    <div className="min-h-screen flex items-center justify-center px-6">
      <div className="w-full max-w-2xl">
        <header className="text-center mb-6">
          <h1 className="text-8xl font-semibold tracking-tight">Reelay</h1>
        </header>

        {!me ? (
          <section className="mx-auto" aria-labelledby="auth-title">
            <div className="text-center mb-6">
              <h2 id="auth-title" className="text-2xl font-medium">
                {mode === 'login' ? 'Welcome back' : 'Create an account'}
              </h2>
              <p className="mt-2 text-sm text-neutral-500">
                {mode === 'login' ? (
                  <>
                    Don&apos;t have an account?{' '}
                    <button
                      type="button"
                      onClick={() => setMode('register')}
                      className="text-neutral-900 underline underline-offset-4"
                    >
                      Create one
                    </button>
                  </>
                ) : (
                  <>
                    Already have an account?{' '}
                    <button
                      type="button"
                      onClick={() => setMode('login')}
                      className="text-neutral-900 underline underline-offset-4"
                    >
                      Log in
                    </button>
                  </>
                )}
              </p>
            </div>

            {err && <p className="mb-3 text-sm text-red-600 text-center">{err}</p>}

            <form onSubmit={onSubmit} className="grid gap-5">
              <div>
                <label className="block text-sm font-medium mb-1">Email</label>
                <input
                  type="email"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  required
                  placeholder="you@example.com"
                  className="w-full rounded-lg border border-neutral-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-neutral-900"
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">
                  {mode === 'login' ? 'Password' : 'Create a password'}
                </label>
                <input
                  type="password"
                  minLength={mode === 'login' ? undefined : 8}
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  required
                  placeholder="••••••••"
                  className="w-full rounded-lg border border-neutral-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-neutral-900"
                />
                <p className="mt-2 text-xs text-neutral-500 h-5">
                  {mode === 'register' ? 'Use 8+ characters with a mix of letters, numbers & symbols.' : ' '}
                </p>
              </div>

              <button
                type="submit"
                disabled={submitting}
                className="w-full rounded-full bg-neutral-900 text-white px-5 py-3 font-medium hover:opacity-90 disabled:opacity-50 transition"
              >
                {submitting ? (mode === 'login' ? 'Signing in…' : 'Creating…') : (mode === 'login' ? 'Sign in' : 'Create account')}
              </button>
            </form>
          </section>
        ) : (
          <section className="text-center">
          <h2 className="text-2xl font-medium mb-2">Welcome</h2>
          <p className="text-neutral-600">
            You are signed in as <span className="font-medium text-neutral-900">{me.email}</span>.
          </p>
        </section>
        )}
      </div>
    </div>
  );
}