import { useEffect, useState } from 'react';
import { Link, NavLink, Outlet } from 'react-router';

import { Button } from '../components/ui/Button';
import type { User } from '../features/auth/api';
import { useAuth } from '../features/auth/auth-context';
import { strings } from '../lib/strings';
import { ApiStatus } from './ApiStatus';
import { APP_PAGES, canOpen, type NavGroup } from './routes';

const GROUP_ORDER: NavGroup[] = ['overview', 'drivers', 'fleet', 'money', 'admin'];
const NAV_ID = 'main-navigation';

function Navigation({ user, onNavigate }: { user: User; onNavigate: () => void }) {
  const visible = APP_PAGES.filter((page) => page.inNav && canOpen(page, user));
  return (
    <nav id={NAV_ID} aria-label={strings.nav.main} className="flex flex-col gap-5 p-4">
      {GROUP_ORDER.filter((group) => visible.some((page) => page.group === group)).map((group) => (
        <div key={group}>
          <p className="px-2 text-xs font-semibold tracking-wide text-slate-500 uppercase">
            {strings.nav.groups[group]}
          </p>
          <ul className="mt-1 flex flex-col">
            {visible
              .filter((page) => page.group === group)
              .map((page) => (
                <li key={page.path}>
                  <NavLink
                    to={page.path}
                    end
                    onClick={onNavigate}
                    className={({ isActive }) =>
                      `block rounded-md px-2 py-2 text-sm ${
                        isActive
                          ? 'bg-teal-50 font-medium text-teal-900'
                          : 'text-slate-700 hover:bg-slate-100'
                      }`
                    }
                  >
                    {page.title}
                  </NavLink>
                </li>
              ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}

/** Sidebar on wide screens; a drawer behind the menu button on phones. */
function UserMenu({ user, onSignOut }: { user: User; onSignOut: () => void }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="hidden text-slate-700 sm:inline">
        {user.name}{' '}
        <span className="text-slate-500">
          ({user.role === 'owner' ? strings.auth.roleOwner : strings.auth.roleStaff})
        </span>
      </span>
      <Link
        to="/change-password"
        className="hidden rounded-md px-2 py-2 text-slate-700 hover:bg-slate-100 sm:inline"
      >
        {strings.auth.changePassword}
      </Link>
      <Button variant="secondary" onClick={onSignOut}>
        {strings.auth.signOut}
      </Button>
    </div>
  );
}

export function AppShell() {
  const { user, signOut } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (!menuOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMenuOpen(false);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [menuOpen]);

  const closeMenu = () => setMenuOpen(false);

  return (
    <div className="min-h-dvh bg-slate-50 text-slate-900">
      <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-slate-200 bg-white px-4">
        <button
          type="button"
          className="inline-flex size-10 items-center justify-center rounded-md text-slate-700 hover:bg-slate-100 md:hidden"
          aria-label={strings.nav.openMenu}
          aria-controls={NAV_ID}
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((open) => !open)}
        >
          <span aria-hidden="true">☰</span>
        </button>
        <span className="font-semibold text-teal-900">{strings.appName}</span>
        <span className="ml-auto hidden md:inline">
          <ApiStatus />
        </span>
        {user && (
          <span className="ml-auto md:ml-4">
            <UserMenu user={user} onSignOut={() => void signOut()} />
          </span>
        )}
      </header>

      <div className="flex">
        {/* Wide screens: fixed sidebar. Phones: drawer with a backdrop. */}
        <aside
          className={`${
            menuOpen ? 'fixed inset-y-14 left-0 z-20 block' : 'hidden'
          } w-64 shrink-0 overflow-y-auto border-r border-slate-200 bg-white md:sticky md:top-14 md:block md:h-[calc(100dvh-3.5rem)]`}
        >
          {user && <Navigation user={user} onNavigate={closeMenu} />}
        </aside>
        {menuOpen && (
          <div
            aria-hidden="true"
            className="fixed inset-0 top-14 z-10 bg-slate-900/30 md:hidden"
            onClick={closeMenu}
          />
        )}

        <main className="min-w-0 flex-1 px-4 py-6 md:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
