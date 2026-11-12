import { Route, Routes } from 'react-router';

import { AppShell } from './AppShell';
import { NotFoundPage } from './NotFoundPage';
import { APP_PAGES } from './routes';

export function AppRoutes() {
  return (
    <Routes>
      {APP_PAGES.filter((page) => !page.inShell).map(({ path, Component }) => (
        <Route key={path} path={path} element={<Component />} />
      ))}
      <Route element={<AppShell />}>
        {APP_PAGES.filter((page) => page.inShell).map(({ path, Component }) => (
          <Route key={path} path={path} element={<Component />} />
        ))}
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
