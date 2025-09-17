'use client';

import { useState } from 'react';
import { useAuth } from '../providers/AuthProvider';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

type Mode = 'login' | 'register';

export default function SignIn() {
  const { setMe, getCsrf } = useAuth();
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
      setMe(user);
      setPassword('');
    } catch (e: any) {
      setErr(e.message || 'Request failed');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-[100vh] flex items-center justify-center px-6">
      <div className="w-full max-w-2xl">
        <header className="text-center mb-6">
          <div className="flex items-center justify-center gap-2">
            <span className="inline-block w-4 h-4 rounded-sm bg-violet-600" />
            <h1 className="text-6xl font-semibold tracking-tight">Reelay</h1>
          </div>
        </header>

        {err && <p className="mb-3 text-sm text-red-400 text-center">{err}</p>}
        <form onSubmit={onSubmit} className="grid gap-5">
          <div>
            <label className="block text-sm font-medium mb-1">Email</label>
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
              placeholder="you@example.com"
              className="w-full rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-neutral-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">{mode === 'login' ? 'Password' : 'Create a password'}</label>
            <input
              type="password"
              minLength={mode === 'login' ? undefined : 8}
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
              placeholder="••••••••"
              className="w-full rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-neutral-500"
            />
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-full bg-neutral-100 text-neutral-900 px-5 py-[10px] mt-2 font-medium hover:opacity-90 disabled:opacity-50 transition"
          >
            {submitting ? (mode === 'login' ? 'Signing in…' : 'Creating…') : (mode === 'login' ? 'Sign in' : 'Create account')}
          </button>
          <p className="text-center text-sm text-neutral-400">
            {mode === 'login' ? (
              <>No account? <button type="button" onClick={() => setMode('register')} className="text-neutral-100 underline underline-offset-4">Create one</button></>
            ) : (
              <>Already have an account? <button type="button" onClick={() => setMode('login')} className="text-neutral-100 underline underline-offset-4">Log in</button></>
            )}
          </p>
        </form>
      </div>
    </div>
  );
}


