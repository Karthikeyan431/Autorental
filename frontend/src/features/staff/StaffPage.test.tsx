import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { apiError, callsTo, mockApi } from '../../test/mock-api';
import { renderApp } from '../../test/render';
import { ownerUser, staffUser } from '../../test/users';

const catalogue = {
  items: [
    { code: 'drivers.create', label: 'Register drivers', grantable: true, staff_default: true },
    {
      code: 'drivers.restrict',
      label: 'Suspend or reactivate drivers; place or lift restrictions',
      grantable: true,
      staff_default: false,
    },
    {
      code: 'adjustments.decide',
      label: 'Decide charge adjustments',
      grantable: false,
      staff_default: false,
    },
  ],
};

const page = (items = [staffUser]) => ({
  body: { items, total: items.length, page: 1, page_size: 20 },
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function setup(extra: Parameters<typeof mockApi>[0] = {}) {
  return mockApi({
    'GET /api/v1/users': page(),
    'GET /api/v1/settings/current': { body: { staff_limit: 10 } },
    'GET /api/v1/permissions': { body: catalogue },
    ...extra,
  });
}

describe('Staff page', () => {
  it('lists staff with the limit', async () => {
    setup();
    renderApp('/staff', { user: ownerUser });
    expect(await screen.findByText('Test Staff 001')).toBeInTheDocument();
    expect(await screen.findByText('1 of 10 active staff allowed.')).toBeInTheDocument();
  });

  it('adds a staff member and shows the temporary password once', async () => {
    const fetchMock = setup({
      'POST /api/v1/users': {
        status: 201,
        body: {
          user: { ...staffUser, id: 3, name: 'Test Staff 003' },
          temporary_password: 'Tmp-pass-abcdef',
        },
      },
    });
    renderApp('/staff', { user: ownerUser });
    await userEvent.click(await screen.findByRole('button', { name: 'Add staff' }));
    const dialog = screen.getByRole('dialog', { name: 'Add a staff member' });
    await userEvent.type(within(dialog).getByLabelText('Name'), 'Test Staff 003');
    await userEvent.type(within(dialog).getByLabelText('Mobile'), '12345');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    expect(within(dialog).getByText('Enter a 10-digit Indian mobile number.')).toBeInTheDocument();

    await userEvent.clear(within(dialog).getByLabelText('Mobile'));
    await userEvent.type(within(dialog).getByLabelText('Mobile'), '9000000003');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }));

    expect(await screen.findByTestId('temporary-password')).toHaveTextContent('Tmp-pass-abcdef');
    expect(callsTo(fetchMock, 'POST', '/api/v1/users')[0]?.body).toEqual({
      name: 'Test Staff 003',
      mobile: '9000000003',
      email: null,
    });
  });

  it('shows the staff limit refusal', async () => {
    setup({
      'POST /api/v1/users': apiError(
        409,
        'STAFF_LIMIT_REACHED',
        'You already have 10 active staff, the most allowed.',
      ),
    });
    renderApp('/staff', { user: ownerUser });
    await userEvent.click(await screen.findByRole('button', { name: 'Add staff' }));
    const dialog = screen.getByRole('dialog', { name: 'Add a staff member' });
    await userEvent.type(within(dialog).getByLabelText('Name'), 'Test Staff 011');
    await userEvent.type(within(dialog).getByLabelText('Mobile'), '9000000011');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      'You already have 10 active staff, the most allowed.',
    );
  });

  it('confirms before deactivating and sends the reason', async () => {
    const fetchMock = setup({
      'POST /api/v1/users/2/deactivate': { body: { ...staffUser, is_active: false } },
    });
    renderApp('/staff', { user: ownerUser });
    await userEvent.click(await screen.findByRole('button', { name: 'Deactivate' }));
    const dialog = screen.getByRole('dialog', { name: 'Deactivate Test Staff 001?' });
    await userEvent.type(within(dialog).getByLabelText('Reason (optional)'), 'Left the business');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Deactivate' }));
    expect(await screen.findByText('Staff member deactivated.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/v1/users/2/deactivate')[0]?.body).toEqual({
      reason: 'Left the business',
    });
  });

  it('edits permissions; owner-only codes are locked', async () => {
    const fetchMock = setup({
      'PUT /api/v1/users/2/permissions': { body: staffUser },
    });
    renderApp('/staff', { user: ownerUser });
    await userEvent.click(await screen.findByRole('button', { name: 'Permissions' }));
    const dialog = screen.getByRole('dialog', { name: 'Permissions for Test Staff 001' });

    const ownerOnly = await within(dialog).findByRole('checkbox', {
      name: /Decide charge adjustments/,
    });
    expect(ownerOnly).toBeDisabled();
    expect(ownerOnly).not.toBeChecked();
    expect(within(dialog).getByText(/adjustments\.decide · Owner only/)).toBeInTheDocument();

    const restrict = within(dialog).getByRole('checkbox', { name: /Suspend or reactivate/ });
    expect(restrict).not.toBeChecked();
    await userEvent.click(restrict);
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }));

    expect(await screen.findByText('Permissions saved.')).toBeInTheDocument();
    const sent = callsTo(fetchMock, 'PUT', '/api/v1/users/2/permissions')[0]?.body as {
      permissions: string[];
    };
    expect(sent.permissions).toContain('drivers.restrict');
    expect(sent.permissions).not.toContain('adjustments.decide');
  });
});
