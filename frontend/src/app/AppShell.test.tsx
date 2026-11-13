import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderApp } from '../test/render';
import { ownerUser } from '../test/users';
import { APP_PAGES, canOpen } from './routes';

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'ok', db: 'ok', version: '0.1.0' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    ),
  );
});

describe('App shell', () => {
  it('lists every module the owner can open in the navigation', () => {
    renderApp('/');
    const nav = screen.getByRole('navigation', { name: 'Main' });
    for (const page of APP_PAGES.filter((p) => p.inNav && canOpen(p, ownerUser))) {
      expect(within(nav).getByRole('link', { name: page.title })).toBeInTheDocument();
    }
  });

  // Screens that later milestones build still show their placeholder.
  it.each(APP_PAGES.filter((p) => p.week > 3).map((p) => [p.path, p.title, p.week] as const))(
    '%s shows its empty page',
    (path, title, week) => {
      renderApp(path.replace(':id', '1'));
      expect(screen.getByRole('heading', { level: 1, name: title })).toBeInTheDocument();
      expect(screen.getByText(`Coming in Week ${week}`)).toBeInTheDocument();
    },
  );

  it('covers every screen in requirements §4', () => {
    expect(APP_PAGES.map((p) => p.title)).toEqual(
      expect.arrayContaining([
        'Sign in',
        'Owner dashboard',
        'Staff dashboard',
        'Drivers',
        'Driver',
        'Register driver',
        'KYC queue',
        'Autos',
        'Agreements',
        'Pay requests today',
        'Payments',
        'Bank statements',
        'Escalations',
        'Reports',
        'Staff',
        'Settings',
        'Audit log',
      ]),
    );
  });

  it('marks the current page in the navigation', () => {
    renderApp('/drivers');
    const nav = screen.getByRole('navigation', { name: 'Main' });
    expect(within(nav).getByRole('link', { name: 'Drivers' })).toHaveAttribute(
      'aria-current',
      'page',
    );
  });

  it('opens and closes the menu drawer on small screens', async () => {
    renderApp('/');
    const menuButton = screen.getByRole('button', { name: 'Open menu' });
    expect(menuButton).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(menuButton);
    expect(menuButton).toHaveAttribute('aria-expanded', 'true');
    await userEvent.keyboard('{Escape}');
    expect(menuButton).toHaveAttribute('aria-expanded', 'false');
  });

  it('shows the API status from /api/v1/health', async () => {
    renderApp('/');
    expect(await screen.findByText('API online')).toBeInTheDocument();
  });

  it('shows a not-found page for unknown addresses', () => {
    renderApp('/no-such-page');
    expect(screen.getByRole('heading', { level: 1, name: 'Page not found' })).toBeInTheDocument();
  });
});
