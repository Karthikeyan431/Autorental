import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router';

import { AppRoutes } from '../app/AppRoutes';
import { ToastProvider } from '../components/ui/Toast';
import { AuthProvider } from '../features/auth/AuthProvider';
import type { User } from '../features/auth/api';
import { setAccessToken } from '../lib/session';
import { ownerUser } from './users';

/**
 * Render the whole app at `path`, with fresh providers and no retries. Signed in as the fake
 * owner by default; pass `user: null` to start signed out (the app then tries a refresh).
 */
export function renderApp(path: string, { user = ownerUser }: { user?: User | null } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  setAccessToken(user ? 'test-access-token' : null);
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <AuthProvider initialUser={user ?? undefined}>
          <MemoryRouter initialEntries={[path]}>
            <AppRoutes />
          </MemoryRouter>
        </AuthProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}
