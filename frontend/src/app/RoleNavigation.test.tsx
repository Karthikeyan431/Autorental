import { screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { mockApi } from '../test/mock-api';
import { renderApp } from '../test/render';
import { ownerUser, staffUser } from '../test/users';

afterEach(() => {
  vi.unstubAllGlobals();
});

const OWNER_ONLY_LINKS = ['Owner dashboard', 'Staff', 'Settings', 'Audit log', 'Bank statements'];

describe('Role-aware navigation', () => {
  it('hides owner pages from staff', () => {
    mockApi({});
    renderApp('/my-dashboard', { user: staffUser });
    const nav = screen.getByRole('navigation', { name: 'Main' });
    for (const name of OWNER_ONLY_LINKS) {
      expect(within(nav).queryByRole('link', { name })).not.toBeInTheDocument();
    }
    expect(within(nav).getByRole('link', { name: 'Staff dashboard' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Drivers' })).toBeInTheDocument();
  });

  it('shows bank statements to staff granted statements.upload', () => {
    mockApi({});
    renderApp('/my-dashboard', {
      user: { ...staffUser, permissions: [...staffUser.permissions, 'statements.upload'] },
    });
    const nav = screen.getByRole('navigation', { name: 'Main' });
    expect(within(nav).getByRole('link', { name: 'Bank statements' })).toBeInTheDocument();
  });

  it('shows the owner everything except the staff dashboard', () => {
    mockApi({});
    renderApp('/', { user: ownerUser });
    const nav = screen.getByRole('navigation', { name: 'Main' });
    for (const name of OWNER_ONLY_LINKS) {
      expect(within(nav).getByRole('link', { name })).toBeInTheDocument();
    }
    expect(within(nav).queryByRole('link', { name: 'Staff dashboard' })).not.toBeInTheDocument();
  });

  it('tells staff they cannot open an owner page', () => {
    mockApi({});
    renderApp('/staff', { user: staffUser });
    expect(
      screen.getByRole('heading', { level: 1, name: 'You do not have access to this page.' }),
    ).toBeInTheDocument();
  });

  it('sends each role to its own dashboard', async () => {
    mockApi({});
    renderApp('/', { user: staffUser });
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Staff dashboard' }),
    ).toBeInTheDocument();
  });

  it('labels both meanings of active drivers on the owner dashboard (Q28)', () => {
    mockApi({});
    renderApp('/', { user: ownerUser });
    expect(screen.getByText('Active drivers (with an auto)')).toBeInTheDocument();
    expect(screen.getByText('Active drivers (KYC approved)')).toBeInTheDocument();
  });

  it('shows who is signed in with a sign-out button', () => {
    mockApi({});
    renderApp('/', { user: ownerUser });
    expect(screen.getByText('Test Owner')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
  });
});
