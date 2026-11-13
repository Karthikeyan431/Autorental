import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import { createRefreshCoordinator, type RefreshCoordinator } from '../../lib/refresh-coordinator';
import { setAccessToken, setRefreshHandler, setSessionExpiredHandler } from '../../lib/session';
import { logout, refreshSession, type SignedIn, type User } from './api';
import { AuthContext, type AuthApi, type AuthState } from './auth-context';

/**
 * Holds the signed-in user. On start it tries to restore the session from the refresh cookie,
 * so reloading the page keeps you signed in. Only one refresh runs at a time, in this tab and
 * across tabs (lib/refresh-coordinator.ts); a refresh or sign-out in one tab reaches the others.
 */
export function AuthProvider({
  children,
  initialUser,
}: {
  children: ReactNode;
  /** Tests start signed in without calling the API. */
  initialUser?: User;
}) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<AuthState>(
    initialUser ? { status: 'signedIn', user: initialUser } : { status: 'loading' },
  );
  const inFlight = useRef<Promise<boolean> | null>(null);

  const completeSignIn = useCallback((result: SignedIn) => {
    setAccessToken(result.access_token);
    setState({ status: 'signedIn', user: result.user });
  }, []);

  const clear = useCallback(() => {
    setAccessToken(null);
    queryClient.clear();
    setState({ status: 'signedOut' });
  }, [queryClient]);

  // Created in an effect (and closed in its cleanup) so StrictMode's remount gets a live
  // channel. Remote events go through a ref to the latest handlers.
  const coordinator = useRef<RefreshCoordinator<SignedIn> | null>(null);
  const remote = useRef({ refreshed: completeSignIn, signedOut: clear });
  useEffect(() => {
    remote.current = { refreshed: completeSignIn, signedOut: clear };
  }, [completeSignIn, clear]);
  useEffect(() => {
    const created = createRefreshCoordinator<SignedIn>({
      callRefresh: refreshSession,
      onRemoteRefresh: (result) => remote.current.refreshed(result),
      onRemoteSignOut: () => remote.current.signedOut(),
    });
    coordinator.current = created;
    return () => {
      created.close();
      if (coordinator.current === created) coordinator.current = null;
    };
  }, []);

  const refresh = useCallback((): Promise<boolean> => {
    if (!inFlight.current) {
      const run = coordinator.current ? coordinator.current.refresh() : refreshSession();
      inFlight.current = run
        .then((result) => {
          completeSignIn(result);
          return true;
        })
        .catch(() => false)
        .finally(() => {
          inFlight.current = null;
        });
    }
    return inFlight.current;
  }, [completeSignIn]);

  useEffect(() => {
    setRefreshHandler(refresh);
    setSessionExpiredHandler(clear);
    return () => {
      setRefreshHandler(null);
      setSessionExpiredHandler(null);
    };
  }, [refresh, clear]);

  useEffect(() => {
    if (initialUser) return;
    let cancelled = false;
    void refresh().then((ok) => {
      if (!ok && !cancelled) setState({ status: 'signedOut' });
    });
    return () => {
      cancelled = true;
    };
  }, [initialUser, refresh]);

  const signOut = useCallback(async () => {
    try {
      await logout();
    } catch {
      // Signing out locally is enough if the server is unreachable or the session is gone.
    }
    coordinator.current?.announceSignOut();
    clear();
  }, [clear]);

  const updateUser = useCallback((user: User) => {
    setState({ status: 'signedIn', user });
  }, []);

  const api = useMemo<AuthApi>(
    () => ({
      state,
      user: state.status === 'signedIn' ? state.user : null,
      completeSignIn,
      updateUser,
      signOut,
    }),
    [state, completeSignIn, updateUser, signOut],
  );

  return <AuthContext.Provider value={api}>{children}</AuthContext.Provider>;
}
