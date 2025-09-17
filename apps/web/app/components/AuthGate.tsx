'use client';

import React from 'react';
import { useAuth } from '../providers/AuthProvider';
import SignIn from './SignIn';

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const { me, loading } = useAuth();
  if (loading) return null;
  if (!me) return <SignIn />;
  return <>{children}</>;
}


