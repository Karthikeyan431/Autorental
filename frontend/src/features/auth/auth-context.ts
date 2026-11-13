import { createContext, useContext } from 'react';

import type { SignedIn, User } from './api';

export type AuthState =
  { status: 'loading' } | { status: 'signedOut' } | { status: 'signedIn'; user: User };

export type AuthApi = {
  state: AuthState;
  user: User | null;
  /** Store the session from a successful sign-in, TOTP step or refresh. */
  completeSignIn: (result: SignedIn) => void;
  updateUser: (user: User) => void;
  signOut: () => Promise<void>;
};

export const AuthContext = createContext<AuthApi | null>(null);

export function useAuth(): AuthApi {
  const api = useContext(AuthContext);
  if (!api) throw new Error('useAuth must be used inside <AuthProvider>.');
  return api;
}

/** The owner has every permission; staff have what the owner granted. */
export function can(user: User | null, permission: string): boolean {
  return user !== null && user.permissions.includes(permission);
}

export function homePath(user: User): string {
  return user.role === 'owner' ? '/' : '/my-dashboard';
}
