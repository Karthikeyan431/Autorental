import { useEffect, useState } from 'react';
import { NavLink, Outlet } from 'react-router';

import { strings } from '../lib/strings';
import { ApiStatus } from './ApiStatus';
import { APP_PAGES, type NavGroup } from './routes';

const GROUP_ORDER: NavGroup[] = ['overview', 'drivers', 'fleet', 'money', 'admin'];
const NAV_ID = 'main-navigation';

function Navigation({ onNavigate }: { onNavigate: () => void }) {
  return (
    <nav id={NAV_ID} aria-label={strings.nav.main} className="flex flex-col gap-5 p-4">
      {GROUP_ORDER.map((group) => (
        <div key={group}>
          <p className="px-2 text-xs font-semibold tracking-wide text-slate-500 uppercase">
            {strings.nav.groups[group]}
          </p>
          <ul className="mt-1 flex flex-col">
            {APP_PAGES.filter((page) => page.inNav && page.group === group).map((page) => (
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
export function AppShell() {
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
        <span className="ml-auto">
          <ApiStatus />
        </span>
      </header>

      <div className="flex">
        {/* Wide screens: fixed sidebar. Phones: drawer with a backdrop. */}
        <aside
          className={`${
            menuOpen ? 'fixed inset-y-14 left-0 z-20 block' : 'hidden'
          } w-64 shrink-0 overflow-y-auto border-r border-slate-200 bg-white md:sticky md:top-14 md:block md:h-[calc(100dvh-3.5rem)]`}
        >
          <Navigation onNavigate={closeMenu} />
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
