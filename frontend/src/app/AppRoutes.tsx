import { Navigate, Route, Routes, useLocation } from 'react-router';

import { Loading } from '../components/ui/Loading';
import { homePath, useAuth } from '../features/auth/auth-context';
import { strings } from '../lib/strings';
import { AppShell } from './AppShell';
import { NotFoundPage } from './NotFoundPage';
import { APP_PAGES, canOpen, type AppPage } from './routes';

/** Signed-in area: restores the session, then forces a password change when required. */
function RequireAuth() {
  const { state } = useAuth();
  const location = useLocation();
  if (state.status === 'loading') {
    return (
      <div className="flex min-h-dvh items-center justify-center">
        <Loading label={strings.auth.restoring} />
      </div>
    );
  }
  if (state.status === 'signedOut') {
    return <Navigate to="/sign-in" replace state={{ from: location.pathname }} />;
  }
  if (state.user.must_change_password && location.pathname !== '/change-password') {
    return <Navigate to="/change-password" replace />;
  }
  return <AppShell />;
}

function NoAccess() {
  return (
    <section className="flex flex-col gap-2">
      <h1 className="text-2xl font-semibold text-slate-900">{strings.auth.noAccess}</h1>
    </section>
  );
}

/** A page the user may not open: dashboards send you to your own; anything else says so. */
function Guarded({ page }: { page: AppPage }) {
  const { user } = useAuth();
  if (!user) return null;
  if (canOpen(page, user)) return <page.Component />;
  if (page.access?.role) return <Navigate to={homePath(user)} replace />;
  return <NoAccess />;
}

export function AppRoutes() {
  return (
    <Routes>
      {APP_PAGES.filter((page) => !page.inShell).map(({ path, Component }) => (
        <Route key={path} path={path} element={<Component />} />
      ))}
      <Route element={<RequireAuth />}>
        {APP_PAGES.filter((page) => page.inShell).map((page) => (
          <Route key={page.path} path={page.path} element={<Guarded page={page} />} />
        ))}
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
