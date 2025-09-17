'use client';

import { useAuth } from '../providers/AuthProvider';

export default function HistoryPage() {
  const { me, loading } = useAuth();
  if (loading || !me) return null;

  return (
    <div className="px-6 py-6">
      <h1 className="text-xl font-semibold mb-2">History</h1>
      <p className="text-sm text-neutral-600">Coming soon.</p>
    </div>
  );
}